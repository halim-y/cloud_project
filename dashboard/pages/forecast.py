import streamlit as st
from utils import (
    COMMON_CSS,
    fetch_flask, section_label,
    get_weather_bg, weather_overlay_html, temp_quality,
)

st.markdown(COMMON_CSS, unsafe_allow_html=True)

data = fetch_flask("/forecast")

if not data:
    st.warning("Forecast data unavailable — backend unreachable.")
    st.stop()

daily  = data.get("daily", [])
hourly = data.get("hourly_upcoming") or data.get("hourly_today") or []

today_condition = hourly[0]["description"] if hourly else (daily[0]["description"] if daily else "")
st.markdown(get_weather_bg(today_condition), unsafe_allow_html=True)
overlay = weather_overlay_html(today_condition)
if overlay:
    st.markdown(overlay, unsafe_allow_html=True)

st.markdown("# 🌤 Forecast")
if daily:
    d0 = daily[0]
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

# ── 5-day daily cards ─────────────────────────────────────────────────────────
if daily:
    section_label("📅 5-Day Forecast")
    html = '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px;">'
    for i, d in enumerate(daily):
        is_today = (i == 0)
        bg       = "rgba(40,44,62,0.88)" if is_today else CARD_BG
        border   = "2px solid rgba(255,255,255,0.18)" if is_today else CARD_BORDER
        today_tag = (
            '<div style="font-size:9px;color:#aaa;letter-spacing:1.5px;'
            'text-transform:uppercase;margin-bottom:4px;">Today</div>'
            if is_today else ""
        )
        t_color  = temp_quality(d["temp_max"])[1]
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

