from __future__ import annotations

import unittest

from balagh.core import (
    ReportInput,
    report_similarity,
    triage_report,
)


class TriageTests(unittest.TestCase):
    def test_road_issue_classification(self) -> None:
        report = ReportInput(
            title="حفرة في الشارع",
            description="حفرة كبيرة منذ يومين تسبب انحراف السيارات",
            city="الرياض",
            district="الروابي",
            landmark="بجوار الحديقة",
        )
        result = triage_report(report, existing_reports=[], language="Arabic")
        self.assertEqual(result.category, "Roads & Sidewalks")
        self.assertIn(result.priority, {"Medium", "High"})

    def test_critical_warning(self) -> None:
        report = ReportInput(
            title="سلك مكشوف",
            description="سلك كهرباء مكشوف بجوار الممر",
            city="الرياض",
            district="الملز",
        )
        result = triage_report(report, existing_reports=[], language="Arabic")
        self.assertEqual(result.priority, "Critical")
        self.assertIsNotNone(result.emergency_warning)

    def test_duplicate_similarity(self) -> None:
        score = report_similarity(
            "حفرة كبيرة في الشارع",
            "حفرة تسبب انحراف السيارات بجوار الحديقة",
            "الرياض",
            "الروابي",
            "بلاغ عن حفرة في الطريق",
            "حفرة كبيرة قرب الحديقة وتؤثر على السيارات",
            "الرياض",
            "الروابي",
        )
        self.assertGreater(score, 0.55)


if __name__ == "__main__":
    unittest.main()
