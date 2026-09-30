from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from balagh import create_app, database, store
from balagh.auth import create_user
from balagh.semantic import validate_proposal
from balagh.staff_routes import _format_datetime


class StaffRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.data_patch = patch.object(database, "DATA_DIR", self.path)
        self.db_patch = patch.object(database, "DB_PATH", self.path / "test.db")
        self.data_patch.start(); self.db_patch.start()
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test-secret", "RATE_LIMIT_ENABLED": False})
        self.client = self.app.test_client()
        self.admin_id = create_user("admin", "a-long-private-passphrase", "admin", [])
        self.reviewer_id = create_user("jeddah_reviewer", "another-private-passphrase", "reviewer", ["jeddah"])
        self.client.get("/citizen/")
        with self.client.session_transaction() as user_session:
            nonce = user_session["submission_nonce"]
        self.client.post("/citizen/", data={"submission_nonce": nonce, "title": "حفرة في الطريق",
            "description": "الشارع بعد الأمطار أصبح مليان حفريات", "city": "الرياض", "district": "الروابي"})
        with self.client.session_transaction() as user_session:
            self.tracking_code = user_session["last_submission"]["tracking_code"]
        self.report_id = 1

    def tearDown(self) -> None:
        self.db_patch.stop(); self.data_patch.stop(); self.temp.cleanup()

    def _login(self, username: str = "admin", password: str = "a-long-private-passphrase") -> None:
        result = self.client.post("/staff/login", data={"username": username, "password": password})
        self.assertEqual(result.status_code, 302)

    def _proposal(self) -> int:
        worker = "test-worker"
        self.assertEqual(store.claim_job(worker), self.report_id)
        raw = {"category_ids": ["waste_cleanliness"],
               "proposed_priority": "Medium", "rationale": "مقترح أولي يحتاج مراجعة الموظف",
               "evidence_spans": ["حفرة في الطريق"], "uncertainty_reason": "",
               "missing_information": [], "risk_signals": ["none"]}
        proposal = validate_proposal(raw, "حفرة في الطريق\nالشارع بعد الأمطار أصبح مليان حفريات", "riyadh")
        return store.complete_job(self.report_id, worker, proposal, "mock-model")

    def test_time_display_and_staff_authentication(self) -> None:
        self.assertEqual(_format_datetime("2026-08-27T06:16:00+00:00"), "2026-08-27 09:16")
        self.assertEqual(self.client.get("/staff/").status_code, 302)
        self._login()
        self.assertEqual(self.client.get("/staff/").status_code, 200)
        self.assertEqual(self.client.get("/staff/reports").status_code, 200)

    def test_jurisdiction_blocks_other_city(self) -> None:
        self._login("jeddah_reviewer", "another-private-passphrase")
        self.assertEqual(self.client.get(f"/staff/reports/{self.report_id}").status_code, 403)
        self.assertNotIn("حفرة في الطريق".encode(), self.client.get("/staff/reports").data)

    def test_staff_prefix_search_uses_bounded_indexed_page(self) -> None:
        found = store.search_reports({"q": "حفرة"}, None, page_size=1)
        self.assertEqual([row["id"] for row in found], [self.report_id])
        self.assertEqual(store.search_reports({"q": "الطريق"}, None), [])
        with database._connection() as connection:
            plan = " ".join(row[3] for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM reports WHERE "
                "((title>=? AND title<?) OR (city>=? AND city<?) OR (district>=? AND district<?)) "
                "ORDER BY id DESC LIMIT 26", ("حفرة", "حفرة\uffff") * 3))
        self.assertIn("MULTI-INDEX OR", plan)

    def test_semantic_proposal_and_human_correction_are_separate(self) -> None:
        proposal_id = self._proposal()
        self._login()
        page = self.client.get(f"/staff/reports/{self.report_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("حفرة في الطريق".encode(), page.data)
        response = self.client.post(f"/staff/reports/{self.report_id}/decision", data={
            "version": "0", "decision": "Corrected", "category_ids": "roads_sidewalks",
            "priority": "High", "review_queue": "roads_review", "risk_review": "unreviewed",
            "duplicate_decision": "unreviewed", "reason": "الوصف يشير إلى تلف الطريق."},
            follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        case = store.case_view(self.report_id)
        self.assertEqual(case["proposal"]["id"], proposal_id)
        self.assertEqual(case["proposal"]["status"], "Corrected")
        self.assertEqual(case["decision"]["category_ids"], ["roads_sidewalks"])
        self.assertEqual(case["decision"]["reviewer_name"], "admin")
        self.assertEqual(case["report"]["description"], "الشارع بعد الأمطار أصبح مليان حفريات")
        self.assertEqual(case["report"]["category"], "Needs Human Classification")
        tracked = self.client.post("/citizen/track", data={"tracking_code": self.tracking_code})
        self.assertIn("التصنيف بعد مراجعة الموظف".encode(), tracked.data)
        self.assertIn("الطرق والأرصفة".encode(), tracked.data)

    def test_repeated_review_and_stale_version_do_not_overwrite(self) -> None:
        self._proposal(); self._login()
        data = {"version": "0", "decision": "Approved", "category_ids": "waste_cleanliness",
                "priority": "Medium", "review_queue": "cleanliness_review", "risk_review": "unreviewed",
                "duplicate_decision": "unreviewed", "reason": ""}
        self.client.post(f"/staff/reports/{self.report_id}/decision", data=data)
        self.client.post(f"/staff/reports/{self.report_id}/decision", data=data)
        with database._connection() as connection:
            count = connection.execute("SELECT COUNT(*) FROM staff_decisions WHERE report_id=?",
                                       (self.report_id,)).fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(store.case_view(self.report_id)["report"]["version"], 1)

    def test_manual_failure_queue_cannot_be_approved_or_reviewed_twice(self) -> None:
        with database._connection() as connection:
            connection.execute("UPDATE reports SET analysis_state='needs_human' WHERE id=?", (self.report_id,))
            connection.commit()
        with self.assertRaises(ValueError):
            store.review(self.report_id, None, self.admin_id, 0, "Approved",
                         ["roads_sidewalks"], "Medium", "roads_review", "unreviewed",
                         "unreviewed", None, "")
        store.review(self.report_id, None, self.admin_id, 0, "Corrected",
                     ["roads_sidewalks"], "Medium", "roads_review", "unreviewed",
                     "unreviewed", None, "Manual classification after model failure")
        with self.assertRaises(ValueError):
            store.review(self.report_id, None, self.admin_id, 1, "Corrected",
                         ["waste_cleanliness"], "Medium", "cleanliness_review", "unreviewed",
                         "unreviewed", None, "Another classification")

    def test_pending_proposal_survives_app_restart(self) -> None:
        self._proposal()
        restarted = create_app({"TESTING": True, "SECRET_KEY": "another-test-key", "RATE_LIMIT_ENABLED": False})
        client = restarted.test_client()
        client.post("/staff/login", data={"username": "admin", "password": "a-long-private-passphrase"})
        self.assertIn("مقترح أولي".encode(), client.get(f"/staff/reports/{self.report_id}").data)

    def test_failed_persistence_rolls_back_review_for_retry(self) -> None:
        proposal_id = self._proposal()
        with database._connection() as connection:
            connection.execute("""CREATE TRIGGER fail_decision BEFORE INSERT ON staff_decisions
                BEGIN SELECT RAISE(ABORT, 'simulated persistence failure'); END""")
            connection.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            store.review(self.report_id, proposal_id, self.admin_id, 0, "Approved",
                         ["waste_cleanliness"], "Medium", "cleanliness_review", "unreviewed",
                         "unreviewed", None, "")
        self.assertEqual(store.case_view(self.report_id)["proposal"]["status"], "Pending")
        self.assertEqual(store.case_view(self.report_id)["report"]["version"], 0)
        with database._connection() as connection:
            connection.execute("DROP TRIGGER fail_decision"); connection.commit()
        store.review(self.report_id, proposal_id, self.admin_id, 0, "Approved",
                     ["waste_cleanliness"], "Medium", "cleanliness_review", "unreviewed",
                     "unreviewed", None, "")
        self.assertEqual(store.case_view(self.report_id)["proposal"]["status"], "Approved")

    def test_two_reviewers_cannot_both_save(self) -> None:
        proposal_id = self._proposal()
        def decide(_: int) -> str:
            try:
                store.review(self.report_id, proposal_id, self.admin_id, 0, "Approved",
                             ["waste_cleanliness"], "Medium", "cleanliness_review", "unreviewed",
                             "unreviewed", None, "")
                return "saved"
            except ValueError:
                return "stale"
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(decide, range(2)))
        self.assertCountEqual(outcomes, ["saved", "stale"])

    def test_status_transitions_need_reason(self) -> None:
        with self.assertRaises(ValueError):
            store.change_status(self.report_id, self.admin_id, 0, "Closed", "skip")
        with self.assertRaises(ValueError):
            store.change_status(self.report_id, self.admin_id, 0, "In Progress", "")
        store.change_status(self.report_id, self.admin_id, 0, "In Progress", "بدأت مراجعة الموظف")
        self.assertEqual(store.case_view(self.report_id)["report"]["status"], "In Progress")


if __name__ == "__main__":
    unittest.main()
