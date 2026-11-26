"""Pydantic data models for calls, RAG, BANT qualification, sentiment, CRM, and calendar."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


class RetrievedChunk(BaseModel):
    """A single knowledge-base chunk returned by the RAG retriever."""

    doc_id: str
    title: str
    category: str
    score: float
    excerpt: str


class BANTCriteria(BaseModel):
    """Extracted BANT (Budget, Authority, Need, Timeline) qualification details."""

    budget: Optional[str] = None
    budget_score: int = 0  # 0-25
    authority: Optional[str] = None
    authority_score: int = 0  # 0-25
    need: Optional[str] = None
    need_score: int = 0  # 0-30
    timeline: Optional[str] = None
    timeline_score: int = 0  # 0-20
    total_score: int = 0  # 0-100
    tier: Literal["Hot", "Warm", "Cold"] = "Cold"
    missing_fields: List[str] = Field(
        default_factory=lambda: ["budget", "authority", "need", "timeline"]
    )


class SentimentAnalysis(BaseModel):
    """Real-time sentiment, emotion, buying signals, and objections for an utterance."""

    polarity: float = 0.0  # -1.0 to +1.0
    label: Literal["Enthusiastic", "Positive", "Neutral", "Skeptical", "Frustrated"] = "Neutral"
    buying_signals: List[str] = Field(default_factory=list)
    objections: List[str] = Field(default_factory=list)


class TurnTelemetry(BaseModel):
    """Latency & pipeline execution metrics per conversational turn."""

    rag_ms: float = 0.0
    nlp_ms: float = 0.0
    llm_ms: float = 0.0
    total_ms: float = 0.0
    provider: str = "deterministic-rag"


class ConversationTurn(BaseModel):
    """A single speaker turn in a sales voice session."""

    turn_id: str
    session_id: str
    speaker: Literal["prospect", "agent", "system"]
    text: str
    redacted_text: str
    language: str = "en"
    sentiment: Optional[SentimentAnalysis] = None
    rag_sources: List[RetrievedChunk] = Field(default_factory=list)
    telemetry: Optional[TurnTelemetry] = None
    created_at: str = Field(default_factory=utc_now_iso)


class LeadProfile(BaseModel):
    """Prospect profile synced to the CRM."""

    lead_id: str
    session_id: str
    name: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    language: str = "en"
    bant_score: int = 0
    tier: Literal["Hot", "Warm", "Cold"] = "Cold"
    stage: Literal[
        "New Lead",
        "Discovery",
        "Qualified (SQL)",
        "Demo Scheduled",
        "Nurture",
        "Disqualified",
    ] = "New Lead"
    estimated_acv: int = 17988  # Default Growth annual value ($1,499 * 12)
    notes: str = ""
    updated_at: str = Field(default_factory=utc_now_iso)


class CalendarSlot(BaseModel):
    """An available or booked AE meeting slot."""

    slot_id: str
    ae_name: str
    ae_email: str
    start_iso: str
    end_iso: str
    display_label: str
    is_booked: bool = False


class Appointment(BaseModel):
    """A booked demo or discovery call appointment."""

    appointment_id: str
    session_id: str
    lead_id: str
    slot_id: str
    prospect_name: str
    prospect_email: str
    company: str
    ae_name: str
    start_iso: str
    end_iso: str
    timezone: str = "UTC"
    meeting_link: str
    status: Literal["Confirmed", "Cancelled"] = "Confirmed"
    created_at: str = Field(default_factory=utc_now_iso)


class CallSummary(BaseModel):
    """Structured post-call executive summary and business insights."""

    summary_id: str
    session_id: str
    headline: str
    executive_summary: str
    bant: BANTCriteria
    overall_sentiment: str
    avg_polarity: float
    detected_objections: List[str]
    buying_signals: List[str]
    recommended_plan: str
    estimated_acv: int
    next_actions: List[str]
    follow_up_email_subject: str
    follow_up_email_body: str
    appointment: Optional[Appointment] = None
    created_at: str = Field(default_factory=utc_now_iso)


class CallSession(BaseModel):
    """Complete live or completed voice session state."""

    session_id: str
    language: str = "en"
    status: Literal["active", "completed"] = "active"
    prospect_name: Optional[str] = None
    prospect_email: Optional[str] = None
    company: Optional[str] = None
    bant: BANTCriteria = Field(default_factory=BANTCriteria)
    sentiment_history: List[float] = Field(default_factory=list)
    detected_objections: List[str] = Field(default_factory=list)
    buying_signals: List[str] = Field(default_factory=list)
    appointment_id: Optional[str] = None
    lead_id: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class StartCallRequest(BaseModel):
    """Payload to start a new voice sales session."""

    language: str = "en"
    prospect_name: Optional[str] = None
    prospect_email: Optional[str] = None
    company: Optional[str] = None


class UserMessageRequest(BaseModel):
    """Payload for sending a transcribed or typed prospect message."""

    text: str
    language: Optional[str] = None
    stt_ms: float = 0.0
    prospect_name: Optional[str] = None
    prospect_email: Optional[str] = None
    company: Optional[str] = None


class BookAppointmentRequest(BaseModel):
    """Payload for booking a calendar slot."""

    slot_id: Optional[str] = None
    prospect_name: Optional[str] = None
    prospect_email: Optional[str] = None
    company: Optional[str] = None
    timezone: str = "UTC"


class WebhookEvent(BaseModel):
    """Simulated or dispatched CRM webhook record."""

    event_id: str
    event_type: str
    session_id: str
    idempotency_key: str
    target: str
    status: str
    payload: Dict[str, Any]
    created_at: str = Field(default_factory=utc_now_iso)
