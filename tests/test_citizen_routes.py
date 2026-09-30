from __future__ import annotations

import tempfile
from io import BytesIO
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch
from PIL import Image, PngImagePlugin

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
        self.client.get("/citizen/")
        with self.client.session_transaction() as user_session:
            self.nonce = user_session["submission_nonce"]

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
                "submission_nonce": self.nonce,
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
        self.assertNotIn("التصنيف بعد مراجعة الموظف".encode(), tracked.data)

    def test_repeated_submission_uses_one_report_and_tracking_code(self) -> None:
        payload = {"submission_nonce": self.nonce, "title": "رصيف تالف",
                   "description": "الرصيف متكسر قرب المنزل", "city": "الرياض", "district": "الروابي"}
        self.assertEqual(self.client.post("/citizen/", data=payload).status_code, 302)
        with self.client.session_transaction() as user_session:
            first_code = user_session["last_submission"]["tracking_code"]
        self.assertEqual(self.client.post("/citizen/", data=payload).status_code, 302)
        with self.client.session_transaction() as user_session:
            self.assertEqual(user_session["last_submission"]["tracking_code"], first_code)
        self.assertEqual(len(database.get_reports()), 1)

    def test_failed_report_creation_removes_uploaded_file(self) -> None:
        content = BytesIO()
        Image.new("RGB", (8, 8), "red").save(content, format="PNG")
        content.seek(0)
        with patch("balagh.citizen_routes.store.submit_report", side_effect=RuntimeError("database unavailable")):
            response = self.client.post("/citizen/", data={
                "submission_nonce": self.nonce, "title": "حفرة", "description": "حفرة في الشارع",
                "city": "الرياض", "district": "الروابي",
                "attachment": (content, "photo.png", "image/png"),
            }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(list((self.temp_path / "uploads").glob("*.png")))

    def test_numeric_report_id_is_not_a_tracking_code(self) -> None:
        response = self.client.post(
            "/citizen/track",
            data={"tracking_code": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("لم يتم العثور على بلاغ بهذا الرمز".encode(), response.data)

    def test_fake_image_content_is_rejected(self) -> None:
        response = self.client.post("/citizen/", data={
            "submission_nonce": self.nonce,
            "title": "حفرة في الطريق", "description": "حفرة كبيرة في الطريق قرب الحديقة",
            "city": "الرياض", "district": "الروابي",
            "attachment": (BytesIO(b"not a PNG"), "photo.png", "image/png"),
        }, content_type="multipart/form-data")
        self.assertIn("ملف الصورة غير صالح".encode(), response.data)
        self.assertTrue(database.get_reports().empty)

    def test_valid_image_is_reencoded_without_metadata(self) -> None:
        content = BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Comment", "synthetic private note")
        Image.new("RGB", (8, 8), "red").save(content, format="PNG", pnginfo=metadata)
        content.seek(0)
        response = self.client.post("/citizen/", data={
            "submission_nonce": self.nonce,
            "title": "حفرة في الطريق", "description": "حفرة كبيرة في الطريق قرب الحديقة",
            "city": "الرياض", "district": "الروابي",
            "attachment": (content, "photo.png", "image/png"),
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        report_id = int(database.get_reports().iloc[0]["id"])
        with Image.open(database.get_report(report_id)["attachment_path"]) as saved:
            self.assertEqual(saved.size, (8, 8))
            self.assertNotIn("Comment", saved.info)

    def test_csrf_required_when_enabled(self) -> None:
        self.app.config["CSRF_ENABLED"] = True
        response = self.client.post("/citizen/", data={"title": "example"})
        self.assertEqual(response.status_code, 400)
        self.client.get("/citizen/")
        with self.client.session_transaction() as user_session:
            token = user_session["csrf_token"]
        response = self.client.post("/citizen/", data={"_csrf_token": token})
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
