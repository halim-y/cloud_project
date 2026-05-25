from m5stack import *
from m5ui import *
from uiflow import *
import wifiCfg
import urequests
import ujson
import unit
import time
import os
import ntptime
from machine import I2C, Pin, RTC

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
FLASK_URL     = "https://cloud-project-470570889014.europe-west6.run.app"
PASSWORD_HASH = "f4f263e439cf40925e6a412387a9472a6773c2580212a4fb50d224d3a817de17"

# Sensor + announcement cadences. The 5-minute sensor send is the project
# requirement; everything else is just convenience polling.
SEND_INTERVAL_S     = 300    # send sensor data every 5 minutes
OUTDOOR_INTERVAL_S  = 300    # refresh outdoor weather every 5 minutes
FORECAST_INTERVAL_S = 600    # forecast cache lifetime — 10 min
ANNOUNCE_COOLDOWN_S = 3600   # at most one motion announcement per hour
ANSWER_HOLD_S       = 8      # how long ANSWER screen stays after audio ends
ANN_HOLD_S          = 2      # how long ANNOUNCEMENT stays after audio ends
TZ_OFFSET_HOURS     = 2      # local timezone offset applied after NTP sync

# File paths on the device's flash
ICONS_DIR         = "/flash/icons"
ANSWER_WAV_FILE   = "/flash/answer.wav"
ANNOUNCE_WAV_FILE = "/flash/announce.wav"

# Visual palette — picked to feel like the dashboard's dark glassmorphism look
BG_DARK        = 0x0A0A0A
BG_PANEL       = 0x141622
FG_BRIGHT      = 0xEEEEEE
FG_MUTED       = 0x666666
FG_DIM         = 0x444444
ACCENT_BLUE    = 0x4A9ECC
ACCENT_ORANGE  = 0xE8943A
ACCENT_GREEN   = 0x4AAA77
ACCENT_PURPLE  = 0x9977BB
ACCENT_RED     = 0xE85A3A
ACCENT_YELLOW  = 0xE8C84A

# State machine values
S_HOME         = "home"
S_FORECAST     = "forecast"
S_TRAINS       = "trains"
S_ACTIONS      = "actions"
S_ANSWER       = "answer"
S_ANNOUNCEMENT = "announcement"
S_OFFLINE      = "offline"

# Per-action display metadata — (screen header, accent color, loading message)
_ACTION_META = {
    "current_summary":   ("WEATHER SUMMARY",  ACCENT_BLUE,   "Getting summary..."),
    "morning_briefing":  ("MORNING BRIEFING", ACCENT_PURPLE, "Loading briefing..."),
    "rain_reminder":     ("RAIN CHECK",       ACCENT_BLUE,   "Checking rain..."),
    "air_quality_alert": ("AIR QUALITY",      ACCENT_GREEN,  "Checking air..."),
    "train_delay":       ("TRAIN STATUS",     ACCENT_RED,    "Checking trains..."),
    "humidity_alert":    ("HUMIDITY ALERT",   ACCENT_BLUE,   "Checking humidity..."),
    "motion":            ("WEATHER UPDATE",   ACCENT_ORANGE, "Getting update..."),
}

# Action-menu buttons — (display label, backend action name, symbol, accent color)
ACTION_MENU = [
    ("Summary",    "current_summary",   "i",  ACCENT_BLUE),
    ("Morning",    "morning_briefing",  "M",  ACCENT_YELLOW),
    ("Rain Check", "rain_reminder",     "~",  ACCENT_BLUE),
    ("Air Quality","air_quality_alert", "A",  ACCENT_GREEN),
    ("Train Alert","train_delay",       "!",  ACCENT_RED),
    ("Humidity",   "humidity_alert",    "%",  ACCENT_BLUE),
]


# ─────────────────────────────────────────────────────────────────────────────
# Sensors
# ─────────────────────────────────────────────────────────────────────────────
env3 = unit.get(unit.ENV3, unit.PORTA)
pir  = unit.get(unit.PIR,  unit.PORTB)
i2c_portc   = I2C(sda=Pin(13), scl=Pin(14), freq=100000)
tvoc_sensor = unit.get(unit.TVOC, unit.PORTC)

rtc = RTC()


# ─────────────────────────────────────────────────────────────────────────────
# Module-global state
# ─────────────────────────────────────────────────────────────────────────────
state = S_HOME

# Latest readings (refreshed every tick by read_local_sensors)
indoor_temp = None
indoor_humi = None
indoor_tvoc = None
indoor_eco2 = None
motion_now  = False

# Cached outdoor + last-row data
outdoor_temp    = None
outdoor_humi    = None
outdoor_weather = None
outdoor_icon    = None       # icon code (e.g. "04d")
icon_cached     = None       # what's currently on /flash/wx.png
last_sync_label = "Never"    # short timestamp for the home footer

# Forecast cache: list of {"day": "Tue", "icon": "04d", "max": 18, "min": 12, "desc": "rain"}
forecast_daily  = []
forecast_hourly = []         # list of {"time": "15:00", "icon": "01d", "temp": 18}
forecast_mode   = "daily"    # "daily" or "hourly"

# Timers
last_send       = -SEND_INTERVAL_S
last_outdoor    = -OUTDOOR_INTERVAL_S
last_forecast   = -FORECAST_INTERVAL_S
last_announce   = -ANNOUNCE_COOLDOWN_S
last_morning_date = None     # YYYY-MM-DD string of last morning briefing

