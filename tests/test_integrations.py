"""Unit tests for atomic calendar booking, .ics generation, and CRM sync."""

import tempfile
import unittest
from pathlib import Path

from app.database import Database
from app.integrations.calendar_service import CalendarService
from app.integrations.crm_service import CRMService
from app.models import BANTCriteria, CallSession


class TestIntegrations(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.calendar = CalendarService(self.db)
        self.crm = CRMService(self.db)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_atomic_booking_prevents_double_booking(self) -> None:
        slots = self.calendar.get_available_slots()
        self.assertGreaterEqual(len(slots), 2)
        target_slot = slots[0].slot_id

        appt = self.calendar.book_slot(
            session_id="call-1",
            lead_id="lead-1",
            prospect_name="Alex Rivera",
            prospect_email="alex@acme.io",
            company="Acme Corp",
            slot_id=target_slot,
        )
        self.assertEqual(appt.slot_id, target_slot)

        ics = self.calendar.build_ics(appt)
        self.assertIn("BEGIN:VCALENDAR", ics)
        self.assertIn("Acme Corp", ics)

        with self.assertRaises(ValueError):
            self.calendar.book_slot(
                session_id="call-2",
                lead_id="lead-2",
                prospect_name="Other User",
                prospect_email="other@acme.io",
                company="Other Corp",
                slot_id=target_slot,
            )

    def test_crm_sync_updates_stage_and_logs_webhook(self) -> None:
        session = CallSession(
            session_id="call-crm",
            prospect_name="Priya Patel",
            company="ScaleUp Inc",
            bant=BANTCriteria(total_score=82, tier="Hot", budget="$25k"),
        )
        lead = self.crm.sync_session_to_crm(session, event_type="lead.qualified_update")
        self.assertEqual(lead.stage, "Qualified (SQL)")
        self.assertEqual(lead.tier, "Hot")

        webhooks = self.db.list_webhooks()
        self.assertEqual(len(webhooks), 1)
        self.assertEqual(webhooks[0].event_type, "lead.qualified_update")


if __name__ == "__main__":
    unittest.main()
