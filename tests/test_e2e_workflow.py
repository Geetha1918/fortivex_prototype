"""End-to-end business workflow test over REST & WebSocket."""

import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

from app.main import create_app


class TestEndToEndSalesWorkflow(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "e2e.db"
        self.app = create_app(db_path=self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_complete_voice_sales_workflow(self) -> None:
        with TestClient(self.app) as client:
            # 1. Health check
            health = client.get("/api/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()["status"], "ok")

            # 2. Start call
            start = client.post(
                "/api/calls",
                json={
                    "language": "en",
                    "prospect_name": "Sarah Jenkins",
                    "company": "FinScale Cloud",
                    "prospect_email": "sarah@finscale.io",
                },
            )
            self.assertEqual(start.status_code, 201)
            session_id = start.json()["session"]["session_id"]

            # 3. WebSocket real-time conversation -> qualification -> booking
            with client.websocket_connect(f"/ws/call/{session_id}") as ws:
                ready = ws.receive_json()
                self.assertEqual(ready["type"], "session_ready")

                # Turn 1: Hot lead context
                ws.send_json(
                    {
                        "type": "transcript",
                        "text": (
                            "I am the VP of Sales at FinScale Cloud. We have slow lead response "
                            "times, a $30k budget, and want to launch this month."
                        ),
                    }
                )
                r1 = ws.receive_json()
                self.assertEqual(r1["type"], "agent_response")
                self.assertEqual(r1["session"]["bant"]["tier"], "Hot")
                self.assertGreaterEqual(r1["session"]["bant"]["total_score"], 75)
                self.assertGreaterEqual(len(r1["agent_turn"]["rag_sources"]), 1)

                # Turn 2: Pricing & security objection
                ws.send_json(
                    {
                        "type": "transcript",
                        "text": "Wait, $1,499 sounds expensive and are you SOC 2 compliant?",
                    }
                )
                r2 = ws.receive_json()
                self.assertIn("Pricing / Budget", r2["session"]["detected_objections"])

                # Turn 3: Automated booking trigger
                ws.send_json(
                    {
                        "type": "transcript",
                        "text": "That makes sense! Yes, please book a demo slot for me.",
                    }
                )
                r3 = ws.receive_json()
                self.assertIsNotNone(r3["appointment"])
                appt_id = r3["appointment"]["appointment_id"]
                self.assertEqual(r3["lead"]["stage"], "Demo Scheduled")

                # Turn 4: End call & summarize over WebSocket
                ws.send_json({"type": "end_call"})
                summary_evt = ws.receive_json()
                self.assertEqual(summary_evt["type"], "summary_ready")
                self.assertEqual(summary_evt["summary"]["bant"]["tier"], "Hot")
                self.assertIsNotNone(summary_evt["summary"]["appointment"])

            # 4. Verify .ics calendar invite download
            ics_resp = client.get(f"/api/calendar/appointments/{appt_id}/ics")
            self.assertEqual(ics_resp.status_code, 200)
            self.assertIn("BEGIN:VEVENT", ics_resp.text)

            # 5. Verify CRM and Business Insights reflect the call
            crm_resp = client.get("/api/crm")
            self.assertEqual(crm_resp.status_code, 200)
            self.assertEqual(len(crm_resp.json()["leads"]), 1)
            self.assertEqual(crm_resp.json()["leads"][0]["stage"], "Demo Scheduled")

            insights_resp = client.get("/api/insights")
            self.assertEqual(insights_resp.status_code, 200)
            kpis = insights_resp.json()["kpis"]
            self.assertEqual(kpis["total_calls"], 1)
            self.assertEqual(kpis["booked_demos"], 1)
            self.assertEqual(kpis["conversion_rate_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
