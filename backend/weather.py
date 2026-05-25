import os
import time
import requests
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY")
if not OPENWEATHER_API_KEY:
    raise RuntimeError("OPENWEATHER_API_KEY env var is required")

CITY      = os.environ.get("CITY", "Genève")
BASE_URL  = "http://api.openweathermap.org/data/2.5"
TZ_OFFSET = timedelta(hours=int(os.environ.get("TZ_OFFSET_HOURS", "2")))

_current_cache      = None
_current_cache_time = 0.0
_CURRENT_TTL        = 300   # 5 min

_forecast_cache      = None
_forecast_cache_time = 0.0
_FORECAST_TTL        = 600  # 10 min

ICON_EMOJI = {
    "01": "☀️", "02": "⛅", "03": "☁️", "04": "☁️",
    "09": "🌧️", "10": "🌦️", "11": "⛈️", "13": "❄️", "50": "🌫️",
}


def icon_to_emoji(icon_code):
    return ICON_EMOJI.get(icon_code[:2], "🌡️")


def get_current_weather():
    global _current_cache, _current_cache_time
    if _current_cache is not None and time.time() - _current_cache_time < _CURRENT_TTL:
        return _current_cache
    url = f"{BASE_URL}/weather?q={CITY}&appid={OPENWEATHER_API_KEY}&units=metric"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    result = {
        "outdoor_temp":     round(float(body["main"]["temp"]), 1),
        "outdoor_humidity": round(float(body["main"]["humidity"]), 1),
        "outdoor_weather":  body["weather"][0]["description"],
        "outdoor_icon":     body["weather"][0]["icon"],
    }
    _current_cache      = result
    _current_cache_time = time.time()
    return result


def get_forecast():
    global _forecast_cache, _forecast_cache_time
    if _forecast_cache is not None and time.time() - _forecast_cache_time < _FORECAST_TTL:
        return _forecast_cache
    url = f"{BASE_URL}/forecast?q={CITY}&appid={OPENWEATHER_API_KEY}&units=metric"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    result = resp.json()
    _forecast_cache      = result
    _forecast_cache_time = time.time()
    return result


def parse_daily_forecast(raw):
    days = defaultdict(lambda: {"temps": [], "humidities": [], "icons": [], "descriptions": []})
    for item in raw["list"]:
        dt       = datetime.fromtimestamp(item["dt"], tz=timezone.utc) + TZ_OFFSET
        date_str = dt.strftime("%Y-%m-%d")
        days[date_str]["temps"].append(item["main"]["temp"])
        days[date_str]["humidities"].append(item["main"]["humidity"])
        days[date_str]["icons"].append(item["weather"][0]["icon"])
        days[date_str]["descriptions"].append(item["weather"][0]["description"])

    result = []
    for date_str, data in sorted(days.items())[:5]:
        dt   = datetime.strptime(date_str, "%Y-%m-%d")
        icon = Counter(data["icons"]).most_common(1)[0][0]
        desc = Counter(data["descriptions"]).most_common(1)[0][0]
        result.append({
            "date":        date_str,
            "day":         dt.strftime("%a"),
            "day_num":     dt.strftime("%d"),
            "icon":        icon,
            "emoji":       icon_to_emoji(icon),
            "temp_max":    round(max(data["temps"]), 1),
            "temp_min":    round(min(data["temps"]), 1),
            "description": desc,
            "humidity":    round(sum(data["humidities"]) / len(data["humidities"])),
        })
    return result


def parse_hourly_today(raw):
    now       = datetime.now(timezone.utc) + TZ_OFFSET
    today_str = now.strftime("%Y-%m-%d")
    result    = []
    for item in raw["list"]:
        dt = datetime.fromtimestamp(item["dt"], tz=timezone.utc) + TZ_OFFSET
        if dt.strftime("%Y-%m-%d") == today_str:
            icon = item["weather"][0]["icon"]
            result.append({
                "time":        dt.strftime("%H:%M"),
                "icon":        icon,
                "emoji":       icon_to_emoji(icon),
                "temp":        round(item["main"]["temp"], 1),
                "humidity":    item["main"]["humidity"],
                "description": item["weather"][0]["description"],
            })
    return result


def parse_hourly_upcoming(raw, count=6):
    """Next `count` 3-hour slots from now, regardless of date. Used by the
    M5Stack hourly forecast view — keeps the screen full whether the user
    opens it at 8 AM or 11 PM."""
    now    = datetime.now(timezone.utc) + TZ_OFFSET
    result = []
    for item in raw["list"]:
        dt = datetime.fromtimestamp(item["dt"], tz=timezone.utc) + TZ_OFFSET
        if dt <= now:
            continue
        icon = item["weather"][0]["icon"]
        result.append({
            "time":        dt.strftime("%H:%M"),
            "icon":        icon,
            "emoji":       icon_to_emoji(icon),
            "temp":        round(item["main"]["temp"], 1),
            "humidity":    item["main"]["humidity"],
            "description": item["weather"][0]["description"],
        })
        if len(result) >= count:
            break
    return result
