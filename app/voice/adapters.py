"""STT/TTS adapter abstractions and real-time voice session frame helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from app.config import SUPPORTED_LANGUAGES


@dataclass(frozen=True)
class VoiceConfig:
    """Voice synthesis and recognition configuration per language."""

    language: str
    bcp47_locale: str
    stt_engine: str = "WebSpeech-Streaming / Whisper-Ready"
    tts_engine: str = "WebSpeech-Neural / ElevenLabs-Ready"


def get_voice_config(language: str) -> VoiceConfig:
    """Return locale and engine metadata for a given ISO language code."""
    info = SUPPORTED_LANGUAGES.get(language, SUPPORTED_LANGUAGES["en"])
    return VoiceConfig(
        language=language if language in SUPPORTED_LANGUAGES else "en",
        bcp47_locale=info["bcp47"],
    )


def estimate_tts_duration_ms(text: str) -> int:
    """Estimate spoken audio playback duration (~150 words per minute)."""
    words = max(1, len(text.split()))
    return int((words / 2.5) * 1000)


def build_tts_directive(text: str, language: str) -> Dict[str, object]:
    """Build structured TTS directive sent over WebSocket or REST to the voice client."""
    cfg = get_voice_config(language)
    return {
        "text": text,
        "language": cfg.language,
        "locale": cfg.bcp47_locale,
        "estimated_duration_ms": estimate_tts_duration_ms(text),
        "tts_engine": cfg.tts_engine,
    }
