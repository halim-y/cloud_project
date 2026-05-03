from m5stack import *
from m5ui import *
from uiflow import *
import wifiCfg
import ntptime
import utime
import urequests
import ujson
import unit
from machine import I2C, Pin

# ── Constants ────────────────────────────────────────────────────────────────
FLASK_URL     = "https://cloud-project-470570889014.europe-west6.run.app"
PASSWORD_HASH = "f4f263e439cf40925e6a412387a9472a6773c2580212a4fb50d224d3a817de17"
TZ_OFFSET     = 2  # UTC+2 (Switzerland summer time)

# ── Sensors ───────────────────────────────────────────────────────────────────
env3 = unit.get(unit.ENV3, unit.PORTA)   # PORTA — I2C (GPIO 32/33)
pir  = unit.get(unit.PIR,  unit.PORTB)   # PORTB — digital (GPIO 36/26)

# TVOC on PORTC using software I2C (bit-bang) on GPIO 13 (SDA) and GPIO 14 (SCL)
# PORTC pins on Core2 AWS are GPIO 13 and GPIO 14
i2c_portc    = I2C(sda=Pin(13), scl=Pin(14), freq=100000)
tvoc_sensor  = unit.get(unit.TVOC, unit.PORTC)

# ── Display setup ─────────────────────────────────────────────────────────────
setScreenColor(0x111111)

title_lbl = M5TextBox(40, 8, "WEATHER STATION", lcd.FONT_DejaVu18, 0xFFFFFF, rotate=0)

indoor_hdr  = M5TextBox(10,  38, "-- INDOOR --",  lcd.FONT_DejaVu18, 0xAAAAAA, rotate=0)
outdoor_hdr = M5TextBox(165, 38, "-- OUTDOOR --", lcd.FONT_DejaVu18, 0xAAAAAA, rotate=0)

in_temp_lbl = M5TextBox(10,  65,  "Temp: --",   lcd.FONT_DejaVu18, 0xFF6600, rotate=0)
in_humi_lbl = M5TextBox(10,  90,  "Humi: --",   lcd.FONT_DejaVu18, 0x00AAFF, rotate=0)
in_tvoc_lbl = M5TextBox(10,  115, "TVOC: --",   lcd.FONT_DejaVu18, 0x00FF88, rotate=0)
in_eco2_lbl = M5TextBox(10,  140, "eCO2: --",   lcd.FONT_DejaVu18, 0x00FF88, rotate=0)
in_pir_lbl  = M5TextBox(10,  165, "Motion: --", lcd.FONT_DejaVu18, 0xFF00FF, rotate=0)

out_temp_lbl    = M5TextBox(165, 65,  "Temp: --", lcd.FONT_DejaVu18, 0xFF6600, rotate=0)
out_humi_lbl    = M5TextBox(165, 90,  "Humi: --", lcd.FONT_DejaVu18, 0x00AAFF, rotate=0)
out_weather_lbl = M5TextBox(165, 115, "--",        lcd.FONT_DejaVu18, 0xFFFF00, rotate=0)

sync_lbl = M5TextBox(10, 210, "Connecting...", lcd.FONT_DejaVu18, 0x888888, rotate=0)


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_timestamp():
    t = utime.localtime(utime.time() + TZ_OFFSET * 3600)
    date_str = "{:04d}-{:02d}-{:02d}".format(t[0], t[1], t[2])
    time_str = "{:02d}:{:02d}:{:02d}".format(t[3], t[4], t[5])
    return date_str, time_str


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
            out_temp_lbl.setText("Temp: " + str(data["outdoor_temp"]) + "C")
            out_humi_lbl.setText("Humi: " + str(int(data["outdoor_humidity"])) + "%")
            out_weather_lbl.setText(str(data["outdoor_weather"])[:13])
    except:
        out_weather_lbl.setText("offline")


def send_data(date_str, time_str, temp, humi, tvoc, eco2, motion):
    try:
        payload = {
            "passwd": PASSWORD_HASH,
            "values": {
                "date":             date_str,
                "time":             time_str,
                "indoor_temp":      temp,
                "indoor_humidity":  humi,
                "air_quality_tvoc": tvoc,
                "air_quality_eco2": eco2,
                "motion":           motion,
            }
        }
        resp = urequests.post(
            FLASK_URL + "/send-to-bigquery",
            data=ujson.dumps(payload),
            headers={"Content-Type": "application/json"}
        )
        resp.close()
    except:
        sync_lbl.setText("Sync failed")


# ── WiFi + NTP ────────────────────────────────────────────────────────────────
wifiCfg.autoConnect(lcdShow=True)
try:
    ntptime.settime()
except:
    pass

# ── On boot: show last known outdoor weather immediately ──────────────────────
fetch_outdoor()

# ── Main loop (every 5 minutes) ───────────────────────────────────────────────
while True:
    temperature = round(env3.temperature, 1)
    humidity    = round(env3.humidity, 1)
    tvoc        = tvoc_sensor.TVOC
    eco2        = tvoc_sensor.eCO2
    motion      = pir.state

    date_str, time_str = get_timestamp()

    in_temp_lbl.setText("Temp: " + str(temperature) + "C")
    in_humi_lbl.setText("Humi: " + str(humidity) + "%")
    in_tvoc_lbl.setText("TVOC: " + str(tvoc) + "ppb")
    in_eco2_lbl.setText("eCO2: " + str(eco2) + "ppm")
    in_pir_lbl.setText("Motion: " + ("YES" if motion else "NO"))

    send_data(date_str, time_str, temperature, humidity, tvoc, eco2, motion)
    fetch_outdoor()

    sync_lbl.setText("Synced: " + time_str)

    wait(300)
    wait_ms(2)