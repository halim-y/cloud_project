from flask import Flask, request, jsonify, Response
import os
from datetime import datetime, timezone, timedelta
from weather import get_current_weather, get_forecast, parse_daily_forecast, parse_hourly_today
from database import insert_row, get_latest_row
from voice import process_voice_query
from audio import transcribe, synthesize, synthesize_bytes
from announcements import compose as compose_announcement, ACTIONS

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
    fmt    = body.get("format", "mp3")
    if action not in ACTIONS:
        return jsonify({"status": "error",
                        "message": "Unknown action. Allowed: " + ", ".join(ACTIONS)}), 400
    try:
        text = compose_announcement(action)
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


@app.route("/announce-binary", methods=["POST"])
def announce_binary():
    """Same as /announce but returns the WAV bytes directly with
    Content-Type: audio/wav. Designed for the M5Stack so the device can
    skip JSON parsing and base64 decoding of a large payload."""
    body = request.get_json(force=True)
    if not _auth(body):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    action = body.get("action", "motion")
    if action not in ACTIONS:
        return jsonify({"status": "error",
                        "message": "Unknown action. Allowed: " + ", ".join(ACTIONS)}), 400
    try:
        text = compose_announcement(action)
        if not text:
            # Condition not met (e.g. rain reminder on a sunny day).
            # 204 No Content — the device knows to play nothing.
            return ("", 204)
        wav_bytes = synthesize_bytes(text, fmt="wav")
        return Response(
            wav_bytes,
            mimetype="audio/wav",
            headers={
                "X-Announcement-Text":   text[:200],
                "X-Announcement-Action": action,
            },
        )
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
            "status":       "success",
            "daily":        parse_daily_forecast(raw),
            "hourly_today": parse_hourly_today(raw),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/latest-row", methods=["GET"])
def latest_row():
    try:
        row = get_latest_row()
        if row:
            return jsonify({"status": "success", **row})
        return jsonify({"status": "empty"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "IoT Weather Backend"})


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8080,
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
