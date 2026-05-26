import requests
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Europe/Zurich")

from utils import COMMON_CSS, FLASK_URL, section_label

st.markdown(COMMON_CSS, unsafe_allow_html=True)

# ── Station-night background ──────────────────────────────────────────────────
st.markdown(
    "<style>[data-testid='stAppViewContainer']{"
    "background:linear-gradient(160deg,#06091a 0%,#0b0f22 45%,#07091a 100%)"
    "!important;}</style>",
    unsafe_allow_html=True,
)
st.markdown("""
<div style="position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden;">
  <div style="
    position:absolute;top:-15%;left:-10%;
    width:55vw;height:55vw;border-radius:50%;
    background:radial-gradient(circle,rgba(30,55,160,0.10) 0%,transparent 70%);
    animation:orb1 18s ease-in-out infinite alternate;"></div>
  <div style="
    position:absolute;bottom:-20%;right:-10%;
    width:45vw;height:45vw;border-radius:50%;
    background:radial-gradient(circle,rgba(20,35,110,0.08) 0%,transparent 70%);
    animation:orb2 22s ease-in-out infinite alternate;"></div>
</div>
<style>
@keyframes orb1 { 0%{opacity:.6;transform:scale(1)} 100%{opacity:1;transform:scale(1.18)} }
@keyframes orb2 { 0%{opacity:1;transform:scale(1)} 100%{opacity:.5;transform:scale(1.12)} }
</style>
""", unsafe_allow_html=True)

CARD_BG     = "rgba(20,22,34,0.75)"
CARD_BORDER = "rgba(255,255,255,0.08)"
CARD_BLUR   = "backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);"

