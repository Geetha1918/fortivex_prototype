"""Multi-provider LLM generator with RAG-grounded deterministic multilingual fallback."""

from __future__ import annotations

import logging
from typing import List, Optional

import httpx

from app.config import SUPPORTED_LANGUAGES, settings
from app.models import (
    Appointment,
    BANTCriteria,
    CalendarSlot,
    ConversationTurn,
    RetrievedChunk,
    SentimentAnalysis,
)

logger = logging.getLogger(__name__)

_LOCALIZED_BOOKING_CONFIRM: dict[str, str] = {
    "en": "I've confirmed your 30-minute discovery & live demo with {ae} for {slot_label}. Your calendar invite and meeting link ({link}) are ready!",
    "es": "¡Perfecto! He confirmado tu demo de 30 minutos con {ae} para {slot_label}. Tu invitación de calendario y enlace ({link}) ya están listos.",
    "hi": "बहुत बढ़िया! मैंने {ae} के साथ {slot_label} पर आपका 30-मिनट का लाइव डेमो कन्फर्म कर दिया है। कैलेंडर इनवाइट और मीटिंग लिंक ({link}) तैयार है!",
    "fr": "C'est confirmé ! Votre démo de 30 minutes avec {ae} est réservée pour {slot_label}. Votre invitation et lien ({link}) sont prêts.",
    "de": "Bestätigt! Ihre 30-minütige Live-Demo mit {ae} ist für {slot_label} gebucht. Die Kalendereinladung und der Link ({link}) sind bereit.",
}

_LOCALIZED_OFFER_DEMO: dict[str, str] = {
    "en": "Would you like me to lock in a 30-minute live demo? Our next open slot is {slot_label}.",
    "es": "¿Te gustaría que reservemos una demo en vivo de 30 minutos? Nuestro próximo horario disponible es {slot_label}.",
    "hi": "क्या मैं आपके लिए 30-मिनट का लाइव डेमो बुक कर दूँ? अगला उपलब्ध स्लॉट {slot_label} है।",
    "fr": "Souhaitez-vous que je réserve une démo en direct de 30 minutes ? Le prochain créneau libre est {slot_label}.",
    "de": "Soll ich eine 30-minütige Live-Demo für Sie reservieren? Der nächste freie Termin ist {slot_label}.",
}

_LOCALIZED_BANT_NUDGES: dict[str, dict[str, str]] = {
    "en": {
        "need": "What is the biggest bottleneck in your current sales or lead-response workflow?",
        "authority": "Are you leading the evaluation for your team, or will other stakeholders join?",
        "timeline": "When are you hoping to roll out a solution like this?",
        "budget": "Do you have a monthly budget range in mind (our plans start at $499/mo)?",
    },
    "es": {
        "need": "¿Cuál es el principal cuello de botella actual en su proceso de ventas?",
        "authority": "¿Lideras tú la evaluación o participará alguien más del equipo directivo?",
        "timeline": "¿Para cuándo les gustaría implementar una solución así?",
        "budget": "¿Tienen un rango de presupuesto mensual estimado (nuestros planes inician en $499/mes)?",
    },
    "hi": {
        "need": "आपकी वर्तमान सेल्स या लीड-रिस्पॉन्स प्रक्रिया में सबसे बड़ी चुनौती क्या है?",
        "authority": "क्या आप इस निर्णय का नेतृत्व कर रहे हैं या टीम के अन्य लोग भी शामिल होंगे?",
        "timeline": "आप इसे कब तक लागू करने की योजना बना रहे हैं?",
        "budget": "क्या आपके पास मासिक बजट की कोई सीमा तय है (हमारे प्लान $499/माह से शुरू होते हैं)?",
    },
    "fr": {
        "need": "Quel est le principal frein dans votre processus commercial actuel ?",
        "authority": "Pilotez-vous ce projet ou d'autres décideurs sont-ils impliqués ?",
        "timeline": "Dans quel délai souhaitez-vous déployer une telle solution ?",
        "budget": "Avez-vous une enveloppe budgétaire mensuelle en tête (à partir de 499 $/mois) ?",
    },
    "de": {
        "need": "Was ist aktuell der größte Engpass in Ihrem Vertriebsprozess?",
        "authority": "Leiten Sie die Evaluierung selbst oder sind weitere Entscheider beteiligt?",
        "timeline": "Bis wann möchten Sie eine Lösung einführen?",
        "budget": "Welches monatliche Budget planen Sie ein (unsere Tarife starten bei 499 $/Monat)?",
    },
}

