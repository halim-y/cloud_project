import os
import random
import requests
import streamlit as st
from google.cloud import bigquery
import pandas as pd
import plotly.graph_objects as go

GCP_PROJECT = "acoustic-rider-487915-s8"
BQ_TABLE    = f"{GCP_PROJECT}.cloud_project.weather-records"
FLASK_URL   = os.environ.get("FLASK_URL", "https://cloud-project-470570889014.europe-west6.run.app")
PASSWORD_HASH = os.environ.get("PASSWORD_HASH")
if not PASSWORD_HASH:
    raise RuntimeError("PASSWORD_HASH env var is required")

COLOR_TEMP  = "#E8943A"
COLOR_HUMI  = "#4A9ECC"
COLOR_AIR   = "#4AAA77"
COLOR_ECO2  = "#9977BB"

COMMON_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="st-"], button, input, select, textarea {
    font-family: 'Inter', sans-serif !important;
}

/* Restore Material Symbols font on Streamlit's icon spans
   (otherwise the rule above turns icons into literal text like
   "keyboard_double_arrow_right"). */
[data-testid="stIconMaterial"],
span.material-symbols-rounded,
span.material-symbols-outlined,
span.material-icons {
    font-family: 'Material Symbols Rounded','Material Symbols Outlined','Material Icons' !important;
}

/* ── Weather animation keyframes ─────────────────────────────── */
@keyframes rainfall {
    0%   { transform: translateY(-40px) translateX(0);    opacity: 0; }
    8%   { opacity: 0.65; }
    92%  { opacity: 0.45; }
    100% { transform: translateY(105vh) translateX(20px); opacity: 0; }
}
@keyframes snowfall {
    0%   { transform: translateY(-20px) translateX(0);   opacity: 0; }
    10%  { opacity: 0.85; }
    90%  { opacity: 0.6; }
    100% { transform: translateY(105vh) translateX(40px); opacity: 0; }
}
@keyframes sunspeck {
    0%   { transform: translateY(80vh) translateX(0);    opacity: 0; }
    15%  { opacity: 0.5; }
    85%  { opacity: 0.3; }
    100% { transform: translateY(-10vh) translateX(15px); opacity: 0; }
}
@keyframes clouddrift {
    0%   { transform: translateX(-20vw); opacity: 0; }
    12%  { opacity: 0.45; }
    88%  { opacity: 0.35; }
    100% { transform: translateX(110vw);  opacity: 0; }
}
@keyframes fogdrift {
    0%   { transform: translateX(-30vw); opacity: 0; }
    15%  { opacity: 0.22; }
    85%  { opacity: 0.15; }
    100% { transform: translateX(110vw);  opacity: 0; }
}
/* Subtle ambient brighten that fires loosely in sync with the bolts —
   gives the "the room briefly lit up" feeling without burning the eyes. */
@keyframes lightning {
    0%, 91.5%, 93%, 100% { opacity: 0; }
    92%                    { opacity: 0.13; }
}

/* Bolt flash: most of the cycle invisible, brief main flash + a fainter
   re-flash 20 ms later (real lightning often double-strikes). */
@keyframes bolt-flash {
    0%, 49%, 52%, 52.9%, 54%, 100% { opacity: 0; }
    49.5%                            { opacity: 0.4; }
    50%                              { opacity: 1; }
    51%                              { opacity: 0.7; }
    53.3%                            { opacity: 0.55; }
}
@keyframes smokrise {
    0%   { transform: translateY(0)     scale(1);   opacity: 0.35; }
    100% { transform: translateY(-80px) scale(2.5); opacity: 0; }
}

