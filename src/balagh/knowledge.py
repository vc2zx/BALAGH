from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = PROJECT_ROOT / "data" / "knowledge"
_INDEX_LOCK = Lock()
_DEFAULT_KNOWLEDGE_BASE: "OfficialKnowledgeBase | None" = None


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Parse the small key/value header used by the bundled source notes."""
    if not text.startswith("---\n"):
        return {}, text
    header, separator, body = text[4:].partition("\n---\n")
    if not separator:
        return {}, text
    metadata: dict[str, str] = {}
    for line in header.splitlines():
        key, marker, value = line.partition(":")
        if marker:
            metadata[key.strip()] = value.strip()
    return metadata, body.strip()


def load_official_documents(directory: Path = KNOWLEDGE_DIR) -> list[Document]:
    """Load the checked-in official-source notes as LangChain documents."""
    documents: list[Document] = []
    for path in sorted(directory.glob("*.md")):
        metadata, body = _parse_front_matter(path.read_text(encoding="utf-8"))
        if not body:
            continue
        metadata["source_file"] = path.name
        documents.append(Document(page_content=body, metadata=metadata))
    if not documents:
        raise RuntimeError(f"No knowledge documents found in {directory}")
    return documents


def split_official_documents(
    documents: Iterable[Document],
    *,
    chunk_size: int = 700,
    chunk_overlap: int = 100,
) -> list[Document]:
    """Split source notes into overlapping chunks before embedding."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "،", " ", ""],
    )
    return splitter.split_documents(list(documents))


def ollama_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
        base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
    )


@dataclass
class OfficialKnowledgeBase:
    """Two-step RAG index: embed first, then retrieve before generation."""

    vector_store: InMemoryVectorStore
    chunk_count: int

    @classmethod
    def build(
        cls,
        *,
        embeddings: Embeddings | None = None,
        directory: Path = KNOWLEDGE_DIR,
    ) -> "OfficialKnowledgeBase":
        documents = load_official_documents(directory)
        chunks = split_official_documents(documents)
        store = InMemoryVectorStore(embedding=embeddings or ollama_embeddings())
        store.add_documents(chunks)
        return cls(vector_store=store, chunk_count=len(chunks))

    def retrieve(self, query: str, *, limit: int = 4) -> list[dict[str, str]]:
        if not query.strip():
            raise ValueError("A non-empty retrieval query is required.")
        results = self.vector_store.similarity_search(query, k=max(1, min(limit, 8)))
        return [
            {
                "id": str(document.metadata.get("id", "source")),
                "title": str(document.metadata.get("title", "Official source")),
                "organization": str(document.metadata.get("organization", "")),
                "url": str(document.metadata.get("url", "")),
                "guidance": document.page_content.strip(),
                "source_file": str(document.metadata.get("source_file", "")),
            }
            for document in results
        ]


def get_official_knowledge_base() -> OfficialKnowledgeBase:
    """Build the local vector index once per process."""
    global _DEFAULT_KNOWLEDGE_BASE
    if _DEFAULT_KNOWLEDGE_BASE is None:
        with _INDEX_LOCK:
            if _DEFAULT_KNOWLEDGE_BASE is None:
                _DEFAULT_KNOWLEDGE_BASE = OfficialKnowledgeBase.build()
    return _DEFAULT_KNOWLEDGE_BASE


def retrieve_official_sources(
    case_context: dict[str, Any],
    limit: int = 4,
    *,
    knowledge_base: OfficialKnowledgeBase | None = None,
) -> list[dict[str, str]]:
    """Retrieve semantic context for a stored case from the vector index."""
    facts = case_context["case_facts"]
    preview = case_context["current_rules_preview"]
    query = " ".join(
        str(value or "")
        for value in (
            facts.get("title"),
            facts.get("description"),
            facts.get("city"),
            facts.get("district"),
            preview.get("category"),
            preview.get("department"),
        )
    )
    return (knowledge_base or get_official_knowledge_base()).retrieve(query, limit=limit)


def reset_knowledge_base_cache() -> None:
    """Clear the process-local vector index, primarily for deterministic tests."""
    global _DEFAULT_KNOWLEDGE_BASE
    _DEFAULT_KNOWLEDGE_BASE = None