# ── Upcoming hourly SVG chart (replaces card strip) ───────────────────────────
if hourly:
    section_label("⏱ Next 18 Hours")

    temps    = [float(h["temp"])      for h in hourly]
    humids   = [float(h["humidity"])  for h in hourly]
    times    = [h["time"]             for h in hourly]
    icons    = [h.get("icon", "01d") for h in hourly]
    t_colors = [temp_quality(t)[1]   for t in temps]
    n        = len(hourly)

    t_min = min(temps); t_max = max(temps)
    if t_max - t_min < 2:
        t_max = t_min + 2

    # ── SVG coordinate system ─────────────────────────────────────────────────
    VW       = 700
    LEFT     = 45;  RIGHT = VW - 45;  PW = RIGHT - LEFT
    ICON_Y   = 4;   ICON_SZ = 50
    PLOT_TOP = 82;  PLOT_BOT = 190
    TIME_Y   = 207
    VH       = 220

    step = PW / (n - 1) if n > 1 else PW
    xs   = [LEFT + i * step for i in range(n)]

    # Temperature Y positions (higher temp → lower y)
    ys_t = [
        PLOT_BOT - (t - t_min) / (t_max - t_min) * (PLOT_BOT - PLOT_TOP)
        for t in temps
    ]
    # Humidity Y positions (0% at bottom, 100% at top of the same range)
    ys_h = [PLOT_BOT - (h / 100) * (PLOT_BOT - PLOT_TOP) for h in humids]

    # ── Gradient defs ─────────────────────────────────────────────────────────
    # Horizontal temperature-color gradient for the fill area
    h_stops = "".join(
        f'<stop offset="{(xs[i] - LEFT) / PW * 100:.1f}%"'
        f' stop-color="{t_colors[i]}"/>'
        for i in range(n)
    )
    grad_defs = (
        f'<linearGradient id="hg" x1="{LEFT}" x2="{RIGHT}" y1="0" y2="0"'
        f' gradientUnits="userSpaceOnUse">{h_stops}</linearGradient>'
        # Vertical mask: opaque at top, transparent at bottom
        f'<linearGradient id="vmg" x1="0" x2="0" y1="{PLOT_TOP}" y2="{PLOT_BOT}"'
        f' gradientUnits="userSpaceOnUse">'
        f'<stop offset="0%" stop-color="white" stop-opacity="0.35"/>'
        f'<stop offset="100%" stop-color="white" stop-opacity="0"/>'
        f'</linearGradient>'
        f'<mask id="vm">'
        f'<rect x="{LEFT}" y="{PLOT_TOP}" width="{PW}" height="{PLOT_BOT - PLOT_TOP}"'
        f' fill="url(#vmg)"/>'
        f'</mask>'
    )

    # ── Fill area (temp gradient + vertical fade) ─────────────────────────────
    fill_path = (
        f"M{xs[0]:.1f},{ys_t[0]:.1f}"
        + "".join(f" L{x:.1f},{y:.1f}" for x, y in zip(xs[1:], ys_t[1:]))
        + f" L{xs[-1]:.1f},{PLOT_BOT} L{xs[0]:.1f},{PLOT_BOT} Z"
    )
    fill_elem = f'<path d="{fill_path}" fill="url(#hg)" mask="url(#vm)"/>'

    # ── Temperature line (per-segment color) ──────────────────────────────────
    temp_line = ""
    for i in range(n - 1):
        mid_color = temp_quality((temps[i] + temps[i + 1]) / 2)[1]
        temp_line += (
            f'<line x1="{xs[i]:.1f}" y1="{ys_t[i]:.1f}"'
            f' x2="{xs[i+1]:.1f}" y2="{ys_t[i+1]:.1f}"'
            f' stroke="{mid_color}" stroke-width="2.5" stroke-linecap="round"/>'
        )

    # ── Humidity line (dotted blue) ───────────────────────────────────────────
    hpts      = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys_h))
    humi_line = (
        f'<polyline points="{hpts}" fill="none" stroke="#4A9ECC"'
        f' stroke-width="1.5" stroke-dasharray="5,4" stroke-linecap="round"/>'
    )

    # ── Dots ──────────────────────────────────────────────────────────────────
    temp_dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5"'
        f' fill="{c}" stroke="rgba(255,255,255,0.45)" stroke-width="2"/>'
        for x, y, c in zip(xs, ys_t, t_colors)
    )
    humi_dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#4A9ECC" opacity="0.85"/>'
        for x, y in zip(xs, ys_h)
    )

    # ── Labels ────────────────────────────────────────────────────────────────
    # Temp value above each dot (clamped away from icons)
    temp_lbls = "".join(
        f'<text x="{x:.1f}" y="{max(y - 11, PLOT_TOP - 2):.1f}"'
        f' text-anchor="middle" fill="{c}"'
        f' font-size="13" font-weight="600" font-family="Inter,sans-serif">{t:.0f}°</text>'
        for x, y, t, c in zip(xs, ys_t, temps, t_colors)
    )
    # Time labels
    time_lbls = "".join(
        f'<text x="{x:.1f}" y="{TIME_Y}"'
        f' text-anchor="middle" fill="#666"'
        f' font-size="11" font-family="Inter,sans-serif">{ts}</text>'
        for x, ts in zip(xs, times)
    )
    # Humidity values inline, above each humidity dot (mirroring temp labels)
    humi_lbls = "".join(
        f'<text x="{x:.1f}" y="{max(y - 8, PLOT_TOP - 2):.1f}"'
        f' text-anchor="middle" fill="#4A9ECC" opacity="0.85"'
        f' font-size="10" font-family="Inter,sans-serif">{h:.0f}%</text>'
        for x, y, h in zip(xs, ys_h, humids)
    )

    # ── Icons above each point ────────────────────────────────────────────────
    icon_imgs = "".join(
        f'<image href="https://openweathermap.org/img/wn/{icon}@2x.png"'
        f' x="{xs[i] - ICON_SZ / 2:.1f}" y="{ICON_Y}"'
        f' width="{ICON_SZ}" height="{ICON_SZ}"/>'
        for i, icon in enumerate(icons)
    )

    # ── Grid ──────────────────────────────────────────────────────────────────
    grid = (
        f'<line x1="{LEFT}" y1="{PLOT_TOP}" x2="{RIGHT}" y2="{PLOT_TOP}"'
        f' stroke="#1e2130" stroke-width="1"/>'
        f'<line x1="{LEFT}" y1="{PLOT_BOT}" x2="{RIGHT}" y2="{PLOT_BOT}"'
        f' stroke="#1e2130" stroke-width="1"/>'
    )

    svg_chart = (
        f'<div style="background:rgba(20,22,34,0.7);{CARD_BLUR}'
        f'border:{CARD_BORDER};border-radius:16px;padding:16px 12px 10px;">'
        f'<svg viewBox="0 0 {VW} {VH}" style="width:100%;display:block;"'
        f' xmlns="http://www.w3.org/2000/svg">'
        f'<defs>{grad_defs}</defs>'
        f'{grid}'
        f'{fill_elem}'
        f'{humi_line}'
        f'{temp_line}'
        f'{humi_dots}'
        f'{temp_dots}'
        f'{temp_lbls}'
        f'{time_lbls}'
        f'{humi_lbls}'
        f'{icon_imgs}'
        f'</svg></div>'
    )

    st.markdown(svg_chart, unsafe_allow_html=True)