# Animation tick counter (0..N) for pulsing motion dot etc.
anim_tick = 0

# Last announcement result shown in the HOME footer.
last_announce_status = ""   # e.g. "played: motion", "skipped: no rain"

# Touch debounce — timestamp of the last action triggered by a tap.
_last_tap_time = 0

# Cached train departures (refreshed each time S_TRAINS is entered).
train_departures = []


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def safe_text(s, n=20):
    """Truncate user-visible text to a hard length to keep layouts clean."""
    if s is None:
        return ""
    s = str(s)
    return s[:n]


def now_hhmm():
    try:
        dt = rtc.datetime()
        # rtc.datetime() → (year, month, day, weekday, hour, minute, second, microsecond)
        return "%02d:%02d" % (dt[4], dt[5])
    except:
        return "--:--"


def now_hour():
    try:
        return rtc.datetime()[4]
    except:
        return -1


def today_str():
    try:
        dt = rtc.datetime()
        return "%04d-%02d-%02d" % (dt[0], dt[1], dt[2])
    except:
        return ""


def air_color(label):
    """Map an air-quality category label to one of the accent colors."""
    if label in ("Excellent", "Good"):
        return ACCENT_GREEN
    if label == "Moderate":
        return ACCENT_ORANGE
    return ACCENT_RED


def tvoc_quality(v):
    if v is None: return ("--",        FG_DIM)
    if v < 150:   return ("Excellent", ACCENT_GREEN)
    if v < 300:   return ("Good",      ACCENT_GREEN)
    if v < 500:   return ("Moderate",  ACCENT_ORANGE)
    return            ("Poor",      ACCENT_RED)


def eco2_quality(v):
    if v is None:  return ("--",        FG_DIM)
    if v < 700:    return ("Excellent", ACCENT_GREEN)
    if v < 1000:   return ("Good",      ACCENT_GREEN)
    if v < 1500:   return ("Moderate",  ACCENT_ORANGE)
    return             ("Poor",      ACCENT_RED)


def wifi_ok():
    try:
        return wifiCfg.wlan_sta.isconnected()
    except:
        return False


def file_exists(path):
    try:
        os.stat(path)
        return True
    except:
        return False


def _get_touch():
    """Return (x, y) if the screen is ACTIVELY being touched, else None.
    Only uses forms that include a real pressed-state check."""
    try:
        if touch.isPress():
            return (touch.x, touch.y)
    except: pass
    try:
        if touch.isPressed():
            return (touch.x, touch.y)
    except: pass
    try:
        t = touch.read()
        if t and len(t) >= 3 and t[2]:   # t[2] = pressed flag
            return (t[0], t[1])
    except: pass
    try:
        if M5.Touch.isPressed():
            p = M5.Touch.getPoint()
            return (p.x, p.y)
    except: pass
    try:
        _i = I2C(0, sda=Pin(21), scl=Pin(22), freq=400000)
        buf = bytearray(7)
        _i.readfrom_mem_into(0x38, 0x00, buf)
        if buf[2] & 0x0F > 0:            # TD_STATUS: number of active touches
            x = ((buf[3] & 0x0F) << 8) | buf[4]
            y = ((buf[5] & 0x0F) << 8) | buf[6]
            if x > 0 and y > 0:
                return (x, y)
    except: pass
    return None



def ntp_sync():
    """Sync the RTC to current local time. Tries ntptime first (which is
    flaky on some UIFlow builds), then falls back to fetching the local
    time from our backend's /server-time endpoint."""
    # Try 1: ntptime + manual TZ shift
    try:
        ntptime.settime()
        y, m, d, wd, hh, mm, ss, us = rtc.datetime()
        hh = (hh + TZ_OFFSET_HOURS) % 24
        rtc.datetime((y, m, d, wd, hh, mm, ss, us))
        # Sanity check: if the year is still 2000 (default RTC year),
        # ntptime didn't actually work — fall through to backend.
        if rtc.datetime()[0] >= 2024:
            return True
    except:
        pass

    # Try 2: backend /server-time (already in local TZ)
    try:
        resp = urequests.get(FLASK_URL + "/server-time")
        data = resp.json()
        resp.close()
        if data.get("status") == "success":
            rtc.datetime((
                int(data["year"]), int(data["month"]), int(data["day"]),
                0,
                int(data["hour"]), int(data["minute"]), int(data["second"]), 0,
            ))
            return True
    except:
        pass
    return False


def icon_path(code, small=False):
    suffix = "_s" if small else ""
    return ICONS_DIR + "/" + str(code) + suffix + ".png"


def ensure_icons_dir():
    try:
        os.mkdir(ICONS_DIR)
    except:
        pass  # already exists


def download_icon(code, small=False):
    """Fetch one weather icon from the backend proxy. `small=True` gets
    the 50x50 version (for forecast rows); default is 100x100 (for the
    HOME hero). No-op if already cached."""
    if not code:
        return False
    path = icon_path(code, small=small)
    if file_exists(path):
        return True
    ensure_icons_dir()
    try:
        url = FLASK_URL + "/weather-icon/" + str(code) + ".png"
        if small:
            url += "?size=small"
        resp = urequests.get(url)
        if resp.status_code == 200:
            with open(path, "wb") as f:
                f.write(resp.content)
            resp.close()
            return True
        resp.close()
    except:
        pass
    return False


