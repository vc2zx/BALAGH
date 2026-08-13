from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import balagh.database as database
from balagh.triage import ReportInput, triage_report


class WorkflowTests(unittest.TestCase):
    def test_human_review_workflow_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with (
                patch.object(database, "DATA_DIR", temp_path),
                patch.object(database, "DB_PATH", temp_path / "workflow.db"),
            ):
                database.init_db()
                report = ReportInput(
                    title="إنارة شارع لا تعمل",
                    description="ثلاثة أعمدة إنارة لا تعمل منذ يومين بجوار المدرسة",
                    city="الرياض",
                    district="الملز",
                    landmark="بجوار المدرسة",
                )
                result = triage_report(report, [], "Arabic")
                report_id = database.create_report(report, result, "Arabic")

                recommendation_id = database.save_agent_recommendation(
                    report_id,
                    "Triage review",
                    "Coordinator review",
                    "Recommended next action",
                )
                recommendation = database.get_agent_recommendation(report_id)
                self.assertEqual(recommendation["decision"], "Pending")

                reviewed = database.review_agent_recommendation(
                    recommendation_id,
                    "Modified",
                    "تحقق ميداني أولًا ثم أكمل الإجراء.",
                )
                self.assertTrue(reviewed)

                recommendation = database.get_agent_recommendation(report_id)
                self.assertEqual(recommendation["decision"], "Modified")

                changed = database.update_report_status(report_id, "In Progress")
                self.assertTrue(changed)
                self.assertEqual(database.get_report(report_id)["status"], "In Progress")

                history = database.get_case_history(report_id)
                actions = set(history["action"].tolist())
                self.assertIn("Report created", actions)
                self.assertIn("Recommendation generated", actions)
                self.assertIn("AI recommendation reviewed", actions)
                self.assertIn("Status changed", actions)

    def test_modified_recommendation_requires_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with (
                patch.object(database, "DATA_DIR", temp_path),
                patch.object(database, "DB_PATH", temp_path / "workflow.db"),
            ):
                database.init_db()
                report = ReportInput(
                    title="حفرة",
                    description="حفرة كبيرة منذ يوم في الطريق أمام المنزل رقم 12",
                    city="الرياض",
                    district="الروابي",
                )
                result = triage_report(report, [], "Arabic")
                report_id = database.create_report(report, result, "Arabic")
                recommendation_id = database.save_agent_recommendation(
                    report_id, "review", "coordination", "recommendation"
                )

                with self.assertRaises(ValueError):
                    database.review_agent_recommendation(
                        recommendation_id,
                        "Modified",
                        "",
                    )


if __name__ == "__main__":
    unittest.main()