_LOCALIZED_CATEGORY_INTROS: dict[str, dict[str, str]] = {
    "es": {
        "Pricing": "Sobre precios: ofrecemos Starter ($499/mes), Growth ($1,499/mes, 6,000 minutos con Salesforce/HubSpot) y Enterprise ($3,500+/mes), con 20% de descuento anual.",
        "Security": "En seguridad: contamos con certificación SOC 2 Type II, cumplimiento GDPR, cifrado AES-256/TLS 1.3, enmascaramiento de PII en tiempo real y RAG estricto para evitar alucinaciones.",
        "Integrations": "Respecto a integraciones: nos conectamos en 15 minutos con Salesforce, HubSpot, Pipedrive, Google Calendar y Outlook vía OAuth 2.0 y webhooks firmados.",
        "ROI": "Nuestros clientes B2B logran un ROI promedio de 4.2x en 90 días y reducen el tiempo de respuesta de horas a menos de 12 segundos.",
        "Objections": "Entiendo la preocupación por el costo; comparado con un SDR ($6,500+/mes), nuestro plan Growth cuesta ~$1.25 por llamada calificada 24/7 y ofrecemos piloto de 14 días.",
    },
    "hi": {
        "Pricing": "कीमत के बारे में: हमारा Starter प्लान $499/माह, Growth प्लान $1,499/माह (6,000 मिनट और Salesforce/HubSpot सिंक), और Enterprise $3,500+/माह से शुरू होता है। वार्षिक बिलिंग पर 20% छूट है।",
        "Security": "सुरक्षा के लिए: NovaFlow AI SOC 2 Type II प्रमाणित और GDPR अनुपालन वाला है। इसमें AES-256 एन्क्रिप्शन, रीयल-टाइम PII मास्किंग और RAG ग्राउंडिंग है ताकि गलत जानकारी न दी जाए।",
        "Integrations": "इंटीग्रेशन: हम Salesforce, HubSpot, Pipedrive, Google Calendar और Outlook से 15 मिनट में OAuth 2.0 के ज़रिए जुड़ जाते हैं।",
        "ROI": "हमारे B2B ग्राहकों को 90 दिनों में औसतन 4.2x ROI मिला है और लीड रिस्पॉन्स समय घंटों से घटकर 12 सेकंड रह गया है।",
        "Objections": "बजट की चिंता स्वाभाविक है; एक SDR ($6,500+/माह) की तुलना में Growth प्लान ~$1.25 प्रति कॉल पड़ता है और 14-दिन का पायलट भी उपलब्ध है।",
    },
    "fr": {
        "Pricing": "Côté tarifs : Starter à 499 $/mois, Growth à 1 499 $/mois (6 000 min + Salesforce/HubSpot) et Enterprise dès 3 500 $/mois, avec -20 % en annuel.",
        "Security": "Sécurité : certifié SOC 2 Type II, conforme RGPD, chiffrement AES-256/TLS 1.3, masquage PII en temps réel et réponses ancrées par RAG.",
        "Integrations": "Intégrations : connexion native en 15 minutes à Salesforce, HubSpot, Google Calendar et Outlook via OAuth 2.0.",
        "ROI": "Nos clients obtiennent en moyenne un ROI de 4,2x en 90 jours avec +38 % de démos qualifiées.",
        "Objections": "Par rapport au coût d'un SDR, le plan Growth revient à ~1,25 $ par appel qualifié 24/7, avec un pilote possible de 14 jours.",
    },
    "de": {
        "Pricing": "Zu den Preisen: Starter 499 $/Monat, Growth 1.499 $/Monat (6.000 Min. inkl. Salesforce/HubSpot) und Enterprise ab 3.500 $/Monat (20 % Jahresrabatt).",
        "Security": "Sicherheit: SOC 2 Type II zertifiziert, DSGVO-konform, AES-256/TLS 1.3 Verschlüsselung, Echtzeit-PII-Redaktion und RAG-Grounding.",
        "Integrations": "Integrationen: Native Anbindung an Salesforce, HubSpot, Google Calendar und Outlook in unter 15 Minuten.",
        "ROI": "Unsere B2B-Kunden erzielen im Schnitt 4,2x ROI in 90 Tagen und verkürzen die Reaktionszeit auf unter 12 Sekunden.",
        "Objections": "Im Vergleich zu einem SDR (~6.500 $/Monat) kostet ein qualifiziertes Gespräch im Growth-Tarif nur ca. 1,25 $ rund um die Uhr.",
    },
}


