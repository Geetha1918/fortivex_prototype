(() => {
  const LANG_BCP47 = {
    en: "en-US",
    es: "es-ES",
    hi: "hi-IN",
    fr: "fr-FR",
    de: "de-DE",
  };

  const state = {
    sessionId: null,
    ws: null,
    wsConnected: false,
    recognition: null,
    isListening: false,
    isSpeaking: false,
    availableSlots: [],
  };

  // DOM helpers
  const $ = (id) => document.getElementById(id);

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ---- Navigation Tabs ----
  document.querySelectorAll(".nav-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-tab").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      const tabName = btn.dataset.tab;
      $(`tab-${tabName}`).classList.add("active");

      if (tabName === "crm") {
        loadCRM();
        loadCalendar();
      } else if (tabName === "insights") {
        loadInsights();
      }
    });
  });

  // ---- Health & Engine Status ----
  async function loadHealth() {
    try {
      const res = await fetch("/api/health");
      const data = await res.json();
      $("provider-badge").textContent = `Engine: ${data.llm_provider}`;
      $("pii-badge").textContent = data.pii_redaction_enabled
        ? "PII Guardrail: ON"
        : "PII Guardrail: OFF";
    } catch {
      $("provider-badge").textContent = "Engine: offline";
    }
  }

  // ---- Web Speech API TTS ----
  function speakText(text, langCode = "en") {
    if (!$("toggle-tts").checked || !("speechSynthesis" in window)) {
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    const bcp47 = LANG_BCP47[langCode] || "en-US";
    utterance.lang = bcp47;

    const voices = window.speechSynthesis.getVoices();
    const matched = voices.find((v) => v.lang.toLowerCase().startsWith(langCode));
    if (matched) utterance.voice = matched;
    utterance.rate = 1.03;

    utterance.onstart = () => {
      state.isSpeaking = true;
      $("waveform").classList.add("active");
      $("voice-state-label").textContent = `Speaking (${bcp47})...`;
    };
    utterance.onend = () => {
      state.isSpeaking = false;
      if (!state.isListening) {
        $("waveform").classList.remove("active");
        $("voice-state-label").textContent = "Listening / Ready";
      }
    };
    window.speechSynthesis.speak(utterance);
  }

  function stopSpeaking() {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    state.isSpeaking = false;
    if (!state.isListening) {
      $("waveform").classList.remove("active");
    }
  }

  // ---- Web Speech API STT ----
  function initSpeechRecognition() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      $("btn-mic").title = "Web Speech STT requires Chrome/Edge/Safari; use text input or quick scenarios.";
      return null;
    }
    const rec = new SpeechRec();
    rec.continuous = false;
    rec.interimResults = true;

    rec.onstart = () => {
      state.isListening = true;
      $("btn-mic").classList.add("listening");
      $("btn-mic").textContent = "Listening... (Click to Stop)";
      $("waveform").classList.add("active");
      $("voice-state-label").textContent = `Listening (${rec.lang})...`;
    };

    rec.onresult = (event) => {
      let finalTranscript = "";
      let interimTranscript = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const txt = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalTranscript += txt;
        else interimTranscript += txt;
      }
      if (interimTranscript) {
        $("message-input").value = interimTranscript;
      }
      if (finalTranscript.trim()) {
        $("message-input").value = "";
        sendProspectUtterance(finalTranscript.trim());
      }
    };

    rec.onerror = (err) => {
      state.isListening = false;
      $("btn-mic").classList.remove("listening");
      $("btn-mic").textContent = "Start Mic (STT)";
      $("waveform").classList.remove("active");
      $("voice-state-label").textContent = `Mic note: ${err.error} (text input always active)`;
    };

    rec.onend = () => {
      state.isListening = false;
      $("btn-mic").classList.remove("listening");
      $("btn-mic").textContent = "Start Mic (STT)";
      if (!state.isSpeaking) {
        $("waveform").classList.remove("active");
        $("voice-state-label").textContent = "Ready";
      }
    };

    return rec;
  }

  // ---- Start Call ----
  $("btn-start-call").addEventListener("click", async () => {
    stopSpeaking();
    const payload = {
      language: $("lang-select").value,
      prospect_name: $("prospect-name").value.trim() || null,
      company: $("prospect-company").value.trim() || null,
      prospect_email: $("prospect-email").value.trim() || null,
    };

    const res = await fetch("/api/calls", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    state.sessionId = data.session.session_id;
    state.availableSlots = data.available_slots || [];

    $("session-id-label").textContent = `Active Session: ${state.sessionId}`;
    $("transcript-feed").innerHTML = "";
    $("message-input").disabled = false;
    $("btn-send").disabled = false;
    $("btn-end-call").disabled = false;
    $("btn-mic").disabled = false;
    $("btn-barge-in").disabled = false;

    appendTurn(data.opening_turn);
    updateInspector(data.session, data.opening_turn, null);
    renderQuickSlots(state.availableSlots);
    connectWebSocket(state.sessionId);
    speakText(data.opening_turn.text, data.opening_turn.language);
  });

  function connectWebSocket(sessionId) {
    if (state.ws) {
      state.ws.close();
    }
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/call/${sessionId}`);

    ws.onopen = () => {
      state.wsConnected = true;
      $("ws-status").textContent = "WS: Connected";
      $("ws-status").className = "pill pill-ok";
    };

    ws.onclose = () => {
      state.wsConnected = false;
      $("ws-status").textContent = "WS: Disconnected";
      $("ws-status").className = "pill pill-muted";
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "agent_response") {
        appendTurn(msg.prospect_turn);
        appendTurn(msg.agent_turn);
        state.availableSlots = msg.available_slots || [];
        updateInspector(msg.session, msg.agent_turn, msg.appointment, msg.prospect_turn.sentiment);
        renderQuickSlots(state.availableSlots);
        speakText(msg.agent_turn.text, msg.agent_turn.language);
      } else if (msg.type === "summary_ready") {
        renderSummaryCard(msg.summary);
        document.querySelector('[data-tab="insights"]').click();
      }
    };

    state.ws = ws;
  }

  // ---- Send Prospect Utterance ----
  async function sendProspectUtterance(text) {
    if (!state.sessionId || !text.trim()) return;
    stopSpeaking();
    $("voice-state-label").textContent = "Thinking (NLP + RAG + Agent)...";

    const payload = {
      type: "transcript",
      text: text.trim(),
      prospect_name: $("prospect-name").value.trim() || null,
      company: $("prospect-company").value.trim() || null,
      prospect_email: $("prospect-email").value.trim() || null,
    };

    if (state.wsConnected && state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(payload));
      return;
    }

    // REST fallback if WS disconnected
    const res = await fetch(`/api/calls/${state.sessionId}/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    appendTurn(data.prospect_turn);
    appendTurn(data.agent_turn);
    state.availableSlots = data.available_slots || [];
    updateInspector(data.session, data.agent_turn, data.appointment, data.prospect_turn.sentiment);
    renderQuickSlots(state.availableSlots);
    speakText(data.agent_turn.text, data.agent_turn.language);
  }

  $("message-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const val = $("message-input").value.trim();
    if (!val) return;
    $("message-input").value = "";
    sendProspectUtterance(val);
  });

  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      if (!state.sessionId) {
        alert("Click 'Start New Voice Call' first!");
        return;
      }
      sendProspectUtterance(chip.dataset.text);
    });
  });

  $("btn-mic").addEventListener("click", () => {
    if (!state.recognition) {
      state.recognition = initSpeechRecognition();
    }
    if (!state.recognition) {
      alert("Browser SpeechRecognition API is unavailable in this browser. Use Chrome/Edge or type below.");
      return;
    }
    stopSpeaking();
    if (state.isListening) {
      state.recognition.stop();
    } else {
      state.recognition.lang = LANG_BCP47[$("lang-select").value] || "en-US";
      state.recognition.start();
    }
  });

  $("btn-barge-in").addEventListener("click", () => {
    stopSpeaking();
    if (state.wsConnected && state.ws) {
      state.ws.send(JSON.stringify({ type: "barge_in" }));
    }
    $("voice-state-label").textContent = "Interrupted — Listening";
  });

  $("btn-end-call").addEventListener("click", async () => {
    if (!state.sessionId) return;
    stopSpeaking();
    const res = await fetch(`/api/calls/${state.sessionId}/summarize`, { method: "POST" });
    const data = await res.json();
    renderSummaryCard(data.summary);
    $("session-id-label").textContent = `Completed Session: ${state.sessionId}`;
    document.querySelector('[data-tab="insights"]').click();
  });

  // ---- Transcript & Inspector UI Updates ----
  function appendTurn(turn) {
    const feed = $("transcript-feed");
    const el = document.createElement("div");
    el.className = `msg ${turn.speaker === "agent" ? "msg-agent" : "msg-prospect"}`;
    const who = turn.speaker === "agent" ? "Nova (AI Agent)" : "Prospect";
    const metaRight =
      turn.speaker === "agent" && turn.telemetry
        ? `${turn.language.toUpperCase()} • ${turn.telemetry.total_ms} ms`
        : `${turn.language.toUpperCase()}${turn.sentiment ? " • " + turn.sentiment.label : ""}`;

    el.innerHTML = `
      <div class="msg-meta"><strong>${who}</strong><span>${escapeHtml(metaRight)}</span></div>
      <div>${escapeHtml(turn.redacted_text || turn.text)}</div>
    `;
    feed.appendChild(el);
    feed.scrollTop = feed.scrollHeight;
  }

  function updateInspector(session, agentTurn, appointment, latestSentiment) {
    const bant = session.bant;
    const tierClass =
      bant.tier === "Hot" ? "pill-ok" : bant.tier === "Warm" ? "pill-warn" : "pill-muted";
    $("bant-tier-badge").className = `pill ${tierClass}`;
    $("bant-tier-badge").textContent = `${bant.tier} (${bant.total_score}/100)`;

    $("bant-budget-val").textContent = bant.budget || "Not detected";
    $("bar-budget").style.width = `${(bant.budget_score / 25) * 100}%`;

    $("bant-authority-val").textContent = bant.authority || "Not detected";
    $("bar-authority").style.width = `${(bant.authority_score / 25) * 100}%`;

    $("bant-need-val").textContent = bant.need || "Not detected";
    $("bar-need").style.width = `${(bant.need_score / 30) * 100}%`;

    $("bant-timeline-val").textContent = bant.timeline || "Not detected";
    $("bar-timeline").style.width = `${(bant.timeline_score / 20) * 100}%`;

    // Sentiment
    if (latestSentiment) {
      const sClass =
        latestSentiment.polarity >= 0.2
          ? "pill-ok"
          : latestSentiment.polarity < -0.1
          ? "pill-danger"
          : "pill-info";
      $("sentiment-badge").className = `pill ${sClass}`;
      $("sentiment-badge").textContent = `${latestSentiment.label} (${latestSentiment.polarity.toFixed(2)})`;
    }
    renderSparkline(session.sentiment_history || []);

    $("buying-signals-list").innerHTML = (session.buying_signals || []).length
      ? session.buying_signals.map((s) => `<span class="tag-chip">${escapeHtml(s)}</span>`).join("")
      : '<span class="muted small-label">None yet</span>';

    $("objections-list").innerHTML = (session.detected_objections || []).length
      ? session.detected_objections.map((o) => `<span class="tag-chip">${escapeHtml(o)}</span>`).join("")
      : '<span class="muted small-label">None yet</span>';

    // RAG Citations
    if (agentTurn && agentTurn.telemetry) {
      const t = agentTurn.telemetry;
      $("latency-badge").textContent = `RAG ${t.rag_ms}ms | NLP ${t.nlp_ms}ms | Gen ${t.llm_ms}ms`;
    }
    const sources = (agentTurn && agentTurn.rag_sources) || [];
    $("rag-sources-list").innerHTML = sources.length
      ? sources
          .map(
            (c) => `
          <div class="rag-item">
            <div class="rag-item-head">
              <span>${escapeHtml(c.title)} (${escapeHtml(c.category)})</span>
              <span>sim=${c.score}</span>
            </div>
            <div class="muted">${escapeHtml(c.excerpt)}</div>
          </div>`
          )
          .join("")
      : '<div class="muted small-label">Greeting turn — waiting for first prospect question.</div>';

    // Appointment
    if (appointment) {
      $("appt-status-badge").className = "pill pill-ok";
      $("appt-status-badge").textContent = "Confirmed";
      $("appointment-box").innerHTML = `
        <div class="sub-card">
          <strong>Demo Confirmed with ${escapeHtml(appointment.ae_name)}</strong><br/>
          <span class="muted">${escapeHtml(appointment.start_iso.slice(0, 16).replace("T", " "))} UTC</span><br/>
          <div style="margin-top:6px;display:flex;gap:8px;flex-wrap:wrap;">
            <a class="slot-btn" href="/api/calendar/appointments/${encodeURIComponent(appointment.appointment_id)}/ics">Download .ics Invite</a>
          </div>
        </div>
      `;
    }
  }

  function renderSparkline(values) {
    const box = $("sentiment-sparkline");
    if (!values.length) return;
    const w = 280;
    const h = 42;
    const midY = h / 2;
    const pts = values.map((v, idx) => {
      const x = values.length === 1 ? w / 2 : (idx / (values.length - 1)) * (w - 20) + 10;
      const y = midY - v * (h * 0.38);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    box.innerHTML = `
      <svg width="100%" height="${h}" viewBox="0 0 ${w} ${h}">
        <line x1="0" y1="${midY}" x2="${w}" y2="${midY}" stroke="#27345e" stroke-dasharray="3,3" />
        <polyline fill="none" stroke="#16c784" stroke-width="2.5" points="${pts.join(" ")}" />
        ${pts
          .map((p) => {
            const [cx, cy] = p.split(",");
            return `<circle cx="${cx}" cy="${cy}" r="3.5" fill="#5b8cff" />`;
          })
          .join("")}
      </svg>
    `;
  }

  function renderQuickSlots(slots) {
    const container = $("quick-slots-list");
    if (!container) return;
    if (!slots.length) {
      container.innerHTML = '<span class="muted small-label">No slots available</span>';
      return;
    }
    container.innerHTML = slots
      .slice(0, 4)
      .map(
        (s) =>
          `<button class="slot-btn" data-slot="${escapeHtml(s.slot_id)}">${escapeHtml(s.display_label)}</button>`
      )
      .join("");

    container.querySelectorAll(".slot-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!state.sessionId) return;
        const res = await fetch(`/api/calls/${state.sessionId}/book`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            slot_id: btn.dataset.slot,
            prospect_name: $("prospect-name").value.trim() || null,
            prospect_email: $("prospect-email").value.trim() || null,
            company: $("prospect-company").value.trim() || null,
          }),
        });
        const data = await res.json();
        if (res.ok && data.appointment) {
          const detailRes = await fetch(`/api/calls/${state.sessionId}`);
          const detail = await detailRes.json();
          updateInspector(detail.session, null, data.appointment, null);
        } else {
          alert(data.error || "Could not book slot");
        }
      });
    });
  }

  // ---- CRM & Calendar Tab ----
  async function loadCRM() {
    const res = await fetch("/api/crm");
    const data = await res.json();
    $("crm-leads-tbody").innerHTML = (data.leads || []).length
      ? data.leads
          .map(
            (l) => `
          <tr>
            <td>${escapeHtml(l.name || "Prospect")}</td>
            <td>${escapeHtml(l.company || "—")}</td>
            <td>${escapeHtml(l.language.toUpperCase())}</td>
            <td><strong>${l.bant_score}</strong>/100</td>
            <td><span class="pill ${l.tier === "Hot" ? "pill-ok" : l.tier === "Warm" ? "pill-warn" : "pill-muted"}">${escapeHtml(l.tier)}</span></td>
            <td>${escapeHtml(l.stage)}</td>
            <td>$${Number(l.estimated_acv).toLocaleString()}</td>
          </tr>`
          )
          .join("")
      : '<tr><td colspan="7" class="muted">No CRM leads yet. Start a call in Voice Studio!</td></tr>';

    $("webhook-logs-list").innerHTML = (data.webhooks || []).length
      ? data.webhooks
          .slice(0, 6)
          .map(
            (w) => `
          <div class="sub-card">
            <div style="display:flex;justify-content:space-between;">
              <strong>${escapeHtml(w.event_type)}</strong>
              <span class="pill pill-ok">${escapeHtml(w.status)} • idem:${escapeHtml(w.idempotency_key)}</span>
            </div>
            <pre class="json-pre">${escapeHtml(JSON.stringify(w.payload, null, 2))}</pre>
          </div>`
          )
          .join("")
      : '<div class="muted">No webhook events logged yet.</div>';
  }

  async function loadCalendar() {
    const res = await fetch("/api/calendar");
    const data = await res.json();
    $("booked-appts-list").innerHTML = (data.appointments || []).length
      ? data.appointments
          .map(
            (a) => `
          <div class="sub-card">
            <strong>${escapeHtml(a.prospect_name)} (${escapeHtml(a.company)})</strong> — ${escapeHtml(a.ae_name)}<br/>
            <span class="muted">${escapeHtml(a.start_iso.slice(0, 16).replace("T", " "))} UTC</span>
            <div style="margin-top:6px;">
              <a class="slot-btn" href="/api/calendar/appointments/${encodeURIComponent(a.appointment_id)}/ics">Download .ics</a>
            </div>
          </div>`
          )
          .join("")
      : '<div class="muted">No booked demos yet.</div>';

    $("all-slots-list").innerHTML = (data.slots || [])
      .map(
        (s) => `
      <div class="sub-card">
        <div><strong>${escapeHtml(s.ae_name)}</strong></div>
        <div class="muted small-label">${escapeHtml(s.display_label)}</div>
        <div style="margin-top:6px;">
          <span class="pill ${s.is_booked ? "pill-warn" : "pill-ok"}">${s.is_booked ? "Booked" : "Available"}</span>
        </div>
      </div>`
      )
      .join("");
  }

  $("btn-refresh-crm").addEventListener("click", loadCRM);
  $("btn-refresh-cal").addEventListener("click", loadCalendar);

  // ---- Insights & Summary Tab ----
  async function loadInsights() {
    const res = await fetch("/api/insights");
    const data = await res.json();
    const k = data.kpis;
    $("insights-kpis").innerHTML = `
      <div class="kpi-card"><div class="muted small-label">Total Calls</div><div class="kpi-value">${k.total_calls}</div></div>
      <div class="kpi-card"><div class="muted small-label">Booked Demos</div><div class="kpi-value">${k.booked_demos}</div></div>
      <div class="kpi-card"><div class="muted small-label">Conversion Rate</div><div class="kpi-value">${k.conversion_rate_pct}%</div></div>
      <div class="kpi-card"><div class="muted small-label">Avg BANT Score</div><div class="kpi-value">${k.avg_bant_score}/100</div></div>
      <div class="kpi-card"><div class="muted small-label">Avg Sentiment</div><div class="kpi-value">${k.avg_sentiment_polarity}</div></div>
      <div class="kpi-card"><div class="muted small-label">Pipeline Est. ACV</div><div class="kpi-value">$${Number(k.total_pipeline_acv_usd).toLocaleString()}</div></div>
    `;

    const d = data.distributions;
    const renderKV = (title, obj) => {
      const entries = Object.entries(obj || {});
      return `
        <div class="sub-card">
          <strong>${title}</strong>
          <div style="margin-top:6px;">
            ${
              entries.length
                ? entries.map(([key, val]) => `<div>${escapeHtml(key)}: <strong>${val}</strong></div>`).join("")
                : '<span class="muted small-label">No data yet</span>'
            }
          </div>
        </div>
      `;
    };
    $("insights-distributions").innerHTML =
      renderKV("Lead Tiers", d.tiers) +
      renderKV("CRM Pipeline Stages", d.stages) +
      renderKV("Languages Detected", d.languages) +
      renderKV("Top Objections", d.top_objections);

    if (data.summaries && data.summaries.length) {
      renderSummaryCard(data.summaries[0]);
    }
  }

  function renderSummaryCard(summary) {
    $("latest-summary-box").innerHTML = `
      <div class="sub-card">
        <strong>${escapeHtml(summary.headline)}</strong>
        <p style="margin:8px 0;line-height:1.45;">${escapeHtml(summary.executive_summary)}</p>
        <div class="small-label muted">Sentiment: ${escapeHtml(summary.overall_sentiment)} (${summary.avg_polarity}) • Recommended: ${escapeHtml(summary.recommended_plan)}</div>
        <h4 style="margin:12px 0 6px;">Next Best Actions</h4>
        <ul class="bullet-list" style="margin:0;">
          ${summary.next_actions.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}
        </ul>
        <h4 style="margin:12px 0 6px;">AI-Drafted Follow-Up Email</h4>
        <pre class="json-pre">Subject: ${escapeHtml(summary.follow_up_email_subject)}\n\n${escapeHtml(summary.follow_up_email_body)}</pre>
      </div>
    `;
  }

  // ---- Unit Economics Calculator ----
  function updateCalculator() {
    const calls = Number($("calc-calls").value);
    const mins = Number($("calc-mins").value);
    const ratePerMin = Number($("calc-tier").value);

    $("calc-calls-val").textContent = calls.toLocaleString();
    $("calc-mins-val").textContent = mins;

    const totalMinutes = calls * mins;
    const aiVoiceCost = totalMinutes * ratePerMin;
    const infraFixed = Math.ceil(calls / 10000) * 350; // Kubernetes/Redis/Postgres scaling pods
    const totalMonthlyCost = aiVoiceCost + infraFixed;
    const costPerCall = totalMonthlyCost / calls;
    const humanSdrEquivalent = Math.ceil(calls / 400) * 6500;
    const monthlySavings = Math.max(0, humanSdrEquivalent - totalMonthlyCost);

    $("calc-output").innerHTML = `
      <div class="sub-card"><div class="muted small-label">Total Monthly Minutes</div><strong>${totalMinutes.toLocaleString()} mins</strong></div>
      <div class="sub-card"><div class="muted small-label">AI + Infra Monthly Cost</div><strong>$${Math.round(totalMonthlyCost).toLocaleString()} ($${costPerCall.toFixed(2)}/call)</strong></div>
      <div class="sub-card"><div class="muted small-label">Human SDR Equivalent</div><strong>$${humanSdrEquivalent.toLocaleString()}/mo</strong></div>
      <div class="sub-card"><div class="muted small-label">Estimated Net Savings</div><strong style="color:#16c784;">$${Math.round(monthlySavings).toLocaleString()}/mo</strong></div>
    `;
  }

  ["calc-calls", "calc-mins", "calc-tier"].forEach((id) => {
    $(id).addEventListener("input", updateCalculator);
  });

  // Init
  loadHealth();
  updateCalculator();
})();
