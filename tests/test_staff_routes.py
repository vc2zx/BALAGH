from __future__ import annotations

import os
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import balagh.database as database
from balagh import create_app
from balagh.triage import ReportInput, triage_report


@unittest.skipUnless(find_spec("flask"), "Flask is not installed in this test environment")
class StaffRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.data_patch = patch.object(database, "DATA_DIR", self.temp_path)
        self.db_patch = patch.object(database, "DB_PATH", self.temp_path / "test.db")
        self.env_patch = patch.dict(os.environ, {"STAFF_ACCESS_CODE": "202608"})
        self.data_patch.start()
        self.db_patch.start()
        self.env_patch.start()

        self.app = create_app({"TESTING": True, "SECRET_KEY": "test-secret"})
        self.client = self.app.test_client()
        self.report_id = self._create_report(
            "حفرة في الطريق",
            "حفرة كبيرة منذ يومين أمام المنزل رقم 12 وتعيق السيارات",
            "الرياض",
            "الروابي",
        )

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.db_patch.stop()
        self.data_patch.stop()
        self.temp_dir.cleanup()

    def _create_report(self, title: str, description: str, city: str, district: str) -> int:
        report = ReportInput(
            title=title,
            description=description,
            city=city,
            district=district,
        )
        result = triage_report(report, database.get_open_reports(), "Arabic")
        return database.create_report(report, result, "Arabic")

    def _login(self, code: str = "202608", follow_redirects: bool = False):
        return self.client.post(
            "/staff/login",
            data={"access_code": code},
            follow_redirects=follow_redirects,
        )

    def test_staff_pages_require_login(self) -> None:
        response = self.client.get("/staff/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/staff/login", response.headers["Location"])

    def test_wrong_access_code_is_rejected(self) -> None:
        response = self._login("wrong", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("رمز الوصول غير صحيح".encode(), response.data)

    def test_staff_can_login_and_view_dashboard(self) -> None:
        response = self._login(follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("لوحة التحكم".encode(), response.data)
        self.assertIn("حفرة في الطريق".encode(), response.data)

    def test_report_search_filters_results(self) -> None:
        self._create_report(
            "عمود إنارة متوقف",
            "ثلاثة أعمدة إنارة متوقفة منذ ثلاثة أيام بجوار المدرسة",
            "جدة",
            "الصفا",
        )
        self._login()

        response = self.client.get("/staff/reports?q=حفرة")
        self.assertEqual(response.status_code, 200)
        self.assertIn("حفرة في الطريق".encode(), response.data)
        self.assertNotIn("عمود إنارة متوقف".encode(), response.data)

        by_number = self.client.get(f"/staff/reports?q=BLG-{self.report_id:05d}")
        self.assertEqual(by_number.status_code, 200)
        self.assertIn("حفرة في الطريق".encode(), by_number.data)

    def test_staff_can_update_status_and_history(self) -> None:
        self._login()
        response = self.client.post(
            f"/staff/reports/{self.report_id}/status",
            data={"status": "In Progress"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("تم تحديث الحالة".encode(), response.data)
        self.assertEqual(database.get_report(self.report_id)["status"], "In Progress")
        actions = set(database.get_case_history(self.report_id)["action"].tolist())
        self.assertIn("Status changed", actions)

    def test_staff_can_retriage_a_stale_speed_sign_report(self) -> None:
        report_id = self._create_report(
            "there's no speed limit sign",
            "the speed limit in this road is unknown",
            "riyadh",
            "al malaz",
        )
        with database._connection() as connection:
            connection.execute(
                """
                UPDATE reports
                SET category = 'General Community Services',
                    priority = 'Low',
                    department = 'General Service Coordination'
                WHERE id = ?
                """,
                (report_id,),
            )
            connection.commit()

        self._login()
        response = self.client.post(
            f"/staff/reports/{report_id}/retriage",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("أُعيد فرز البلاغ".encode(), response.data)
        stored = database.get_report(report_id)
        self.assertEqual(stored["category"], "Traffic Signs & Road Safety")
        self.assertEqual(stored["priority"], "Medium")
        self.assertEqual(stored["department"], "Traffic Signs and Road Safety")
        actions = set(database.get_case_history(report_id)["action"].tolist())
        self.assertIn("Triage recalculated", actions)

    def test_agent_recommendation_can_be_generated_and_reviewed(self) -> None:
        self._login()
        fake = SimpleNamespace(
            triage_review="مراجعة الفرز",
            coordinator_review="مراجعة التنسيق",
            final_recommendation="التوصية النهائية",
        )

        with patch("balagh.staff_routes._generate_recommendation", return_value=fake):
            response = self.client.post(
                f"/staff/reports/{self.report_id}/recommendations",
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("تم إنشاء التوصية".encode(), response.data)
        stored = database.get_agent_recommendation(self.report_id)
        self.assertEqual(stored["decision"], "Pending")

        response = self.client.post(
            f"/staff/reports/{self.report_id}/recommendations/{stored['id']}/review",
            data={"decision": "Modified", "reviewer_note": "تحقق ميداني أولًا."},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("تم تسجيل قرار الموظف".encode(), response.data)
        self.assertEqual(
            database.get_agent_recommendation(self.report_id)["decision"],
            "Modified",
        )

    def test_modified_recommendation_requires_note_in_staff_portal(self) -> None:
        self._login()
        recommendation_id = database.save_agent_recommendation(
            self.report_id,
            "مراجعة الفرز",
            "مراجعة التنسيق",
            "التوصية النهائية",
        )

        response = self.client.post(
            f"/staff/reports/{self.report_id}/recommendations/{recommendation_id}/review",
            data={"decision": "Modified", "reviewer_note": ""},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("اكتب ملاحظة".encode(), response.data)
        self.assertEqual(
            database.get_agent_recommendation(self.report_id)["decision"],
            "Pending",
        )

    def test_logout_clears_staff_session(self) -> None:
        self._login()
        response = self.client.post("/staff/logout")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/staff/login"))
        self.assertEqual(self.client.get("/staff/").status_code, 302)


if __name__ == "__main__":
    unittest.main()
