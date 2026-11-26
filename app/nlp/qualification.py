"""Incremental BANT lead qualification and entity extraction engine."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from app.models import BANTCriteria

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_NAME_PATTERNS = [
    re.compile(r"(?i:\b(?:i am|i'm|my name is|this is))\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"),
    re.compile(r"(?i:\b(?:soy|me llamo))\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"),
    re.compile(r"(?i:\b(?:je m'appelle|je suis))\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"),
]
_COMPANY_PATTERNS = [
    re.compile(r"(?i:\b(?:from|at|with|company is))\s+([A-Z][A-Za-z0-9&.-]+(?:\s+[A-Z][A-Za-z0-9&.-]+)?)\b"),
]

_BUDGET_AMOUNT_RE = re.compile(
    r"(?:\$|usd|eur|€|₹|rs\.?)\s*\d+(?:[.,]\d+)?(?:\s*[kKmM])?|\b\d+(?:[.,]\d+)?\s*[kKmM]\b",
    re.IGNORECASE,
)

_HIGH_AUTHORITY_ROLES = [
    ("vp", "VP / Executive"),
    ("vice president", "VP / Executive"),
    ("chief", "C-Level Executive"),
    ("cto", "CTO"),
    ("ceo", "CEO"),
    ("cro", "CRO"),
    ("founder", "Founder"),
    ("co-founder", "Co-Founder"),
    ("head of", "Head of Department"),
    ("director", "Director"),
    ("owner", "Business Owner"),
]

_MID_AUTHORITY_ROLES = [
    ("manager", "Manager"),
    ("lead", "Team Lead"),
    ("revops", "RevOps Lead"),
    ("gerente", "Manager"),
    ("directeur", "Director"),
    ("leiter", "Head / Lead"),
]

_NEED_KEYWORDS: Dict[str, str] = {
    "slow": "Slow lead response time",
    "response time": "Slow lead response time",
    "miss": "Missed inbound calls/leads",
    "missed": "Missed inbound calls/leads",
    "manual": "Manual CRM data entry",
    "qualify": "Automated lead qualification",
    "qualification": "Automated lead qualification",
    "multilingual": "Multilingual prospect coverage",
    "spanish": "Multilingual prospect coverage",
    "hindi": "Multilingual prospect coverage",
    "scale": "Scaling SDR pipeline without headcount",
    "scaling": "Scaling SDR pipeline without headcount",
    "outbound": "Outbound/inbound voice automation",
    "inbound": "24/7 inbound call handling",
    "crm": "CRM automation & sync",
    "book": "Automated demo scheduling",
    "demo": "Automated demo scheduling",
    "necesitamos": "Sales workflow automation",
    "automatizar": "Sales workflow automation",
    "कीमत": "Pricing & ROI evaluation",
    "लीड्स": "Lead response automation",
}

_URGENT_TIMELINE = [
    "immediately", "asap", "this week", "right away", "today", "next week",
    "this month", "within 30 days", "q1", "q2", "q3", "q4", "esta semana",
    "este mes", "inmediatamente", "तुरंत", "इस महीने", "cette semaine", "sofort",
]
_NEAR_TIMELINE = [
    "next month", "few weeks", "1-2 months", "this quarter", "soon", "pronto",
    "अगले महीने", "bald",
]
_LATER_TIMELINE = [
    "next year", "exploring", "just looking", "no rush", "6 months", "later",
]


def extract_contact_entities(text: str) -> Dict[str, Optional[str]]:
    """Extract prospect name, email, and company name when volunteered."""
    entities: Dict[str, Optional[str]] = {"name": None, "email": None, "company": None}
    email_m = _EMAIL_RE.search(text)
    if email_m:
        entities["email"] = email_m.group(0)

    for pattern in _NAME_PATTERNS:
        m = pattern.search(text)
        if m:
            candidate = m.group(1).strip()
            if candidate.lower() not in {"interested", "looking", "calling", "here"}:
                entities["name"] = candidate
                break

    for pattern in _COMPANY_PATTERNS:
        m = pattern.search(text)
        if m:
            candidate = m.group(1).strip()
            if candidate.lower() not in {"novaflow", "google", "salesforce", "hubspot"}:
                entities["company"] = candidate
                break

    return entities


def update_bant(current: BANTCriteria, utterance: str) -> BANTCriteria:
    """Incrementally update BANT qualification criteria and compute total 0-100 score."""
    lower = utterance.lower()
    budget = current.budget
    budget_score = current.budget_score
    authority = current.authority
    authority_score = current.authority_score
    need = current.need
    need_score = current.need_score
    timeline = current.timeline
    timeline_score = current.timeline_score

    # 1. Budget (0-25)
    amt_match = _BUDGET_AMOUNT_RE.search(utterance)
    if amt_match:
        amt_str = amt_match.group(0).strip()
        budget = f"Stated budget: {amt_str}"
        budget_score = 25
    elif any(k in lower for k in ["approved budget", "have budget", "budget ready", "presupuesto aprobado"]):
        budget = "Approved budget confirmed"
        budget_score = max(budget_score, 22)
    elif any(k in lower for k in ["growth plan", "enterprise plan", "starter plan", "pricing", "cost", "precio", "कीमत", "prix", "preis"]):
        if not budget:
            budget = "Evaluating subscription tiers"
            budget_score = max(budget_score, 12)
    elif any(k in lower for k in ["no budget", "free only", "too expensive", "tight budget"]):
        budget = "Budget-sensitive / constrained"
        budget_score = max(budget_score, 8)

    # 2. Authority (0-25)
    for kw, label in _HIGH_AUTHORITY_ROLES:
        if re.search(rf"\b{re.escape(kw)}\b", lower):
            authority = f"Decision Maker ({label})"
            authority_score = 25
            break
    if authority_score < 25:
        for kw, label in _MID_AUTHORITY_ROLES:
            if re.search(rf"\b{re.escape(kw)}\b", lower):
                authority = f"Influencer / Champion ({label})"
                authority_score = max(authority_score, 18)
                break
    if authority_score == 0 and any(
        k in lower for k in ["my team", "our team", "we have", "decision maker", "nuestro equipo"]
    ):
        authority = "Team stakeholder"
        authority_score = 14

    # 3. Need (0-30)
    matched_needs: List[str] = []
    for kw, desc in _NEED_KEYWORDS.items():
        if kw in lower and desc not in matched_needs:
            matched_needs.append(desc)
    if matched_needs:
        existing_parts = [p.strip() for p in need.split(";")] if need else []
        merged = list(dict.fromkeys(existing_parts + matched_needs))
        need = "; ".join(merged[:3])
        need_score = min(30, 18 + 6 * len(merged))

    # 4. Timeline (0-20)
    if any(k in lower for k in _URGENT_TIMELINE):
        timeline = "Immediate / Current Quarter"
        timeline_score = 20
    elif any(k in lower for k in _NEAR_TIMELINE):
        timeline = "Near-term (1-2 months)"
        timeline_score = max(timeline_score, 15)
    elif any(k in lower for k in _LATER_TIMELINE):
        timeline = "Exploratory / Long-term"
        timeline_score = max(timeline_score, 7)

    total = min(100, budget_score + authority_score + need_score + timeline_score)
    tier = "Hot" if total >= 70 else ("Warm" if total >= 40 else "Cold")

    missing: List[str] = []
    if budget_score < 15:
        missing.append("budget")
    if authority_score < 15:
        missing.append("authority")
    if need_score < 15:
        missing.append("need")
    if timeline_score < 12:
        missing.append("timeline")

    return BANTCriteria(
        budget=budget,
        budget_score=budget_score,
        authority=authority,
        authority_score=authority_score,
        need=need,
        need_score=need_score,
        timeline=timeline,
        timeline_score=timeline_score,
        total_score=total,
        tier=tier,  # type: ignore[arg-type]
        missing_fields=missing,
    )
