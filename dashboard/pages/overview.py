import time
import pandas as pd
import streamlit as st
from datetime import timedelta
from utils import (
    COMMON_CSS, COLOR_TEMP, COLOR_HUMI, COLOR_AIR, COLOR_ECO2,
    load_data, fetch_flask, metric_card, status_bar, make_gauge,
    get_weather_bg, weather_overlay_html, smoke_overlay_html,
    temp_quality, humidity_quality, tvoc_quality, eco2_quality,
    section_label,
)

TEMP_CONTEXT = {
    "Cold":        "Bundle up — it's cold in here",
    "Cool":        "A little cool — adjust as needed",
    "Comfortable": "Ideal room temperature",
    "Warm":        "Warmer than recommended",
    "Hot":         "Too warm — consider ventilating",
}
# Demo overlay options — label → condition string fed to get_weather_bg /
# weather_overlay_html. "Auto" keeps the live OpenWeather value.
OVERLAY_OPTIONS = {
    "Auto (live data)": None,
    "Clear sky":        "clear sky",
    "Broken clouds":    "broken clouds",
    "Overcast":         "overcast clouds",
    "Light rain":       "light rain",
    "Drizzle":          "drizzle",
    "Thunderstorm":     "thunderstorm",
    "Snow":             "snow",
    "Mist / Fog":       "mist",
}
HUMI_CONTEXT = {
    "Very Dry":    "Very dry — use a humidifier",
    "Dry":         "Consider using a humidifier",
    "Comfortable": "Humidity is in a healthy range",
    "Humid":       "A bit humid — monitor levels",
    "Very Humid":  "Too humid — consider a dehumidifier",
}

st.markdown(COMMON_CSS, unsafe_allow_html=True)

# Load latest + ~1h ago for delta calculation (13 readings × 5 min ≈ 1h)
df = load_data(13)
if df.empty:
    st.warning("No sensor data in BigQuery yet.")
    st.stop()

latest = df.iloc[-1]
prev   = df.iloc[0]
outdoor = fetch_flask("/current-outdoor")

# Computed values
t_val  = float(latest["indoor_temp"])      if pd.notna(latest["indoor_temp"])      else None
h_val  = float(latest["indoor_humidity"])  if pd.notna(latest["indoor_humidity"])  else None
tv_val = float(latest["air_quality_tvoc"]) if pd.notna(latest["air_quality_tvoc"]) else None
ec_val = float(latest["air_quality_eco2"]) if pd.notna(latest["air_quality_eco2"]) else None

t_delta  = (t_val  - float(prev["indoor_temp"]))      if t_val  and pd.notna(prev["indoor_temp"])      else None
h_delta  = (h_val  - float(prev["indoor_humidity"]))  if h_val  and pd.notna(prev["indoor_humidity"])  else None
tv_delta = (tv_val - float(prev["air_quality_tvoc"])) if tv_val and pd.notna(prev["air_quality_tvoc"]) else None
ec_delta = (ec_val - float(prev["air_quality_eco2"])) if ec_val and pd.notna(prev["air_quality_eco2"]) else None

out_desc = outdoor["outdoor_weather"] if outdoor else latest.get("outdoor_weather", "")
out_icon = outdoor.get("outdoor_icon") if outdoor else None

# Demo override (set via the dropdown at the bottom of the page)
_override = OVERLAY_OPTIONS.get(
    st.session_state.get("overlay_override_label", "Auto (live data)")
)
if _override:
    out_desc = _override

# Dynamic background + animated overlays
st.markdown(get_weather_bg(out_desc), unsafe_allow_html=True)
overlay = weather_overlay_html(out_desc)
if overlay:
    st.markdown(overlay, unsafe_allow_html=True)
if (tv_val and tv_val > 300) or (ec_val and ec_val > 1000):
    st.markdown(smoke_overlay_html(), unsafe_allow_html=True)

# Status bar
status_bar(latest["indoor_humidity"], latest["air_quality_tvoc"], latest["air_quality_eco2"])

# Hero header
st.markdown("# 🌤 IoT Weather Station")

# Freshness indicator — the M5Stack sends data every 5 min. If nothing has
# come in for a while, the dashboard probably is showing stale data and the
# device may be offline.
_now_local = pd.Timestamp.utcnow().tz_localize(None) + timedelta(hours=2)
_age_min   = max(0.0, (_now_local - pd.to_datetime(latest["datetime"])).total_seconds() / 60.0)
if _age_min < 1:
    _dot, _age_text = "🟢", "just now"
elif _age_min < 10:
    _dot, _age_text = "🟢", f"{int(_age_min)} min ago"
