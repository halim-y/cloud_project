import base64
import streamlit as st
from utils import COMMON_CSS, post_flask, section_label

try:
    from streamlit_mic_recorder import mic_recorder
    MIC_AVAILABLE = True
except ImportError:
    MIC_AVAILABLE = False


# ── Page-local styling ────────────────────────────────────────────────────────
PAGE_CSS = """
<style>
/* Quick-actions expander — frame it like the metric cards on Overview */
div[data-testid="stExpander"] {
    background: rgba(28, 31, 46, 0.6);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 14px;
    margin-bottom: 18px;
}
div[data-testid="stExpander"] summary {
    font-weight: 600;
    color: #cfd3df;
}

/* Quick-action buttons inside the expander */
div[data-testid="stExpander"] button[kind="secondary"] {
    background: rgba(15, 17, 23, 0.55) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    color: #cfd3df !important;
    font-size: 13px !important;
    padding: 9px 12px !important;
    text-align: left !important;
    height: auto !important;
    transition: all 0.15s ease;
}
div[data-testid="stExpander"] button[kind="secondary"]:hover {
    background: rgba(74, 158, 204, 0.14) !important;
    border-color: rgba(74, 158, 204, 0.4) !important;
    color: #fff !important;
}

/* Sub-section labels inside the expander */
.qa-sub {
    color: #777;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.4px;
    font-weight: 700;
    margin: 4px 0 10px;
}
.qa-sub.qa-second { margin-top: 18px; }

/* Chat bubbles — glassmorphism */
[data-testid="stChatMessage"] {
    background: rgba(28, 31, 46, 0.7) !important;
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 14px;
    padding: 12px 16px;
    margin-bottom: 10px;
}

/* Empty-state hint in the conversation area */
.conv-empty {
    color: #555;
    font-size: 13px;
    text-align: center;
    padding: 28px 0;
    font-style: italic;
}

/* Hide ALL native audio elements on this page — kills the white preview
   strip from streamlit-mic-recorder. We don't show inline audio players in
   the chat any more; spoken playback happens via the hidden autoplay element
   below (which is positioned off-screen so this rule doesn't matter for it). */
audio { display: none !important; }

/* Hidden TTS playback host — moved off-screen so autoplay still fires */
.tts-host {
    position: absolute;
    left: -9999px;
    top: -9999px;
    width: 1px;
    height: 1px;
    overflow: hidden;
}
.tts-host audio { display: block !important; }

/* Input row at the bottom — tighten alignment */
div[data-testid="stForm"] {
    border: none !important;
    padding: 0 !important;
}

/* Mic helper hint */
.mic-hint {
    color: #555;
    font-size: 10.5px;
    line-height: 1.3;
    margin: 4px 0 0 2px;
}

/* M5Stack announcement bubble — distinct from regular AI chat */
.ann-bubble {
    border-left: 3px solid #9977BB;
    padding: 4px 0 4px 14px;
    color: #b0b0c0;
    font-size: 13.5px;
}
.ann-tag {
    font-size: 9.5px;
    text-transform: uppercase;
    letter-spacing: 1.6px;
    color: #9977BB;
    font-weight: 700;
    margin-bottom: 5px;
}

/* Listen button — positioned right of the message via st.columns, styled
   small and subtle like a chatbot action icon */
[data-testid="stChatMessage"] button[kind="secondary"] {
    background: transparent !important;
    border: 1px solid rgba(74, 158, 204, 0.3) !important;
    color: #7ab8d4 !important;
    font-size: 11px !important;
    padding: 3px 10px !important;
    height: auto !important;
    min-height: 0 !important;
    border-radius: 12px !important;
}
[data-testid="stChatMessage"] button[kind="secondary"]:hover {
    background: rgba(74, 158, 204, 0.14) !important;
    color: #fff !important;
}
</style>
"""


# ── Page header ───────────────────────────────────────────────────────────────
st.markdown(COMMON_CSS, unsafe_allow_html=True)
st.markdown(PAGE_CSS, unsafe_allow_html=True)

st.markdown("# 🤖 AI Assistant")
st.markdown(
    "<p style='color:#888; font-size:14px; margin-top:-8px; margin-bottom:24px;'>"
    "Ask about your home environment in plain language — type a question, "
    "use a quick action, or speak.</p>",
    unsafe_allow_html=True,
)

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
if "pending" not in st.session_state:
    st.session_state["pending"] = None


