# NovaFlow AI — Autonomous Sales Voice Agent

A functional end-to-end AI Sales Voice Agent prototype featuring real-time browser STT/TTS over WebSockets, multilingual conversation (`EN`, `ES`, `HI`, `FR`, `DE`), incremental BANT lead qualification, sentiment & objection analysis, hybrid RAG knowledge grounding with citations, conflict-free calendar booking (`.ics`), CRM webhook sync, and executive call summarization.

---

## Quickstart

### 1. Run the Application
```bash
cd autonomous-ai-sales-voice-agent
./start.sh
# Or directly with Python 3.13:
# /usr/local/bin/python3 run.py
```
Then open **http://127.0.0.1:8000** in Chrome, Edge, or Safari.

> **Conda Note:** If your terminal has `(base)` conda active and `python3` resolves to conda without `uvicorn`, `./start.sh` automatically selects `/usr/local/bin/python3` (or run `conda deactivate` first).

> **Zero-Key Guarantee:** The system runs out-of-the-box with zero external API keys using its built-in **Deterministic RAG + Multilingual Sales Engine**. To enable live frontier LLM generation, copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`.

### 2. Run Automated Tests (Unit + End-to-End WebSocket/REST)
```bash
/usr/local/bin/python3 -m unittest discover -s tests -v
```

---

## End-to-End Demo Walkthrough

1. Click **Start New Voice Call** in the **Voice Studio** tab (optionally enter prospect name/company/language).
2. Click **Start Mic (STT)** to speak directly in your browser, **OR** click any of the **1-Click Demo Utterances**:
   - *Enterprise Hot Lead* → Watch BANT score jump to `Hot` (`>=75/100`), contact entities auto-extract, and CRM stage advance to `Qualified (SQL)`.
   - *Pricing Objection* → Watch Sentiment shift to `Skeptical`, `Pricing / Budget` objection tag appear, and RAG retrieve the Objection Playbook with similarity scores.
   - *Spanish / Hindi* → Watch automatic language detection switch TTS voice and grounded response language seamlessly.
   - *Book Demo Slot* → Watch atomic calendar slot reservation, `.ics` invite generation, and CRM webhook dispatch (`Demo Scheduled`).
3. Click **End Call & Summarize** to inspect the structured executive summary, recommended plan, next actions, and AI-drafted follow-up email.
4. Explore **CRM & Calendar**, **Summaries & Insights**, and **Architecture & 100k Scale** (including the interactive Unit Economics calculator).

---

## Project Structure

```
autonomous-ai-sales-voice-agent/
├── app/
│   ├── agent/
│   │   ├── llm_provider.py      # Multi-LLM router (Anthropic/OpenAI/Gemini) + Deterministic RAG fallback
│   │   └── sales_agent.py       # Core orchestrator (memory, RAG, BANT, sentiment, booking, CRM, summary)
│   ├── api/routes.py            # Starlette REST + WebSocket (/ws/call/{session_id}) endpoints
│   ├── integrations/
│   │   ├── calendar_service.py  # Atomic slot reservation & RFC 5545 .ics invite generator
│   │   └── crm_service.py       # Lead upsert, stage progression & idempotent webhook log
│   ├── nlp/
│   │   ├── multilingual.py      # 5-language detector & localized greetings
│   │   ├── qualification.py     # Incremental BANT scorer & contact entity extractor
│   │   ├── security.py          # Real-time PII redaction (cards, SSNs, optional contact masking)
│   │   └── sentiment.py         # Polarity, emotion, buying-signal & objection detector
│   ├── rag/retriever.py         # Hybrid TF-IDF + tag boost + cross-lingual query expansion
│   ├── voice/adapters.py        # STT/TTS provider directives & latency helpers
│   ├── config.py                # Settings & language registry
│   ├── database.py              # Thread-safe SQLite repository
│   ├── main.py                  # Starlette ASGI app factory
│   └── models.py                # Pydantic schemas
├── data/knowledge_base.json     # Product, pricing, security, CRM, ROI & objection KB
├── static/                      # Executive single-page Voice Studio & BI UI
├── tests/                       # Unit & full E2E REST/WebSocket tests
├── ARCHITECTURE.md              # Architecture Mermaid diagrams, 100k-user scale, security & costs
└── run.py                       # Uvicorn server entrypoint
```

---

## Key API Endpoints

| Method & Path | Purpose |
|---|---|
| `GET /api/health` | Service health, active LLM engine, PII guardrail & KB stats |
| `POST /api/calls` | Start a new voice sales session + localized greeting + CRM lead |
| `WS /ws/call/{session_id}` | Real-time bidirectional voice transcript, barge-in & end-call stream |
| `POST /api/calls/{session_id}/message` | REST turn processing (RAG + BANT + sentiment + auto-booking) |
| `POST /api/calls/{session_id}/book` | Manual or explicit slot reservation |
| `POST /api/calls/{session_id}/summarize` | Generate executive call summary & follow-up email |
| `GET /api/calendar/appointments/{id}/ics` | Download RFC 5545 `.ics` calendar invite |
| `GET /api/crm` | View synced CRM leads & webhook payloads |
| `GET /api/insights` | Aggregate conversion, BANT, sentiment, language & objection KPIs |
| `POST /api/kb/documents` | Dynamically index a new KB document for live RAG retrieval |