/* ── Overlay base styles ─────────────────────────────────────── */
.rain-drop {
    position: fixed; width: 1.5px; height: 18px;
    background: linear-gradient(to bottom, transparent, rgba(130,190,255,0.55));
    border-radius: 2px;
    animation: rainfall linear infinite;
    pointer-events: none; z-index: 1;
}
.snow-flake {
    position: fixed; border-radius: 50%;
    background: rgba(210, 235, 255, 0.75);
    filter: blur(0.5px);
    animation: snowfall ease-in-out infinite;
    pointer-events: none; z-index: 1;
}
.sun-speck {
    position: fixed; border-radius: 50%;
    background: rgba(255, 195, 80, 0.55);
    filter: blur(2px);
    animation: sunspeck ease-in-out infinite;
    pointer-events: none; z-index: 1;
}
.cloud-patch {
    position: fixed; border-radius: 50%;
    background: rgba(205, 215, 230, 0.45);
    filter: blur(40px);
    animation: clouddrift linear infinite;
    pointer-events: none; z-index: 1;
}
.fog-patch {
    position: fixed; border-radius: 50%;
    background: rgba(180, 190, 200, 0.25);
    filter: blur(50px);
    animation: fogdrift linear infinite;
    pointer-events: none; z-index: 1;
}
.lightning-flash {
    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(220, 225, 255, 1);
    opacity: 0;                       /* invisible until the animation flashes it */
    animation: lightning linear infinite;
    pointer-events: none; z-index: 2;
}
.lightning-bolt {
    position: fixed;
    pointer-events: none;
    z-index: 3;
    opacity: 0;
    filter: drop-shadow(0 0 5px rgba(190,215,255,0.85))
            drop-shadow(0 0 16px rgba(150,180,255,0.45));
    animation: bolt-flash linear infinite;
}
.lightning-bolt svg { display: block; width: 100%; height: 100%; }
.lightning-bolt path {
    stroke: rgba(245, 250, 255, 0.95);
    stroke-width: 2.5;
    fill: none;
    stroke-linecap: round;
    stroke-linejoin: round;
}
.smoke-particle {
    position: fixed; border-radius: 50%;
    background: rgba(180,180,160,0.18); filter: blur(6px);
    animation: smokrise ease-out infinite;
    pointer-events: none; z-index: 1;
}

