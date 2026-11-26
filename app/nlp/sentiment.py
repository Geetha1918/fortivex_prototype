"""Real-time sentiment analysis, buying-signal detection, and objection classifier."""

from __future__ import annotations

import re
from typing import Dict, List

from app.models import SentimentAnalysis

_POSITIVE_WORDS = {
    "great", "awesome", "love", "impressed", "perfect", "excellent", "interested",
    "yes", "definitely", "sounds good", "helpful", "fast", "excited", "ready",
    "genial", "excelente", "perfecto", "interesado", "sí", "अच्छा", "बढ़िया", "हाँ",
    "parfait", "super", "intéressé", "gut", "perfekt", "toll",
}

_NEGATIVE_WORDS = {
    "expensive", "costly", "slow", "worried", "concern", "concerned", "hard",
    "difficult", "hate", "annoying", "problem", "issue", "not sure", "skeptical",
    "caro", "preocupado", "problema", "महंगा", "समस्या", "cher", "problème", "teuer",
}

_FRUSTRATED_WORDS = {
    "waste", "terrible", "useless", "stop", "annoyed", "frustrated", "ridiculous",
    "never", "no way",
}

_BUYING_SIGNAL_PATTERNS: Dict[str, List[str]] = {
    "Requested Pricing / Plans": ["price", "pricing", "cost", "plan", "tier", "quote", "precio", "कीमत", "prix", "preis"],
    "Requested Demo / Meeting": ["demo", "schedule", "book", "calendar", "call", "meeting", "slot", "agendar", "reunión", "डेमो", "मीटिंग", "termin"],
    "Timeline Urgency": ["this week", "this month", "asap", "immediately", "q1", "q2", "q3", "q4", "soon", "today"],
    "Integration Evaluation": ["salesforce", "hubspot", "pipedrive", "crm", "api", "webhook", "integrate", "integration"],
    "Security Due Diligence": ["soc2", "soc 2", "gdpr", "hipaa", "security", "compliance", "encrypt", "pii"],
}

_OBJECTION_PATTERNS: Dict[str, List[str]] = {
    "Pricing / Budget": ["expensive", "too much", "costly", "budget", "cheaper", "discount", "caro", "महंगा", "cher", "teuer"],
    "Incumbent Stack / Already Have SDRs": ["already have", "already use", "current team", "replace", "chatbot", "in-house"],
    "Security / AI Trust": ["hallucination", "hallucinate", "data leak", "privacy", "secure", "trust ai", "accurate"],
    "Implementation Bandwidth": ["no time", "too busy", "long to implement", "complex setup", "bandwidth", "hard to deploy"],
}


def analyze_sentiment(text: str) -> SentimentAnalysis:
    """Analyze utterance sentiment polarity, emotion label, buying signals, and objections."""
    lower = text.lower()
    tokens = set(re.findall(r"[\w\u0900-\u097F]+", lower))

    pos_hits = sum(1 for w in _POSITIVE_WORDS if w in lower or w in tokens)
    neg_hits = sum(1 for w in _NEGATIVE_WORDS if w in lower or w in tokens)
    frust_hits = sum(1 for w in _FRUSTRATED_WORDS if w in lower or w in tokens)

    buying_signals: List[str] = []
    for label, keywords in _BUYING_SIGNAL_PATTERNS.items():
        if any(k in lower for k in keywords):
            buying_signals.append(label)

    objections: List[str] = []
    for label, keywords in _OBJECTION_PATTERNS.items():
        if any(k in lower for k in keywords):
            objections.append(label)

    # Calculate bounded polarity [-1.0, +1.0]
    raw_score = (pos_hits * 0.25 + len(buying_signals) * 0.15) - (
        neg_hits * 0.25 + frust_hits * 0.45 + len(objections) * 0.12
    )
    polarity = max(-1.0, min(1.0, round(raw_score, 2)))

    if frust_hits > 0 or (polarity <= -0.85 and not objections):
        label = "Frustrated"
    elif len(objections) > 0 and polarity < 0.2:
        label = "Skeptical"
    elif polarity >= 0.45:
        label = "Enthusiastic"
    elif polarity >= 0.12:
        label = "Positive"
    else:
        label = "Neutral"

    return SentimentAnalysis(
        polarity=polarity,
        label=label,  # type: ignore[arg-type]
        buying_signals=buying_signals,
        objections=objections,
    )
