from __future__ import annotations

import tempfile
import sqlite3
from contextlib import closing
import unittest
from pathlib import Path
from unittest.mock import patch

import balagh.database as database
from balagh.triage import ReportInput, triage_report


class DatabaseTests(unittest.TestCase):
    def test_v3_migration_preserves_legacy_report_and_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir)
            db_path = path / "legacy.db"
            with closing(sqlite3.connect(db_path)) as connection:
                connection.executescript("""
                    CREATE TABLE reports (
                        id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT,
                        title TEXT NOT NULL, description TEXT NOT NULL, city TEXT NOT NULL,
                        district TEXT NOT NULL, landmark TEXT, category TEXT NOT NULL,
                        priority TEXT NOT NULL, department TEXT NOT NULL,
                        category_confidence TEXT NOT NULL DEFAULT 'None', category_evidence TEXT,
                        status TEXT NOT NULL DEFAULT 'Open', duplicate_of INTEGER,
                        duplicate_score REAL NOT NULL DEFAULT 0, reasoning TEXT NOT NULL,
                        missing_information TEXT, acknowledgment TEXT NOT NULL,
                        emergency_warning TEXT, language TEXT NOT NULL,
                        attachment_path TEXT, tracking_token_hash TEXT
                    );
                    CREATE TABLE agent_recommendations (
                        id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL, created_at TEXT NOT NULL,
                        triage_review TEXT NOT NULL, coordinator_review TEXT NOT NULL,
                        final_recommendation TEXT NOT NULL, decision TEXT NOT NULL,
                        reviewer_note TEXT, reviewed_at TEXT, workflow_name TEXT NOT NULL DEFAULT 'legacy',
                        validation_notes TEXT, source_citations TEXT, source_evidence TEXT,
                        workflow_thread_id TEXT, agent_route TEXT, tool_calls TEXT,
                        workflow_resume_status TEXT NOT NULL DEFAULT 'not_applicable'
                    );
                    CREATE TABLE case_history (id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL,
                        created_at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, details TEXT);
                    INSERT INTO reports (id,created_at,title,description,city,district,category,
                        priority,department,reasoning,acknowledgment,language)
                    VALUES (7,'2026-08-27','قديم','نص قديم','الرياض','الملز',
                        'Roads & Sidewalks','Medium','Road and Sidewalk Maintenance','old rules','received','Arabic');
                    INSERT INTO agent_recommendations (id,report_id,created_at,triage_review,
                        coordinator_review,final_recommendation,decision,reviewer_note)
                    VALUES (3,7,'2026-08-27','audit','plan','old proposal','Rejected','reviewed before migration');
                """)
            with patch.object(database, "DATA_DIR", path), patch.object(database, "DB_PATH", db_path):
                database.init_db()
                self.assertEqual(database.get_report(7)["category"], "Roads & Sidewalks")
                self.assertEqual(database.get_report(7)["intake_mode"], "legacy")
                self.assertEqual(database.get_agent_recommendation(7)["decision"], "Rejected")
                with database._connection() as connection:
                    self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM staff_decisions").fetchone()[0], 0)

    def test_report_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with (
                patch.object(database, "DATA_DIR", temp_path),
                patch.object(database, "DB_PATH", temp_path / "test.db"),
            ):
                database.init_db()
                report = ReportInput(
                    title="نفايات بجوار الحديقة",
                    description="توجد 5 أكياس نفايات متراكمة منذ يومين بجوار الحديقة",
                    city="الرياض",
                    district="الروابي",
                    landmark="بجوار الحديقة",
                )
                result = triage_report(report, [], "Arabic")
                report_id = database.create_report(report, result, "Arabic")

                stored = database.get_report(report_id)
                self.assertIsNotNone(stored)
                self.assertEqual(stored["title"], report.title)
                self.assertEqual(stored["status"], "Open")
                self.assertEqual(stored["category_confidence"], result.category_confidence)
                self.assertIn("نفايات", stored["category_evidence"])

                history = database.get_case_history(report_id)
                self.assertEqual(len(history), 1)
                self.assertEqual(history.iloc[0]["action"], "Report created")

    def test_report_can_be_found_by_tracking_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with (
                patch.object(database, "DATA_DIR", temp_path),
                patch.object(database, "DB_PATH", temp_path / "test.db"),
            ):
                database.init_db()
                report = ReportInput(
                    title="إنارة شارع متوقفة",
                    description="ثلاثة أعمدة إنارة متوقفة منذ يومين",
                    city="الرياض",
                    district="الروابي",
                    landmark="قرب المسجد",
                )
                result = triage_report(report, [], "Arabic")
                token_hash = "example-tracking-hash"
                report_id = database.create_report(
                    report,
                    result,
                    "Arabic",
                    tracking_token_hash=token_hash,
                )

                stored = database.get_report_by_tracking_hash(token_hash)
                self.assertIsNotNone(stored)
                self.assertEqual(stored["id"], report_id)
                self.assertIsNone(database.get_report_by_tracking_hash("wrong-hash"))

    def test_recommendation_persists_workflow_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with (
                patch.object(database, "DATA_DIR", temp_path),
                patch.object(database, "DB_PATH", temp_path / "test.db"),
            ):
                database.init_db()
                report = ReportInput(
                    title="لوحة سرعة مفقودة",
                    description="لا توجد لوحة تحدد السرعة على الطريق",
                    city="الرياض",
                    district="الملز",
                    landmark="طريق عبدالله",
                )
                result = triage_report(report, [], "Arabic")
                report_id = database.create_report(report, result, "Arabic")
                database.save_agent_recommendation(
                    report_id,
                    "audit",
                    "plan",
                    "recommendation",
                    workflow_thread_id="thread-test",
                    agent_route="traffic_safety",
                    tool_calls="load_case_record | retrieve_official_guidance",
                )

                stored = database.get_agent_recommendation(report_id)
                self.assertEqual(stored["workflow_thread_id"], "thread-test")
                self.assertEqual(stored["agent_route"], "traffic_safety")
                self.assertEqual(stored["workflow_resume_status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