def render_listen_button(msg, idx):
    """Show a 🔊 Listen pill on the right side of any spoken assistant
    message, like the action icons in real chatbots. On click: fetch TTS
    audio if missing (text-only answers), then trigger inline autoplay via
    session_state['play_audio_b64']."""
    _, btn_col = st.columns([6, 1])
    with btn_col:
        if st.button("🔊 Listen", key=f"tts_{idx}",
                     help="Hear this answer spoken aloud"):
            if not msg.get("audio_b64"):
                with st.spinner("Generating audio..."):
                    tts = post_flask("/tts", {"text": msg["content"]})
                if tts.get("status") == "success":
                    msg["audio_b64"] = tts["audio_b64"]
                else:
                    st.error(f"TTS error: {tts.get('message', 'unknown')}")
                    return
            st.session_state["play_audio_b64"] = msg["audio_b64"]
            st.rerun()


def is_speakable(msg):
    """Skip the Listen button on error messages and on skipped announcements."""
    if msg["role"] != "assistant":
        return False
    content = msg.get("content", "")
    if content.startswith("⚠️"):
        return False
    if msg.get("kind") == "announcement" and content.startswith("_skipped"):
        return False
    return True


# ── Queue helpers ─────────────────────────────────────────────────────────────
# Pattern: the user's message is appended to history and a `pending` flag is
# set. Streamlit reruns and renders the question immediately, then the pending
# block below fires the actual backend call inside a visible "Thinking..."
# bubble. This makes the conversation feel responsive rather than freezing
# until the answer is ready.

def queue_text_query(text: str):
    st.session_state["chat_history"].append(
        {"role": "user", "content": text, "kind": "chat"}
    )
    st.session_state["pending"] = {"type": "text", "text": text}


def queue_audio_query(wav_bytes, sample_rate):
    audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
    st.session_state["chat_history"].append({
        "role":                 "user",
        "content":              "🎤 _Voice message — transcribing..._",
        "kind":                 "chat",
        "is_voice_placeholder": True,
    })
    st.session_state["pending"] = {
        "type":        "audio",
        "audio_b64":   audio_b64,
        "sample_rate": sample_rate or 48000,
    }


def handle_announcement(action: str):
    with st.spinner("Composing..."):
        data = post_flask("/announce", {"action": action, "format": "mp3"}, timeout=30)
    if data.get("status") == "speak":
        st.session_state["chat_history"].append({
            "role":      "assistant",
            "kind":      "announcement",
            "action":    action,
            "content":   data.get("text", ""),
            "audio_b64": data.get("audio_b64"),
        })
    elif data.get("status") == "skip":
        st.session_state["chat_history"].append({
            "role":    "assistant",
            "kind":    "announcement",
            "action":  action,
            "content": f"_skipped — {data.get('reason', 'condition not met')}_",
        })
    else:
        st.session_state["chat_history"].append({
            "role":    "assistant",
            "kind":    "chat",
            "content": f"⚠️ Backend error: {data.get('message', 'unknown')}",
        })


# ── Quick actions panel (closed by default) ───────────────────────────────────
QUESTIONS = [
    "What's the temperature now?",
    "How is the air quality this week?",
    "Is it raining today?",
    "What's the humidity trend?",
]
ANNOUNCEMENTS = [
    ("motion",           "🚶 Auto-pick"),
    ("current_summary",  "🌡️ Current summary"),
    ("morning_briefing", "🌅 Morning briefing"),
    ("rain_reminder",    "☔ Rain reminder"),
    ("humidity_alert",   "💧 Humidity alert"),
    ("train_delay",      "🚆 Train alert"),
]

