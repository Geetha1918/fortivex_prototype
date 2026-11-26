"""Starlette REST and WebSocket endpoints for the Autonomous AI Sales Voice Agent."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.agent.sales_agent import SalesVoiceAgent
from app.config import SUPPORTED_LANGUAGES, settings
from app.database import Database
from app.integrations.calendar_service import CalendarService
from app.integrations.crm_service import CRMService
from app.models import BookAppointmentRequest, StartCallRequest, UserMessageRequest
from app.rag.retriever import KnowledgeRetriever
from app.voice.adapters import build_tts_directive


class ServiceContainer:
    """Holds initialized singletons bound to the application lifecycle."""

    def __init__(self, db_path=None, kb_path=None) -> None:
        self.db = Database(db_path or settings.database_path)
        self.retriever = KnowledgeRetriever(kb_path or settings.knowledge_base_path)
        self.calendar = CalendarService(self.db)
        self.crm = CRMService(self.db)
        self.agent = SalesVoiceAgent(
            db=self.db,
            retriever=self.retriever,
            calendar=self.calendar,
            crm=self.crm,
        )


def _services(request_or_ws: Any) -> ServiceContainer:
    return request_or_ws.app.state.services


async def health(request: Request) -> JSONResponse:
    svc = _services(request)
    return JSONResponse(
        {
            "status": "ok",
            "app": settings.app_name,
            "llm_provider": settings.active_llm_provider,
            "pii_redaction_enabled": settings.pii_redaction_enabled,
            "kb_documents": len(svc.retriever.documents),
            "supported_languages": SUPPORTED_LANGUAGES,
        }
    )


async def list_calls(request: Request) -> JSONResponse:
    svc = _services(request)
    sessions = [s.model_dump() for s in svc.db.list_sessions()]
    return JSONResponse({"sessions": sessions})


async def start_call(request: Request) -> JSONResponse:
    svc = _services(request)
    try:
        body = await request.json() if await request.body() else {}
        payload = StartCallRequest.model_validate(body)
    except ValidationError as exc:
        return JSONResponse({"error": exc.errors()}, status_code=422)

    session, opening_turn, lead = svc.agent.start_session(
        language=payload.language,
        prospect_name=payload.prospect_name,
        prospect_email=payload.prospect_email,
        company=payload.company,
    )
    return JSONResponse(
        {
            "session": session.model_dump(),
            "opening_turn": opening_turn.model_dump(),
            "lead": lead.model_dump(),
            "tts": build_tts_directive(opening_turn.text, session.language),
            "available_slots": [s.model_dump() for s in svc.calendar.get_available_slots()],
        },
        status_code=201,
    )


async def get_call_detail(request: Request) -> JSONResponse:
    svc = _services(request)
    session_id = request.path_params["session_id"]
    session = svc.db.get_session(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    turns = [t.model_dump() for t in svc.db.get_turns(session_id)]
    lead = svc.db.get_lead_by_session(session_id)
    summary = svc.db.get_summary(session_id)
    appointment = (
        svc.db.get_appointment(session.appointment_id)
        if session.appointment_id
        else None
    )
    return JSONResponse(
        {
            "session": session.model_dump(),
            "turns": turns,
            "lead": lead.model_dump() if lead else None,
            "appointment": appointment.model_dump() if appointment else None,
            "summary": summary.model_dump() if summary else None,
        }
    )


async def post_message(request: Request) -> JSONResponse:
    svc = _services(request)
    session_id = request.path_params["session_id"]
    try:
        payload = UserMessageRequest.model_validate(await request.json())
    except ValidationError as exc:
        return JSONResponse({"error": exc.errors()}, status_code=422)

    if not payload.text.strip():
        return JSONResponse({"error": "Message text cannot be empty"}, status_code=400)

    try:
        result = svc.agent.handle_prospect_message(
            session_id=session_id,
            text=payload.text.strip(),
            language_override=payload.language,
            prospect_name=payload.prospect_name,
            prospect_email=payload.prospect_email,
            company=payload.company,
        )
    except KeyError:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    agent_turn = result["agent_turn"]
    return JSONResponse(
        {
            "session": result["session"].model_dump(),
            "prospect_turn": result["prospect_turn"].model_dump(),
            "agent_turn": agent_turn.model_dump(),
            "lead": result["lead"].model_dump(),
            "appointment": result["appointment"].model_dump() if result["appointment"] else None,
            "available_slots": [s.model_dump() for s in result["available_slots"]],
            "tts": build_tts_directive(agent_turn.text, agent_turn.language),
        }
    )


async def summarize_call(request: Request) -> JSONResponse:
    svc = _services(request)
    session_id = request.path_params["session_id"]
    try:
        summary = svc.agent.generate_call_summary(session_id, complete_call=True)
    except KeyError:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse({"summary": summary.model_dump()})


async def book_call_appointment(request: Request) -> JSONResponse:
    svc = _services(request)
    session_id = request.path_params["session_id"]
    session = svc.db.get_session(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    try:
        body = await request.json() if await request.body() else {}
        payload = BookAppointmentRequest.model_validate(body)
    except ValidationError as exc:
        return JSONResponse({"error": exc.errors()}, status_code=422)

    lead = svc.db.get_lead_by_session(session_id)
    lead_id = lead.lead_id if lead else (session.lead_id or "lead-manual")
    try:
        appointment = svc.calendar.book_slot(
            session_id=session_id,
            lead_id=lead_id,
            prospect_name=payload.prospect_name or session.prospect_name or "Valued Prospect",
            prospect_email=payload.prospect_email or session.prospect_email or "prospect@company.com",
            company=payload.company or session.company or "Enterprise Prospect",
            slot_id=payload.slot_id,
            timezone_str=payload.timezone,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)

    session.appointment_id = appointment.appointment_id
    if payload.prospect_name:
        session.prospect_name = payload.prospect_name
    if payload.prospect_email:
        session.prospect_email = payload.prospect_email
    if payload.company:
        session.company = payload.company
    svc.db.upsert_session(session)
    updated_lead = svc.crm.sync_session_to_crm(
        session, event_type="appointment.booked", appointment=appointment
    )
    return JSONResponse(
        {
            "appointment": appointment.model_dump(),
            "lead": updated_lead.model_dump(),
        },
        status_code=201,
    )


async def list_crm(request: Request) -> JSONResponse:
    svc = _services(request)
    leads = [l.model_dump() for l in svc.db.list_leads()]
    webhooks = [w.model_dump() for w in svc.db.list_webhooks(limit=30)]
    return JSONResponse({"leads": leads, "webhooks": webhooks})


async def list_calendar(request: Request) -> JSONResponse:
    svc = _services(request)
    slots = [s.model_dump() for s in svc.calendar.get_all_slots()]
    appointments = [a.model_dump() for a in svc.db.list_appointments()]
    return JSONResponse({"slots": slots, "appointments": appointments})


async def download_ics(request: Request) -> Response:
    svc = _services(request)
    appointment_id = request.path_params["appointment_id"]
    appt = svc.db.get_appointment(appointment_id)
    if not appt:
        return JSONResponse({"error": "Appointment not found"}, status_code=404)
    ics_text = svc.calendar.build_ics(appt)
    return PlainTextResponse(
        ics_text,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{appointment_id}.ics"'},
    )


async def kb_query_or_list(request: Request) -> JSONResponse:
    svc = _services(request)
    query = request.query_params.get("q", "").strip()
    if query:
        chunks = [c.model_dump() for c in svc.retriever.retrieve(query, top_k=3)]
        return JSONResponse({"query": query, "results": chunks})
    return JSONResponse({"documents": svc.retriever.documents})


async def kb_add_document(request: Request) -> JSONResponse:
    svc = _services(request)
    body = await request.json()
    for field in ("doc_id", "title", "category", "content"):
        if not body.get(field):
            return JSONResponse({"error": f"Missing required field '{field}'"}, status_code=400)
    doc = svc.retriever.add_document(
        doc_id=body["doc_id"],
        title=body["title"],
        category=body["category"],
        content=body["content"],
        tags=body.get("tags", []),
    )
    return JSONResponse({"document": doc, "total_documents": len(svc.retriever.documents)}, status_code=201)


async def business_insights(request: Request) -> JSONResponse:
    svc = _services(request)
    sessions = svc.db.list_sessions(limit=200)
    leads = svc.db.list_leads()
    appointments = svc.db.list_appointments()
    summaries = svc.db.list_summaries()

    total_calls = len(sessions)
    avg_bant = round(sum(s.bant.total_score for s in sessions) / total_calls, 1) if total_calls else 0.0
    all_polarities = [p for s in sessions for p in s.sentiment_history]
    avg_polarity = round(sum(all_polarities) / len(all_polarities), 2) if all_polarities else 0.0
    total_pipeline_acv = sum(l.estimated_acv for l in leads)

    tier_counts = Counter(l.tier for l in leads)
    stage_counts = Counter(l.stage for l in leads)
    lang_counts = Counter(s.language for s in sessions)
    objection_counts = Counter(obj for s in sessions for obj in s.detected_objections)

    return JSONResponse(
        {
            "kpis": {
                "total_calls": total_calls,
                "active_calls": sum(1 for s in sessions if s.status == "active"),
                "completed_calls": sum(1 for s in sessions if s.status == "completed"),
                "booked_demos": len(appointments),
                "conversion_rate_pct": round((len(appointments) / total_calls) * 100, 1)
                if total_calls
                else 0.0,
                "avg_bant_score": avg_bant,
                "avg_sentiment_polarity": avg_polarity,
                "total_pipeline_acv_usd": total_pipeline_acv,
            },
            "distributions": {
                "tiers": dict(tier_counts),
                "stages": dict(stage_counts),
                "languages": dict(lang_counts),
                "top_objections": dict(objection_counts.most_common(6)),
            },
            "summaries": [s.model_dump() for s in summaries[:15]],
        }
    )


async def ws_voice_call(websocket: WebSocket) -> None:
    """Real-time bidirectional voice & event WebSocket for low-latency sales calls."""
    svc = _services(websocket)
    session_id = websocket.path_params["session_id"]
    session = svc.db.get_session(session_id)
    if not session:
        await websocket.close(code=4004, reason="Session not found")
        return

    await websocket.accept()
    await websocket.send_json(
        {
            "type": "session_ready",
            "session": session.model_dump(),
            "turns": [t.model_dump() for t in svc.db.get_turns(session_id)],
            "available_slots": [s.model_dump() for s in svc.calendar.get_available_slots()],
        }
    )

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type", "transcript")

            if msg_type == "barge_in":
                await websocket.send_json({"type": "tts_interrupt", "status": "listening"})
                continue

            if msg_type == "audio_chunk":
                # Hook for server-side VAD/Whisper binary frames when using raw mic PCM
                await websocket.send_json(
                    {
                        "type": "audio_ack",
                        "bytes": len(msg.get("data", "")),
                        "vad_active": True,
                    }
                )
                continue

            if msg_type == "end_call":
                summary = svc.agent.generate_call_summary(session_id, complete_call=True)
                await websocket.send_json(
                    {"type": "summary_ready", "summary": summary.model_dump()}
                )
                continue

            if msg_type == "transcript":
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                result = svc.agent.handle_prospect_message(
                    session_id=session_id,
                    text=text,
                    language_override=msg.get("language"),
                    prospect_name=msg.get("prospect_name"),
                    prospect_email=msg.get("prospect_email"),
                    company=msg.get("company"),
                )
                agent_turn = result["agent_turn"]
                await websocket.send_json(
                    {
                        "type": "agent_response",
                        "session": result["session"].model_dump(),
                        "prospect_turn": result["prospect_turn"].model_dump(),
                        "agent_turn": agent_turn.model_dump(),
                        "lead": result["lead"].model_dump(),
                        "appointment": result["appointment"].model_dump()
                        if result["appointment"]
                        else None,
                        "available_slots": [
                            s.model_dump() for s in result["available_slots"]
                        ],
                        "tts": build_tts_directive(agent_turn.text, agent_turn.language),
                    }
                )
    except WebSocketDisconnect:
        return


routes = [
    Route("/api/health", health, methods=["GET"]),
    Route("/api/calls", list_calls, methods=["GET"]),
    Route("/api/calls", start_call, methods=["POST"]),
    Route("/api/calls/{session_id}", get_call_detail, methods=["GET"]),
    Route("/api/calls/{session_id}/message", post_message, methods=["POST"]),
    Route("/api/calls/{session_id}/summarize", summarize_call, methods=["POST"]),
    Route("/api/calls/{session_id}/book", book_call_appointment, methods=["POST"]),
    Route("/api/crm", list_crm, methods=["GET"]),
    Route("/api/calendar", list_calendar, methods=["GET"]),
    Route("/api/calendar/appointments/{appointment_id}/ics", download_ics, methods=["GET"]),
    Route("/api/kb", kb_query_or_list, methods=["GET"]),
    Route("/api/kb/documents", kb_add_document, methods=["POST"]),
    Route("/api/insights", business_insights, methods=["GET"]),
    WebSocketRoute("/ws/call/{session_id}", ws_voice_call),
]
