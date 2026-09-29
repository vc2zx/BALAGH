"""One synthetic, isolated Flask-to-Ollama-to-human-review smoke run.

Requires the configured Ollama chat and embedding models to be available.
Writes no report to the normal BALAGH database.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import balagh.database as database
from balagh import create_app
from balagh.knowledge import load_official_documents
from balagh.triage import ReportInput, triage_report


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with tempfile.TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with patch.object(database, "DATA_DIR", data_dir), patch.object(database, "DB_PATH", data_dir / "smoke.db"):
            with patch.dict(os.environ, {"STAFF_ACCESS_CODE": "synthetic-smoke-access"}):
                app = create_app({"TESTING": True, "SECRET_KEY": "synthetic-smoke-key"})
                report = ReportInput(
                    title="لوحة تحديد السرعة مفقودة",
                    description="لوحة تحديد السرعة غير ظاهرة عند مخرج تجريبي؛ يرجى التحقق من الاتجاه والموقع.",
                    city="مدينة تجريبية", district="حي تجريبي", landmark="مخرج تجريبي",
                )
                report_id = database.create_report(report, triage_report(report, [], "Arabic"), "Arabic")
                client = app.test_client()
                client.post("/staff/login", data={"access_code": "synthetic-smoke-access"})
                started = time.perf_counter()
                client.post(f"/staff/reports/{report_id}/recommendations")
                inference_seconds = time.perf_counter() - started
                recommendation = database.get_agent_recommendation(report_id)
                if not recommendation:
                    raise RuntimeError("The real model did not create a reviewable recommendation.")
                started = time.perf_counter()
                client.post(
                    f"/staff/reports/{report_id}/recommendations/{recommendation['id']}/review",
                    data={"decision": "Rejected", "reviewer_note": "Synthetic smoke test only."},
                )
                review_seconds = time.perf_counter() - started
                saved = database.get_agent_recommendation(report_id)
                evidence = json.loads(saved["source_evidence"] or "[]")
                known_sources = {
                    (document.metadata.get("id"), document.metadata.get("url"))
                    for document in load_official_documents()
                }
                result = {
                    "model": os.getenv("MODEL", "qwen3:4b-instruct"),
                    "embedding_model": os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
                    "synthetic": True,
                    "inference_seconds": round(inference_seconds, 3),
                    "review_seconds": round(review_seconds, 3),
                    "route": saved["agent_route"],
                    "tool_calls": saved["tool_calls"],
                    "source_citations": saved["source_citations"],
                    "source_evidence_count": len(evidence),
                    "source_provenance_matches": sum(
                        (item.get("id"), item.get("url")) in known_sources for item in evidence
                    ),
                    "decision": saved["decision"],
                    "resume_status": saved["workflow_resume_status"],
                    "history_actions": database.get_case_history(report_id)["action"].tolist(),
                    "recommendation": saved["final_recommendation"],
                    "model_audit": saved["triage_review"],
                    "validation_notes": saved["validation_notes"],
                }
                print(json.dumps(result, ensure_ascii=False, indent=2))
                if (result["decision"] != "Rejected" or result["resume_status"] != "completed"
                        or result["source_evidence_count"] == 0
                        or result["source_evidence_count"] != result["source_provenance_matches"]):
                    raise RuntimeError("The staff decision was not completed after the model run.")
                if any(key in result["model_audit"] for key in
                       ("current_rules_preview", "interpretation_rules", "stored_triage", "case_facts")):
                    raise RuntimeError("Internal field names leaked into the staff-facing audit.")


if __name__ == "__main__":
    main()
