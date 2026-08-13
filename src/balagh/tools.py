from __future__ import annotations

import json
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from balagh.database import find_similar_reports, get_case_history, get_report


class ReportIdInput(BaseModel):
    report_id: int = Field(..., description="The numeric BALAGH report ID.")


class GetCaseTool(BaseTool):
    name: str = "get_case"
    description: str = (
        "Read the stored facts, deterministic triage, current status, and safety warning "
        "for one BALAGH case. This tool is read-only."
    )
    args_schema: Type[BaseModel] = ReportIdInput

    def _run(self, report_id: int) -> str:
        row = get_report(report_id)
        if row is None:
            return "Case not found."

        allowed_fields = [
            "id",
            "created_at",
            "title",
            "description",
            "city",
            "district",
            "landmark",
            "category",
            "priority",
            "department",
            "status",
            "duplicate_of",
            "duplicate_score",
            "reasoning",
            "missing_information",
            "emergency_warning",
        ]
        payload = {field: row.get(field) for field in allowed_fields}
        return json.dumps(payload, ensure_ascii=False, indent=2)


class FindSimilarReportsTool(BaseTool):
    name: str = "find_similar_reports"
    description: str = (
        "Read the most similar stored BALAGH reports for a selected case. "
        "Returns case IDs, locations, status, and similarity scores. Read-only."
    )
    args_schema: Type[BaseModel] = ReportIdInput

    def _run(self, report_id: int) -> str:
        rows = find_similar_reports(report_id, limit=5)
        return json.dumps(rows, ensure_ascii=False, indent=2)


class GetCaseHistoryTool(BaseTool):
    name: str = "get_case_history"
    description: str = (
        "Read the auditable action history of one BALAGH case. This tool cannot "
        "change or append history records."
    )
    args_schema: Type[BaseModel] = ReportIdInput

    def _run(self, report_id: int) -> str:
        frame = get_case_history(report_id)
        if frame.empty:
            return "No recorded history for this case."
        return frame.to_json(orient="records", force_ascii=False)
