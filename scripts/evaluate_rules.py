"""Measure the deterministic baseline on held-out synthetic Arabic cases.

Run from the repository root: .venv/Scripts/python scripts/evaluate_rules.py
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from balagh.triage import CATEGORY_RULES, ReportInput, triage_report


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evaluation" / "arabic_cases.json"


def ratio(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator}" if denominator else "n/a (0 cases)"


def main() -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    rows = []
    for case in cases:
        report = ReportInput(*(case[key] for key in ("title", "description", "city", "district", "landmark")))
        started = time.perf_counter_ns()
        result = triage_report(report, case.get("existing", []), "Arabic")
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        rows.append({
            "id": case["id"], "expected_category": case["category"],
            "actual_category": result.category,
            "expected_route": ("Triage Review Queue" if case["category"] == "Needs Human Classification" else
                               CATEGORY_RULES[case["category"]]["department"]),
            "actual_route": result.department,
            "expected_urgent": case["urgent"], "actual_urgent": result.priority == "Critical",
            "expected_duplicate": case["duplicate"], "actual_duplicate": result.duplicate_of is not None,
            "elapsed_ms": elapsed_ms,
        })
    total = len(rows)
    category_ok = sum(row["expected_category"] == row["actual_category"] for row in rows)
    route_ok = sum(row["expected_route"] == row["actual_route"] for row in rows)
    urgent_tp = sum(row["expected_urgent"] and row["actual_urgent"] for row in rows)
    urgent_fp = sum(not row["expected_urgent"] and row["actual_urgent"] for row in rows)
    urgent_count = sum(row["expected_urgent"] for row in rows)
    duplicate_tp = sum(row["expected_duplicate"] and row["actual_duplicate"] for row in rows)
    duplicate_fp = sum(not row["expected_duplicate"] and row["actual_duplicate"] for row in rows)
    duplicate_count = sum(row["expected_duplicate"] for row in rows)
    ambiguous = [row for row in rows if row["expected_category"] == "Needs Human Classification"]
    abstained = sum(row["actual_category"] == "Needs Human Classification" for row in ambiguous)
    latencies = sorted(row["elapsed_ms"] for row in rows)
    print(f"Cases: {total}; category: {ratio(category_ok, total)}; route: {ratio(route_ok, total)}")
    print(f"Urgent recall: {ratio(urgent_tp, urgent_count)}; false-positive rate: {ratio(urgent_fp, total - urgent_count)}")
    print(f"Duplicate precision: {ratio(duplicate_tp, duplicate_tp + duplicate_fp)}; recall: {ratio(duplicate_tp, duplicate_count)}")
    print(f"Ambiguous abstention: {ratio(abstained, len(ambiguous))}")
    print(f"Latency median: {statistics.median(latencies):.3f} ms; p95 nearest-rank: {latencies[max(0, (95 * total + 99) // 100 - 1)]:.3f} ms")
    for row in rows:
        if any((row["expected_category"] != row["actual_category"], row["expected_route"] != row["actual_route"],
                row["expected_urgent"] != row["actual_urgent"], row["expected_duplicate"] != row["actual_duplicate"])):
            print(f"ERROR {row['id']}: category {row['expected_category']} -> {row['actual_category']}; "
                  f"urgent {row['expected_urgent']} -> {row['actual_urgent']}; "
                  f"duplicate {row['expected_duplicate']} -> {row['actual_duplicate']}")


if __name__ == "__main__":
    main()
