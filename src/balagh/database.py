from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from balagh.triage import ReportInput, TriageResult, report_similarity


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "balagh.db"
ALLOWED_STATUSES = {"Open", "In Progress", "Resolved", "Closed"}
ALLOWED_REVIEW_DECISIONS = {"Approved", "Modified", "Rejected"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def _connection():
    """Open a SQLite connection and always close the file handle."""
    connection = _connect()
    try:
        yield connection
    finally:
        connection.close()


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def init_db() -> None:
    """Create the V2 schema and add missing columns to a V1 database."""
    with _connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                city TEXT NOT NULL,
                district TEXT NOT NULL,
                landmark TEXT,
                category TEXT NOT NULL,
                priority TEXT NOT NULL,
                department TEXT NOT NULL,
                category_confidence TEXT NOT NULL DEFAULT 'None',
                category_evidence TEXT,
                status TEXT NOT NULL DEFAULT 'Open',
                duplicate_of INTEGER,
                duplicate_score REAL NOT NULL DEFAULT 0,
                reasoning TEXT NOT NULL,
                missing_information TEXT,
                acknowledgment TEXT NOT NULL,
                emergency_warning TEXT,
                language TEXT NOT NULL,
                attachment_path TEXT,
                tracking_token_hash TEXT
            )
            """
        )

        _ensure_column(connection, "reports", "updated_at", "TEXT")
        _ensure_column(connection, "reports", "attachment_path", "TEXT")
        _ensure_column(connection, "reports", "tracking_token_hash", "TEXT")
        _ensure_column(
            connection,
            "reports",
            "category_confidence",
            "TEXT NOT NULL DEFAULT 'None'",
        )
        _ensure_column(connection, "reports", "category_evidence", "TEXT")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_tracking_token_hash
            ON reports(tracking_token_hash)
            WHERE tracking_token_hash IS NOT NULL
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                triage_review TEXT NOT NULL,
                coordinator_review TEXT NOT NULL,
                final_recommendation TEXT NOT NULL,
                decision TEXT NOT NULL DEFAULT 'Pending',
                reviewer_note TEXT,
                reviewed_at TEXT,
                workflow_name TEXT NOT NULL DEFAULT 'legacy',
                validation_notes TEXT,
                source_citations TEXT,
                workflow_thread_id TEXT,
                agent_route TEXT,
                tool_calls TEXT,
                workflow_resume_status TEXT NOT NULL DEFAULT 'not_applicable',
                FOREIGN KEY(report_id) REFERENCES reports(id)
            )
            """
        )
        _ensure_column(
            connection,
            "agent_recommendations",
            "workflow_name",
            "TEXT NOT NULL DEFAULT 'legacy'",
        )
        _ensure_column(connection, "agent_recommendations", "validation_notes", "TEXT")
        _ensure_column(connection, "agent_recommendations", "source_citations", "TEXT")
        _ensure_column(connection, "agent_recommendations", "workflow_thread_id", "TEXT")
        _ensure_column(connection, "agent_recommendations", "agent_route", "TEXT")
        _ensure_column(connection, "agent_recommendations", "tool_calls", "TEXT")
        _ensure_column(
            connection,
            "agent_recommendations",
            "workflow_resume_status",
            "TEXT NOT NULL DEFAULT 'not_applicable'",
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS case_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT,
                FOREIGN KEY(report_id) REFERENCES reports(id)
            )
            """
        )
        connection.commit()


def record_case_action(
    report_id: int,
    actor: str,
    action: str,
    details: str = "",
) -> None:
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO case_history (report_id, created_at, actor, action, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (report_id, _now(), actor, action, details),
        )
        connection.commit()


def create_report(
    report: ReportInput,
    result: TriageResult,
    language: str = "Arabic",
    attachment_path: str | None = None,
    tracking_token_hash: str | None = None,
) -> int:
    now = _now()
    with _connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO reports (
                created_at, updated_at, title, description, city, district,
                landmark, category, priority, department,
                category_confidence, category_evidence, status,
                duplicate_of, duplicate_score, reasoning, missing_information,
                acknowledgment, emergency_warning, language, attachment_path,
                tracking_token_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Open', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                report.title,
                report.description,
                report.city,
                report.district,
                report.landmark,
                result.category,
                result.priority,
                result.department,
                result.category_confidence,
                " | ".join(result.category_evidence),
                result.duplicate_of,
                result.duplicate_score,
                result.reasoning,
                " | ".join(result.missing_information),
                result.acknowledgment,
                result.emergency_warning,
                language,
                attachment_path,
                tracking_token_hash,
            ),
        )
        report_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO case_history (report_id, created_at, actor, action, details)
            VALUES (?, ?, 'system', 'Report created', ?)
            """,
            (report_id, now, "Initial deterministic triage completed."),
        )
        connection.commit()
        return report_id


