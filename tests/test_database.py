from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import balagh.database as database
from balagh.triage import ReportInput, triage_report


class DatabaseTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
