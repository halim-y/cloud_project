import base64
from google.cloud import speech, texttospeech

_stt = speech.SpeechClient()
_tts = texttospeech.TextToSpeechClient()

VOICE = texttospeech.VoiceSelectionParams(
    language_code="en-US",
    name="en-US-Neural2-F",
)

WAV_SAMPLE_RATE = 16000  # 16 kHz is a good fit for the M5Stack speaker and
                         # ~33% smaller than 24 kHz with no audible loss for
                         # short spoken sentences.


def transcribe_bytes(audio_bytes: bytes, sample_rate: int) -> str:
    """Transcribe raw PCM bytes (LINEAR16) at the given sample rate."""
    rate = sample_rate if sample_rate is not None else 16000
    audio = speech.RecognitionAudio(content=audio_bytes)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=rate,
        language_code="en-US",
        enable_automatic_punctuation=True,
        model="latest_short",
    )
    resp = _stt.recognize(config=config, audio=audio)
    if not resp.results:
        return ""
    return resp.results[0].alternatives[0].transcript.strip()


def transcribe(audio_b64: str, sample_rate: int) -> str:
    return transcribe_bytes(base64.b64decode(audio_b64), sample_rate)


def _wav_wrap(pcm_bytes: bytes, sample_rate: int = WAV_SAMPLE_RATE,
              channels: int = 1, bits: int = 16) -> bytes:
    data_len    = len(pcm_bytes)
    byte_rate   = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    header  = b"RIFF" + (data_len + 36).to_bytes(4, "little") + b"WAVE"
    header += b"fmt " + (16).to_bytes(4, "little")
    header += (1).to_bytes(2, "little")            # PCM
    header += channels.to_bytes(2, "little")
    header += sample_rate.to_bytes(4, "little")
    header += byte_rate.to_bytes(4, "little")
    header += block_align.to_bytes(2, "little")
    header += bits.to_bytes(2, "little")
    header += b"data" + data_len.to_bytes(4, "little")
    return header + pcm_bytes


def synthesize_bytes(text: str, fmt: str = "mp3") -> bytes:
    """Return raw audio bytes — MP3 (for dashboard) or WAV LINEAR16 wrapped
    with a RIFF header (for the M5Stack speaker)."""
    if fmt == "wav":
        audio_cfg = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=WAV_SAMPLE_RATE,
            volume_gain_db=16.0,  # +16 dB boost for M5Stack speaker (API max)
        )
    else:
        audio_cfg = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.0,
        )
    resp = _tts.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=VOICE,
        audio_config=audio_cfg,
    )
    payload = resp.audio_content
    if fmt == "wav":
        # Google TTS LINEAR16 already returns a RIFF/WAV-wrapped file.
        # Only add our own header if it came back as raw PCM (no RIFF magic).
        if payload[:4] != b"RIFF":
            payload = _wav_wrap(payload)
    return payload


def synthesize(text: str, fmt: str = "mp3") -> str:
    """Same as `synthesize_bytes` but base64-encoded for JSON transport."""
    return base64.b64encode(synthesize_bytes(text, fmt=fmt)).decode("ascii")
