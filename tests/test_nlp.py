"""Unit tests for multilingual detection, BANT qualification, sentiment, and PII redaction."""

import unittest

from app.models import BANTCriteria
from app.nlp.multilingual import detect_language
from app.nlp.qualification import extract_contact_entities, update_bant
from app.nlp.security import redact_pii
from app.nlp.sentiment import analyze_sentiment


class TestNLPModules(unittest.TestCase):
    def test_language_detection(self) -> None:
        self.assertEqual(detect_language("Hola, queremos saber el precio para nuestro equipo."), "es")
        self.assertEqual(detect_language("नमस्ते, हमें कीमत की जानकारी चाहिए।"), "hi")
        self.assertEqual(detect_language("Bonjour, quel est votre tarif pour l'équipe ?"), "fr")
        self.assertEqual(detect_language("Hallo, wir brauchen eine Demo nächste Woche."), "de")
        self.assertEqual(detect_language("Hello, we want to automate inbound sales calls."), "en")

    def test_incremental_bant_scoring(self) -> None:
        bant = BANTCriteria()
        bant = update_bant(bant, "I'm the VP of Sales and we lose leads due to slow response times.")
        self.assertGreaterEqual(bant.authority_score, 20)
        self.assertGreaterEqual(bant.need_score, 18)

        bant = update_bant(bant, "We have an approved $25k budget and want to launch this month.")
        self.assertEqual(bant.tier, "Hot")
        self.assertGreaterEqual(bant.total_score, 75)
        self.assertEqual(bant.missing_fields, [])

    def test_contact_entity_extraction(self) -> None:
        entities = extract_contact_entities(
            "Hi, I'm Sarah Jenkins from FinScale Cloud and my email is sarah@finscale.io."
        )
        self.assertEqual(entities["name"], "Sarah Jenkins")
        self.assertEqual(entities["email"], "sarah@finscale.io")
        self.assertEqual(entities["company"], "FinScale Cloud")

    def test_sentiment_and_objections(self) -> None:
        skeptical = analyze_sentiment("This sounds too expensive and I'm concerned about hallucinations.")
        self.assertEqual(skeptical.label, "Skeptical")
        self.assertIn("Pricing / Budget", skeptical.objections)
        self.assertIn("Security / AI Trust", skeptical.objections)

        enthusiastic = analyze_sentiment("Awesome! Let's schedule a demo this week.")
        self.assertIn(enthusiastic.label, {"Positive", "Enthusiastic"})
        self.assertIn("Requested Demo / Meeting", enthusiastic.buying_signals)

    def test_pii_redaction(self) -> None:
        raw = "My card is 4111-2222-3333-4444 and SSN is 123-45-6789."
        cleaned = redact_pii(raw)
        self.assertNotIn("4111", cleaned)
        self.assertNotIn("123-45-6789", cleaned)
        self.assertIn("[REDACTED-CARD]", cleaned)
        self.assertIn("[REDACTED-SSN]", cleaned)


if __name__ == "__main__":
    unittest.main()
