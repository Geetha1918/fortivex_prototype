"""Real-time PII redaction guardrails for transcripts and LLM audit logs."""

from __future__ import annotations

import re

_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")


def redact_pii(text: str, mask_contact_details: bool = False) -> str:
    """Mask sensitive payment/government IDs and optionally mask email/phone numbers."""
    redacted = _SSN_RE.sub("[REDACTED-SSN]", text)
    redacted = _CARD_RE.sub("[REDACTED-CARD]", redacted)
    if mask_contact_details:
        redacted = _EMAIL_RE.sub(r"\1***@\2", redacted)
        redacted = _PHONE_RE.sub("[REDACTED-PHONE]", redacted)
    return redacted