def draw_weather_block(x, y, code, fallback_text=""):
    """Render a weather icon at (x, y) — or a clearly-visible fallback if
    the PNG isn't on disk yet. Lets us always show *something* even when
    the icon download hasn't completed."""
    path = icon_path(code) if code else None
    if path and file_exists(path):
        try:
            lcd.image(x, y, path)
            return
        except:
            pass
    # Loud fallback: a small colored square + the description text so the
    # screen never looks broken even when icons aren't downloaded.
    lcd.fillRect(x + 8, y + 8, 40, 40, ACCENT_BLUE)
    lcd.font(lcd.FONT_Default)
    if fallback_text:
        lcd.print(safe_text(fallback_text, 8), x, y + 52, FG_BRIGHT)


# ─────────────────────────────────────────────────────────────────────────────
# Backend communication
# ─────────────────────────────────────────────────────────────────────────────
def fetch_last_row():
    """On boot: pre-populate indoor + outdoor labels from BigQuery."""
    global indoor_temp, indoor_humi, indoor_tvoc, indoor_eco2
    global outdoor_temp, outdoor_humi, outdoor_weather, outdoor_icon
    global last_sync_label
    try:
        resp = urequests.get(FLASK_URL + "/latest-row")
        data = resp.json()
        resp.close()
        if data.get("status") != "success":
            return False
        indoor_temp     = data.get("indoor_temp")
        indoor_humi     = data.get("indoor_humidity")
        indoor_tvoc     = data.get("air_quality_tvoc")
        indoor_eco2     = data.get("air_quality_eco2")
        outdoor_temp    = data.get("outdoor_temp")
        outdoor_humi    = data.get("outdoor_humidity")
        outdoor_weather = data.get("outdoor_weather")
        outdoor_icon    = data.get("outdoor_icon")
        t = data.get("time", "")
        if t:
            last_sync_label = str(t)[:5]
        ensure_icon_cached()
        return True
    except:
        return False


def fetch_outdoor():
    """Pull fresh outdoor weather + download the icon if it has changed."""
    global outdoor_temp, outdoor_humi, outdoor_weather, outdoor_icon
    try:
        resp = urequests.post(
            FLASK_URL + "/get_outdoor_weather",
            data=ujson.dumps({"passwd": PASSWORD_HASH}),
            headers={"Content-Type": "application/json"},
        )
        data = resp.json()
        resp.close()
        if data.get("status") == "success":
            outdoor_temp    = data.get("outdoor_temp")
            outdoor_humi    = data.get("outdoor_humidity")
            outdoor_weather = data.get("outdoor_weather")
            outdoor_icon    = data.get("outdoor_icon")
            ensure_icon_cached()
            return True
    except:
        pass
    return False


def ensure_icon_cached():
    """Make sure the current outdoor icon is downloaded. Routed through the
    backend proxy at /weather-icon/<code> — that avoids any HTTPS quirks
    talking to openweathermap.org directly from MicroPython."""
    global icon_cached
    code = outdoor_icon
    if not code or code == icon_cached:
        return
    if download_icon(code):
        icon_cached = code


def fetch_forecast():
    """Refresh the cached forecast (daily + hourly upcoming).
    Also pre-downloads the icon PNGs for every slot so draw_forecast()
    can render them instantly."""
    global forecast_daily, forecast_hourly
    try:
        resp = urequests.get(FLASK_URL + "/forecast")
        data = resp.json()
        resp.close()
        if data.get("status") != "success":
            return False
        forecast_daily  = data.get("daily", [])[:3]
        # hourly_upcoming is the rolling 6-slot view across midnight; falls
        # back to hourly_today if an older backend is still serving us.
        forecast_hourly = (data.get("hourly_upcoming") or data.get("hourly_today") or [])[:6]
        # Cache every icon we're about to display. Daily uses large
        # icons (one big icon per column); hourly uses small icons so
        # they fit inside the chart's data-point markers.
        for d in forecast_daily:
            download_icon(d.get("icon"), small=False)
        for h in forecast_hourly:
            download_icon(h.get("icon"), small=True)
        return True
    except:
        return False


