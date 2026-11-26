"""SQLite persistence layer for sessions, turns, CRM leads, calendar slots, and summaries."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.models import (
    Appointment,
    CalendarSlot,
    CallSession,
    CallSummary,
    ConversationTurn,
    LeadProfile,
    WebhookEvent,
)


class Database:
    """Thread-safe SQLite repository backing the Autonomous Sales Voice Agent."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._seed_calendar_slots()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    language TEXT NOT NULL,
                    status TEXT NOT NULL,
                    prospect_name TEXT,
                    prospect_email TEXT,
                    company TEXT,
                    bant_json TEXT NOT NULL,
                    sentiment_history_json TEXT NOT NULL,
                    detected_objections_json TEXT NOT NULL,
                    buying_signals_json TEXT NOT NULL,
                    appointment_id TEXT,
                    lead_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS turns (
                    turn_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    speaker TEXT NOT NULL,
                    text TEXT NOT NULL,
                    redacted_text TEXT NOT NULL,
                    language TEXT NOT NULL,
                    sentiment_json TEXT,
                    rag_sources_json TEXT NOT NULL,
                    telemetry_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS leads (
                    lead_id TEXT PRIMARY KEY,
                    session_id TEXT UNIQUE NOT NULL,
                    name TEXT,
                    email TEXT,
                    company TEXT,
                    role TEXT,
                    phone TEXT,
                    language TEXT NOT NULL,
                    bant_score INTEGER NOT NULL,
                    tier TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    estimated_acv INTEGER NOT NULL,
                    notes TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS calendar_slots (
                    slot_id TEXT PRIMARY KEY,
                    ae_name TEXT NOT NULL,
                    ae_email TEXT NOT NULL,
                    start_iso TEXT NOT NULL,
                    end_iso TEXT NOT NULL,
                    display_label TEXT NOT NULL,
                    is_booked INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS appointments (
                    appointment_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    lead_id TEXT NOT NULL,
                    slot_id TEXT NOT NULL,
                    prospect_name TEXT NOT NULL,
                    prospect_email TEXT NOT NULL,
                    company TEXT NOT NULL,
                    ae_name TEXT NOT NULL,
                    start_iso TEXT NOT NULL,
                    end_iso TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    meeting_link TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS webhook_logs (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    target TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS call_summaries (
                    summary_id TEXT PRIMARY KEY,
                    session_id TEXT UNIQUE NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _seed_calendar_slots(self) -> None:
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM calendar_slots").fetchone()[0]
            if count > 0:
                return

            now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            aes = [
                ("Priya Sharma", "priya.sharma@novaflow.ai"),
                ("Marcus Vance", "marcus.vance@novaflow.ai"),
            ]
            slots: List[tuple[Any, ...]] = []
            day_offset = 1
            created = 0
            while created < 8:
                candidate_day = now + timedelta(days=day_offset)
                day_offset += 1
                if candidate_day.weekday() >= 5:
                    continue
                for hour, ae_idx in [(14, 0), (16, 1)]:
                    start_dt = candidate_day.replace(hour=hour)
                    end_dt = start_dt + timedelta(minutes=30)
                    slot_id = f"slot-{start_dt.strftime('%Y%m%d-%H%M')}"
                    ae_name, ae_email = aes[ae_idx]
                    label = f"{start_dt.strftime('%a %b %d, %H:%M')} UTC ({ae_name})"
                    slots.append(
                        (
                            slot_id,
                            ae_name,
                            ae_email,
                            start_dt.isoformat(),
                            end_dt.isoformat(),
                            label,
                            0,
                        )
                    )
                    created += 1
                    if created >= 8:
                        break

            conn.executemany(
                """
                INSERT OR IGNORE INTO calendar_slots
                (slot_id, ae_name, ae_email, start_iso, end_iso, display_label, is_booked)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                slots,
            )

    # ---- Session CRUD ----
    def upsert_session(self, session: CallSession) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, language, status, prospect_name, prospect_email, company,
                    bant_json, sentiment_history_json, detected_objections_json,
                    buying_signals_json, appointment_id, lead_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    language=excluded.language,
                    status=excluded.status,
                    prospect_name=excluded.prospect_name,
                    prospect_email=excluded.prospect_email,
                    company=excluded.company,
                    bant_json=excluded.bant_json,
                    sentiment_history_json=excluded.sentiment_history_json,
                    detected_objections_json=excluded.detected_objections_json,
                    buying_signals_json=excluded.buying_signals_json,
                    appointment_id=excluded.appointment_id,
                    lead_id=excluded.lead_id,
                    updated_at=excluded.updated_at
                """,
                (
                    session.session_id,
                    session.language,
                    session.status,
                    session.prospect_name,
                    session.prospect_email,
                    session.company,
                    session.bant.model_dump_json(),
                    json.dumps(session.sentiment_history),
                    json.dumps(session.detected_objections),
                    json.dumps(session.buying_signals),
                    session.appointment_id,
                    session.lead_id,
                    session.created_at,
                    session.updated_at,
                ),
            )

    def get_session(self, session_id: str) -> Optional[CallSession]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_session(row)

    def list_sessions(self, limit: int = 50) -> List[CallSession]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._row_to_session(r) for r in rows]

    def _row_to_session(self, row: sqlite3.Row) -> CallSession:
        return CallSession(
            session_id=row["session_id"],
            language=row["language"],
            status=row["status"],
            prospect_name=row["prospect_name"],
            prospect_email=row["prospect_email"],
            company=row["company"],
            bant=json.loads(row["bant_json"]),
            sentiment_history=json.loads(row["sentiment_history_json"]),
            detected_objections=json.loads(row["detected_objections_json"]),
            buying_signals=json.loads(row["buying_signals_json"]),
            appointment_id=row["appointment_id"],
            lead_id=row["lead_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ---- Turns CRUD ----
    def add_turn(self, turn: ConversationTurn) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO turns (
                    turn_id, session_id, speaker, text, redacted_text, language,
                    sentiment_json, rag_sources_json, telemetry_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn.turn_id,
                    turn.session_id,
                    turn.speaker,
                    turn.text,
                    turn.redacted_text,
                    turn.language,
                    turn.sentiment.model_dump_json() if turn.sentiment else None,
                    json.dumps([c.model_dump() for c in turn.rag_sources]),
                    turn.telemetry.model_dump_json() if turn.telemetry else None,
                    turn.created_at,
                ),
            )

    def get_turns(self, session_id: str) -> List[ConversationTurn]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM turns WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
            turns: List[ConversationTurn] = []
            for row in rows:
                turns.append(
                    ConversationTurn(
                        turn_id=row["turn_id"],
                        session_id=row["session_id"],
                        speaker=row["speaker"],
                        text=row["text"],
                        redacted_text=row["redacted_text"],
                        language=row["language"],
                        sentiment=json.loads(row["sentiment_json"])
                        if row["sentiment_json"]
                        else None,
                        rag_sources=json.loads(row["rag_sources_json"]),
                        telemetry=json.loads(row["telemetry_json"])
                        if row["telemetry_json"]
                        else None,
                        created_at=row["created_at"],
                    )
                )
            return turns

    # ---- Leads / CRM ----
    def upsert_lead(self, lead: LeadProfile) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO leads (
                    lead_id, session_id, name, email, company, role, phone, language,
                    bant_score, tier, stage, estimated_acv, notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    name=excluded.name,
                    email=excluded.email,
                    company=excluded.company,
                    role=excluded.role,
                    phone=excluded.phone,
                    language=excluded.language,
                    bant_score=excluded.bant_score,
                    tier=excluded.tier,
                    stage=excluded.stage,
                    estimated_acv=excluded.estimated_acv,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    lead.lead_id,
                    lead.session_id,
                    lead.name,
                    lead.email,
                    lead.company,
                    lead.role,
                    lead.phone,
                    lead.language,
                    lead.bant_score,
                    lead.tier,
                    lead.stage,
                    lead.estimated_acv,
                    lead.notes,
                    lead.updated_at,
                ),
            )

    def get_lead_by_session(self, session_id: str) -> Optional[LeadProfile]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM leads WHERE session_id = ?", (session_id,)
            ).fetchone()
            return self._row_to_lead(row) if row else None

    def list_leads(self) -> List[LeadProfile]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM leads ORDER BY updated_at DESC"
            ).fetchall()
            return [self._row_to_lead(r) for r in rows]

    def _row_to_lead(self, row: sqlite3.Row) -> LeadProfile:
        return LeadProfile(
            lead_id=row["lead_id"],
            session_id=row["session_id"],
            name=row["name"],
            email=row["email"],
            company=row["company"],
            role=row["role"],
            phone=row["phone"],
            language=row["language"],
            bant_score=row["bant_score"],
            tier=row["tier"],
            stage=row["stage"],
            estimated_acv=row["estimated_acv"],
            notes=row["notes"],
            updated_at=row["updated_at"],
        )

    # ---- Calendar & Appointments ----
    def list_slots(self, available_only: bool = False) -> List[CalendarSlot]:
        with self._connect() as conn:
            query = "SELECT * FROM calendar_slots"
            if available_only:
                query += " WHERE is_booked = 0"
            query += " ORDER BY start_iso ASC"
            rows = conn.execute(query).fetchall()
            return [
                CalendarSlot(
                    slot_id=r["slot_id"],
                    ae_name=r["ae_name"],
                    ae_email=r["ae_email"],
                    start_iso=r["start_iso"],
                    end_iso=r["end_iso"],
                    display_label=r["display_label"],
                    is_booked=bool(r["is_booked"]),
                )
                for r in rows
            ]

    def book_slot_transaction(self, appointment: Appointment) -> bool:
        """Atomically mark slot as booked and insert appointment if slot is still free."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE calendar_slots SET is_booked = 1 WHERE slot_id = ? AND is_booked = 0",
                (appointment.slot_id,),
            )
            if cur.rowcount == 0:
                return False
            conn.execute(
                """
                INSERT INTO appointments (
                    appointment_id, session_id, lead_id, slot_id, prospect_name,
                    prospect_email, company, ae_name, start_iso, end_iso, timezone,
                    meeting_link, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    appointment.appointment_id,
                    appointment.session_id,
                    appointment.lead_id,
                    appointment.slot_id,
                    appointment.prospect_name,
                    appointment.prospect_email,
                    appointment.company,
                    appointment.ae_name,
                    appointment.start_iso,
                    appointment.end_iso,
                    appointment.timezone,
                    appointment.meeting_link,
                    appointment.status,
                    appointment.created_at,
                ),
            )
            return True

    def get_slot(self, slot_id: str) -> Optional[CalendarSlot]:
        with self._connect() as conn:
            r = conn.execute(
                "SELECT * FROM calendar_slots WHERE slot_id = ?", (slot_id,)
            ).fetchone()
            if not r:
                return None
            return CalendarSlot(
                slot_id=r["slot_id"],
                ae_name=r["ae_name"],
                ae_email=r["ae_email"],
                start_iso=r["start_iso"],
                end_iso=r["end_iso"],
                display_label=r["display_label"],
                is_booked=bool(r["is_booked"]),
            )

    def get_appointment(self, appointment_id: str) -> Optional[Appointment]:
        with self._connect() as conn:
            r = conn.execute(
                "SELECT * FROM appointments WHERE appointment_id = ?", (appointment_id,)
            ).fetchone()
            return self._row_to_appointment(r) if r else None

    def list_appointments(self) -> List[Appointment]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM appointments ORDER BY start_iso ASC"
            ).fetchall()
            return [self._row_to_appointment(r) for r in rows]

    def _row_to_appointment(self, r: sqlite3.Row) -> Appointment:
        return Appointment(
            appointment_id=r["appointment_id"],
            session_id=r["session_id"],
            lead_id=r["lead_id"],
            slot_id=r["slot_id"],
            prospect_name=r["prospect_name"],
            prospect_email=r["prospect_email"],
            company=r["company"],
            ae_name=r["ae_name"],
            start_iso=r["start_iso"],
            end_iso=r["end_iso"],
            timezone=r["timezone"],
            meeting_link=r["meeting_link"],
            status=r["status"],
            created_at=r["created_at"],
        )

    # ---- Webhooks & Summaries ----
    def log_webhook(self, event: WebhookEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO webhook_logs (
                    event_id, event_type, session_id, idempotency_key,
                    target, status, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.session_id,
                    event.idempotency_key,
                    event.target,
                    event.status,
                    json.dumps(event.payload),
                    event.created_at,
                ),
            )

    def list_webhooks(self, limit: int = 50) -> List[WebhookEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM webhook_logs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [
                WebhookEvent(
                    event_id=r["event_id"],
                    event_type=r["event_type"],
                    session_id=r["session_id"],
                    idempotency_key=r["idempotency_key"],
                    target=r["target"],
                    status=r["status"],
                    payload=json.loads(r["payload_json"]),
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def save_summary(self, summary: CallSummary) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO call_summaries (summary_id, session_id, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    summary_id=excluded.summary_id,
                    payload_json=excluded.payload_json,
                    created_at=excluded.created_at
                """,
                (
                    summary.summary_id,
                    summary.session_id,
                    summary.model_dump_json(),
                    summary.created_at,
                ),
            )

    def get_summary(self, session_id: str) -> Optional[CallSummary]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM call_summaries WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return CallSummary.model_validate_json(row["payload_json"]) if row else None

    def list_summaries(self) -> List[CallSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM call_summaries ORDER BY created_at DESC"
            ).fetchall()
            return [CallSummary.model_validate_json(r["payload_json"]) for r in rows]
