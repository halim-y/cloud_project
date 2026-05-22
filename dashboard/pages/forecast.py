import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from utils import (
    COMMON_CSS, COLOR_TEMP, COLOR_HUMI,
    fetch_flask, apply_chart_theme, hex_to_rgba, section_label,
    get_weather_bg, weather_overlay_html, temp_quality,
)

st.markdown(COMMON_CSS, unsafe_allow_html=True)

data = fetch_flask("/forecast")

if not data:
    st.warning("Forecast data unavailable — backend unreachable.")
    st.stop()

daily  = data.get("daily", [])
hourly = data.get("hourly_today", [])

# Dynamic background + animation based on today's condition
today_condition = hourly[0]["description"] if hourly else (daily[0]["description"] if daily else "")
st.markdown(get_weather_bg(today_condition), unsafe_allow_html=True)
overlay = weather_overlay_html(today_condition)
if overlay:
    st.markdown(overlay, unsafe_allow_html=True)

# Page header with today's snapshot
st.markdown("# 🌤 Forecast")
if daily:
    d0 = daily[0]
    t_color = temp_quality(d0["temp_max"])[1]
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:4px;">'
        f'<img src="https://openweathermap.org/img/wn/{d0["icon"]}@2x.png" width="48">'
        f'<div>'
        f'<span style="font-size:20px;font-weight:700;color:#ddd;text-transform:capitalize;">'
        f'{d0["description"]}</span>'
        f'<span style="font-size:14px;color:#555;margin-left:12px;">'
        f'{d0["temp_max"]:.0f}° high · {d0["temp_min"]:.0f}° low · 💧{d0["humidity"]}%'
        f'</span></div></div>',
        unsafe_allow_html=True,
    )

CARD_BG     = "rgba(30,33,48,0.6)"
CARD_BORDER = "1px solid rgba(255,255,255,0.07)"
CARD_BLUR   = "backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);"

# 5-day daily cards
if daily:
    section_label("📅 5-Day Forecast")
    html = '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px;">'
    for i, d in enumerate(daily):
        is_today  = (i == 0)
        bg        = "rgba(40,44,62,0.88)" if is_today else CARD_BG
        border    = "2px solid rgba(255,255,255,0.18)" if is_today else CARD_BORDER
        today_tag = (
            '<div style="font-size:9px;color:#aaa;letter-spacing:1.5px;'
            'text-transform:uppercase;margin-bottom:4px;">Today</div>'
            if is_today else ""
        )
        t_color = temp_quality(d["temp_max"])[1]
        icon_url = f"https://openweathermap.org/img/wn/{d['icon']}@2x.png"
        html += (
            f'<div style="background:{bg};{CARD_BLUR}border:{border};'
            f'border-radius:16px;padding:16px 14px;min-width:130px;flex:1;text-align:center;">'
            f'{today_tag}'
            f'<div style="font-size:13px;font-weight:600;color:#ccc;margin-bottom:2px;">{d["day"]}</div>'
            f'<div style="font-size:11px;color:#555;margin-bottom:8px;">{d["date"]}</div>'
            f'<img src="{icon_url}" width="50" style="margin:4px 0;">'
            f'<div style="font-size:18px;font-weight:700;color:{t_color};margin-top:4px;letter-spacing:-0.5px;">'
            f'{d["temp_max"]:.0f}°'
            f'<span style="color:#555;font-size:14px;font-weight:400;"> / {d["temp_min"]:.0f}°</span>'
            f'</div>'
            f'<div style="font-size:11px;color:#777;text-transform:capitalize;margin-top:6px;">{d["description"]}</div>'
            f'<div style="font-size:11px;color:#4A9ECC;margin-top:4px;">💧 {d["humidity"]}%</div>'
            f'</div>'
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)

# Today's hourly strip + dual chart
if hourly:
    section_label("⏱ Today's Hourly")
    strip = '<div style="display:flex;gap:14px;overflow-x:auto;padding:8px 0 16px;">'
    for h in hourly:
        icon_url = f"https://openweathermap.org/img/wn/{h['icon']}@2x.png"
        t_color  = temp_quality(h["temp"])[1]
        strip += (
            f'<div style="background:{CARD_BG};{CARD_BLUR}border:{CARD_BORDER};'
            f'border-radius:14px;padding:16px 14px;min-width:120px;flex-shrink:0;text-align:center;">'
            f'<div style="font-size:13px;color:#888;margin-bottom:8px;">{h["time"]}</div>'
            f'<img src="{icon_url}" width="56">'
            f'<div style="font-size:24px;font-weight:700;color:{t_color};margin-top:6px;letter-spacing:-0.5px;">'
            f'{h["temp"]:.0f}°</div>'
            f'<div style="font-size:12px;color:#4A9ECC;margin-top:4px;">💧{h["humidity"]}%</div>'
            f'</div>'
        )
    strip += "</div>"
    st.markdown(strip, unsafe_allow_html=True)

    df_h = pd.DataFrame(hourly)
    if not df_h.empty and "temp" in df_h.columns:
        section_label("📈 Today's Temperature & Humidity")
        t_color_today = temp_quality(df_h["temp"].mean())[1]
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_h["time"], y=df_h["temp"], name="Temperature (°C)",
            mode="lines+markers",
            line=dict(color=t_color_today, width=2.5),
            fill="tozeroy", fillcolor=hex_to_rgba(t_color_today, 0.12),
            marker=dict(size=7, color=t_color_today),
        ))
        if "humidity" in df_h.columns:
            fig.add_trace(go.Scatter(
                x=df_h["time"], y=df_h["humidity"], name="Humidity (%)",
                mode="lines",
                line=dict(color=COLOR_HUMI, width=2, dash="dot"),
                yaxis="y2",
            ))
        fig.update_layout(
            yaxis2=dict(
                overlaying="y", side="right", showgrid=False,
                tickfont=dict(color=COLOR_HUMI, size=9), range=[0, 100],
            ),
        )
        st.plotly_chart(apply_chart_theme(fig), use_container_width=True)
