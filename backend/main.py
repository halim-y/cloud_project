from flask import Flask, request, jsonify, Response
import os
import requests
from datetime import datetime, timezone, timedelta
from backend.services.weather import (
    get_current_weather, get_forecast,
    parse_daily_forecast, parse_hourly_today, parse_hourly_upcoming,
)
from backend.services.database import insert_row, get_latest_row
from backend.services.voice import process_voice_query
from backend.services.audio import transcribe, synthesize
from backend.services.announcements import compose as compose_announcement, ACTIONS

PASSWORD_HASH = os.environ.get("PASSWORD_HASH")
if not PASSWORD_HASH:
    raise RuntimeError("PASSWORD_HASH env var is required")

TZ_OFFSET = timedelta(hours=int(os.environ.get("TZ_OFFSET_HOURS", "2")))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB cap on POST bodies


def _server_time():
    now = datetime.now(timezone.utc) + TZ_OFFSET
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")


def _auth(body):
    return body.get("passwd") == PASSWORD_HASH


# ── Authenticated device endpoints ────────────────────────────────────────────

@app.route("/send-to-bigquery", methods=["POST"])
def send_to_bigquery():
    body = request.get_json(force=True)
    if not _auth(body):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = body.get("values", {})
    data["date"], data["time"] = _server_time()

    try:
        data.update(get_current_weather())
    except Exception as e:
        return jsonify({"status": "error", "message": "weather:" + str(e)[:40]}), 500

    # outdoor_icon is for the dashboard UI only; the BigQuery table has
    # no such column, so leaving it in causes a schema-mismatch error.
    data.pop("outdoor_icon", None)

    errors = insert_row(data)
    if errors:
        return jsonify({"status": "error", "message": str(errors[0])[:60]}), 500

    return jsonify({"status": "success", "server_time": data["time"]})


@app.route("/get_outdoor_weather", methods=["POST"])
def get_outdoor_weather():
    body = request.get_json(force=True)
    if not _auth(body):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    return jsonify({"status": "success", **get_current_weather()})


@app.route("/voice-query", methods=["POST"])
def voice_query():
    body = request.get_json(force=True)
    if not _auth(body):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    try:
        response = process_voice_query(
            body.get("text", ""),
            history=body.get("history"),
        )
        return jsonify({"status": "success", "response": response})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:200]}), 500


@app.route("/announce", methods=["POST"])
def announce():
    body = request.get_json(force=True)
    if not _auth(body):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    action = body.get("action", "motion")
    force  = bool(body.get("force", False))
    fmt    = body.get("format", "mp3")
    if action not in ACTIONS:
        return jsonify({"status": "error",
                        "message": "Unknown action. Allowed: " + ", ".join(ACTIONS)}), 400
    try:
        text = compose_announcement(action, force=force)
        if not text:
            return jsonify({"status": "skip", "action": action, "reason": "condition not met"})
        return jsonify({
            "status":    "speak",
            "action":    action,
            "text":      text,
            "audio_b64": synthesize(text, fmt=fmt),
            "format":    fmt,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:120]}), 500


@app.route("/tts", methods=["POST"])
def tts():
    body = request.get_json(force=True)
    if not _auth(body):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    text = (body.get("text") or "").strip()
    fmt  = body.get("format", "mp3")
    if not text:
        return jsonify({"status": "error", "message": "No text"}), 400
    try:
        return jsonify({"status": "success", "audio_b64": synthesize(text, fmt=fmt)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:120]}), 500


@app.route("/voice-audio", methods=["POST"])
def voice_audio():
    body = request.get_json(force=True)
    if not _auth(body):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    audio_b64   = body.get("audio_b64", "")
    sr_raw      = body.get("sample_rate")
    sample_rate = int(sr_raw) if sr_raw is not None else 48000
    if not audio_b64:
        return jsonify({"status": "error", "message": "No audio"}), 400
    try:
        transcript = transcribe(audio_b64, sample_rate)
        if not transcript:
            reply = "I didn't catch that — could you try again?"
            return jsonify({
                "status":     "empty",
                "transcript": "",
                "response":   reply,
                "audio_b64":  synthesize(reply),
            })
        answer = process_voice_query(transcript, history=body.get("history"))
        return jsonify({
            "status":     "success",
            "transcript": transcript,
            "response":   answer,
            "audio_b64":  synthesize(answer),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:120]}), 500