with st.expander("⚡ Quick actions", expanded=False):
    st.markdown('<div class="qa-sub">💬 Ask</div>', unsafe_allow_html=True)
    cols = st.columns(2)
    for i, q in enumerate(QUESTIONS):
        with cols[i % 2]:
            if st.button(q, key=f"q_{i}", width="stretch"):
                queue_text_query(q)
                st.rerun()

    st.markdown(
        '<div class="qa-sub qa-second">📣 Announce '
        '<span style="font-weight:500; text-transform:none; letter-spacing:0.5px; '
        'color:#555;">— proactive announcements the M5Stack plays on motion'
        '</span></div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(3)
    for i, (action, label) in enumerate(ANNOUNCEMENTS):
        with cols[i % 3]:
            if st.button(label, key=f"ann_{action}", width="stretch"):
                handle_announcement(action)
                st.rerun()


# ── Conversation ──────────────────────────────────────────────────────────────
section_label("Conversation")

if not st.session_state["chat_history"] and not st.session_state["pending"]:
    st.markdown(
        '<div class="conv-empty">Start by typing below, picking a quick action '
        'above, or recording your voice.</div>',
        unsafe_allow_html=True,
    )
else:
    for idx, msg in enumerate(st.session_state["chat_history"]):
        if msg.get("kind") == "announcement":
            with st.chat_message("assistant", avatar="📣"):
                action_label = msg.get("action", "announcement").replace("_", " ")
                st.markdown(
                    f'<div class="ann-bubble">'
                    f'  <div class="ann-tag">M5Stack · {action_label}</div>'
                    f'  {msg["content"]}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if is_speakable(msg):
                    render_listen_button(msg, idx)
        else:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
                if is_speakable(msg):
                    render_listen_button(msg, idx)


# ── Pending request: render a thinking bubble and fire the backend call ──────
def _history_for_backend():
    """Recent conversation context sent to /voice-query and /voice-audio so
    Gemini can resolve follow-up pronouns ("and yesterday?", "what about
    humidity?"). Excludes the current pending user turn (last item), all
    transient placeholders, errors, and skipped-announcement notes."""
    history = []
    for m in st.session_state["chat_history"][:-1]:
        if m.get("is_voice_placeholder"):
            continue
        content = (m.get("content") or "").strip()
        if not content or content.startswith("⚠️"):
            continue
        if m.get("kind") == "announcement" and content.startswith("_skipped"):
            continue
        history.append({"role": m["role"], "content": content})
    return history[-6:]  # last 6 messages


if st.session_state.get("pending"):
    p = st.session_state["pending"]
    history = _history_for_backend()
    with st.chat_message("assistant"):
        spinner_label = "Transcribing & thinking..." if p["type"] == "audio" else "Thinking..."
        with st.spinner(spinner_label):
            if p["type"] == "text":
                data = post_flask(
                    "/voice-query",
                    {"text": p["text"], "history": history},
                )
            else:
                data = post_flask(
                    "/voice-audio",
                    {
                        "audio_b64":   p["audio_b64"],
                        "sample_rate": p["sample_rate"],
                        "history":     history,
                    },
                    timeout=45,
                )

    if p["type"] == "text":
        if data.get("status") == "success":
            answer = data.get("response", "(empty response)")
        else:
            answer = f"⚠️ Backend error: {data.get('message', 'unknown')}"
        st.session_state["chat_history"].append(
            {"role": "assistant", "content": answer, "kind": "chat"}
        )
    else:
        status = data.get("status")
        if status in ("success", "empty"):
            transcript      = data.get("transcript") or "(unintelligible)"
            response        = data.get("response", "(no response)")
            reply_audio_b64 = data.get("audio_b64")
        else:
            transcript      = "(audio)"
            response        = f"⚠️ Backend error: {data.get('message', 'unknown')}"
            reply_audio_b64 = None
        # Replace the voice-message placeholder with the real transcript
        for m in reversed(st.session_state["chat_history"]):
            if m.get("is_voice_placeholder"):
                m["content"] = transcript
                del m["is_voice_placeholder"]
                break
        st.session_state["chat_history"].append({
            "role":      "assistant",
            "content":   response,
            "audio_b64": reply_audio_b64,
            "kind":      "chat",
        })

    st.session_state["pending"] = None
    st.rerun()


# ── Hidden TTS playback element ──────────────────────────────────────────────
# When the user clicks 🔊 Listen, the handler stores audio in
# `play_audio_b64` and reruns. On the next render we inject an <audio
# autoplay> element off-screen so the answer plays without any visible widget.
_tts_audio = st.session_state.pop("play_audio_b64", None)
if _tts_audio:
    st.markdown(
        f'<div class="tts-host">'
        f'<audio autoplay src="data:audio/mp3;base64,{_tts_audio}"></audio>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Input row: mic + text + send, all on one line ─────────────────────────────
mic_col, form_col = st.columns([1, 14])

with mic_col:
    if MIC_AVAILABLE:
        audio = mic_recorder(
            start_prompt="🎤",
            stop_prompt="⏹",
            format="wav",
            just_once=True,
            use_container_width=True,
            key="voice_recorder",
        )
        if audio and audio.get("bytes"):
            queue_audio_query(audio["bytes"], audio.get("sample_rate"))
            st.rerun()

with form_col:
    with st.form("chat_form", clear_on_submit=True, border=False):
        input_col, send_col = st.columns([14, 2])
        with input_col:
            user_text = st.text_input(
                "msg",
                label_visibility="collapsed",
                placeholder="Type your question...",
            )
        with send_col:
            submitted = st.form_submit_button("Send", width="stretch")
        if submitted and user_text:
            queue_text_query(user_text)
            st.rerun()

if MIC_AVAILABLE:
    st.markdown(
        '<div class="mic-hint">Tip: click the mic, wait for the icon to flip to '
        '⏹, then speak. The browser needs a moment to enable the microphone.'
        '</div>',
        unsafe_allow_html=True,
    )
