# Fortivex AI Round 3 — Autonomous AI Sales Voice Agent

## Business problem and end-to-end workflow

Sales teams spend time repeating product answers, qualifying prospects, writing call notes, and arranging follow-ups. This prototype demonstrates one workflow that can reduce that work while leaving the salesperson in control.

The salesperson records a call turn or pastes a transcript. Speech recognition transcribes recorded audio; optional translation supports seven demo languages. The app keeps recent turns in session memory, finds a relevant Fortivex note with TF-IDF, and—when an OpenAI API key is supplied—uses an LLM to write a natural answer grounded in that note. Explainable rules identify buying signals, sentiment, and a starter lead score. The app summarizes the call, saves a lead record and appointment to local CSV files, and shows aggregate call insights. The source is `app.py`; setup and the system diagram are in `README.md`.

## Technical implementation

Python and Streamlit keep the prototype easy to explain and modify. Scikit-learn TF-IDF with cosine similarity provides a simple retrieval baseline. The OpenAI Responses API generates the answer from the transcript, recent context, and retrieved product note; the prompt tells it not to invent Fortivex features or prices. If there is no API key, the app returns the retrieved note instead. Sentiment and lead qualification use transparent keyword rules, not a trained predictive model. Speech and translation are replaceable service adapters. Voice is record-and-submit, not continuous phone streaming; CSV files are demo CRM/calendar connectors, not production integrations.

## Commercial feasibility

A pilot could reduce time spent on notes and missed follow-ups. Evaluate answer accuracy, staff correction rate, minutes saved per call, appointment conversion, and cost per qualified lead using consented, labeled calls. Human review should remain in place until quality is demonstrated. Product notes must be approved and kept current. API usage for language, transcription, translation, and speech may incur charges.

## Scale, security, deployment, and operating cost

To support 100,000 registered users, deploy stateless web/API workers behind a load balancer and autoscale them based on measured request load. Put audio and model work on a queue, then scale speech/LLM workers independently. Store customer records in a tenant-aware managed database, transcripts in encrypted object storage, short-lived conversation state in a managed cache, and product notes in a vector/search service. Connect CRM and calendar through isolated adapters. Validate concurrency and latency with load tests; 100,000 registered users does not imply 100,000 simultaneous calls.

Package with containers and deploy through CI/CD to a managed cloud platform. Use separate development/staging/production environments, health checks, monitored rollouts, backups, and rollback. Protect data with TLS, encryption at rest and managed keys, secrets management, authentication, role-based access, tenant isolation, consent, audit logs, rate limits, retention/deletion controls, and human escalation. The local prototype has none of these production protections and must not receive confidential customer data.

Monthly operating cost is driven by: **app/worker compute + database and object storage + network/monitoring + call minutes × speech/translation rates + model input/output tokens × model rates + CRM/calendar licenses**. Measure these variables in a capped pilot, track cost per call and per qualified lead, set tenant budgets and alerts, and use smaller models, caching, and audio retention limits where quality permits. Exact estimates require expected call minutes, concurrency, token volume, and selected vendor prices.

## Interview summary

“I built an explainable Python prototype that completes a sales-call workflow. TF-IDF retrieves product facts, an optional LLM writes a grounded response, and simple rules score lead signals. I used local adapters to make the demo easy to run, then mapped them to scalable and protected services for production. Before launch, I would validate quality, concurrency, security, and cost in a consented pilot.”