def send_data():
    """Periodic sensor upload. Updates last_sync_label on success."""
    global last_sync_label
    try:
        payload = {
            "passwd": PASSWORD_HASH,
            "values": {
                "indoor_temp":      indoor_temp,
                "indoor_humidity":  indoor_humi,
                "air_quality_tvoc": indoor_tvoc,
                "air_quality_eco2": indoor_eco2,
            },
        }
        resp = urequests.post(
            FLASK_URL + "/send-to-bigquery",
            data=ujson.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        result = resp.json()
        resp.close()
        if result.get("status") == "success":
            last_sync_label = str(result.get("server_time", "?"))[:5]
            return True
    except:
        pass
    return False


def play_announcement(action, force=False):
    """Fetch announcement text + WAV from /announce (JSON).
    Returns (text, reason); text is None on skip/error, "" if audio
    downloaded but text unavailable."""
    global last_announce_status
    try:
        body = {"passwd": PASSWORD_HASH, "action": action, "format": "wav"}
        if force:
            body["force"] = True
        resp = urequests.post(
            FLASK_URL + "/announce",
            data=ujson.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        data = resp.json()
        resp.close()
        status = data.get("status")
        if status == "skip":
            reason = "skipped: " + action[:8]
            last_announce_status = reason
            return (None, reason)
        if status != "speak":
            reason = "err: " + str(status)[:10]
            last_announce_status = reason
            return (None, reason)
        text = (data.get("text") or "").replace("°", " C")
        audio_b64 = data.get("audio_b64") or ""
        if audio_b64:
            import ubinascii
            wav_bytes = ubinascii.a2b_base64(audio_b64)
            with open(ANNOUNCE_WAV_FILE, "wb") as f:
                f.write(wav_bytes)
        reason = "ready: " + action[:10]
        last_announce_status = reason
        return (text, reason)
    except Exception as e:
        reason = "err: " + type(e).__name__[:10]
        last_announce_status = reason
        return (None, reason)


def fetch_trains():
    global train_departures
    try:
        resp = urequests.get(FLASK_URL + "/next-trains")
        data = resp.json()
        resp.close()
        if data.get("status") == "success":
            train_departures = data.get("trains", [])
            return True
    except:
        pass
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Drawing primitives
# ─────────────────────────────────────────────────────────────────────────────
def clear_screen(bg=BG_DARK):
    lcd.fillScreen(bg)


def draw_topbar(title=""):
    """20-px header: clock (left) | title (center) | sync + wifi (right)."""
    lcd.fillRect(0, 0, 320, 20, BG_PANEL)
    lcd.font(lcd.FONT_Default)
    lcd.print(now_hhmm(), 8, 5, FG_BRIGHT)
    if title:
        # Crude centering: ~6 px per char at FONT_Default
        cx = 160 - len(title) * 3
        lcd.print(title, max(60, cx), 5, FG_MUTED)
    # Sync timestamp + WiFi dot on the right
    sync_text = "Sync " + last_sync_label
    lcd.print(sync_text, 232, 5, FG_DIM)
    color = ACCENT_GREEN if wifi_ok() else ACCENT_RED
    lcd.fillCircle(311, 10, 4, color)


def draw_footer_buttons(a_label, b_label, c_label):
    """20-px footer with three button labels visually aligned over the
    M5Stack Core2's three capacitive buttons (centered roughly at
    x = 64 / 160 / 256)."""
    lcd.fillRect(0, 220, 320, 20, BG_PANEL)
    lcd.font(lcd.FONT_Default)
    for label, cx in ((a_label, 64), (b_label, 160), (c_label, 256)):
        x = cx - len(label) * 3
        lcd.print(label, x, 225, FG_BRIGHT)


def draw_footer(text):
    """Free-text footer — status line or button hints."""
    lcd.fillRect(0, 220, 320, 20, BG_PANEL)
    lcd.font(lcd.FONT_Default)
    lcd.print(text, 8, 225, FG_MUTED)


# ─────────────────────────────────────────────────────────────────────────────
# State drawing — HOME
# ─────────────────────────────────────────────────────────────────────────────
def draw_droplet(cx, cy, color):
    """Small water-drop glyph drawn from primitives (the lcd bitmap font has
    no emoji). cy is the vertical centre of the drop. Falls back to a plain
    dot if lcd.triangle isn't available on this firmware."""
    try:
        lcd.fillCircle(cx, cy + 2, 4, color)                       # round base
        lcd.triangle(cx - 4, cy + 1, cx + 4, cy + 1, cx, cy - 6, color, color)
    except:
        try:
            lcd.fillCircle(cx, cy, 4, color)
        except:
            pass


def draw_home():
    clear_screen()
    draw_topbar("")

    # ── RIGHT COLUMN: icon + description centered below (x=168..320) ──────
    draw_weather_block(194, 34, outdoor_icon, fallback_text=outdoor_weather)
    lcd.font(lcd.FONT_Default)
    desc = safe_text(outdoor_weather, 22)
    lcd.print(desc, max(172, 244 - len(desc) * 3), 154, FG_MUTED)

    # Vertical divider
    lcd.line(168, 22, 168, 193, 0x2A2A2A)

    # ── LEFT COLUMN: temp + humidity centered (x=0..168, center=84) ───────
    # Both use DejaVu24 so they read as a balanced pair, aligned with the icon
    lcd.font(lcd.FONT_DejaVu24)
    ot_str = ("%.0f C" % outdoor_temp) if outdoor_temp is not None else "-- C"
    lcd.print(ot_str, max(4, 84 - len(ot_str) * 8), 48, ACCENT_ORANGE)

    # Humidity: drawn droplet + value, centred as one unit
    lcd.font(lcd.FONT_DejaVu24)
    oh_str = ("%d%%" % int(outdoor_humi)) if outdoor_humi is not None else "--"
    total_w = 12 + 8 + len(oh_str) * 16
    oh_left = max(6, 84 - total_w // 2)
    draw_droplet(oh_left + 5, 102, ACCENT_BLUE)
    lcd.print(oh_str, oh_left + 20, 90, ACCENT_BLUE)

    # Motion indicator — animated each tick via draw_motion_dot()
    draw_motion_dot()

    # ── INDOOR STRIP (y=193..220) ─────────────────────────────────────────
    lcd.fillRect(0, 193, 320, 27, 0x14171F)
    lcd.line(0, 193, 320, 193, 0x2A2A2A)

    lcd.font(lcd.FONT_Default)
    lcd.print("INDOOR", 8, 201, FG_MUTED)

    in_t = ("%.1f C" % indoor_temp) if indoor_temp is not None else "-- C"
    lcd.print(in_t, 62, 201, ACCENT_ORANGE)

    in_h = ("%d%%" % int(indoor_humi)) if indoor_humi is not None else "--%"
    lcd.print(in_h, 116, 201, ACCENT_BLUE)

    tv_lbl, tv_col = tvoc_quality(indoor_tvoc)
    ec_lbl, ec_col = eco2_quality(indoor_eco2)
    severity = {"Excellent": 0, "Good": 1, "Moderate": 2, "Poor": 3, "--": 0}
    if severity.get(ec_lbl, 0) >= severity.get(tv_lbl, 0):
        air_lbl, air_col = ec_lbl, ec_col
    else:
        air_lbl, air_col = tv_lbl, tv_col
    lcd.print("AIR:", 162, 201, FG_MUTED)
    lcd.print(air_lbl, 190, 201, air_col)

    draw_footer_buttons("ACTIONS", "TRAINS", "FORECAST")


def draw_motion_dot():
    """Pulsing indicator in the left column — DejaVu18 to match the weather
    description on the right, positioned at the same baseline (~y=154)."""
    if state != S_HOME:
        return
    # Clear the motion zone (humidity ends ~y=114, strip starts y=193)
    lcd.fillRect(0, 128, 168, 52, BG_DARK)
    if motion_now:
        col   = ACCENT_PURPLE if (anim_tick % 2 == 0) else 0x553388
        label = "Motion"
        l_col = ACCENT_PURPLE
    else:
        col   = FG_DIM
        label = "Idle"
        l_col = FG_DIM
    # Centre dot + label as one unit, same size as the description text
    lcd.font(lcd.FONT_Default)
    total_w = 8 + 4 + len(label) * 6
    m_left  = max(4, 84 - total_w // 2)
    lcd.fillCircle(m_left + 4, 162, 4, col)
    lcd.print(label, m_left + 12, 158, l_col)


# ─────────────────────────────────────────────────────────────────────────────
# State drawing — FORECAST
# ─────────────────────────────────────────────────────────────────────────────
def draw_forecast():
    clear_screen()
    draw_topbar("FORECAST" if forecast_mode == "daily" else "NEXT 18H")
    if forecast_mode == "daily":
        draw_forecast_daily()
    else:
        draw_forecast_hourly()
    b_label = "HOURLY" if forecast_mode == "daily" else "DAILY"
    draw_footer_buttons("ACTIONS", b_label, "HOME")


def draw_forecast_daily():
    """3 columns side by side. Each: day, icon, max temp, min temp,
    wrapped description (up to 2 lines)."""
    days = forecast_daily[:3]
    if not days:
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print("No forecast data", 70, 110, FG_MUTED)
        return
    col_w = 320 // 3

    for i, d in enumerate(days):
        x = i * col_w
        cx = x + col_w // 2

        # Day name — centered
        lcd.font(lcd.FONT_DejaVu18)
        day_label = safe_text(d.get("day", "--"), 4)
        # Crude horizontal centering: 11px per char at DejaVu18
        lcd.print(day_label, cx - len(day_label) * 6, 28, FG_BRIGHT)

        # Icon — 100x100 PNG centered horizontally
        draw_weather_block(cx - 50, 48, d.get("icon"),
                           fallback_text=d.get("description", ""))

        # Max temp (orange)
        lcd.font(lcd.FONT_DejaVu24)
        mx = d.get("temp_max", "--")
        mx_str = "%.0f" % mx if isinstance(mx, (int, float)) else str(mx)
        lcd.print(mx_str + "°", cx - len(mx_str) * 8, 152, ACCENT_ORANGE)

        # Min temp (blue, smaller, just below)
        lcd.font(lcd.FONT_DejaVu18)
        mn = d.get("temp_min", "--")
        mn_str = "%.0f" % mn if isinstance(mn, (int, float)) else str(mn)
        lcd.print(mn_str + "°", cx - len(mn_str) * 6, 180, ACCENT_BLUE)


def draw_forecast_hourly():
    """Temperature line chart for the next ~18 hours.

    Plot area: x = 30..305, y = 60..170 (275 wide, 110 tall).
    - Time labels at y = 178 along the x-axis
    - max/min summary in the top-right corner
    - 50x50 weather icons placed above each data point
    - Bottom label: 'next: <description>' for the next slot
    """
    slots = forecast_hourly[:6]
    if not slots:
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print("No forecast data", 70, 110, FG_MUTED)
        return

    # Extract temp values (skip non-numerics gracefully)
    temps = []
    for h in slots:
        t = h.get("temp")
        if isinstance(t, (int, float)):
            temps.append(t)
    if not temps:
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print("No forecast data", 70, 110, FG_MUTED)
        return

    t_min = min(temps)
    t_max = max(temps)
    if t_max - t_min < 2:  # avoid divide-by-zero / flat chart
        t_max = t_min + 2

    # Top-right summary
    lcd.font(lcd.FONT_Default)
    summary = "max %d°  min %d°" % (round(t_max), round(t_min))
    # Increased char width to 7 and right margin to 15 to prevent edge wrapping
    lcd.print(summary, 320 - len(summary) * 7 - 15, 28, FG_MUTED)

    # Plot area
    px0, px1 = 30, 305
    py0, py1 = 70, 170          # py0 = top (warmer), py1 = bottom (cooler)
    n = len(slots)
    if n < 2:
        # Single point — just draw a dot
        lcd.fillCircle((px0 + px1) // 2, (py0 + py1) // 2, 4, ACCENT_ORANGE)
        return

    step = (px1 - px0) // (n - 1)

    # Map each slot to a chart coordinate
    points = []
    for i, h in enumerate(slots):
        t = h.get("temp", t_min)
        if not isinstance(t, (int, float)):
            t = t_min
        x = px0 + i * step
        # Higher temp → smaller y (inverted axis)
        y = py1 - int((t - t_min) / (t_max - t_min) * (py1 - py0))
        points.append((x, y, h))

    # Connect the dots with line segments
    for i in range(n - 1):
        x1, y1, _ = points[i]
        x2, y2, _ = points[i + 1]
        # Slightly thicker line — three parallel passes
        lcd.line(x1, y1,     x2, y2,     ACCENT_ORANGE)
        lcd.line(x1, y1 - 1, x2, y2 - 1, ACCENT_ORANGE)

    # Markers + small icons + time labels under each
    for x, y, h in points:
        # Data point marker
        lcd.fillCircle(x, y, 4, ACCENT_ORANGE)
        # Time label below the chart (Formatted to "20h")
        raw_time = h.get("time", "--")
        if ":" in raw_time:
            time_label = raw_time.split(":")[0] + "h"
        else:
            time_label = safe_text(raw_time, 5)
        lcd.font(lcd.FONT_Default)
        # Center the narrower text exactly under its dot
        label_x = x - len(time_label) * 4
        lcd.print(time_label, label_x, 178, FG_MUTED)
        # Small icon above the point (skip if it would clip the topbar)
        code = h.get("icon")
        path = icon_path(code, small=True) if code else None
        icon_y = max(28, y - 60)
        if path and file_exists(path):
            try:
                lcd.image(x - 25, icon_y, path)
            except:
                lcd.fillRect(x - 6, icon_y + 18, 14, 14, ACCENT_BLUE)


# ─────────────────────────────────────────────────────────────────────────────
# State drawing — TRAINS
# ─────────────────────────────────────────────────────────────────────────────
def draw_trains():
    clear_screen()
    draw_topbar("GVA > RENENS")

    trains = train_departures
    if not trains:
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print("No departures found", 35, 110, FG_MUTED)
        draw_footer_buttons("REFRESH", "", "HOME")
        return

    for i, t in enumerate(trains[:5]):
        y = 20 + i * 40
        delay = t.get("delay", 0) or 0

        # Row divider
        if i > 0:
            lcd.fillRect(0, y, 320, 1, 0x252535)

        # Departure time — red if delayed, bright white if on time
        dep_col = ACCENT_RED if delay > 0 else FG_BRIGHT
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print(t.get("dep", "--:--"), 5, y + 6, dep_col)

        # Line name
        lcd.font(lcd.FONT_Default)
        lcd.print(safe_text(t.get("line", "?"), 8), 70, y + 6, ACCENT_BLUE)

        # Arrival time
        lcd.print("arr " + t.get("arr", "--:--"), 70, y + 22, FG_MUTED)

        # Platform
        pf = str(t.get("platform", ""))
        if pf:
            lcd.print("pf." + pf, 170, y + 6, FG_DIM)

        # Delay indicator — green dot or red "+X min"
        if delay > 0:
            lcd.print("+" + str(delay) + " min", 225, y + 14, ACCENT_RED)
        else:
            lcd.fillCircle(318, y + 14, 5, ACCENT_GREEN)

    draw_footer_buttons("REFRESH", "", "HOME")


# ─────────────────────────────────────────────────────────────────────────────
# State drawing — THINKING
# ─────────────────────────────────────────────────────────────────────────────
def draw_loading(label="Loading..."):
    clear_screen()
    lcd.font(lcd.FONT_DejaVu24)
    lcd.print(label, max(5, 160 - len(label) * 7), 100, FG_MUTED)
    lcd.font(lcd.FONT_Default)
    lcd.print("Please wait", 120, 140, FG_DIM)


def draw_action_loading(action):
    """Loading screen that previews the announcement header so the transition
    feels intentional rather than generic."""
    meta = _ACTION_META.get(action, ("ANNOUNCEMENT", ACCENT_BLUE, "Fetching..."))
    header, color, loading_msg = meta
    clear_screen()
    lcd.fillRect(0, 0, 320, 28, color)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(header, max(5, 160 - len(header) * 6), 5, FG_BRIGHT)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(loading_msg, max(5, 160 - len(loading_msg) * 6), 108, FG_MUTED)
    lcd.font(lcd.FONT_Default)
    lcd.print("Please wait", 120, 143, FG_DIM)


def draw_actions():
    clear_screen()
    draw_topbar("ACTIONS")
    BTN_W = 320 // 3
    BTN_H = (220 - 20) // 2   # 2 rows in the 20-220 content area
    for i, (label, _, sym, sym_col) in enumerate(ACTION_MENU):
        row = i // 3
        col = i % 3
        x = col * BTN_W
        y = 20 + row * BTN_H
        cx = x + BTN_W // 2
        # Card background + accent border
        lcd.fillRect(x + 2, y + 2, BTN_W - 4, BTN_H - 4, BG_PANEL)
        lcd.rect(x + 2, y + 2, BTN_W - 4, BTN_H - 4, sym_col)
        # Symbol — large, centered, colored (upper third of card)
        lcd.font(lcd.FONT_DejaVu18)
        sym_y = y + BTN_H // 4
        lcd.print(sym, cx - len(sym) * 6, sym_y, sym_col)
        # Divider
        lcd.line(x + 8, y + BTN_H // 2 + 2, x + BTN_W - 8, y + BTN_H // 2 + 2, 0x2A2A2A)
        # Label — centered below divider
        lcd.font(lcd.FONT_Default)
        label_x = cx - len(label) * 3
        lcd.print(label, max(x + 5, label_x), y + BTN_H // 2 + 10, FG_BRIGHT)
    draw_footer_buttons("FORECAST", "TRAINS", "HOME")


# ─────────────────────────────────────────────────────────────────────────────
# State drawing — ANSWER / ANNOUNCEMENT / OFFLINE
# ─────────────────────────────────────────────────────────────────────────────
def wrap_lines(text, width=30, max_lines=4):
    """Tiny word-wrap for MicroPython — splits on spaces, no fancy
    hyphenation. Returns up to max_lines lines."""
    text = text or ""
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 <= width:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines[:max_lines]


def draw_announcement(text, action=""):
    clear_screen()
    meta = _ACTION_META.get(action, ("ANNOUNCEMENT", ACCENT_BLUE, ""))
    header, color, _ = meta
    lcd.fillRect(0, 0, 320, 28, color)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(header, max(5, 160 - len(header) * 6), 5, FG_BRIGHT)
    if text:
        # DejaVu24: ~16px wide per char → wrap at 18 chars, 30px line height
        lines = wrap_lines(text, width=18, max_lines=6)
        line_h = 30
        # Vertically center the text block between header (y=28) and footer (y=220)
        start_y = 28 + (192 - len(lines) * line_h) // 2
        lcd.font(lcd.FONT_DejaVu24)
        for i, line in enumerate(lines):
            lcd.print(line, max(5, 160 - len(line) * 8), start_y + i * line_h, FG_BRIGHT)
    else:
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print("Playing...", max(5, 160 - 10 * 6), 108, FG_MUTED)
    draw_footer("Playing...")


def draw_offline():
    clear_screen()
    lcd.font(lcd.FONT_DejaVu40)
    lcd.print("OFFLINE", 60, 60, ACCENT_RED)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print("Checking network...", 50, 130, FG_MUTED)
    lcd.font(lcd.FONT_Default)
    lcd.print("Last sync: " + last_sync_label, 90, 170, FG_DIM)
    lcd.print("Sensors still active", 80, 195, FG_DIM)


# ─────────────────────────────────────────────────────────────────────────────
# State dispatcher
# ─────────────────────────────────────────────────────────────────────────────
def go(new_state):
    global state
    state = new_state
    draw_current()


def draw_current():
    if   state == S_HOME:     draw_home()
    elif state == S_FORECAST: draw_forecast()
    elif state == S_TRAINS:   draw_trains()
    elif state == S_ACTIONS:  draw_actions()
    elif state == S_OFFLINE:  draw_offline()


# ─────────────────────────────────────────────────────────────────────────────
# High-level action handlers
# ─────────────────────────────────────────────────────────────────────────────
def read_local_sensors():
    """Read every tick. Cheap and feeds the home screen + motion indicator."""
    global indoor_temp, indoor_humi, indoor_tvoc, indoor_eco2, motion_now
    try: indoor_temp = round(env3.temperature, 1)
    except: pass
    try: indoor_humi = round(env3.humidity, 1)
    except: pass
    try: indoor_tvoc = tvoc_sensor.TVOC
    except: pass
    try: indoor_eco2 = tvoc_sensor.eCO2
    except: pass
    try: motion_now = bool(pir.state)
    except: pass



def motion_action_for_now():
    """Returns 'morning_briefing' once per day when the user walks past in
    the 7-9 am window; falls through to 'motion' otherwise."""
    global last_morning_date
    h = now_hour()
    if 7 <= h < 9:
        td = today_str()
        if td and td != last_morning_date:
            last_morning_date = td
            return "morning_briefing"
    return "motion"


def play_wav(path):
    try: speaker.playWAV(path, 0)   # CHN_LR=0 (both channels, loudest available)
    except: pass


def play_announcement_with_screen(action, return_state=None, force=False):
    """Fetch the announcement, show the screen, THEN play audio so the user
    sees the text while listening. force=True always generates a response."""
    if return_state is None:
        return_state = S_HOME
    draw_action_loading(action)
    text, _reason = play_announcement(action, force=force)
    if text is None:
        _SKIP_MSG = {
            "rain_reminder":     "No rain forecast in the next 6 hours.",
            "humidity_alert":    "Indoor humidity is within normal range.",
            "air_quality_alert": "Air quality is currently fine.",
            "train_delay":       "All trains are running on time.",
            "morning_briefing":  "Outside the morning briefing window.",
            "current_summary":   "Could not retrieve weather data.",
        }
        meta = _ACTION_META.get(action, ("ANNOUNCEMENT", ACCENT_BLUE, ""))
        header, color, _ = meta
        clear_screen()
        lcd.fillRect(0, 0, 320, 28, color)
        lcd.font(lcd.FONT_DejaVu18)
        lcd.print(header, max(5, 160 - len(header) * 6), 5, FG_BRIGHT)
        lcd.line(0, 28, 320, 28, 0x2A2A2A)
        lcd.font(lcd.FONT_DejaVu18)
        nothing = "Nothing to report"
        lcd.print(nothing, max(5, 160 - len(nothing) * 6), 90, FG_MUTED)
        msg = _SKIP_MSG.get(action, _reason or "Condition not met")
        lcd.font(lcd.FONT_Default)
        for i, line in enumerate(wrap_lines(msg, width=44, max_lines=3)):
            lcd.print(line, max(5, 160 - len(line) * 3), 130 + i * 16, color)
        draw_footer("Returning...")
        wait(2)
        go(return_state)
        return
    # Draw the announcement screen first, play audio second
    go(S_ANNOUNCEMENT)
    draw_announcement(text, action=action)
    play_wav(ANNOUNCE_WAV_FILE)        # user reads the text while this plays
    wait(ANN_HOLD_S)
    go(return_state)


#def force_sync():
#    """BtnA on  — push fresh data immediately."""
#    global last_send, last_outdoor
#    send_data()
#    fetch_outdoor()
#    last_send = time.time()
#    last_outdoor = time.time()
#    if state == S_HOME:
#        draw_home()


def toggle_home_forecast():
    """BtnC — flip between HOME and FORECAST."""
    if state == S_HOME:
        go(S_FORECAST)
    elif state == S_FORECAST:
        go(S_HOME)


def toggle_forecast_mode():
    """BtnB on FORECAST — daily ↔ hourly."""
    global forecast_mode
    forecast_mode = "hourly" if forecast_mode == "daily" else "daily"
    draw_forecast()


def tick_animations():
    global anim_tick
    anim_tick += 1
    if state == S_HOME:
        draw_motion_dot()


# ─────────────────────────────────────────────────────────────────────────────
# Boot sequence
# ─────────────────────────────────────────────────────────────────────────────
clear_screen()
lcd.font(lcd.FONT_DejaVu18)
lcd.print("Connecting WiFi...", 60, 110, FG_BRIGHT)

try:
    wifiCfg.autoConnect(lcdShow=False)
except:
    pass

wait(2)

# Sync the RTC to NTP so the clock in the top bar shows real local time.
# Without this, M5Stack's RTC counts from 00:00 at boot.
clear_screen()
lcd.font(lcd.FONT_DejaVu18)
lcd.print("Syncing clock...", 65, 110, FG_BRIGHT)
ntp_sync()

ensure_icons_dir()

clear_screen()
lcd.font(lcd.FONT_DejaVu18)
lcd.print("Loading last data...", 50, 110, FG_BRIGHT)

fetch_last_row()
fetch_forecast()

go(S_HOME)


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────
while True:
    now_s = time.time()

    # 1. WiFi sentinel
    if not wifi_ok():
        if state != S_OFFLINE:
            go(S_OFFLINE)
        try:
            wifiCfg.autoConnect()
        except:
            pass
        wait(1)
        continue
    elif state == S_OFFLINE:
        go(S_HOME)

    # 2. Local sensors every tick
    read_local_sensors()

    # 3. Periodic sensor upload (5 min)
    if now_s - last_send >= SEND_INTERVAL_S:
        send_data()
        last_send = now_s
        if state == S_HOME:
            draw_home()

    # 4. Periodic outdoor refresh (5 min)
    if now_s - last_outdoor >= OUTDOOR_INTERVAL_S:
        fetch_outdoor()
        last_outdoor = now_s
        if state == S_HOME:
            draw_home()

    # 5. Forecast cache refresh (10 min)
    if now_s - last_forecast >= FORECAST_INTERVAL_S:
        fetch_forecast()
        last_forecast = now_s
        if state == S_FORECAST:
            draw_forecast()

    # 6. Motion-triggered announcement — morning only (06:00–11:00).
    # Manual announcements via BtnB work at any hour.
    if motion_now and (now_s - last_announce) >= ANNOUNCE_COOLDOWN_S:
        if 6 <= now_hour() < 11:
            action = motion_action_for_now()
            last_announce = now_s
            play_announcement_with_screen(action)

    # 7. Touchscreen — action menu (time-based debounce, 1 s between taps)
    _cur_touch = _get_touch()
    if state == S_ACTIONS and _cur_touch and now_s - _last_tap_time > 1:
        _last_tap_time = now_s
        tx, ty = _cur_touch
        BTN_W = 320 // 3
        BTN_H = (220 - 20) // 2
        col = tx // BTN_W
        row = (ty - 20) // BTN_H
        if 0 <= row < 2 and 0 <= col < 3:
            idx = row * 3 + col
            if idx < len(ACTION_MENU):
                _, action, _, _ = ACTION_MENU[idx]
                play_announcement_with_screen(action, return_state=S_ACTIONS, force=True)

    # 8. Physical buttons
    if btnA.wasPressed():
        if state in (S_HOME, S_FORECAST):
            go(S_ACTIONS)
        elif state == S_ACTIONS:
            go(S_FORECAST)
        elif state == S_TRAINS:
            draw_loading("Refreshing...")
            fetch_trains()
            go(S_TRAINS)
        elif state in (S_ANSWER, S_ANNOUNCEMENT):
            go(S_HOME)
    if btnB.wasPressed():
        if state == S_HOME:
            draw_loading("Fetching trains...")
            fetch_trains()
            go(S_TRAINS)
        elif state == S_FORECAST:
            toggle_forecast_mode()
        elif state == S_ACTIONS:
            draw_loading("Fetching trains...")
            fetch_trains()
            go(S_TRAINS)
        elif state in (S_ANSWER, S_ANNOUNCEMENT, S_TRAINS):
            go(S_HOME)
    if btnC.wasPressed():
        if state in (S_HOME, S_FORECAST):
            toggle_home_forecast()
        elif state in (S_ANSWER, S_ANNOUNCEMENT, S_TRAINS, S_ACTIONS):
            go(S_HOME)

    # 9. Animation tick
    tick_animations()

    wait(1)
    wait_ms(2)