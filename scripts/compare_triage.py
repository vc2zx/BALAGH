"""Replay a frozen synthetic set through legacy rules and the V3 local pipeline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import tempfile
import time
from pathlib import Path

from balagh import database, store, worker
from balagh.catalog import catalog
from balagh.knowledge import source_set_version
from balagh.semantic import PROMPT_VERSION, SCHEMA_VERSION
from balagh.triage import ReportInput, triage_report


ROOT = Path(__file__).resolve().parents[1]
LEGACY_IDS = {
    "Traffic Signs & Road Safety": "traffic_safety", "Roads & Sidewalks": "roads_sidewalks",
    "Waste & Cleanliness": "waste_cleanliness",
    "Street Lighting & Electrical": "street_lighting_electrical",
    "Water & Drainage": "water_drainage", "Accessibility": "accessibility",
    "Public Facilities": "public_facilities", "Noise & Community Disturbance": "noise_community",
    "Needs Human Classification": "unknown",
}


def _p95(values: list[float]) -> float | None:
    return sorted(values)[max(0, (95 * len(values) + 99) // 100 - 1)] if values else None


def _summary(rows: list[dict], key: str) -> dict:
    valid = [item for item in rows if item[key] is not None and item[key].get("valid", True)]
    category_correct = sum(set(item[key]["category_ids"]) == set(item["gold_ids"]) for item in valid)
    urgent = [item for item in rows if item[key] is not None and item["urgent_gold"]]
    nonurgent = [item for item in rows if item[key] is not None and not item["urgent_gold"]]
    latency = [item[key]["latency_ms"] for item in rows if item[key] is not None]
    id_map = {item["id"]: index for index, item in enumerate(rows, start=1)}
    positives = [item for item in rows if item["gold_duplicate_of"]]
    flagged = [item for item in rows if item[key] is not None and item[key]["duplicate_of"] is not None]
    correct_duplicates = sum(item[key]["duplicate_of"] == id_map[item["gold_duplicate_of"]]
                             for item in positives if item[key] is not None)
    special = [item for item in rows if item["gold_ids"] in (["unknown"], ["out_of_scope"])]
    mixed = [item for item in rows if len(item["gold_ids"]) > 1]
    abstentions = [item for item in rows if item[key] is not None and
                   set(item[key]["category_ids"]) & {"unknown", "out_of_scope"}]
    return {
        "cases": len(rows), "valid": len(valid), "category_correct": category_correct,
        "category_denominator": len(rows),
        "urgent_recall": [sum(item[key]["urgent"] for item in urgent), len(urgent)],
        "urgent_false_positives": [sum(item[key]["urgent"] for item in nonurgent), len(nonurgent)],
        "special_outcome_correct": [sum(item in valid and item[key]["category_ids"] == item["gold_ids"] for item in special), len(special)],
        "mixed_issues_correct": [sum(item in valid and set(item[key]["category_ids"]) == set(item["gold_ids"]) for item in mixed), len(mixed)],
        "abstention_predictions": [len(abstentions), len(rows)],
        "duplicate_precision": [correct_duplicates, len(flagged)],
        "duplicate_recall": [correct_duplicates, len(positives)],
        "median_ms": round(statistics.median(latency), 2) if latency else None,
        "p95_ms": round(_p95(latency), 2) if latency else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluation" / "frozen_arabic_v3.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "evidence" / "semantic_comparison.json")
    parser.add_argument("--rules-only", action="store_true")
    args = parser.parse_args()
    payload = args.dataset.read_bytes()
    dataset = json.loads(payload)
    rows: list[dict] = []
    earlier: list[dict] = []
    report_ids: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as temp:
        original_data, original_db = database.DATA_DIR, database.DB_PATH
        database.DATA_DIR = Path(temp)
        database.DB_PATH = Path(temp) / "evaluation.db"
        try:
            database.init_db()
            for case in dataset["cases"]:
                report = ReportInput(case["title"], case["description"], case["city"], case["district"])
                row = {"id": case["id"], "gold_ids": case["gold_ids"],
                       "urgent_gold": case["urgent"], "gold_duplicate_of": case.get("gold_duplicate_of")}
                started = time.perf_counter()
                baseline = triage_report(report, earlier, "Arabic")
                baseline_ms = (time.perf_counter() - started) * 1000
                row["rules"] = {"category_ids": [LEGACY_IDS.get(baseline.category, "unknown")],
                                "urgent": baseline.priority == "Critical",
                                "duplicate_of": baseline.duplicate_of,
                                "latency_ms": round(baseline_ms, 3)}
                if not args.rules_only:
                    report_id, _ = store.submit_report(report,
                        hashlib.sha256(f"evaluation:{case['id']}".encode()).hexdigest())
                    report_ids[case["id"]] = report_id
                    started = time.perf_counter()
                    # Earlier failed jobs can become eligible again. Drain only
                    # until this report has had its own attempt, never assign
                    # a previous report's result to the current evaluation row.
                    for _ in range(12):
                        state = store.case_view(report_id)["report"]["analysis_state"]
                        if state not in {"queued", "running"}:
                            break
                        if not worker.process_one("frozen-eval-worker"):
                            break
                    elapsed = (time.perf_counter() - started) * 1000
                    view = store.case_view(report_id)
                    if view["proposal"]:
                        proposal = view["proposal"]["content"]
                        suggested = view["duplicates"][0]["candidate_report_id"] if view["duplicates"] else None
                        row["semantic"] = {
                            "valid": True,
                            "category_ids": proposal["category_ids"],
                            "outcome": proposal["outcome"],
                            "urgent": bool(view["safety"]["urgent_review"]),
                            "duplicate_of": suggested,
                            "source_count": len(proposal["sources"]),
                            "latency_ms": round(elapsed, 3),
                        }
                    else:
                        row["semantic"] = {"valid": False, "category_ids": [], "outcome": "unavailable",
                                           "urgent": bool(view["safety"]["urgent_review"]),
                                           "duplicate_of": None, "source_count": 0,
                                           "latency_ms": round(elapsed, 3)}
                        with database._connection() as connection:
                            job = connection.execute("SELECT last_error FROM triage_jobs WHERE report_id=?", (report_id,)).fetchone()
                        row["semantic_error"] = {"state": view["report"]["analysis_state"],
                                                 "last_error": job["last_error"] if job else None}
                else:
                    row["semantic"] = None
                earlier.append({"id": len(earlier) + 1, "title": report.title,
                                "description": report.description, "city": report.city,
                                "district": report.district, "landmark": report.landmark})
                rows.append(row)
                print(f"{case['id']}: rules={row['rules']['category_ids']} semantic={row['semantic']['category_ids'] if row['semantic'] else 'not_run'}", flush=True)
        finally:
            database.DATA_DIR, database.DB_PATH = original_data, original_db
    result = {"dataset_sha256": hashlib.sha256(payload).hexdigest(),
              "review_status": dataset["review_status"], "model_run": not args.rules_only,
              "run_config": {"triage_model": os.getenv("TRIAGE_MODEL", "qwen3:4b-instruct"),
                             "embedding_model": os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
                             "catalog_version": catalog()["version"], "prompt_version": PROMPT_VERSION,
                             "schema_version": SCHEMA_VERSION, "source_set_version": source_set_version(),
                             "source_relevance_threshold": float(os.getenv("SOURCE_RELEVANCE_THRESHOLD", "0.80"))},
              "rules_summary": _summary(rows, "rules"),
              "semantic_summary": _summary(rows, "semantic") if not args.rules_only else None,
              "cases": rows,
              "limitations": ["Synthetic author labels; independent domain review pending",
                              "One run per case; model timings include local retrieval and embeddings",
                              "Staff correction rate and claim-level source support require human review"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
