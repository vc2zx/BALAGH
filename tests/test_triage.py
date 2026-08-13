from __future__ import annotations

import unittest

from balagh.triage import ReportInput, report_similarity, triage_report


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

    def test_critical_warning_is_deterministic(self) -> None:
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

    def test_different_city_has_zero_similarity(self) -> None:
        score = report_similarity(
            "حفرة في الشارع", "حفرة كبيرة", "الرياض", "الروابي",
            "حفرة في الشارع", "حفرة كبيرة", "جدة", "الروابي",
        )
        self.assertEqual(score, 0.0)

    def test_unrelated_reports_same_district_are_not_duplicates(self) -> None:
        score = report_similarity(
            "حفرة كبيرة في الشارع",
            "حفرة في الطريق تسبب انحراف السيارات منذ يومين",
            "الرياض",
            "الروابي",
            "نفايات بجوار الحديقة",
            "خمسة أكياس نفايات متراكمة قرب الحديقة منذ يوم",
            "الرياض",
            "الروابي",
        )
        self.assertLess(score, 0.64)

    def test_same_issue_different_district_is_not_duplicate(self) -> None:
         score = report_similarity(
            "حفرة كبيرة في الشارع",
            "حفرة كبيرة تسبب انحراف السيارات منذ يومين",
            "الرياض",
            "الروابي",
            "حفرة كبيرة في الشارع",
            "حفرة كبيرة تسبب انحراف السيارات منذ يومين",
            "الرياض",
            "الملز",
        )
         self.assertEqual(score, 0.0)

if __name__ == "__main__":
    unittest.main()
