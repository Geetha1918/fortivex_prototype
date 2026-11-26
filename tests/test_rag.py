"""Unit tests for the hybrid TF-IDF + multilingual RAG retriever."""

import unittest

from app.config import settings
from app.rag.retriever import KnowledgeRetriever


class TestKnowledgeRetriever(unittest.TestCase):
    def setUp(self) -> None:
        self.retriever = KnowledgeRetriever(settings.knowledge_base_path)

    def test_pricing_retrieval(self) -> None:
        chunks = self.retriever.retrieve("What are your pricing plans and Growth tier cost?", top_k=2)
        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(chunks[0].category, "Pricing")
        self.assertIn("1,499", chunks[0].excerpt)

    def test_multilingual_query_expansion(self) -> None:
        spanish_chunks = self.retriever.retrieve("¿Cuál es el precio mensual?", top_k=2)
        self.assertGreaterEqual(len(spanish_chunks), 1)
        self.assertEqual(spanish_chunks[0].category, "Pricing")

        hindi_chunks = self.retriever.retrieve("कीमत और प्लान क्या है?", top_k=2)
        self.assertGreaterEqual(len(hindi_chunks), 1)
        self.assertEqual(hindi_chunks[0].category, "Pricing")

    def test_dynamic_document_indexing(self) -> None:
        self.retriever.add_document(
            doc_id="kb-custom-sla",
            title="Custom GovCloud Deployment",
            category="Security",
            content="NovaFlow supports FedRAMP and GovCloud isolated deployments.",
            tags=["govcloud", "fedramp"],
        )
        chunks = self.retriever.retrieve("Do you support FedRAMP GovCloud?", top_k=1)
        self.assertEqual(chunks[0].doc_id, "kb-custom-sla")


if __name__ == "__main__":
    unittest.main()
