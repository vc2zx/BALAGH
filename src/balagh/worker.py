"""Separate bounded worker for durable semantic triage jobs."""
from __future__ import annotations

import argparse
import logging
import os
import time
from uuid import uuid4

from balagh import database, store
from balagh.duplicates import rank_candidates
from balagh.semantic import propose


LOGGER = logging.getLogger(__name__)


def _embedding(text: str) -> list[float]:
    from langchain_ollama import OllamaEmbeddings
    return OllamaEmbeddings(
        model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
        base_url=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
    ).embed_query(text)


def _sources(report: dict) -> tuple[list[dict], str]:
    """Source notes support context only; no generated operational claim is accepted."""
    try:
        from balagh.knowledge import get_official_knowledge_base, source_set_version
        query = " ".join(str(report.get(key) or "") for key in ("title", "description", "city", "district"))
        sources = [item for item in get_official_knowledge_base().retrieve(query, limit=6)
                   if item["jurisdiction"] in {"saudi_arabia", report.get("city_id")}][:3]
        return sources, source_set_version()
    except Exception as exc:
        LOGGER.warning("Knowledge retrieval unavailable for report %s: %s", report["id"], exc)
        return [], "unavailable"


def process_one(worker_id: str | None = None) -> bool:
    worker_id = worker_id or uuid4().hex
    report_id = store.claim_job(worker_id)
    if report_id is None:
        return False
    try:
        view = store.case_view(report_id)
        if view is None:
            raise ValueError("Report disappeared")
        report = view["report"]
        proposal, model = propose(report["title"], report["description"], report["city_id"])
        safety = view["safety"] or {}
        proposal["safety_floor"] = "Critical" if safety.get("urgent_review") else None
        proposal["effective_priority"] = (
            "Critical" if safety.get("urgent_review") else proposal["proposed_priority"]
        )
        sources, source_version = _sources(report)
        proposal["sources"] = sources
        proposal["source_support"] = "context_only" if sources else "no_suitable_source"
        embedding = None
        candidates: list[dict] = []
        asset_type = proposal["category_ids"][0] if len(proposal["category_ids"]) == 1 else None
        try:
            embedding = _embedding(f"{report['title']} {report['description']}")
            candidates = rank_candidates(report_id, embedding, asset_type)
        except Exception as exc:
            LOGGER.warning("Duplicate embedding unavailable for report %s: %s", report_id, exc)
        store.complete_job(report_id, worker_id, proposal, model, candidates,
                           embedding, asset_type, source_version)
    except Exception as exc:
        LOGGER.exception("Semantic analysis failed for report %s", report_id)
        store.fail_job(report_id, worker_id, type(exc).__name__ + ": " + str(exc))
    return True


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process at most one queued report")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    database.init_db()
    worker_id = uuid4().hex
    if args.once:
        process_one(worker_id)
        return
    while True:
        if not process_one(worker_id):
            time.sleep(2)


if __name__ == "__main__":
    main()
