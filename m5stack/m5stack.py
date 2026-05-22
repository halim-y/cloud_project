from m5stack import *
from m5ui import *
from uiflow import *
import wifiCfg
import urequests
import ujson
import unit
import time
import os
from machine import I2C, Pin

# ── Constants ────────────────────────────────────────────────────────────────
FLASK_URL     = "https://cloud-project-470570889014.europe-west6.run.app"
PASSWORD_HASH = "f4f263e439cf40925e6a412387a9472a6773c2580212a4fb50d224d3a817de17"

# Sensor data is uploaded to BigQuery every 5 minutes, as required by the
# assignment. The main loop polls every second so motion can trigger
# announcements in between sends — the cadence below is still 300 s.
SEND_INTERVAL_S     = 300   # send sensor data every 5 minutes
ANNOUNCE_COOLDOWN_S = 3600  # at most one motion announcement per hour
ANNOUNCE_FILE       = "/flash/announce.wav"

# ── Sensors ───────────────────────────────────────────────────────────────────
env3 = unit.get(unit.ENV3, unit.PORTA)
pir  = unit.get(unit.PIR,  unit.PORTB)

i2c_portc   = I2C(sda=Pin(13), scl=Pin(14), freq=100000)
tvoc_sensor = unit.get(unit.TVOC, unit.PORTC)

# ── WiFi (must come before display setup — autoConnect draws a white overlay) ──
wifiCfg.autoConnect(lcdShow=True)
wait(2)  # let DHCP/DNS settle

# ── Display setup (after WiFi so the white overlay is gone) ───────────────────
setScreenColor(0x0A0A0A)

title_lbl = M5TextBox(30, 5, "WEATHER STATION", lcd.FONT_DejaVu18, 0xEEEEEE, rotate=0)

lcd.line(0, 25,  320, 25,  0x2A2A2A)
lcd.line(0, 146, 320, 146, 0x2A2A2A)
lcd.line(0, 204, 320, 204, 0x2A2A2A)

indoor_hdr  = M5TextBox(10, 29, "INDOOR", lcd.FONT_Default, 0x666666, rotate=0)
in_temp_lbl = M5TextBox(10,  40,  "Temp: --",   lcd.FONT_DejaVu18, 0xE8943A, rotate=0)
in_humi_lbl = M5TextBox(10,  61,  "Humi: --",   lcd.FONT_DejaVu18, 0x4A9ECC, rotate=0)
in_tvoc_lbl = M5TextBox(10,  82,  "TVOC: --",   lcd.FONT_DejaVu18, 0x4AAA77, rotate=0)
in_eco2_lbl = M5TextBox(10,  103, "eCO2: --",   lcd.FONT_DejaVu18, 0x4AAA77, rotate=0)
in_pir_lbl  = M5TextBox(10,  124, "Motion: --", lcd.FONT_DejaVu18, 0x9977BB, rotate=0)

outdoor_hdr     = M5TextBox(10,  150, "OUTDOOR", lcd.FONT_Default,  0x666666, rotate=0)
out_temp_lbl    = M5TextBox(10,  161, "T: --",   lcd.FONT_DejaVu18, 0xE8943A, rotate=0)
out_humi_lbl    = M5TextBox(175, 161, "H: --",   lcd.FONT_DejaVu18, 0x4A9ECC, rotate=0)
out_weather_lbl = M5TextBox(10,  182, "--",       lcd.FONT_DejaVu18, 0xAAAAAA, rotate=0)

sync_lbl = M5TextBox(10, 210, "Ready", lcd.FONT_DejaVu18, 0x444444, rotate=0)


# ── Helpers ───────────────────────────────────────────────────────────────────
def fetch_outdoor():
    try:
        resp = urequests.post(
            FLASK_URL + "/get_outdoor_weather",
            data=ujson.dumps({"passwd": PASSWORD_HASH}),
            headers={"Content-Type": "application/json"}
        )
        data = resp.json()
        resp.close()
        if data.get("status") == "success":
            t = data["outdoor_temp"]
            h = data["outdoor_humidity"]
            w = data["outdoor_weather"]
            out_temp_lbl.setText("T: " + (str(t) if t is not None else "--") + "C")
            out_humi_lbl.setText("H: " + (str(int(h)) if h is not None else "--") + "%")
            out_weather_lbl.setText(str(w)[:20] if w is not None else "--")
        else:
            out_weather_lbl.setText("no data yet")
    except:
        out_weather_lbl.setText("offline")


