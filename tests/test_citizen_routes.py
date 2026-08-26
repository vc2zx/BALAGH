from __future__ import annotations

import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

import balagh.database as database
from balagh import create_app


@unittest.skipUnless(find_spec("flask"), "Flask is not installed in this test environment")
class CitizenRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.data_patch = patch.object(database, "DATA_DIR", self.temp_path)
        self.db_patch = patch.object(database, "DB_PATH", self.temp_path / "test.db")
        self.data_patch.start()
        self.db_patch.start()

        self.app = create_app({"TESTING": True, "SECRET_KEY": "test-secret"})
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.data_patch.stop()
        self.temp_dir.cleanup()

    def test_home_page_is_available(self) -> None:
        response = self.client.get("/citizen/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("إرسال بلاغ".encode(), response.data)

    def test_required_fields_are_validated(self) -> None:
        response = self.client.post("/citizen/", data={})
        self.assertEqual(response.status_code, 200)
        self.assertIn("حقل عنوان البلاغ مطلوب".encode(), response.data)
        self.assertTrue(database.get_reports().empty)

    def test_report_can_be_submitted_and_tracked(self) -> None:
        response = self.client.post(
            "/citizen/",
            data={
                "title": "حفرة في الشارع",
                "description": "حفرة كبيرة منذ يومين تسبب انحراف السيارات وعددها 1",
                "city": "الرياض",
                "district": "الروابي",
                "landmark": "بجوار الحديقة",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("احتفظ برمز المتابعة".encode(), response.data)

        with self.client.session_transaction() as user_session:
            tracking_code = user_session["last_submission"]["tracking_code"]

        tracked = self.client.post(
            "/citizen/track",
            data={"tracking_code": tracking_code.lower()},
        )
        self.assertEqual(tracked.status_code, 200)
        self.assertIn("حفرة في الشارع".encode(), tracked.data)
        self.assertIn("مفتوح".encode(), tracked.data)

    def test_numeric_report_id_is_not_a_tracking_code(self) -> None:
        response = self.client.post(
            "/citizen/track",
            data={"tracking_code": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("لم يتم العثور على بلاغ بهذا الرمز".encode(), response.data)


if __name__ == "__main__":
    unittest.main()
