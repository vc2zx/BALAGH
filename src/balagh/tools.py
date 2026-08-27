from __future__ import annotations

from typing import Any

from balagh import database
from balagh.agent_policy import build_agent_case_context
from balagh.knowledge import retrieve_official_sources


def get_case_context(report_id: int, language: str = "Arabic") -> dict[str, Any]:
    """Return normalized, read-only facts and deterministic triage for one case."""
    report = database.get_report(report_id)
    if report is None:
        raise ValueError(f"Report #{report_id} does not exist.")
    return build_agent_case_context(report, language=language)


def find_similar_report_candidates(
    report_id: int,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return similarity candidates without confirming that they are duplicates."""
    return database.find_similar_reports(report_id, limit=limit)


def get_case_history_records(report_id: int) -> list[dict[str, Any]]:
    """Return the auditable case history as JSON-compatible records."""
    history = database.get_case_history(report_id)
    return history.astype(object).where(history.notna(), None).to_dict(
        orient="records"
    )


def get_official_reference_context(
    case_context: dict[str, Any],
    limit: int = 3,
) -> list[dict[str, str]]:
    """Return semantically retrieved official-reference chunks for the case."""
    return retrieve_official_sources(case_context, limit=limit)


def get_human_decision_memory(report_id: int, limit: int = 3) -> list[dict[str, Any]]:
    """Return prior reviewer feedback as bounded long-term decision memory."""
    return database.get_human_decision_memory(report_id, limit=limit)
