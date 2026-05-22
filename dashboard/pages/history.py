from datetime import date, timedelta
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from utils import (
    COMMON_CSS, COLOR_TEMP, COLOR_HUMI, COLOR_AIR, COLOR_ECO2,
    load_data_range, metric_card, apply_chart_theme, hex_to_rgba,
    section_label,
)

st.markdown(COMMON_CSS, unsafe_allow_html=True)
st.markdown("# 📅 History")

today = date.today()
dates = st.date_input(
    "Select date or range",
    value=(today - timedelta(days=7), today),
    max_value=today,
)

if isinstance(dates, (list, tuple)):
    start = dates[0]
    end   = dates[1] if len(dates) == 2 else dates[0]
else:
    start = end = dates

df = load_data_range(str(start), str(end))

if df.empty:
    st.warning("No data for the selected date range.")
    st.stop()

section_label("📊 Summary")
c1, c2, c3, c4 = st.columns(4)
with c1:
    avg = df["indoor_temp"].mean()
    metric_card("Avg Indoor Temp", f"{avg:.1f}", "°C", COLOR_TEMP, "🌡️")
with c2:
    avg = df["indoor_humidity"].mean()
    metric_card("Avg Indoor Humidity", f"{avg:.0f}", "%", COLOR_HUMI, "💧")
with c3:
    avg = df["air_quality_tvoc"].mean()
    metric_card("Avg TVOC", f"{avg:.0f}" if pd.notna(avg) else "--", "ppb", COLOR_AIR, "🌬️")
with c4:
    avg = df["air_quality_eco2"].mean()
    metric_card("Avg eCO₂", f"{avg:.0f}" if pd.notna(avg) else "--", "ppm", COLOR_ECO2, "🌿")

section_label("📈 Charts")

col_left, col_right = st.columns(2)

with col_left:
    section_label("🌡️ Temperature (°C)")
    fig = go.Figure()
    if "indoor_temp" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=df["indoor_temp"], name="Indoor",
            mode="lines", line=dict(color=COLOR_TEMP, width=2.5),
            fill="tozeroy", fillcolor=hex_to_rgba(COLOR_TEMP, 0.12),
        ))
    if "outdoor_temp" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=df["outdoor_temp"], name="Outdoor",
            mode="lines", line=dict(color="#c07030", width=2),
            fill="tozeroy", fillcolor="rgba(192,112,48,0.08)",
        ))
    st.plotly_chart(apply_chart_theme(fig), use_container_width=True)

with col_right:
    section_label("💧 Humidity (%)")
    fig = go.Figure()
    if "indoor_humidity" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=df["indoor_humidity"], name="Indoor",
            mode="lines", line=dict(color=COLOR_HUMI, width=2.5),
            fill="tozeroy", fillcolor=hex_to_rgba(COLOR_HUMI, 0.12),
        ))
    if "outdoor_humidity" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=df["outdoor_humidity"], name="Outdoor",
            mode="lines", line=dict(color="#2a6e9e", width=2),
            fill="tozeroy", fillcolor="rgba(42,110,158,0.08)",
        ))
    st.plotly_chart(apply_chart_theme(fig), use_container_width=True)

air_cols = [c for c in ["air_quality_tvoc", "air_quality_eco2"] if c in df.columns]
if air_cols:
    section_label("🌬️ Air Quality")
    fig = go.Figure()
    if "air_quality_tvoc" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=df["air_quality_tvoc"], name="TVOC (ppb)",
            mode="lines", line=dict(color=COLOR_AIR, width=2.5),
            fill="tozeroy", fillcolor=hex_to_rgba(COLOR_AIR, 0.12),
        ))
    if "air_quality_eco2" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=df["air_quality_eco2"], name="eCO₂ (ppm)",
            mode="lines", line=dict(color=COLOR_ECO2, width=2),
            fill="tozeroy", fillcolor=hex_to_rgba(COLOR_ECO2, 0.10),
        ))
    st.plotly_chart(apply_chart_theme(fig), use_container_width=True)

with st.expander("📋 Raw data", expanded=False):
    display_cols = [
        "datetime", "indoor_temp", "indoor_humidity",
        "air_quality_tvoc", "air_quality_eco2",
        "outdoor_temp", "outdoor_humidity", "outdoor_weather",
    ]
    st.dataframe(
        df[[c for c in display_cols if c in df.columns]],
        width="stretch",
    )
