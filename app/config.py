"""Application configuration and environment loader."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"


def _load_dotenv(env_path: Path) -> None:
    """Load simple KEY=VALUE pairs from .env if present without overwriting existing env vars."""
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")


SUPPORTED_LANGUAGES: Dict[str, Dict[str, str]] = {
    "en": {"name": "English", "bcp47": "en-US", "flag": "US"},
    "es": {"name": "Spanish", "bcp47": "es-ES", "flag": "ES"},
    "hi": {"name": "Hindi", "bcp47": "hi-IN", "flag": "IN"},
    "fr": {"name": "French", "bcp47": "fr-FR", "flag": "FR"},
    "de": {"name": "German", "bcp47": "de-DE", "flag": "DE"},
}


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the Autonomous AI Sales Voice Agent."""

    app_name: str = "NovaFlow AI — Autonomous Sales Voice Agent"
    host: str = field(default_factory=lambda: os.getenv("APP_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("APP_PORT", "8000")))
    database_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("DATABASE_PATH", str(BASE_DIR / "sales_agent.db"))
        )
    )
    knowledge_base_path: Path = field(
        default_factory=lambda: DATA_DIR / "knowledge_base.json"
    )
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
    )
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    crm_webhook_url: str = field(default_factory=lambda: os.getenv("CRM_WEBHOOK_URL", ""))
    pii_redaction_enabled: bool = field(
        default_factory=lambda: os.getenv("PII_REDACTION_ENABLED", "true").lower() == "true"
    )

    @property
    def active_llm_provider(self) -> str:
        """Return whichever external LLM provider is configured, or deterministic fallback."""
        if self.anthropic_api_key:
            return "anthropic"
        if self.openai_api_key:
            return "openai"
        if self.gemini_api_key:
            return "gemini"
        return "deterministic-rag"


settings = Settings()
