from __future__ import annotations

import math
import unittest

from langchain_core.embeddings import Embeddings

from balagh.agent_policy import build_agent_case_context
from balagh.knowledge import (
    OfficialKnowledgeBase,
    load_official_documents,
    retrieve_official_sources,
    split_official_documents,
)


class _KeywordEmbeddings(Embeddings):
    vocabulary = ("طريق", "لوحة", "اشارة", "بلاغ", "الرياض", "نفايات")

    def _vector(self, text: str) -> list[float]:
        values = [float(text.count(term)) for term in self.vocabulary]
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class KnowledgeTests(unittest.TestCase):
    def test_documents_are_loaded_split_embedded_and_retrieved(self) -> None:
        documents = load_official_documents()
        chunks = split_official_documents(documents, chunk_size=220, chunk_overlap=30)
        self.assertGreaterEqual(len(documents), 3)
        self.assertGreater(len(chunks), len(documents))

        knowledge_base = OfficialKnowledgeBase.build(embeddings=_KeywordEmbeddings())
        results = knowledge_base.retrieve("لوحة سرعة مفقودة على طريق", limit=2)

        self.assertTrue(results)
        self.assertEqual(results[0]["id"], "S2")
        self.assertIn("road-code-library", results[0]["url"])

    def test_case_retrieval_returns_source_metadata_and_context(self) -> None:
        report = {
            "title": "لا توجد لوحة سرعة",
            "description": "لوحة تحديد السرعة مفقودة من الطريق",
            "city": "الرياض",
            "district": "الملز",
            "landmark": "طريق عبدالله",
            "category": "Traffic Signs & Road Safety",
            "priority": "Medium",
            "department": "Traffic Signs and Road Safety",
            "category_confidence": "High",
            "category_evidence": "لوحة السرعة",
        }
        context = build_agent_case_context(report, "Arabic")
        knowledge_base = OfficialKnowledgeBase.build(embeddings=_KeywordEmbeddings())

        sources = retrieve_official_sources(
            context,
            knowledge_base=knowledge_base,
        )

        self.assertTrue(any(source["id"] == "S2" for source in sources))
        self.assertTrue(all(source["guidance"] for source in sources))
        self.assertTrue(all(source["source_file"].endswith(".md") for source in sources))


if __name__ == "__main__":
    unittest.main()
