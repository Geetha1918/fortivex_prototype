"""CRM synchronization service mimicking HubSpot/Salesforce REST + webhook pipelines."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, Optional

import httpx

from app.config import settings
from app.database import Database
from app.models import Appointment, CallSession, LeadProfile, WebhookEvent, utc_now_iso


class CRMService:
    """Synchronizes qualified leads, deal stages, and call activities to the CRM."""

    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _estimate_acv(session: CallSession) -> int:
        budget_text = (session.bant.budget or "").lower()
        if "enterprise" in budget_text or "50k" in budget_text or "25k" in budget_text:
            return 42000
        if "starter" in budget_text or "499" in budget_text:
            return 5988
        if session.bant.tier == "Hot":
            return 24000
        return 17988

    @staticmethod
    def _derive_stage(session: CallSession) -> str:
        if session.appointment_id:
            return "Demo Scheduled"
        if session.bant.tier == "Hot":
            return "Qualified (SQL)"
        if session.bant.tier == "Warm":
            return "Discovery"
        return "New Lead"

    def sync_session_to_crm(
        self,
        session: CallSession,
        event_type: str = "lead.upserted",
        appointment: Optional[Appointment] = None,
    ) -> LeadProfile:
        """Upsert LeadProfile in SQLite CRM and record an idempotent CRM webhook event."""
        existing = self.db.get_lead_by_session(session.session_id)
        lead_id = existing.lead_id if existing else f"lead-{uuid.uuid4().hex[:8]}"

        notes_parts = []
        if session.bant.need:
            notes_parts.append(f"Need: {session.bant.need}")
        if session.bant.budget:
            notes_parts.append(f"Budget: {session.bant.budget}")
        if session.bant.timeline:
            notes_parts.append(f"Timeline: {session.bant.timeline}")
        if session.detected_objections:
            notes_parts.append(f"Objections: {', '.join(session.detected_objections)}")
        if appointment:
            notes_parts.append(f"Demo booked: {appointment.start_iso} w/ {appointment.ae_name}")

        lead = LeadProfile(
            lead_id=lead_id,
            session_id=session.session_id,
            name=session.prospect_name or (existing.name if existing else "Anonymous Prospect"),
            email=session.prospect_email or (existing.email if existing else None),
            company=session.company or (existing.company if existing else "Unknown Company"),
            role=session.bant.authority or (existing.role if existing else None),
            language=session.language,
            bant_score=session.bant.total_score,
            tier=session.bant.tier,
            stage=self._derive_stage(session),  # type: ignore[arg-type]
            estimated_acv=self._estimate_acv(session),
            notes=" | ".join(notes_parts),
            updated_at=utc_now_iso(),
        )
        self.db.upsert_lead(lead)

        payload: Dict[str, Any] = {
            "crm_provider": "HubSpot / Salesforce Unified Adapter",
            "lead_id": lead.lead_id,
            "session_id": session.session_id,
            "properties": {
                "firstname_lastname": lead.name,
                "email": lead.email,
                "company": lead.company,
                "jobtitle": lead.role,
                "hs_lead_status": lead.stage,
                "bant_score": lead.bant_score,
                "lead_tier": lead.tier,
                "preferred_language": lead.language,
                "amount_acv_usd": lead.estimated_acv,
            },
            "appointment": appointment.model_dump() if appointment else None,
        }

        idem_raw = f"{event_type}:{session.session_id}:{lead.bant_score}:{lead.stage}"
        idempotency_key = hashlib.sha256(idem_raw.encode("utf-8")).hexdigest()[:16]

        target = settings.crm_webhook_url or "internal://crm-sync-simulator"
        status = "200 OK (Simulated)"

        if settings.crm_webhook_url:
            try:
                resp = httpx.post(
                    settings.crm_webhook_url,
                    json=payload,
                    headers={"X-Idempotency-Key": idempotency_key},
                    timeout=3.0,
                )
                status = f"{resp.status_code} Dispatched"
            except Exception as exc:  # pragma: no cover - external network fallback
                status = f"Queued Retry ({exc.__class__.__name__})"

        self.db.log_webhook(
            WebhookEvent(
                event_id=f"evt-{uuid.uuid4().hex[:8]}",
                event_type=event_type,
                session_id=session.session_id,
                idempotency_key=idempotency_key,
                target=target,
                status=status,
                payload=payload,
            )
        )
        return lead