def get_report(report_id: int) -> dict[str, Any] | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()
    return dict(row) if row else None


def get_report_by_tracking_hash(tracking_token_hash: str) -> dict[str, Any] | None:
    """Return a report using its non-public tracking-token hash."""
    if not tracking_token_hash:
        return None

    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM reports WHERE tracking_token_hash = ?",
            (tracking_token_hash,),
        ).fetchone()
    return dict(row) if row else None


def get_reports(limit: int = 500) -> pd.DataFrame:
    with _connection() as connection:
        return pd.read_sql_query(
            """
            SELECT
                id, created_at, updated_at, title, city, district, category,
                priority, department, status, duplicate_of,
                ROUND(duplicate_score, 3) AS duplicate_score
            FROM reports
            ORDER BY id DESC
            LIMIT ?
            """,
            connection,
            params=(limit,),
        )


def get_open_reports() -> list[dict[str, Any]]:
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT id, title, description, city, district
            FROM reports
            WHERE status IN ('Open', 'In Progress')
            ORDER BY id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def update_report_status(
    report_id: int,
    status: str,
    actor: str = "staff",
) -> bool:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Unsupported status: {status}")

    with _connection() as connection:
        previous = connection.execute(
            "SELECT status FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        if previous is None:
            return False

        connection.execute(
            "UPDATE reports SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), report_id),
        )
        connection.execute(
            """
            INSERT INTO case_history (report_id, created_at, actor, action, details)
            VALUES (?, ?, ?, 'Status changed', ?)
            """,
            (report_id, _now(), actor, f"{previous['status']} → {status}"),
        )
        connection.commit()
        return True


def update_report_triage(
    report_id: int,
    result: TriageResult,
    actor: str = "staff",
) -> bool:
    """Apply a human-triggered recalculation using the current deterministic rules."""
    with _connection() as connection:
        previous = connection.execute(
            "SELECT category, priority, department FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        if previous is None:
            return False

        now = _now()
        connection.execute(
            """
            UPDATE reports
            SET category = ?,
                priority = ?,
                department = ?,
                category_confidence = ?,
                category_evidence = ?,
                duplicate_of = ?,
                duplicate_score = ?,
                reasoning = ?,
                missing_information = ?,
                acknowledgment = ?,
                emergency_warning = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                result.category,
                result.priority,
                result.department,
                result.category_confidence,
                " | ".join(result.category_evidence),
                result.duplicate_of,
                result.duplicate_score,
                result.reasoning,
                " | ".join(result.missing_information),
                result.acknowledgment,
                result.emergency_warning,
                now,
                report_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO case_history (report_id, created_at, actor, action, details)
            VALUES (?, ?, ?, 'Triage recalculated', ?)
            """,
            (
                report_id,
                now,
                actor,
                f"{previous['category']} / {previous['priority']} → "
                f"{result.category} / {result.priority}",
            ),
        )
        connection.commit()
        return True


def summary_metrics() -> dict[str, int]:
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN priority = 'Critical' THEN 1 ELSE 0 END) AS critical,
                SUM(CASE WHEN duplicate_of IS NOT NULL THEN 1 ELSE 0 END) AS duplicates,
                SUM(CASE WHEN status IN ('Resolved', 'Closed') THEN 1 ELSE 0 END) AS closed
            FROM reports
            """
        ).fetchone()

        pending_row = connection.execute(
            """
            SELECT COUNT(*) AS pending
            FROM agent_recommendations
            WHERE decision = 'Pending'
            """
        ).fetchone()

    return {
        "total": int(row["total"] or 0),
        "critical": int(row["critical"] or 0),
        "duplicates": int(row["duplicates"] or 0),
        "closed": int(row["closed"] or 0),
        "pending_ai": int(pending_row["pending"] or 0),
    }


def find_similar_reports(report_id: int, limit: int = 5) -> list[dict[str, Any]]:
    target = get_report(report_id)
    if target is None:
        return []

    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT id, title, description, city, district, status
            FROM reports
            WHERE id != ?
            """,
            (report_id,),
        ).fetchall()

    scored: list[dict[str, Any]] = []
    for row in rows:
        score = report_similarity(
            target["title"],
            target["description"],
            target["city"],
            target["district"],
            row["title"],
            row["description"],
            row["city"],
            row["district"],
        )
        if score <= 0:
            continue
        item = dict(row)
        item["similarity"] = round(score, 4)
        scored.append(item)

    scored.sort(key=lambda item: item["similarity"], reverse=True)
    return scored[:limit]


