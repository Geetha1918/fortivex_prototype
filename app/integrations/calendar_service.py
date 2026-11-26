"""Calendar availability, conflict-free appointment booking, and .ics invite generation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.database import Database
from app.models import Appointment, CalendarSlot


class CalendarService:
    """Manages AE calendar slots and automated demo booking."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get_available_slots(self, limit: int = 8) -> List[CalendarSlot]:
        """Return unbooked AE calendar slots."""
        return self.db.list_slots(available_only=True)[:limit]

    def get_all_slots(self) -> List[CalendarSlot]:
        """Return all calendar slots (booked and available)."""
        return self.db.list_slots(available_only=False)

    def book_slot(
        self,
        session_id: str,
        lead_id: str,
        prospect_name: str,
        prospect_email: str,
        company: str,
        slot_id: Optional[str] = None,
        timezone_str: str = "UTC",
    ) -> Appointment:
        """Book the requested slot (or next available slot) atomically."""
        slot: Optional[CalendarSlot] = None
        if slot_id:
            slot = self.db.get_slot(slot_id)
            if not slot:
                raise ValueError(f"Calendar slot '{slot_id}' not found.")
            if slot.is_booked:
                raise ValueError(f"Calendar slot '{slot_id}' is already booked.")
        else:
            available = self.get_available_slots(limit=1)
            if not available:
                raise ValueError("No calendar slots are currently available.")
            slot = available[0]

        appt_id = f"appt-{uuid.uuid4().hex[:8]}"
        meeting_link = f"https://meet.novaflow.ai/room/{appt_id}"
        appointment = Appointment(
            appointment_id=appt_id,
            session_id=session_id,
            lead_id=lead_id,
            slot_id=slot.slot_id,
            prospect_name=prospect_name or "Valued Prospect",
            prospect_email=prospect_email or "prospect@company.com",
            company=company or "Prospect Organization",
            ae_name=slot.ae_name,
            start_iso=slot.start_iso,
            end_iso=slot.end_iso,
            timezone=timezone_str,
            meeting_link=meeting_link,
        )

        success = self.db.book_slot_transaction(appointment)
        if not success:
            raise ValueError(f"Slot '{slot.slot_id}' was just booked by another session.")
        return appointment

    @staticmethod
    def build_ics(appointment: Appointment) -> str:
        """Generate a standards-compliant RFC 5545 .ics calendar invite."""
        start_dt = datetime.fromisoformat(appointment.start_iso)
        end_dt = datetime.fromisoformat(appointment.end_iso)
        dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dtstart = start_dt.strftime("%Y%m%dT%H%M%SZ")
        dtend = end_dt.strftime("%Y%m%dT%H%M%SZ")

        return "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//NovaFlow AI//Autonomous Sales Voice Agent//EN",
                "CALSCALE:GREGORIAN",
                "METHOD:REQUEST",
                "BEGIN:VEVENT",
                f"UID:{appointment.appointment_id}@novaflow.ai",
                f"DTSTAMP:{dtstamp}",
                f"DTSTART:{dtstart}",
                f"DTEND:{dtend}",
                f"SUMMARY:NovaFlow AI Discovery & Live Demo — {appointment.company}",
                f"DESCRIPTION:Autonomous AI Sales Demo with {appointment.ae_name}. Join: {appointment.meeting_link}",
                f"LOCATION:{appointment.meeting_link}",
                "STATUS:CONFIRMED",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        )