# ── Public dashboard endpoints ────────────────────────────────────────────────

@app.route("/current-outdoor", methods=["GET"])
def current_outdoor():
    try:
        return jsonify({"status": "success", **get_current_weather()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/forecast", methods=["GET"])
def forecast():
    try:
        raw = get_forecast()
        return jsonify({
            "status":          "success",
            "daily":           parse_daily_forecast(raw),
            "hourly_today":    parse_hourly_today(raw),
            "hourly_upcoming": parse_hourly_upcoming(raw, count=6),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


_ICON_CACHE = {}  # in-memory cache of icon_code -> PNG bytes (populated on demand)


@app.route("/weather-icon/<code>", methods=["GET"])
def weather_icon(code):
    """Proxy the OpenWeather icon PNG. The M5Stack hits this instead of
    openweathermap.org directly — keeps the device's HTTPS traffic on a
    single host (our backend) and lets us cache.

    Query param `size=small` returns the 50x50 @1x icon (for forecast
    rows). Default is the 100x100 @2x icon (for the HOME hero)."""
    # Defensive: icon codes are at most 4 chars, alnum only.
    if not code or not code.replace(".", "").isalnum() or len(code) > 8:
        return ("", 400)
    code = code.replace(".png", "")
    size = request.args.get("size", "large")
    suffix = "" if size == "small" else "@2x"
    cache_key = code + suffix
    cached = _ICON_CACHE.get(cache_key)
    if cached is None:
        try:
            r = requests.get(
                "https://openweathermap.org/img/wn/" + code + suffix + ".png",
                timeout=5,
            )
            if r.status_code != 200:
                return ("", 502)
            cached = r.content
            _ICON_CACHE[cache_key] = cached
        except Exception:
            return ("", 502)
    return Response(
        cached,
        mimetype="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.route("/latest-row", methods=["GET"])
def latest_row():
    try:
        row = get_latest_row()
        if row:
            return jsonify({"status": "success", **row})
        return jsonify({"status": "empty"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/server-time", methods=["GET"])
def server_time():
    """Current local time, for devices that can't sync NTP themselves
    (the M5Stack's `ntptime` module is unreliable on some firmwares).
    Returns year/month/day/hour/minute/second as integers."""
    now = datetime.now(timezone.utc) + TZ_OFFSET
    return jsonify({
        "status": "success",
        "year":   now.year,
        "month":  now.month,
        "day":    now.day,
        "hour":   now.hour,
        "minute": now.minute,
        "second": now.second,
        "date":   now.strftime("%Y-%m-%d"),
        "time":   now.strftime("%H:%M:%S"),
    })


@app.route("/next-trains", methods=["GET"])
def next_trains():
    """Next train connections from Genève Cornavin to Renens VD.
    Proxies transport.opendata.ch — no API key required.
    Returns up to 5 departures with time, line, platform and delay."""
    frm = request.args.get("from", "Genève")
    to  = request.args.get("to",   "Renens VD")
    try:
        r = requests.get(
            "https://transport.opendata.ch/v1/connections",
            params={"from": frm, "to": to, "transportations[]": "train", "limit": 5},
            timeout=10,
        )
        data = r.json()
        trains = []
        for conn in data.get("connections", []):
            f = conn.get("from") or {}
            t = conn.get("to")   or {}
            dep_raw = f.get("departure") or ""
            arr_raw = t.get("arrival")   or ""
            delay_s = f.get("delay")     or 0
            # First section carries the line/train name
            line = ""
            secs = conn.get("sections") or []
            if secs and secs[0].get("journey"):
                j = secs[0]["journey"]
                line = (j.get("name") or j.get("category") or "").strip()
            trains.append({
                "dep":      dep_raw[11:16] if len(dep_raw) >= 16 else "--:--",
                "arr":      arr_raw[11:16] if len(arr_raw) >= 16 else "--:--",
                "line":     line[:8],
                "delay":    int(delay_s) // 60 if delay_s else 0,
                "platform": str(f.get("platform") or "")[:3],
            })
        return jsonify({"status": "success", "trains": trains})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:120]}), 500


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "IoT Weather Backend"})


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8080,
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