elif _age_min < 30:
    _dot, _age_text = "🟡", f"{int(_age_min)} min ago — device may be slow"
else:
    _dot, _age_text = "🔴", f"offline ({int(_age_min)} min)"

st.markdown(
    f"<span style='color:#555; font-size:14px;'>Geneva &nbsp;·&nbsp; "
    f"Last reading: {latest['date']} &nbsp;{latest['time']} "
    f"&nbsp;·&nbsp; {_dot} {_age_text}</span>",
    unsafe_allow_html=True,
)

# ── Indoor ────────────────────────────────────────────────────────────────────
section_label("🏠 Indoor")

# Gauges for temperature and humidity — temp color shifts with value
t_q     = temp_quality(t_val) if t_val is not None else None
t_color = t_q[1] if t_q else COLOR_TEMP

g1, g2 = st.columns(2)
with g1:
    fig = make_gauge(t_val or 0, "Temperature", "°C", t_color, 0, 40)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
with g2:
    fig = make_gauge(h_val or 0, "Humidity", "%", COLOR_HUMI, 0, 100)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

TVOC_CONTEXT = {
    "Excellent": "Air quality is excellent",
    "Good":      "Air quality is good",
    "Moderate":  "Getting stuffy — open a window",
    "Poor":      "Poor air quality — ventilate now",
}
ECO2_CONTEXT = {
    "Excellent": "CO₂ levels are optimal",
    "Good":      "CO₂ levels are fine",
    "Moderate":  "CO₂ building up — ventilate soon",
    "Poor":      "High CO₂ — open windows immediately",
}

c3, c4 = st.columns(2)
with c3:
    tv_q = tvoc_quality(tv_val) if tv_val is not None else None
    metric_card(
        "TVOC",
        f"{int(tv_val)}" if tv_val is not None else "--",
        "ppb", COLOR_AIR, "🌬️",
        quality=tv_q,
        delta=tv_delta,
        context=TVOC_CONTEXT.get(tv_q[0], "") if tv_q else None,
    )
with c4:
    ec_q = eco2_quality(ec_val) if ec_val is not None else None
    metric_card(
        "eCO₂",
        f"{int(ec_val)}" if ec_val is not None else "--",
        "ppm", COLOR_ECO2, "🌿",
        quality=ec_q,
        delta=ec_delta,
        context=ECO2_CONTEXT.get(ec_q[0], "") if ec_q else None,
    )

# ── Outdoor ───────────────────────────────────────────────────────────────────
section_label("🌍 Outdoor")

out_temp = outdoor["outdoor_temp"]     if outdoor else latest.get("outdoor_temp", "--")
out_humi = outdoor["outdoor_humidity"] if outdoor else latest.get("outdoor_humidity")

out_t_q = temp_quality(out_temp) if out_temp != "--" else None
out_h_q = humidity_quality(out_humi) if pd.notna(out_humi) else None

out_t_color = out_t_q[1] if out_t_q else COLOR_TEMP

c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    metric_card(
        "Temperature", f"{out_temp}", "°C", out_t_color, "🌡️",
        quality=out_t_q,
        context=TEMP_CONTEXT.get(out_t_q[0], "") if out_t_q else None,
    )
with c2:
    humi_str = f"{int(out_humi)}" if pd.notna(out_humi) else "--"
    metric_card(
        "Humidity", humi_str, "%", COLOR_HUMI, "💧",
        quality=out_h_q,
        context=HUMI_CONTEXT.get(out_h_q[0], "") if out_h_q else None,
    )
with c3:
    if out_icon:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:18px;height:100%;min-height:148px;padding:0 8px;">'
            f'<img src="https://openweathermap.org/img/wn/{out_icon}@4x.png" width="110" style="flex-shrink:0;">'
            f'<div style="font-size:26px;font-weight:700;color:#ddd;text-transform:capitalize;line-height:1.25;">{out_desc}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div style="display:flex;align-items:center;height:100%;min-height:148px;padding:0 8px;">'
            f'<div style="font-size:26px;font-weight:700;color:#ddd;text-transform:capitalize;">{out_desc or "—"}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

# Auto-refresh countdown
st.divider()

# Small demo control — override the weather overlay for in-class demos.
demo_col, _ = st.columns([2, 7])
with demo_col:
    st.selectbox(
        "Demo overlay",
        list(OVERLAY_OPTIONS.keys()),
        key="overlay_override_label",
        label_visibility="collapsed",
        help="Override the weather overlay for the demo. 'Auto' uses live data.",
    )

st.caption("↻ Auto-refreshes every 5 minutes")
time.sleep(300)
st.cache_data.clear()
st.rerun()
