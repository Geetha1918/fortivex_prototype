"""Hybrid TF-IDF + metadata tag RAG retriever with cross-lingual keyword expansion."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.models import RetrievedChunk

_MULTILINGUAL_ALIASES: Dict[str, str] = {
    # Spanish
    "precio": "pricing cost plans",
    "precios": "pricing cost plans",
    "costo": "pricing cost budget",
    "seguridad": "security compliance soc2 gdpr",
    "integracion": "integrations salesforce hubspot crm",
    "integración": "integrations salesforce hubspot crm",
    "demo": "onboarding implementation demo",
    "caro": "expensive pricing budget discount",
    # Hindi (Devanagari & transliterated)
    "कीमत": "pricing cost plans",
    "दाम": "pricing cost plans",
    "बजट": "budget pricing plans",
    "सुरक्षा": "security compliance soc2 gdpr",
    "एकीकरण": "integrations salesforce hubspot crm",
    "डेमो": "onboarding implementation demo",
    "महंगा": "expensive pricing budget discount",
    "kimat": "pricing cost plans",
    "mehnga": "expensive pricing budget",
    # French
    "prix": "pricing cost plans",
    "tarif": "pricing cost plans",
    "sécurité": "security compliance soc2 gdpr",
    "intégration": "integrations salesforce hubspot crm",
    "cher": "expensive pricing budget",
    # German
    "preis": "pricing cost plans",
    "preise": "pricing cost plans",
    "kosten": "pricing cost budget",
    "sicherheit": "security compliance soc2 gdpr",
    "teuer": "expensive pricing budget",
}


class KnowledgeRetriever:
    """In-memory hybrid vector + tag RAG retriever over the product knowledge base."""

    def __init__(self, kb_path: Path) -> None:
        self.kb_path = Path(kb_path)
        self.documents: List[Dict[str, Any]] = []
        self._vectorizer: TfidfVectorizer | None = None
        self._matrix: Any = None
        self.reload()

    def reload(self) -> None:
        """Load documents from disk and rebuild the TF-IDF index."""
        raw = json.loads(self.kb_path.read_text(encoding="utf-8"))
        self.documents = raw
        self._build_index()

    def add_document(
        self,
        doc_id: str,
        title: str,
        category: str,
        content: str,
        tags: List[str] | None = None,
    ) -> Dict[str, Any]:
        """Add or update a knowledge base document in-memory and re-index."""
        doc = {
            "doc_id": doc_id,
            "title": title,
            "category": category,
            "tags": tags or [],
            "content": content,
        }
        self.documents = [d for d in self.documents if d["doc_id"] != doc_id]
        self.documents.append(doc)
        self._build_index()
        return doc

    def _build_index(self) -> None:
        corpus = [
            f"{d['title']} {d['category']} {' '.join(d.get('tags', []))} {d['content']}"
            for d in self.documents
        ]
        self._vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
        self._matrix = self._vectorizer.fit_transform(corpus)

    def _expand_query(self, query: str) -> str:
        tokens = re.findall(r"[\w\u0900-\u097F]+", query.lower())
        expansions = [_MULTILINGUAL_ALIASES[t] for t in tokens if t in _MULTILINGUAL_ALIASES]
        return f"{query} {' '.join(expansions)}".strip()

    def retrieve(self, query: str, top_k: int = 3, min_score: float = 0.05) -> List[RetrievedChunk]:
        """Return top-k grounded knowledge chunks with normalized hybrid similarity scores."""
        if not self.documents or self._vectorizer is None or self._matrix is None:
            return []

        expanded = self._expand_query(query)
        q_vec = self._vectorizer.transform([expanded])
        cosine_scores = cosine_similarity(q_vec, self._matrix).flatten()

        q_tokens = set(re.findall(r"[\w\u0900-\u097F]+", expanded.lower()))
        results: List[RetrievedChunk] = []

        for idx, doc in enumerate(self.documents):
            base_score = float(cosine_scores[idx])
            tags = {t.lower() for t in doc.get("tags", [])}
            tag_hits = len(q_tokens.intersection(tags))
            hybrid_score = min(0.99, base_score + 0.08 * tag_hits)

            if hybrid_score >= min_score:
                excerpt = doc["content"]
                if len(excerpt) > 340:
                    excerpt = excerpt[:337].rsplit(" ", 1)[0] + "..."
                results.append(
                    RetrievedChunk(
                        doc_id=doc["doc_id"],
                        title=doc["title"],
                        category=doc["category"],
                        score=round(hybrid_score, 3),
                        excerpt=excerpt,
                    )
                )

        results.sort(key=lambda c: c.score, reverse=True)
        if not results and self.documents:
            # Always provide overview fallback with low confidence if no lexical match
            overview = self.documents[0]
            results.append(
                RetrievedChunk(
                    doc_id=overview["doc_id"],
                    title=overview["title"],
                    category=overview["category"],
                    score=0.12,
                    excerpt=overview["content"][:337] + "...",
                )
            )
        return results[:top_k]