def send_data(temp, humi, tvoc, eco2):
    try:
        payload = {
            "passwd": PASSWORD_HASH,
            "values": {
                "indoor_temp":      temp,
                "indoor_humidity":  humi,
                "air_quality_tvoc": tvoc,
                "air_quality_eco2": eco2,
            }
        }
        resp = urequests.post(
            FLASK_URL + "/send-to-bigquery",
            data=ujson.dumps(payload),
            headers={"Content-Type": "application/json"}
        )
        result = resp.json()
        resp.close()
        if result.get("status") == "success":
            sync_lbl.setText("Synced: " + result.get("server_time", "?"))
        else:
            sync_lbl.setText("ERR: " + result.get("message", "err")[:14])
    except:
        sync_lbl.setText("Sync failed")


def play_announcement(action):
    """Ask backend for the right announcement, save the WAV, play it.

    Uses /announce-binary which returns raw WAV bytes directly (no JSON, no
    base64 decode) — much faster on the device. A 204 No Content response
    means the announcement condition was not met (e.g. rain reminder on a
    sunny day) and nothing should be played."""
    try:
        sync_lbl.setText("Announcing...")
        resp = urequests.post(
            FLASK_URL + "/announce-binary",
            data=ujson.dumps({
                "passwd": PASSWORD_HASH,
                "action": action,
            }),
            headers={"Content-Type": "application/json"}
        )
        status = resp.status_code
        if status == 204:
            resp.close()
            sync_lbl.setText("No announcement")
            return False
        if status != 200:
            resp.close()
            sync_lbl.setText("Ann HTTP " + str(status))
            return False
        wav_bytes = resp.content
        resp.close()
        with open(ANNOUNCE_FILE, "wb") as f:
            f.write(wav_bytes)
        speaker.playWAV(ANNOUNCE_FILE)
        sync_lbl.setText("Spoke: " + action[:10])
        return True
    except Exception as e:
        sync_lbl.setText("Ann err: " + str(e)[:10])
        return False


# ── On boot: show last known outdoor weather immediately ──────────────────────
fetch_outdoor()

# ── Main loop ─────────────────────────────────────────────────────────────────
# Tight 1-second poll. The old blocking wait(300) call meant motion events
# during the gap were lost; now motion is checked every second and the heavy
# sensor send runs on its own timer.

last_send     = -SEND_INTERVAL_S     # send immediately on first iteration
last_announce = -ANNOUNCE_COOLDOWN_S # allow first announcement right away

while True:
    now_s = time.time()

    # Always refresh the screen so it's lively
    temperature = round(env3.temperature, 1)
    humidity    = round(env3.humidity, 1)
    tvoc        = tvoc_sensor.TVOC
    eco2        = tvoc_sensor.eCO2
    motion      = pir.state

    in_temp_lbl.setText("Temp: " + str(temperature) + "C")
    in_humi_lbl.setText("Humi: " + str(humidity) + "%")
    in_tvoc_lbl.setText("TVOC: " + str(tvoc) + "ppb")
    in_eco2_lbl.setText("eCO2: " + str(eco2) + "ppm")
    in_pir_lbl.setText("Motion: " + ("YES" if motion else "NO"))

    # Periodic sensor upload + outdoor refresh
    if now_s - last_send >= SEND_INTERVAL_S:
        send_data(temperature, humidity, tvoc, eco2)
        fetch_outdoor()
        last_send = now_s

    # Motion-triggered announcement, at most once per hour
    if motion and (now_s - last_announce) >= ANNOUNCE_COOLDOWN_S:
        if play_announcement("motion"):
            last_announce = now_s

    wait(1)
    wait_ms(2)