class SalesLLMProvider:
    """Generates natural, grounded responses via configured LLM or deterministic RAG engine."""

    def generate_reply(
        self,
        user_text: str,
        language: str,
        bant: BANTCriteria,
        sentiment: SentimentAnalysis,
        rag_chunks: List[RetrievedChunk],
        history: List[ConversationTurn],
        available_slots: List[CalendarSlot],
        booked_appointment: Optional[Appointment] = None,
    ) -> tuple[str, str]:
        """Return (reply_text, provider_name)."""
        if settings.active_llm_provider != "deterministic-rag":
            try:
                reply = self._call_external_llm(
                    user_text=user_text,
                    language=language,
                    bant=bant,
                    sentiment=sentiment,
                    rag_chunks=rag_chunks,
                    history=history,
                    available_slots=available_slots,
                    booked_appointment=booked_appointment,
                )
                if reply:
                    return reply, settings.active_llm_provider
            except Exception as exc:  # pragma: no cover - graceful degradation
                logger.warning("External LLM failed, falling back to deterministic RAG: %s", exc)

        return (
            self._deterministic_rag_reply(
                user_text=user_text,
                language=language,
                bant=bant,
                sentiment=sentiment,
                rag_chunks=rag_chunks,
                available_slots=available_slots,
                booked_appointment=booked_appointment,
            ),
            "deterministic-rag",
        )

    def _build_system_prompt(
        self,
        language: str,
        bant: BANTCriteria,
        sentiment: SentimentAnalysis,
        rag_chunks: List[RetrievedChunk],
        available_slots: List[CalendarSlot],
        booked_appointment: Optional[Appointment],
    ) -> str:
        lang_name = SUPPORTED_LANGUAGES.get(language, {}).get("name", "English")
        kb_context = "\n".join(
            f"[{c.doc_id} | {c.title} | score={c.score}]: {c.excerpt}" for c in rag_chunks
        )
        slots_text = ", ".join(s.display_label for s in available_slots[:3]) or "No open slots"
        appt_note = (
            f"CONFIRMED APPOINTMENT: {booked_appointment.ae_name} at {booked_appointment.start_iso} ({booked_appointment.meeting_link})"
            if booked_appointment
            else "No appointment booked yet."
        )
        return (
            f"You are Nova, an elite Autonomous B2B AI Sales Voice Agent for NovaFlow AI.\n"
            f"Respond concisely (2-4 spoken sentences max, optimized for voice TTS) in {lang_name}.\n"
            f"Current BANT score: {bant.total_score}/100 ({bant.tier}). Missing BANT fields: {bant.missing_fields}.\n"
            f"Prospect Sentiment: {sentiment.label} (polarity={sentiment.polarity}). Objections: {sentiment.objections}.\n"
            f"{appt_note}\n"
            f"Next open demo slots: {slots_text}\n"
            f"Grounded Knowledge Base Context (ONLY cite facts from here):\n{kb_context}\n"
            f"Instructions: Address the prospect's question or objection warmly using RAG facts, "
            f"and naturally advance toward BANT qualification or booking a 30-min demo."
        )

    def _call_external_llm(
        self,
        user_text: str,
        language: str,
        bant: BANTCriteria,
        sentiment: SentimentAnalysis,
        rag_chunks: List[RetrievedChunk],
        history: List[ConversationTurn],
        available_slots: List[CalendarSlot],
        booked_appointment: Optional[Appointment],
    ) -> str:
        system_prompt = self._build_system_prompt(
            language, bant, sentiment, rag_chunks, available_slots, booked_appointment
        )
        messages = [
            {
                "role": "user" if t.speaker == "prospect" else "assistant",
                "content": t.text,
            }
            for t in history[-8:]
            if t.speaker in {"prospect", "agent"}
        ]
        messages.append({"role": "user", "content": user_text})

        if settings.active_llm_provider == "anthropic":
            import anthropic

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            resp = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=260,
                system=system_prompt,
                messages=messages,  # type: ignore[arg-type]
            )
            return resp.content[0].text.strip()

        if settings.active_llm_provider == "openai":
            resp = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "messages": [{"role": "system", "content": system_prompt}, *messages],
                    "max_tokens": 260,
                    "temperature": 0.4,
                },
                timeout=12.0,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()

        if settings.active_llm_provider == "gemini":
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
            )
            transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            resp = httpx.post(
                url,
                json={
                    "contents": [
                        {
                            "parts": [
                                {"text": f"{system_prompt}\n\nConversation:\n{transcript}"}
                            ]
                        }
                    ]
                },
                timeout=12.0,
            )
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

        return ""

    def _deterministic_rag_reply(
        self,
        user_text: str,
        language: str,
        bant: BANTCriteria,
        sentiment: SentimentAnalysis,
        rag_chunks: List[RetrievedChunk],
        available_slots: List[CalendarSlot],
        booked_appointment: Optional[Appointment],
    ) -> str:
        lang = language if language in SUPPORTED_LANGUAGES else "en"
        parts: List[str] = []

        # 1. If a booking was just completed, lead with confirmation
        if booked_appointment:
            slot_label = booked_appointment.start_iso[:16].replace("T", " ") + " UTC"
            confirm_tpl = _LOCALIZED_BOOKING_CONFIRM.get(lang, _LOCALIZED_BOOKING_CONFIRM["en"])
            parts.append(
                confirm_tpl.format(
                    ae=booked_appointment.ae_name,
                    slot_label=slot_label,
                    link=booked_appointment.meeting_link,
                )
            )
            return " ".join(parts)

        # 2. Empathy prefix for skeptical/frustrated prospects
        if sentiment.label in {"Skeptical", "Frustrated"}:
            empathy = {
                "en": "That's a completely fair concern.",
                "es": "Es una preocupación totalmente válida.",
                "hi": "आपकी यह चिंता बिल्कुल जायज़ है।",
                "fr": "C'est une préoccupation tout à fait légitime.",
                "de": "Das ist ein völlig berechtigter Punkt.",
            }
            parts.append(empathy.get(lang, empathy["en"]))

        # 3. Grounded answer from top RAG chunk
        if rag_chunks:
            top = rag_chunks[0]
            if lang == "en":
                # Keep spoken output crisp by taking first 2 sentences of the excerpt
                sentences = [s.strip() for s in top.excerpt.split(". ") if s.strip()]
                spoken_fact = ". ".join(sentences[:2])
                if not spoken_fact.endswith("."):
                    spoken_fact += "."
                parts.append(spoken_fact)
            else:
                localized_cat = _LOCALIZED_CATEGORY_INTROS.get(lang, {}).get(top.category)
                if localized_cat:
                    parts.append(localized_cat)
                else:
                    parts.append(_LOCALIZED_CATEGORY_INTROS[lang]["ROI"])

        # 4. Next conversational step: either offer demo (if Hot/Warm or buying signals) or ask next missing BANT
        if (bant.total_score >= 55 or "Requested Demo / Meeting" in sentiment.buying_signals) and available_slots:
            offer_tpl = _LOCALIZED_OFFER_DEMO.get(lang, _LOCALIZED_OFFER_DEMO["en"])
            parts.append(offer_tpl.format(slot_label=available_slots[0].display_label))
        elif bant.missing_fields:
            next_field = bant.missing_fields[0]
            nudge = _LOCALIZED_BANT_NUDGES.get(lang, _LOCALIZED_BANT_NUDGES["en"]).get(next_field)
            if nudge:
                parts.append(nudge)

        return " ".join(parts)
