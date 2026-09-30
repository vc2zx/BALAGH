"""Configurable closed-case retention and orphaned upload cleanup."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from balagh import database


def expired_closed_cases(days: int, limit: int = 500) -> list[dict]:
    if days < 1:
        raise ValueError("Retention period must be positive")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with database._connection() as connection:
        rows = connection.execute("""SELECT id,attachment_path FROM reports
            WHERE status='Closed' AND COALESCE(updated_at,created_at) < ?
            ORDER BY id LIMIT ?""", (cutoff, min(limit, 500))).fetchall()
    return [dict(row) for row in rows]


def purge_expired(days: int, apply: bool = False) -> dict[str, int]:
    cases = expired_closed_cases(days)
    if not apply:
        return {"eligible_closed_cases": len(cases), "deleted_cases": 0, "orphan_uploads": 0}
    uploads = (database.DATA_DIR / "uploads").resolve()
    with database._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for case in cases:
            report_id = int(case["id"])
            connection.execute("DELETE FROM duplicate_candidates WHERE candidate_report_id=? OR proposal_id IN (SELECT id FROM triage_proposals WHERE report_id=?)", (report_id, report_id))
            for table in ("staff_decisions", "status_events", "triage_jobs", "safety_assessments",
                          "report_features", "agent_recommendations", "case_history", "triage_proposals"):
                connection.execute(f"DELETE FROM {table} WHERE report_id=?", (report_id,))
            connection.execute("DELETE FROM reports WHERE id=? AND status='Closed'", (report_id,))
        connection.commit()
    for case in cases:
        if case["attachment_path"]:
            path = Path(case["attachment_path"]).resolve()
            if uploads in path.parents:
                path.unlink(missing_ok=True)
    with database._connection() as connection:
        referenced = {Path(row[0]).resolve() for row in connection.execute(
            "SELECT attachment_path FROM reports WHERE attachment_path IS NOT NULL")}
    orphans = 0
    if uploads.is_dir():
        for path in uploads.iterdir():
            if path.is_file() and path.name != ".gitkeep" and path.resolve() not in referenced:
                path.unlink()
                orphans += 1
    return {"eligible_closed_cases": len(cases), "deleted_cases": len(cases), "orphan_uploads": orphans}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=int(os.getenv("BALAGH_RETENTION_DAYS", "365")))
    parser.add_argument("--apply", action="store_true", help="Actually delete eligible closed cases")
    args = parser.parse_args()
    database.init_db()
    print(purge_expired(args.days, args.apply))


if __name__ == "__main__":
    main()