st.markdown(f"""
<style>
/* ── Pulsing live dot ──────────────────────────────────────────── */
@keyframes pulse-dot {{
    0%, 100% {{ opacity: 1;   transform: scale(1);    }}
    50%       {{ opacity: 0.5; transform: scale(0.75); }}
}}
.pulse-dot {{
    display: inline-block;
    width: 7px; height: 7px;
    border-radius: 50%;
    margin-right: 7px;
    flex-shrink: 0;
    animation: pulse-dot 2s ease-in-out infinite;
    vertical-align: middle;
}}
.pulse-dot.ok   {{ background: #4ade80; box-shadow: 0 0 7px #4ade8088; }}
.pulse-dot.warn {{ background: #fb923c; box-shadow: 0 0 7px #fb923c88; }}
.pulse-dot.late {{ background: #f87171; box-shadow: 0 0 7px #f8717188; }}

/* ── Combined hero card ─────────────────────────────────────────── */
details.dep-hero {{
    background: rgba(14,17,34,0.88);
    {CARD_BLUR}
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 20px;
    margin-bottom: 16px;
    overflow: hidden;
    transition: border-color 0.2s;
}}
details.dep-hero[open] {{ border-color: rgba(255,255,255,0.22); }}
details.dep-hero > summary {{
    list-style: none;
    cursor: pointer;
    padding: 20px 26px 16px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    user-select: none;
}}
details.dep-hero > summary::-webkit-details-marker {{ display: none; }}
details.dep-hero > summary::marker {{ content: ""; }}
details.dep-hero > summary:hover {{ background: rgba(255,255,255,0.02); }}

/* ── Route animation row ──────────────────────────────────────── */
.board-route {{
    display: flex;
    align-items: center;
    gap: 16px;
}}
.board-stn {{
    font-size: 1.05rem;
    font-weight: 800;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    color: #d0d4f0;
    white-space: nowrap;
}}
.board-track-wrap {{
    flex: 1;
    position: relative;
    height: 14px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 5px;
}}
.board-rail {{
    height: 2px;
    border-radius: 1px;
    background: linear-gradient(to right,
        transparent 0%,
        rgba(255,255,255,0.12) 10%,
        rgba(255,255,255,0.12) 90%,
        transparent 100%);
}}
@keyframes train-dot {{
    0%   {{ left: 2%;  opacity: 0; }}
    5%   {{ opacity: 1; }}
    95%  {{ opacity: 1; }}
    100% {{ left: 96%; opacity: 0; }}
}}
.board-train-dot {{
    position: absolute;
    top: 50%; transform: translateY(-50%);
    width: 10px; height: 10px;
    border-radius: 50%;
    background: #4A9ECC;
    box-shadow: 0 0 10px #4A9ECC, 0 0 20px rgba(74,158,204,0.4);
    animation: train-dot 4s ease-in-out infinite;
}}

/* ── Hero main row (time + countdown + chevron) ───────────────── */
.hero-main-row {{
    display: flex;
    align-items: center;
    gap: 12px;
}}
.hero-left {{ flex: 1; display: flex; flex-direction: column; gap: 5px; min-width: 0; }}
.hero-next-label {{
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #555;
}}
/* Single merged info row: dep time → arr · dur · line · platform */
.hero-info-row {{
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}}
.hero-dep {{
    font-size: 2.2rem;
    font-weight: 800;
    color: #f0f0ff;
    font-variant-numeric: tabular-nums;
    letter-spacing: -1px;
}}
.hero-arrow {{
    font-size: 1.1rem;
    color: #444;
}}
.hero-arr {{
    font-size: 1.3rem;
    color: #888;
    font-variant-numeric: tabular-nums;
}}
.hero-dur {{
    font-size: 0.78rem;
    color: #444;
}}
/* Right-side group: status badge + countdown bubble */
.hero-right {{
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
}}

/* Countdown bubble */
.hero-countdown {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
    padding: 10px 22px;
    margin: 0 16px;
    min-width: 90px;
    text-align: center;
}}
.hero-countdown-num {{
    font-size: 2rem;
    font-weight: 800;
    color: #e8e8f0;
    line-height: 1;
    font-variant-numeric: tabular-nums;
}}
.hero-countdown-unit {{
    font-size: 0.7rem;
    color: #555;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-top: 2px;
}}
.hero-countdown.boarding {{ border-color: rgba(74,222,128,0.35); }}
.hero-countdown.boarding .hero-countdown-num {{ color: #4ade80; font-size: 1.2rem; }}

/* ── Progress bar row ─────────────────────────────────────────── */
.board-bottom {{
    display: flex;
    align-items: center;
    gap: 16px;
}}
.board-bar-bg {{
    flex: 1;
    height: 5px;
    border-radius: 3px;
    background: rgba(255,255,255,0.06);
    overflow: hidden;
}}
.board-bar-fill {{
    height: 100%;
    border-radius: 3px;
    transition: width 0.8s ease;
}}
.board-clock {{
    font-size: 0.78rem;
    color: #444;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}}
.board-next {{
    font-size: 0.78rem;
    font-weight: 600;
    white-space: nowrap;
}}

/* ── Regular departure cards ───────────────────────────────────── */
details.dep-card {{
    background: {CARD_BG};
    {CARD_BLUR}
    border: 1px solid {CARD_BORDER};
    border-radius: 16px;
    margin-bottom: 10px;
    overflow: hidden;
    transition: border-color 0.2s;
}}
details.dep-card[open] {{ border-color: rgba(255,255,255,0.18); }}
details.dep-card > summary {{
    list-style: none;
    cursor: pointer;
    padding: 14px 20px;
    display: flex;
    align-items: center;
    gap: 0;
    user-select: none;
}}
details.dep-card > summary::-webkit-details-marker {{ display: none; }}
details.dep-card > summary::marker {{ content: ""; }}
details.dep-card > summary:hover {{ background: rgba(255,255,255,0.03); }}

.dep-time {{
    font-size: 1.25rem;
    font-weight: 700;
    color: #e8e8f0;
    min-width: 56px;
    font-variant-numeric: tabular-nums;
}}
.dep-arrow {{ color: #444; margin: 0 8px; font-size: 0.9rem; }}
.dep-arr   {{ font-size: 0.95rem; color: #888; min-width: 50px; font-variant-numeric: tabular-nums; }}
.dep-duration {{ font-size: 0.75rem; color: #444; margin-left: 5px; align-self: flex-end; padding-bottom: 1px; }}
.dep-countdown {{
    font-size: 0.8rem;
    font-weight: 600;
    color: #777;
    margin-left: 10px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}}
.dep-line {{
    font-weight: 600;
    font-size: 0.8rem;
    padding: 3px 10px;
    border-radius: 8px;
    margin: 0 12px;
    min-width: 66px;
    text-align: center;
    letter-spacing: 0.3px;
}}
.line-train {{ background: rgba(100,120,255,0.18); color: #a0b4ff; border: 1px solid rgba(100,120,255,0.3); }}
.line-bus   {{ background: rgba(74,170,119,0.18);  color: #86efac; border: 1px solid rgba(74,170,119,0.3); }}
.line-tram  {{ background: rgba(251,146,60,0.18);  color: #fdba74; border: 1px solid rgba(251,146,60,0.3); }}
.line-metro {{ background: rgba(232,121,249,0.18); color: #e879f9; border: 1px solid rgba(232,121,249,0.3); }}
.line-other {{ background: rgba(120,120,120,0.18); color: #aaa;    border: 1px solid rgba(120,120,120,0.3); }}
.dep-platform {{ color: #555; font-size: 0.78rem; min-width: 58px; }}
.dep-chevron  {{ margin-left: auto; color: #444; font-size: 0.8rem; transition: transform 0.2s; }}
details.dep-card[open]  .dep-chevron {{ transform: rotate(180deg); }}
details.dep-hero[open] .dep-chevron {{ transform: rotate(180deg); }}

/* ── Status badge ──────────────────────────────────────────────── */
.dep-status {{
    display: flex;
    align-items: center;
    font-weight: 600;
    font-size: 0.8rem;
    padding: 3px 11px;
    border-radius: 20px;
    margin-right: 10px;
    white-space: nowrap;
}}
.status-ok   {{ background: rgba(74,222,128,0.12); color: #4ade80; border: 1px solid rgba(74,222,128,0.25); }}
.status-warn {{ background: rgba(251,146,60,0.12);  color: #fb923c; border: 1px solid rgba(251,146,60,0.25); }}
.status-late {{ background: rgba(248,113,113,0.12); color: #f87171; border: 1px solid rgba(248,113,113,0.25); }}

/* ── Expanded details panel ────────────────────────────────────── */
.dep-details {{
    border-top: 1px solid rgba(255,255,255,0.06);
    padding: 14px 22px 18px;
}}
.dep-meta {{
    display: flex;
    gap: 16px;
    font-size: 0.78rem;
    color: #666;
    margin-bottom: 14px;
}}
.dep-meta span {{ display: flex; align-items: center; gap: 5px; }}
.dep-legs {{ display: flex; flex-direction: column; gap: 0; }}
.leg-row {{
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 6px 0;
    position: relative;
}}
.leg-dot {{
    width: 8px; height: 8px;
    border-radius: 50%;
    background: rgba(255,255,255,0.2);
    border: 2px solid rgba(255,255,255,0.35);
    margin-top: 5px;
    flex-shrink: 0;
}}
.leg-dot.first {{ background: #4ade80; border-color: #4ade80; }}
.leg-dot.last  {{ background: #60a5fa; border-color: #60a5fa; }}
.leg-vline {{
    position: absolute;
    left: 3px; top: 18px; bottom: -6px;
    width: 2px;
    background: rgba(255,255,255,0.07);
}}
.leg-time {{ font-size: 0.83rem; font-weight: 600; color: #ccc; min-width: 40px; font-variant-numeric: tabular-nums; }}
.leg-stop {{ font-size: 0.83rem; color: #bbb; flex: 1; }}
.leg-info {{ font-size: 0.76rem; color: #666; text-align: right; }}
.transfer-badge {{
    display: inline-block;
    font-size: 0.7rem;
    color: #888;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 6px;
    padding: 1px 8px;
    margin: 3px 0 3px 52px;
}}
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
_TYPE_MAP = {
    ("IC", "IR", "EC", "TGV", "RE", "RB", "S", "R", "PE", "VAE"): ("🚆", "line-train"),
    ("T", "TRAM"):                                                   ("🚋", "line-tram"),
    ("M", "METRO"):                                                  ("🚇", "line-metro"),
    ("BAT", "SHIP"):                                                 ("⛴",  "line-other"),
    ("PB", "GB", "CABLEWAY"):                                        ("🚡", "line-other"),
}

def infer_transport(category: str):
    c = category.upper()
    for keys, val in _TYPE_MAP.items():
        if c in keys:
            return val
    return ("🚌", "line-bus")

def build_leg_line_badge(leg: dict) -> str:
    emoji, cls = infer_transport(leg.get("category", ""))
    return f'<span class="dep-line {cls}">{emoji}&nbsp;{leg.get("line","—")}</span>'

def minutes_until(dep_hhmm: str, delay_min: int = 0) -> int | None:
    try:
        now = datetime.now(tz=_TZ)
        now_min = now.hour * 60 + now.minute
        dep_min = int(dep_hhmm[:2]) * 60 + int(dep_hhmm[3:]) + delay_min
        diff = dep_min - now_min
        if diff < -60:
            diff += 1440
        return diff
    except Exception:
        return None

def fmt_countdown(mins: int | None) -> str:
    if mins is None:
        return ""
    if mins <= 0:
        return "now"
    if mins < 60:
        return f"in {mins} min"
    h, m = divmod(mins, 60)
    return f"in {h}h {m:02d}m" if m else f"in {h}h"

def dot_cls(delay: int) -> str:
    if delay == 0:   return "ok"
    if delay < 5:    return "warn"
    return "late"

def status_label(delay: int) -> str:
    if delay == 0:   return "On time"
    return f"+{delay} min"

def status_css(delay: int) -> str:
    if delay == 0:   return "status-ok"
    if delay < 5:    return "status-warn"
    return "status-late"


# ── Fetch ─────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def load_trains(frm: str, to: str, kind: str):
    try:
        resp = requests.get(
            FLASK_URL + "/next-trains",
            params={"from": frm, "to": to, "type": kind},
            timeout=10,
        )
        data = resp.json()
        if data.get("status") == "success":
            return data.get("trains", []), None
        return [], data.get("message", "Unknown error")
    except Exception as e:
        return [], str(e)


def build_details_html(legs: list, dur_str: str) -> str:
    if not legs:
        return ""
    transfers = max(0, len(legs) - 1)
    trans_str = "Direct" if transfers == 0 else f"{transfers} transfer{'s' if transfers > 1 else ''}"
    meta = (
        f'<div class="dep-meta">'
        f'<span>⏱ {dur_str}</span>'
        f'<span>{"→" if transfers == 0 else "⇄"} {trans_str}</span>'
        f'</div>'
        if dur_str else ""
    )
    legs_html = ""
    for i, leg in enumerate(legs):
        is_last = (i == len(legs) - 1)
        dot_c   = "first" if i == 0 else ""
        vline   = "" if is_last else '<div class="leg-vline"></div>'
        info    = build_leg_line_badge(leg)
        direction = leg.get("direction", "")
        dir_html  = f'<span style="font-size:0.72rem;color:#555">→ {direction}</span>' if direction else ""
        legs_html += (
            f'<div class="leg-row" style="position:relative">'
            f'{vline}'
            f'<div class="leg-dot {dot_c}"></div>'
            f'<div class="leg-time">{leg.get("dep","")}</div>'
            f'<div class="leg-stop">{leg.get("from","")}</div>'
            f'<div class="leg-info">{info}<br>{dir_html}</div>'
            f'</div>'
        )
        if is_last:
            legs_html += (
                f'<div class="leg-row">'
                f'<div class="leg-dot last"></div>'
                f'<div class="leg-time">{leg.get("arr","")}</div>'
                f'<div class="leg-stop">{leg.get("to","")}</div>'
                f'</div>'
            )
        else:
            next_leg = legs[i + 1]
            try:
                ah, am = int(leg["arr"][:2]), int(leg["arr"][3:])
                dh, dm = int(next_leg["dep"][:2]), int(next_leg["dep"][3:])
                wait = (dh * 60 + dm) - (ah * 60 + am)
                if wait < 0: wait += 1440
                wait_str = f"change · {wait} min wait"
            except Exception:
                wait_str = "change"
            legs_html += (
                f'<div class="leg-row">'
                f'<div class="leg-dot"></div>'
                f'<div class="leg-time">{leg.get("arr","")}</div>'
                f'<div class="leg-stop">{leg.get("to","")}</div>'
                f'</div>'
                f'<div class="transfer-badge">🔄 {wait_str}</div>'
            )
    return f'<div class="dep-details">{meta}<div class="dep-legs">{legs_html}</div></div>'


# ── Page header ───────────────────────────────────────────────────────────────
st.title("🚆 Next Departures")

# ── Route + filter controls ───────────────────────────────────────────────────
section_label("ROUTE")
c1, c2, c3 = st.columns([2, 2, 1])
with c1:
    from_station = st.text_input("From", value="Genève", placeholder="e.g. Genève")
with c2:
    to_station = st.text_input("To", value="Renens VD", placeholder="e.g. Renens VD")
with c3:
    transport_label = st.selectbox("Type", ["All", "Train", "Bus", "Tram"], index=0)

TYPE_PARAM = {"All": "all", "Train": "train", "Bus": "bus", "Tram": "tram"}


# ── Departure board — auto-refreshes every 60 s ───────────────────────────────
@st.fragment(run_every=60)
def departure_board(frm: str, to: str, kind_label: str):
    col_info, col_btn = st.columns([5, 1])
    with col_btn:
        if st.button("⟳ Refresh", use_container_width=True):
            st.cache_data.clear()

    kind = TYPE_PARAM[kind_label]
    trains, error = load_trains(frm, to, kind)
    now = datetime.now(tz=_TZ)
    now_str = now.strftime("%H:%M")

    section_label(f"{frm.upper()} → {to.upper()}")
    st.caption(f"Updated at {now_str} · auto-refreshes every 60 s · click a card to expand")

    if error:
        st.error(f"Could not fetch departures: {error}")
        return
    if not trains:
        st.info("No departures found for this route.")
        return

    for idx, t in enumerate(trains):
        dep      = t.get("dep", "--:--")
        arr      = t.get("arr", "--:--")
        line     = t.get("line") or "—"
        category = t.get("category") or ""
        delay    = t.get("delay", 0) or 0
        platform = t.get("platform") or ""
        duration = t.get("duration")
        legs     = t.get("legs") or []

        emoji, line_cls = infer_transport(category)
        dur_str   = f"{duration} min" if duration is not None else ""
        mins      = minutes_until(dep, delay)
        countdown = fmt_countdown(mins)
        d_cls     = dot_cls(delay)
        s_text    = status_label(delay)
        s_css     = status_css(delay)
        plat_html = (
            f'<span class="dep-platform">Pl.&nbsp;{platform}</span>'
            if platform else
            '<span class="dep-platform" style="color:#2a2a3a">—</span>'
        )
        details_html = build_details_html(legs, dur_str)
        pulse = f'<span class="pulse-dot {d_cls}"></span>'

        if idx == 0:
            # ── Combined hero card ────────────────────────────────────────
            boarding = mins is not None and mins <= 2
            cd_cls   = "boarding" if boarding else ""
            cd_num   = "NOW" if boarding else (str(mins) if mins is not None else "—")
            cd_unit  = "" if boarding else "min"

            # Progress bar: fills 0→100% over a 30-min window before departure
            fill = max(0, min(100, int((1 - (mins or 30) / 30) * 100)))
            if fill < 33:   bar_color = "#4A9ECC"
            elif fill < 66: bar_color = "#fb923c"
            else:           bar_color = "#f87171"
            next_color = "#4ade80" if (mins or 99) > 10 else ("#fb923c" if (mins or 99) > 3 else "#f87171")

            st.markdown(
                f'<details class="dep-hero">'
                f'<summary>'
                # Row 1: animated station-to-station track
                f'  <div class="board-route">'
                f'    <span class="board-stn">{frm}</span>'
                f'    <div class="board-track-wrap">'
                f'      <div class="board-rail"></div>'
                f'      <div class="board-rail"></div>'
                f'      <div class="board-train-dot"></div>'
                f'    </div>'
                f'    <span class="board-stn">{to}</span>'
                f'  </div>'
                # Row 2: single info line left · status + countdown right
                f'  <div class="hero-main-row">'
                f'    <div class="hero-left">'
                f'      <div class="hero-next-label">Next Departure</div>'
                f'      <div class="hero-info-row">'
                f'        <span class="hero-dep">{dep}</span>'
                f'        <span class="hero-arrow">→</span>'
                f'        <span class="hero-arr">{arr}</span>'
                f'        <span class="hero-dur">{dur_str}</span>'
                f'        <span class="dep-line {line_cls}" style="margin:0 4px;">{emoji}&nbsp;{line}</span>'
                f'        {plat_html}'
                f'      </div>'
                f'    </div>'
                f'    <div class="hero-right">'
                f'      <span class="dep-status {s_css}">{pulse}{s_text}</span>'
                f'      <div class="hero-countdown {cd_cls}">'
                f'        <div class="hero-countdown-num">{cd_num}</div>'
                f'        <div class="hero-countdown-unit">{cd_unit}</div>'
                f'      </div>'
                f'    </div>'
                f'    <span class="dep-chevron">▼</span>'
                f'  </div>'
                # Row 3: clock + progress bar + countdown label
                f'  <div class="board-bottom">'
                f'    <span class="board-clock">🕐 {now_str}</span>'
                f'    <div class="board-bar-bg">'
                f'      <div class="board-bar-fill" style="width:{fill}%;background:{bar_color};"></div>'
                f'    </div>'
                f'    <span class="board-next" style="color:{next_color};">{countdown}</span>'
                f'  </div>'
                f'</summary>'
                f'{details_html}'
                f'</details>',
                unsafe_allow_html=True,
            )
        else:
            # ── Secondary card ────────────────────────────────────────────
            st.markdown(
                f'<details class="dep-card">'
                f'<summary>'
                f'  <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0;">'
                f'    <span class="dep-time">{dep}</span>'
                f'    <span class="dep-arrow">→</span>'
                f'    <span class="dep-arr">{arr}</span>'
                f'    <span class="dep-duration">{dur_str}</span>'
                f'    <span class="dep-line {line_cls}">{emoji}&nbsp;{line}</span>'
                f'    {plat_html}'
                f'  </div>'
                f'  <div style="margin-left:auto;display:flex;align-items:center;gap:10px;flex-shrink:0;">'
                f'    <span class="dep-status {s_css}">{pulse}{s_text}</span>'
                f'    <span class="dep-countdown">{countdown}</span>'
                f'    <span class="dep-chevron">▼</span>'
                f'  </div>'
                f'</summary>'
                f'{details_html}'
                f'</details>',
                unsafe_allow_html=True,
            )


departure_board(from_station.strip(), to_station.strip(), transport_label)