/* ── Metric cards ────────────────────────────────────────────── */
.metric-card {
    background: rgba(28, 31, 46, 0.88);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 16px;
    padding: 20px 18px 16px;
    margin: 2px 0 8px;
    min-height: 148px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4), 0 1px 0 rgba(255,255,255,0.06) inset;
}
.metric-label {
    font-size: 10px; color: #777;
    text-transform: uppercase; letter-spacing: 1.5px;
    font-weight: 600; margin-bottom: 10px;
}
.metric-value  { font-size: 38px; font-weight: 700; line-height: 1; letter-spacing: -1px; }
.metric-unit   { font-size: 13px; color: #666; font-weight: 500; margin-left: 2px; }
.metric-badge  {
    font-size: 10px; border-radius: 20px; padding: 2px 9px;
    font-weight: 600; letter-spacing: 0.3px; white-space: nowrap;
}
.metric-delta   { font-size: 11px; margin-top: 6px; font-weight: 500; }
.metric-context { font-size: 11px; color: #555; margin-top: 5px; font-style: italic; line-height: 1.4; }
.section-label  {
    font-size: 13px; text-transform: uppercase; letter-spacing: 1.8px;
    color: #666; font-weight: 700; padding-bottom: 10px;
    border-bottom: 1px solid rgba(255,255,255,0.06); margin: 32px 0 16px;
}
</style>
"""

_WRAP = '<div style="position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:1;">{}</div>'


# ── Color utilities ───────────────────────────────────────────────────────────

def hex_to_rgba(hex_color, alpha):
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ── Quality helpers ───────────────────────────────────────────────────────────

def temp_quality(t):
    t = float(t)
    if t < 16: return ("Cold",        "#4A9ECC")
    if t < 20: return ("Cool",        "#7ab8d4")
    if t < 24: return ("Comfortable", "#4AAA77")
    if t < 27: return ("Warm",        "#E8943A")
    return             ("Hot",        "#e85a3a")

def humidity_quality(h):
    h = float(h)
    if h < 30:  return ("Very Dry",    "#e85a3a")
    if h < 40:  return ("Dry",         "#E8943A")
    if h <= 60: return ("Comfortable", "#4AAA77")
    if h <= 70: return ("Humid",       "#E8943A")
    return              ("Very Humid", "#e85a3a")

def tvoc_quality(v):
    v = float(v)
    if v < 150: return ("Excellent", "#4AAA77")
    if v < 300: return ("Good",      "#7ab877")
    if v < 500: return ("Moderate",  "#E8943A")
    return              ("Poor",     "#e85a3a")

def eco2_quality(v):
    v = float(v)
    if v < 700:  return ("Excellent", "#4AAA77")
    if v < 1000: return ("Good",      "#7ab877")
    if v < 1500: return ("Moderate",  "#E8943A")
    return               ("Poor",    "#e85a3a")


# ── Dynamic background ────────────────────────────────────────────────────────

def get_weather_bg(condition: str) -> str:
    c = (condition or "").lower()
    if any(k in c for k in ("thunder", "storm")):
        gradient = "160deg, #120820 0%, #1a0d30 40%, #0f1117 100%"
    elif any(k in c for k in ("rain", "drizzle", "shower")):
        gradient = "160deg, #0a1628 0%, #12213d 40%, #0f1117 100%"
    elif "snow" in c:
        gradient = "160deg, #0d1e30 0%, #152535 40%, #0f1117 100%"
    elif "clear" in c:
        gradient = "160deg, #241408 0%, #1c1218 40%, #0f1117 100%"
    elif any(k in c for k in ("cloud", "overcast")):
        gradient = "160deg, #111824 0%, #161c28 40%, #0f1117 100%"
    elif any(k in c for k in ("mist", "fog", "haze")):
        gradient = "160deg, #141a1e 0%, #181e22 40%, #0f1117 100%"
    else:
        gradient = "160deg, #0f1117 0%, #13161f 100%"
    return (
        f"<style>[data-testid='stAppViewContainer']"
        f"{{background:linear-gradient({gradient}) !important;}}</style>"
    )


# ── Weather animated overlays ─────────────────────────────────────────────────

def _rain_overlay(n=40, seed=42, speed_min=1.0, speed_max=2.2) -> str:
    rng = random.Random(seed)
    drops = "".join(
        f'<div class="rain-drop" style="left:{rng.uniform(0,100):.1f}vw;'
        f'animation-duration:{rng.uniform(speed_min,speed_max):.2f}s;'
        f'animation-delay:{rng.uniform(0,3):.2f}s;"></div>'
        for _ in range(n)
    )
    return _WRAP.format(drops)


def _snow_overlay() -> str:
    rng = random.Random(11)
    flakes = "".join(
        f'<div class="snow-flake" style="left:{rng.uniform(0,100):.1f}vw;'
        f'width:{rng.uniform(3,9):.1f}px;height:{rng.uniform(3,9):.1f}px;'
        f'animation-duration:{rng.uniform(4,9):.1f}s;'
        f'animation-delay:{rng.uniform(0,6):.2f}s;"></div>'
        for _ in range(35)
    )
    return _WRAP.format(flakes)


def _sun_overlay() -> str:
    rng = random.Random(5)
    specks = "".join(
        f'<div class="sun-speck" style="left:{rng.uniform(0,100):.1f}vw;'
        f'width:{rng.uniform(3,8):.1f}px;height:{rng.uniform(3,8):.1f}px;'
        f'animation-duration:{rng.uniform(8,16):.1f}s;'
        f'animation-delay:{rng.uniform(0,10):.2f}s;"></div>'
        for _ in range(25)
    )
    return _WRAP.format(specks)


def _cloud_overlay() -> str:
    # Negative animation-delays "fast-forward" each cloud to a random point
    # along its drift, so patches appear pre-distributed across the screen at
    # t=0 instead of all marching in from the left over the first 15 seconds.
    rng = random.Random(3)
    patches = []
    for _ in range(7):
        duration = rng.uniform(18, 30)
        delay    = -rng.uniform(0.5, duration - 0.5)
        patches.append(
            f'<div class="cloud-patch" style="'
            f'top:{rng.uniform(5,70):.1f}vh;'
            f'width:{rng.randint(150,300)}px;height:{rng.randint(80,160)}px;'
            f'animation-duration:{duration:.1f}s;'
            f'animation-delay:{delay:.2f}s;"></div>'
        )
    return _WRAP.format("".join(patches))


def _fog_overlay() -> str:
    rng = random.Random(9)
    bands = []
    for _ in range(8):
        duration = rng.uniform(20, 40)
        delay    = -rng.uniform(0.5, duration - 0.5)
        bands.append(
            f'<div class="fog-patch" style="'
            f'top:{rng.uniform(10,85):.1f}vh;'
            f'width:{rng.randint(300,600)}px;height:{rng.randint(60,120)}px;'
            f'animation-duration:{duration:.1f}s;'
            f'animation-delay:{delay:.2f}s;"></div>'
        )
    return _WRAP.format("".join(bands))


LIGHTNING_BOLT_PATHS = (
    "M50,0 L30,60 L55,70 L25,150 L60,160 L20,230 L45,240 L15,300 "
    "M55,70 L80,110",

    "M50,0 L65,55 L35,75 L70,135 L30,150 L55,220 L25,235 L50,300 "
    "M30,150 L10,200",

    "M50,0 L40,40 L60,55 L25,110 L65,125 L35,200 L60,210 L40,300",

    "M50,0 L55,50 L25,75 L60,145 L30,165 L70,235 L35,250 L55,300 "
    "M60,145 L88,185",
)


def _storm_overlay() -> str:
    rain = _rain_overlay(n=60, seed=17, speed_min=0.7, speed_max=1.4)

    # Jagged SVG bolts — ~5 per 10 s, scattered across the upper screen.
    # Each bolt animates over 6-10 s; visible window is the brief flash at
    # 50% of its cycle, so with 5 staggered bolts a strike fires every ~2 s.
    rng = random.Random(23)
    bolts = []
    for _ in range(5):
        path      = rng.choice(LIGHTNING_BOLT_PATHS)
        height_vh = rng.uniform(34, 52)
        width_vh  = height_vh * 0.34  # viewBox aspect is roughly 1:3
        left_vw   = rng.uniform(8, 88)
        duration  = rng.uniform(6, 10)
        delay     = rng.uniform(0, duration)
        bolts.append(
            f'<div class="lightning-bolt" style="'
            f'left:{left_vw:.1f}vw;top:-2vh;'
            f'width:{width_vh:.1f}vh;height:{height_vh:.1f}vh;'
            f'animation-duration:{duration:.1f}s;'
            f'animation-delay:{delay:.2f}s;">'
            f'<svg viewBox="0 0 100 300" preserveAspectRatio="xMidYMin meet">'
            f'<path d="{path}"/></svg>'
            f'</div>'
        )

    # Two layers of dim ambient brighten, loosely independent of the bolts.
    flashes = "".join(
        f'<div class="lightning-flash" style="'
        f'animation-duration:{random.Random(i).uniform(7,12):.1f}s;'
        f'animation-delay:{random.Random(i+100).uniform(0,6):.2f}s;"></div>'
        for i in range(2)
    )

    lightning_wrap = _WRAP.format("".join(bolts) + flashes)
    return rain + lightning_wrap


def weather_overlay_html(condition: str) -> str:
    c = (condition or "").lower()
    if any(k in c for k in ("thunder", "storm")):
        return _storm_overlay()
    if any(k in c for k in ("rain", "drizzle", "shower")):
        return _rain_overlay()
    if "snow" in c:
        return _snow_overlay()
    if "clear" in c:
        return _sun_overlay()
    if any(k in c for k in ("cloud", "overcast")):
        return _cloud_overlay()
    if any(k in c for k in ("mist", "fog", "haze")):
        return _fog_overlay()
    return ""


def smoke_overlay_html() -> str:
    rng = random.Random(7)
    particles = "".join(
        f'<div class="smoke-particle" style="'
        f'left:{rng.uniform(0,100):.1f}vw;bottom:{rng.uniform(0,30):.1f}vh;'
        f'width:{rng.uniform(10,24):.1f}px;height:{rng.uniform(10,24):.1f}px;'
        f'animation-duration:{rng.uniform(3,6):.2f}s;'
        f'animation-delay:{rng.uniform(0,5):.2f}s;"></div>'
        for _ in range(20)
    )
    return _WRAP.format(particles)


# ── BQ client + data loaders ──────────────────────────────────────────────────

@st.cache_resource
def get_bq_client():
    return bigquery.Client(project=GCP_PROJECT)


@st.cache_data(ttl=300)
def load_data(limit):
    client = get_bq_client()
    limit_clause = f"LIMIT {limit}" if limit else ""
    query = f"""
        SELECT *
        FROM `{BQ_TABLE}`
        WHERE date IS NOT NULL AND time IS NOT NULL
        ORDER BY date DESC, time DESC
        {limit_clause}
    """
    df = client.query(query).to_dataframe()
    if not df.empty:
        df["datetime"] = pd.to_datetime(
            df["date"].astype(str) + " " + df["time"].astype(str)
        )
        df = df.sort_values("datetime").reset_index(drop=True)
    return df


@st.cache_data(ttl=300)
def load_data_range(start_date, end_date):
    client = get_bq_client()
    query = f"""
        SELECT *
        FROM `{BQ_TABLE}`
        WHERE date >= '{start_date}' AND date <= '{end_date}'
          AND date IS NOT NULL AND time IS NOT NULL
        ORDER BY date ASC, time ASC
    """
    df = client.query(query).to_dataframe()
    if not df.empty:
        df["datetime"] = pd.to_datetime(
            df["date"].astype(str) + " " + df["time"].astype(str)
        )
        df = df.sort_values("datetime").reset_index(drop=True)
    return df


def fetch_flask(path):
    try:
        resp = requests.get(FLASK_URL + path, timeout=5)
        data = resp.json()
        if data.get("status") == "success":
            return data
    except Exception:
        pass
    return None


def post_flask(path, payload=None, timeout=30):
    body = {"passwd": PASSWORD_HASH, **(payload or {})}
    try:
        resp = requests.post(FLASK_URL + path, json=body, timeout=timeout)
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── UI components ─────────────────────────────────────────────────────────────

def metric_card(label, value, unit, color, icon="", quality=None, delta=None, context=None):
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)

    badge_html = ""
    if quality:
        q_label, q_color = quality
        badge_html = (
            f'<span class="metric-badge" '
            f'style="background:{q_color}22;color:{q_color};">'
            f'{q_label}</span>'
        )

    delta_html = ""
    if delta is not None:
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        delta_color = "#e85a3a" if abs(delta) > 3 else "#ffaa44" if abs(delta) > 1 else "#4AAA77"
        delta_html = (
            f'<div class="metric-delta" style="color:{delta_color};">'
            f'{arrow} {abs(delta):.1f} {unit} from 1h ago</div>'
        )

    context_html = f'<div class="metric-context">{context}</div>' if context else ""

    st.markdown(f"""
<div class="metric-card" style="border-left:3px solid {color};box-shadow:0 4px 24px rgba({r},{g},{b},0.14),0 8px 32px rgba(0,0,0,0.4),0 1px 0 rgba(255,255,255,0.06) inset;">
<div class="metric-label">{icon}&nbsp; {label}</div>
<div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;">
<span class="metric-value" style="color:{color};">{value}</span>
<span class="metric-unit">{unit}</span>
{badge_html}
</div>
{delta_html}
{context_html}
</div>
""", unsafe_allow_html=True)


def make_gauge(value, label, unit, color, min_val, max_val):
    safe_val = float(value) if pd.notna(value) else min_val
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=safe_val,
        number={"suffix": f" {unit}", "font": {"size": 30, "color": color}},
        title={"text": label.upper(), "font": {"size": 10, "color": "#666"}},
        gauge={
            "axis": {
                "range": [min_val, max_val],
                "tickcolor": "#333",
                "tickfont": {"color": "#444", "size": 9},
                "nticks": 5,
            },
            "bar": {"color": color, "thickness": 0.22},
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
            "steps": [{"range": [min_val, max_val], "color": hex_to_rgba(color, 0.07)}],
        }
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=30, b=5, l=20, r=20),
        height=180,
    )
    return fig


def apply_chart_theme(fig):
    fig.update_layout(
        paper_bgcolor="#0f1117",
        plot_bgcolor="#0f1117",
        font_color="#aaa",
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=40, b=20, l=0, r=0),
        xaxis=dict(gridcolor="#1e2130", showgrid=True),
        yaxis=dict(gridcolor="#1e2130", showgrid=True),
    )
    fig.update_traces(line_width=2.5)
    return fig


def section_label(title):
    st.markdown(
        f'<div class="section-label">{title}</div>'
        f'<div style="height:12px;"></div>',
        unsafe_allow_html=True,
    )


def status_bar(indoor_humidity, tvoc, eco2):
    humi_val = float(indoor_humidity) if pd.notna(indoor_humidity) else None
    tvoc_val = float(tvoc)            if pd.notna(tvoc)            else None
    eco2_val = float(eco2)            if pd.notna(eco2)            else None

    if humi_val is not None and humi_val < 40:
        color, bg, icon = "#ffaa44", "#2a1f00", "⚠️"
        msg = f"Low humidity: {humi_val:.0f}% — consider using a humidifier"
    elif (tvoc_val and tvoc_val > 300) or (eco2_val and eco2_val > 1000):
        color, bg, icon = "#ff6b6b", "#2a0000", "🚨"
        msg = f"Poor air quality: TVOC {tvoc_val:.0f} ppb — open a window"
    else:
        color, bg, icon = "#4AAA77", "#0a1f12", "✅"
        humi_str = f"{humi_val:.0f}%" if humi_val else "--"
        msg = f"All systems good · Humidity {humi_str} · Air quality: Good"

    st.markdown(
        f'<div style="background:{bg};border-left:4px solid {color};'
        f'border-radius:8px;padding:12px 16px;margin-bottom:20px;'
        f'color:{color};font-size:14px;">'
        f'{icon}&nbsp; {msg}</div>',
        unsafe_allow_html=True,
    )
