"""Core Autonomous AI Sales Voice Agent orchestrator."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.agent.llm_provider import SalesLLMProvider
from app.config import settings
from app.database import Database
from app.integrations.calendar_service import CalendarService
from app.integrations.crm_service import CRMService
from app.models import (
    Appointment,
    CallSession,
    CallSummary,
    ConversationTurn,
    LeadProfile,
    TurnTelemetry,
    utc_now_iso,
)
from app.nlp.multilingual import detect_language, get_greeting
from app.nlp.qualification import extract_contact_entities, update_bant
from app.nlp.security import redact_pii
from app.nlp.sentiment import analyze_sentiment
from app.rag.retriever import KnowledgeRetriever

_BOOKING_INTENT_RE = re.compile(
    r"\b(book|schedule|lock in|confirm|reserve|set up|agendar|reservar|confirmar|"
    r"réserver|buchen|termin|डेमो बुक|बुक कर|मीटिंग फिक्स)\b",
    re.IGNORECASE,
)
_AFFIRMATIVE_RE = re.compile(
    r"\b(yes|yeah|yep|sure|sounds good|go ahead|please do|let's do it|sí|si|claro|"
    r"हाँ|जी|बिलकुल|oui|d'accord|ja|gerne)\b",
    re.IGNORECASE,
)


class SalesVoiceAgent:
    """Orchestrates memory, RAG, BANT qualification, sentiment, booking, CRM sync, and summaries."""

    def __init__(
        self,
        db: Database,
        retriever: KnowledgeRetriever,
        calendar: CalendarService,
        crm: CRMService,
        llm: Optional[SalesLLMProvider] = None,
    ) -> None:
        self.db = db
        self.retriever = retriever
        self.calendar = calendar
        self.crm = crm
        self.llm = llm or SalesLLMProvider()

    def start_session(
        self,
        language: str = "en",
        prospect_name: Optional[str] = None,
        prospect_email: Optional[str] = None,
        company: Optional[str] = None,
    ) -> Tuple[CallSession, ConversationTurn, LeadProfile]:
        """Initialize a new sales voice session with an opening agent turn and CRM lead."""
        session_id = f"call-{uuid.uuid4().hex[:8]}"
        session = CallSession(
            session_id=session_id,
            language=language,
            prospect_name=prospect_name,
            prospect_email=prospect_email,
            company=company,
        )
        self.db.upsert_session(session)

        greeting = get_greeting(language, prospect_name)
        opening_turn = ConversationTurn(
            turn_id=f"turn-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            speaker="agent",
            text=greeting,
            redacted_text=greeting,
            language=language,
            telemetry=TurnTelemetry(provider=settings.active_llm_provider),
        )
        self.db.add_turn(opening_turn)
        lead = self.crm.sync_session_to_crm(session, event_type="call.started")
        session.lead_id = lead.lead_id
        self.db.upsert_session(session)
        return session, opening_turn, lead

    def _should_auto_book(self, text: str, history: List[ConversationTurn], session: CallSession) -> bool:
        if session.appointment_id:
            return False
        if _BOOKING_INTENT_RE.search(text):
            return True
        # Also trigger if previous agent turn explicitly offered a demo slot and prospect says "yes / sounds good"
        agent_turns = [t for t in history if t.speaker == "agent"]
        if agent_turns and _AFFIRMATIVE_RE.search(text):
            last_agent = agent_turns[-1].text.lower()
            if any(k in last_agent for k in ["slot", "demo", "horario", "स्लॉट", "créneau", "termin"]):
                return True
        return False

    def handle_prospect_message(
        self,
        session_id: str,
        text: str,
        language_override: Optional[str] = None,
        prospect_name: Optional[str] = None,
        prospect_email: Optional[str] = None,
        company: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process one prospect utterance end-to-end and return updated session state."""
        t0 = time.perf_counter()
        session = self.db.get_session(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found.")

        history = self.db.get_turns(session_id)

        # Update metadata if supplied or extracted
        if prospect_name:
            session.prospect_name = prospect_name
        if prospect_email:
            session.prospect_email = prospect_email
        if company:
            session.company = company

        extracted = extract_contact_entities(text)
        if extracted["name"] and not session.prospect_name:
            session.prospect_name = extracted["name"]
        if extracted["email"] and not session.prospect_email:
            session.prospect_email = extracted["email"]
        if extracted["company"] and not session.company:
            session.company = extracted["company"]

        # 1. Language detection & PII redaction
        detected_lang = language_override or detect_language(text, default=session.language)
        session.language = detected_lang
        redacted = redact_pii(text) if settings.pii_redaction_enabled else text

        # 2. NLP: Sentiment + BANT qualification
        t_nlp0 = time.perf_counter()
        sentiment = analyze_sentiment(text)
        session.bant = update_bant(session.bant, text)
        session.sentiment_history.append(sentiment.polarity)
        for obj in sentiment.objections:
            if obj not in session.detected_objections:
                session.detected_objections.append(obj)
        for sig in sentiment.buying_signals:
            if sig not in session.buying_signals:
                session.buying_signals.append(sig)
        nlp_ms = round((time.perf_counter() - t_nlp0) * 1000, 2)

        prospect_turn = ConversationTurn(
            turn_id=f"turn-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            speaker="prospect",
            text=text,
            redacted_text=redacted,
            language=detected_lang,
            sentiment=sentiment,
        )
        self.db.add_turn(prospect_turn)

        # 3. RAG knowledge retrieval
        t_rag0 = time.perf_counter()
        rag_chunks = self.retriever.retrieve(text, top_k=3)
        rag_ms = round((time.perf_counter() - t_rag0) * 1000, 2)

        # 4. Automated Appointment Booking check
        booked_appointment: Optional[Appointment] = None
        if self._should_auto_book(text, history, session):
            try:
                lead = self.db.get_lead_by_session(session_id)
                lead_id = lead.lead_id if lead else (session.lead_id or f"lead-{uuid.uuid4().hex[:8]}")
                booked_appointment = self.calendar.book_slot(
                    session_id=session_id,
                    lead_id=lead_id,
                    prospect_name=session.prospect_name or "Valued Prospect",
                    prospect_email=session.prospect_email or "prospect@company.com",
                    company=session.company or "Enterprise Prospect",
                )
                session.appointment_id = booked_appointment.appointment_id
            except ValueError:
                booked_appointment = None

        # 5. Agent response generation
        t_llm0 = time.perf_counter()
        available_slots = self.calendar.get_available_slots(limit=4)
        reply_text, provider_name = self.llm.generate_reply(
            user_text=text,
            language=detected_lang,
            bant=session.bant,
            sentiment=sentiment,
            rag_chunks=rag_chunks,
            history=history,
            available_slots=available_slots,
            booked_appointment=booked_appointment,
        )
        llm_ms = round((time.perf_counter() - t_llm0) * 1000, 2)
        total_ms = round((time.perf_counter() - t0) * 1000, 2)

        agent_turn = ConversationTurn(
            turn_id=f"turn-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            speaker="agent",
            text=reply_text,
            redacted_text=reply_text,
            language=detected_lang,
            rag_sources=rag_chunks,
            telemetry=TurnTelemetry(
                rag_ms=rag_ms,
                nlp_ms=nlp_ms,
                llm_ms=llm_ms,
                total_ms=total_ms,
                provider=provider_name,
            ),
        )
        self.db.add_turn(agent_turn)

        # 6. Persist session & sync CRM
        session.updated_at = utc_now_iso()
        self.db.upsert_session(session)
        event_type = "appointment.booked" if booked_appointment else "lead.qualified_update"
        lead = self.crm.sync_session_to_crm(
            session, event_type=event_type, appointment=booked_appointment
        )
        session.lead_id = lead.lead_id
        self.db.upsert_session(session)

        return {
            "session": session,
            "prospect_turn": prospect_turn,
            "agent_turn": agent_turn,
            "lead": lead,
            "appointment": booked_appointment,
            "available_slots": available_slots,
        }

    def generate_call_summary(self, session_id: str, complete_call: bool = True) -> CallSummary:
        """Create and persist a structured post-call executive summary & follow-up email."""
        session = self.db.get_session(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found.")

        turns = self.db.get_turns(session_id)
        lead = self.crm.sync_session_to_crm(session, event_type="call.summarized")
        appointment = (
            self.db.get_appointment(session.appointment_id)
            if session.appointment_id
            else None
        )

        avg_polarity = (
            round(sum(session.sentiment_history) / len(session.sentiment_history), 2)
            if session.sentiment_history
            else 0.0
        )
        overall_sentiment = (
            "Positive / High Intent"
            if avg_polarity >= 0.2
            else ("Skeptical / Needs Nurturing" if avg_polarity < -0.1 else "Neutral / Exploratory")
        )

        if lead.estimated_acv >= 35000:
            recommended_plan = "Enterprise Plan ($3,500+/mo)"
        elif lead.estimated_acv <= 7000:
            recommended_plan = "Starter Plan ($499/mo)"
        else:
            recommended_plan = "Growth Plan ($1,499/mo)"

        prospect_turns_count = sum(1 for t in turns if t.speaker == "prospect")
        company_label = session.company or "the prospect's team"
        name_label = session.prospect_name or "there"

        headline = (
            f"{session.bant.tier} Lead ({session.bant.total_score}/100) — "
            f"{company_label} | {recommended_plan}"
        )
        exec_summary = (
            f"Completed a {prospect_turns_count}-turn {session.language.upper()} voice discovery call with "
            f"{session.prospect_name or 'Prospect'} ({company_label}). "
            f"BANT qualification scored {session.bant.total_score}/100 ({session.bant.tier} tier). "
            f"Primary need: {session.bant.need or 'Workflow & lead response automation'}. "
            f"Timeline: {session.bant.timeline or 'Evaluating'}. "
            + (
                f"Demo confirmed with {appointment.ae_name} on {appointment.start_iso[:16].replace('T', ' ')} UTC."
                if appointment
                else "Next step: share tailored ROI brief and lock in AE demo slot."
            )
        )

        next_actions: List[str] = []
        if appointment:
            next_actions.append(
                f"AE {appointment.ae_name} to prepare custom CRM integration sandbox for {appointment.start_iso[:10]}."
            )
        else:
            next_actions.append("Send calendar link to confirm 30-minute technical discovery demo.")
        if session.detected_objections:
            next_actions.append(
                f"Address {', '.join(session.detected_objections)} in follow-up ROI one-pager."
            )
        if session.bant.missing_fields:
            next_actions.append(
                f"Confirm remaining BANT criteria: {', '.join(session.bant.missing_fields)}."
            )
        next_actions.append(f"CRM stage synced as '{lead.stage}' (Est. ACV ${lead.estimated_acv:,}).")

        email_subject = (
            f"NovaFlow AI Demo Confirmed — {company_label}"
            if appointment
            else f"Following up on our NovaFlow AI conversation — {company_label}"
        )
        email_body = (
            f"Hi {name_label},\n\n"
            f"Thank you for speaking with NovaFlow AI today! Based on our discussion around "
            f"{session.bant.need or 'automating lead qualification and CRM workflows'}, "
            f"we recommend our {recommended_plan}.\n\n"
            + (
                f"Your 30-minute live demo with {appointment.ae_name} is confirmed for "
                f"{appointment.start_iso[:16].replace('T', ' ')} UTC.\n"
                f"Meeting link: {appointment.meeting_link}\n\n"
                if appointment
                else "I'd love to schedule a quick 30-minute walkthrough tailored to your CRM stack.\n\n"
            )
            + "Best regards,\nNova — NovaFlow AI Solutions Team"
        )

        summary = CallSummary(
            summary_id=f"sum-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            headline=headline,
            executive_summary=exec_summary,
            bant=session.bant,
            overall_sentiment=overall_sentiment,
            avg_polarity=avg_polarity,
            detected_objections=session.detected_objections,
            buying_signals=session.buying_signals,
            recommended_plan=recommended_plan,
            estimated_acv=lead.estimated_acv,
            next_actions=next_actions,
            follow_up_email_subject=email_subject,
            follow_up_email_body=email_body,
            appointment=appointment,
        )
        self.db.save_summary(summary)

        if complete_call:
            session.status = "completed"
            session.updated_at = utc_now_iso()
            self.db.upsert_session(session)

        return summary
