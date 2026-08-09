from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from balagh.core import ReportInput, TriageResult


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "balagh.db"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


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
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"
        )


def init_db() -> None:
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                city TEXT NOT NULL,
                district TEXT NOT NULL,
                landmark TEXT,
                category TEXT NOT NULL,
                priority TEXT NOT NULL,
                department TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Open',
                duplicate_of INTEGER,
                duplicate_score REAL NOT NULL DEFAULT 0,
                reasoning TEXT NOT NULL,
                missing_information TEXT,
                acknowledgment TEXT NOT NULL,
                emergency_warning TEXT,
                language TEXT NOT NULL,
                attachment_path TEXT
            )
            """
        )
        _ensure_column(
            connection,
            "reports",
            "attachment_path",
            "TEXT",
        )
        connection.commit()


def insert_report(
    report: ReportInput,
    result: TriageResult,
    language: str,
    attachment_path: str | None = None,
) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO reports (
                created_at,
                title,
                description,
                city,
                district,
                landmark,
                category,
                priority,
                department,
                status,
                duplicate_of,
                duplicate_score,
                reasoning,
                missing_information,
                acknowledgment,
                emergency_warning,
                language,
                attachment_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Open', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                report.title,
                report.description,
                report.city,
                report.district,
                report.landmark,
                result.category,
                result.priority,
                result.department,
                result.duplicate_of,
                result.duplicate_score,
                result.reasoning,
                " | ".join(result.missing_information),
                result.acknowledgment,
                result.emergency_warning,
                language,
                attachment_path,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def fetch_open_reports() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, title, description, city, district
            FROM reports
            WHERE status IN ('Open', 'In Progress')
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def fetch_reports(limit: int = 200) -> pd.DataFrame:
    with _connect() as connection:
        return pd.read_sql_query(
            """
            SELECT
                id,
                created_at,
                title,
                city,
                district,
                category,
                priority,
                department,
                status,
                duplicate_of,
                ROUND(duplicate_score, 3) AS duplicate_score
            FROM reports
            ORDER BY id DESC
            LIMIT ?
            """,
            connection,
            params=(limit,),
        )


def fetch_report_by_id(report_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM reports
            WHERE id = ?
            """,
            (report_id,),
        ).fetchone()

    return dict(row) if row else None


def update_status(report_id: int, status: str) -> bool:
    allowed = {"Open", "In Progress", "Resolved", "Closed"}
    if status not in allowed:
        raise ValueError(f"Unsupported status: {status}")

    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE reports SET status = ? WHERE id = ?",
            (status, report_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def summary_metrics() -> dict[str, int]:
    with _connect() as connection:
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

    return {
        "total": int(row["total"] or 0),
        "critical": int(row["critical"] or 0),
        "duplicates": int(row["duplicates"] or 0),
        "closed": int(row["closed"] or 0),
    }
