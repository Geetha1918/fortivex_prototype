"""Multilingual language detection and localized voice-agent templates."""

from __future__ import annotations

import re
from typing import Dict, Set

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

_LANG_MARKERS: Dict[str, Set[str]] = {
    "es": {
        "hola", "buenos", "gracias", "precio", "precios", "somos", "necesitamos",
        "equipo", "ventas", "empresa", "presupuesto", "reunion", "reunión", "demo",
        "quiero", "queremos", "como", "cómo", "para", "con", "nuestro", "seguridad",
        "caro", "mensual", "semana", "mes", "agenda", "agendar",
    },
    "hi": {
        "namaste", "नमस्ते", "हमें", "हम", "कीमत", "दाम", "बजट", "डेमो", "सुरक्षा",
        "टीम", "कंपनी", "चाहिए", "बात", "करना", "क्या", "है", "कैसे", "महंगा",
        "मीटिंग", "बुक", "जी", "हाँ", "नहीं", "सेल्स", "kimat", "chahiye", "hum",
    },
    "fr": {
        "bonjour", "merci", "prix", "tarif", "nous", "sommes", "équipe", "equipe",
        "ventes", "entreprise", "budget", "sécurité", "securite", "besoin",
        "démo", "demo", "semaine", "mois", "avec", "pour", "votre", "cher",
    },
    "de": {
        "hallo", "guten", "danke", "preis", "preise", "wir", "brauchen", "team",
        "vertrieb", "unternehmen", "sicherheit", "kosten", "woche", "monat",
        "termin", "können", "unsere", "teuer", "für", "mit", "ja", "nein",
    },
}


def detect_language(text: str, default: str = "en") -> str:
    """Detect language among en, es, hi, fr, de using script and lexical markers."""
    if not text or not text.strip():
        return default

    if _DEVANAGARI_RE.search(text):
        return "hi"

    tokens = set(re.findall(r"[\w\u0900-\u097F]+", text.lower()))
    best_lang = default
    best_hits = 0
    for lang, markers in _LANG_MARKERS.items():
        hits = len(tokens.intersection(markers))
        if hits > best_hits:
            best_hits = hits
            best_lang = lang

    # Require at least 1 strong marker to switch away from default, or 2 if short overlap
    if best_hits >= 1 and best_lang != default:
        return best_lang
    return default


GREETINGS: Dict[str, str] = {
    "en": (
        "Hi{name_part}! I'm Nova, your AI Solutions Specialist at NovaFlow AI. "
        "We help B2B revenue teams respond to leads in seconds, qualify prospects automatically, "
        "and book meetings directly into your CRM. What prompted you to explore sales automation today?"
    ),
    "es": (
        "¡Hola{name_part}! Soy Nova, especialista de soluciones en NovaFlow AI. "
        "Ayudamos a equipos B2B a responder leads en segundos, calificar oportunidades y agendar "
        "reuniones directamente en su CRM. ¿Qué los motivó a explorar la automatización hoy?"
    ),
    "hi": (
        "नमस्ते{name_part}! मैं नोवा हूँ, NovaFlow AI की AI सॉल्यूशंस स्पेशलिस्ट। "
        "हम B2B सेल्स टीमों को सेकंडों में लीड्स का जवाब देने, क्वालिफाई करने और सीधे CRM में मीटिंग बुक करने में मदद करते हैं। "
        "आज आप सेल्स ऑटोमेशन के बारे में क्या जानना चाहेंगे?"
    ),
    "fr": (
        "Bonjour{name_part} ! Je suis Nova, spécialiste solutions chez NovaFlow AI. "
        "Nous aidons les équipes commerciales B2B à répondre aux prospects en quelques secondes "
        "et à planifier des démos automatiquement dans votre CRM. Qu'est-ce qui vous amène aujourd'hui ?"
    ),
    "de": (
        "Hallo{name_part}! Ich bin Nova, AI Solutions Specialist bei NovaFlow AI. "
        "Wir helfen B2B-Vertriebsteams, Leads in Sekunden zu qualifizieren und Termine direkt im CRM zu buchen. "
        "Was hat Sie heute dazu bewegt, sich mit Vertriebsautomatisierung zu beschäftigen?"
    ),
}


def get_greeting(language: str, prospect_name: str | None = None) -> str:
    """Return a natural localized opening greeting."""
    lang = language if language in GREETINGS else "en"
    name_part = f" {prospect_name}" if prospect_name else ""
    return GREETINGS[lang].format(name_part=name_part)
