from __future__ import annotations

from typing import Any, Mapping

from balagh.triage import ReportInput, triage_report


AGENT_INTERPRETATION_RULES = [
    (
        "matched_category_keywords are lexical phrases found in the report text. "
        "They are not observations, images, or proof that an object exists."
    ),
    (
        "A negative statement such as 'no speed limit sign' means that the reporter "
        "says the sign is absent; matching 'speed limit sign' does not contradict it."
    ),
    (
        "A similarity score identifies only a potential duplicate for employee review; "
        "it never confirms duplication by itself."
    ),
    (
        "BALAGH has no configured service-level deadline. Do not invent hours, days, "
        "deadlines, or automatic escalation rules."
    ),
]


def split_stored_list(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def build_agent_case_context(
    stored_report: Mapping[str, object],
    language: str,
) -> dict[str, Any]:
    """Build an unambiguous, read-only case payload for both agents and their tools."""
    report = ReportInput(
        title=str(stored_report.get("title", "")),
        description=str(stored_report.get("description", "")),
        city=str(stored_report.get("city", "")),
        district=str(stored_report.get("district", "")),
        landmark=str(stored_report.get("landmark", "") or ""),
    )
    preview = triage_report(report, existing_reports=[], language=language)
    categories_match = stored_report.get("category") == preview.category

    potential_duplicate = None
    if stored_report.get("duplicate_of") is not None:
        potential_duplicate = {
            "report_id": stored_report.get("duplicate_of"),
            "similarity_score": stored_report.get("duplicate_score"),
            "interpretation": (
                "Candidate only. Similarity does not confirm duplication; "
                "an employee must decide."
            ),
        }

    return {
        "case_facts": {
            "id": stored_report.get("id"),
            "created_at": stored_report.get("created_at"),
            "title": stored_report.get("title"),
            "description": stored_report.get("description"),
            "city": stored_report.get("city"),
            "district": stored_report.get("district"),
            "landmark": stored_report.get("landmark"),
            "status": stored_report.get("status"),
            "emergency_warning": stored_report.get("emergency_warning"),
        },
        "stored_triage": {
            "category": stored_report.get("category"),
            "priority": stored_report.get("priority"),
            "department": stored_report.get("department"),
            "category_confidence": stored_report.get("category_confidence"),
            "matched_category_keywords": split_stored_list(
                stored_report.get("category_evidence")
            ),
            "missing_information": split_stored_list(
                stored_report.get("missing_information")
            ),
        },
        "stored_potential_duplicate": potential_duplicate,
        "current_rules_preview": {
            "category": preview.category,
            "priority": preview.priority,
            "department": preview.department,
            "category_confidence": preview.category_confidence,
            "matched_category_keywords": preview.category_evidence,
            "missing_information": preview.missing_information,
        },
        "comparison": {
            "stored_category_matches_current_rules": categories_match,
            "instruction": (
                "If true, state that no category correction is required. "
                "Do not propose changing a category to the same category."
            ),
        },
        "interpretation_rules": AGENT_INTERPRETATION_RULES,
    }