def get_human_decision_memory(
    report_id: int,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return concise reviewer feedback from earlier decisions in the same category."""
    report = get_report(report_id)
    if report is None:
        return []

    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT
                ar.report_id,
                ar.decision,
                ar.reviewer_note,
                ar.reviewed_at
            FROM agent_recommendations AS ar
            JOIN reports AS r ON r.id = ar.report_id
            WHERE r.category = ?
              AND ar.decision IN ('Modified', 'Rejected')
              AND TRIM(COALESCE(ar.reviewer_note, '')) != ''
            ORDER BY ar.reviewed_at DESC
            LIMIT ?
            """,
            (report["category"], limit),
        ).fetchall()
    return [dict(row) for row in rows]


def save_agent_recommendation(
    report_id: int,
    triage_review: str,
    coordinator_review: str,
    final_recommendation: str,
    workflow_name: str = "langgraph-functional-capstone-v2",
    validation_notes: str = "",
    source_citations: str = "",
    workflow_thread_id: str = "",
    agent_route: str = "",
    tool_calls: str = "",
) -> int:
    if get_report(report_id) is None:
        raise ValueError(f"Report #{report_id} does not exist.")

    now = _now()

    with _connection() as connection:
        pending = connection.execute(
            """
            SELECT id
            FROM agent_recommendations
            WHERE report_id = ?
              AND decision = 'Pending'
            ORDER BY id DESC
            LIMIT 1
            """,
            (report_id,),
        ).fetchone()

        if pending is not None:
            raise ValueError(
                f"Report #{report_id} already has a pending AI recommendation."
            )

        cursor = connection.execute(
            """
            INSERT INTO agent_recommendations (
                report_id,
                created_at,
                triage_review,
                coordinator_review,
                final_recommendation,
                decision,
                workflow_name,
                validation_notes,
                source_citations,
                workflow_thread_id,
                agent_route,
                tool_calls,
                workflow_resume_status
            )
            VALUES (?, ?, ?, ?, ?, 'Pending', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                now,
                triage_review,
                coordinator_review,
                final_recommendation,
                workflow_name,
                validation_notes,
                source_citations,
                workflow_thread_id or None,
                agent_route or None,
                tool_calls or None,
                "interrupted" if workflow_thread_id else "not_applicable",
            ),
        )

        recommendation_id = int(cursor.lastrowid)

        connection.execute(
            """
            INSERT INTO case_history (
                report_id,
                created_at,
                actor,
                action,
                details
            )
            VALUES (?, ?, 'AI', 'Recommendation generated', ?)
            """,
            (
                report_id,
                now,
                f"Recommendation #{recommendation_id} created for human review.",
            ),
        )

        connection.commit()
        return recommendation_id


def get_agent_recommendation(report_id: int) -> dict[str, Any] | None:
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM agent_recommendations
            WHERE report_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (report_id,),
        ).fetchone()

    return dict(row) if row else None


def review_agent_recommendation(
    recommendation_id: int,
    decision: str,
    reviewer_note: str = "",
    actor: str = "staff",
    workflow_resume_status: str = "completed",
) -> bool:
    if decision not in ALLOWED_REVIEW_DECISIONS:
        raise ValueError(f"Unsupported decision: {decision}")

    if decision == "Modified" and not reviewer_note.strip():
        raise ValueError(
            "A reviewer note is required when modifying a recommendation."
        )

    with _connection() as connection:
        recommendation = connection.execute(
            """
            SELECT report_id, decision
            FROM agent_recommendations
            WHERE id = ?
            """,
            (recommendation_id,),
        ).fetchone()

        if recommendation is None:
            return False

        if recommendation["decision"] != "Pending":
            raise ValueError(
                "This recommendation has already been reviewed."
            )

        now = _now()

        connection.execute(
            """
            UPDATE agent_recommendations
            SET decision = ?,
                reviewer_note = ?,
                reviewed_at = ?,
                workflow_resume_status = ?
            WHERE id = ?
            """,
            (
                decision,
                reviewer_note.strip(),
                now,
                workflow_resume_status,
                recommendation_id,
            ),
        )

        connection.execute(
            """
            INSERT INTO case_history (
                report_id,
                created_at,
                actor,
                action,
                details
            )
            VALUES (?, ?, ?, 'AI recommendation reviewed', ?)
            """,
            (
                int(recommendation["report_id"]),
                now,
                actor,
                f"Decision: {decision}. "
                f"Note: {reviewer_note.strip() or 'None'}",
            ),
        )

        connection.commit()
        return True


def get_case_history(report_id: int) -> pd.DataFrame:
    with _connection() as connection:
        return pd.read_sql_query(
            """
            SELECT created_at, actor, action, details
            FROM case_history
            WHERE report_id = ?
            ORDER BY id DESC
            """,
            connection,
            params=(report_id,),
        )
