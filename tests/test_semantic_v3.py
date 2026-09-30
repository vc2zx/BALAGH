from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from balagh import database, store, worker
from balagh.duplicates import rank_candidates
from balagh.safety import safety_signals
from balagh.semantic import propose, validate_proposal
from balagh.triage import ReportInput


def raw_proposal(ids: list[str], evidence: list[str], uncertainty: str = "") -> dict:
    return {"category_ids": ids, "proposed_priority": "Medium", "rationale": "اقتراح يحتاج مراجعة",
            "evidence_spans": evidence, "uncertainty_reason": uncertainty,
            "missing_information": [], "risk_signals": ["none"]}


class SemanticTests(unittest.TestCase):
    def test_required_arabic_regressions(self) -> None:
        roads = validate_proposal(raw_proposal(["roads_sidewalks"], ["الشارع بعد الأمطار أصبح مليان حفريات"]),
                                  "الشارع بعد الأمطار أصبح مليان حفريات", "riyadh")
        self.assertEqual(roads["category_ids"], ["roads_sidewalks"])
        mixed = validate_proposal(raw_proposal(["waste_cleanliness", "roads_sidewalks"], ["قمامة", "حفرة"], "مشكلتان"),
                                  "قمامة وحفرة", "riyadh")
        self.assertEqual(mixed["outcome"], "multiple_issues")
        self.assertEqual(mixed["review_queue"], "human_triage_review")
        outside = validate_proposal(raw_proposal(["out_of_scope"], [], "خارج الفئات"),
                                    "أريد حجز موعد طبي", "riyadh")
        self.assertEqual(outside["outcome"], "out_of_scope")

    def test_independent_safety_distinguishes_time_and_negation(self) -> None:
        self.assertTrue(safety_signals("دخان", "يوجد دخان كثيف يخرج من المبنى الآن")["urgent_review"])
        self.assertFalse(safety_signals("حريق", "كان هناك حريق أمس وتم إخماده بالكامل")["urgent_review"])
        self.assertTrue(safety_signals("حريق", "كان هناك حريق أمس وتم إخماده بالكامل")["historical_context"])
        self.assertFalse(safety_signals("بلاغ", "لا يوجد حريق الآن لكن الإنارة معطلة")["urgent_review"])
        self.assertTrue(safety_signals("أسلاك", "سلك كهربائي مكشوف على الأرض الآن")["urgent_review"])
        self.assertFalse(safety_signals("الإنارة ضعيفة", "تعطل عدة مصابيح")["urgent_review"])
        self.assertTrue(safety_signals("بلاغ", "حريق أمس وتم إخماده، لكن يوجد دخان الآن")["urgent_review"])

    def test_untrusted_model_output_requires_exact_evidence_and_no_extra_fields(self) -> None:
        text = "حفرة قرب المدرسة"
        with self.assertRaises(ValueError):
            validate_proposal(raw_proposal(["roads_sidewalks"], ["حفرة كبيرة"]), text, "riyadh")
        injected = raw_proposal(["roads_sidewalks"], ["حفرة"])
        injected["write_tool"] = "close_report"
        with self.assertRaises(ValueError):
            validate_proposal(injected, text, "riyadh")
        invented = raw_proposal(["roads_sidewalks"], ["حفرة"])
        invented["rationale"] = "الجهة ملزمة بمهلة 24 ساعة"
        with self.assertRaises(ValueError):
            validate_proposal(invented, text, "riyadh")
        with self.assertRaises(ValueError):
            validate_proposal(raw_proposal(["waste_cleanliness", "out_of_scope"], ["حفرة"]), text, "riyadh")

    def test_one_model_call_and_no_write_tools(self) -> None:
        calls = []
        def client(messages: list[dict], schema: dict):
            calls.append((messages, schema))
            return raw_proposal(["roads_sidewalks"], ["حفرة"]), "mock-model"
        proposal, model = propose("حفرة", "في الشارع", "riyadh", client=client)
        self.assertEqual(len(calls), 1)
        self.assertEqual([message["role"] for message in calls[0][0]], ["system", "user"])
        self.assertEqual(model, "mock-model")
        self.assertEqual(proposal["category_ids"], ["roads_sidewalks"])


class WorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.data_patch = patch.object(database, "DATA_DIR", self.path)
        self.db_patch = patch.object(database, "DB_PATH", self.path / "test.db")
        self.data_patch.start(); self.db_patch.start(); database.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop(); self.data_patch.stop(); self.temp.cleanup()

    def test_failed_model_retries_then_routes_to_human(self) -> None:
        report_id, _ = store.submit_report(ReportInput("بلاغ", "الوصف غير واضح", "الرياض", "الروابي"), "hash-1")
        with patch.object(worker, "propose", side_effect=TimeoutError("model timed out")):
            for attempt in range(3):
                self.assertTrue(worker.process_one("worker-1"))
                if attempt < 2:
                    with database._connection() as connection:
                        connection.execute("UPDATE triage_jobs SET available_at='2000-01-01' WHERE report_id=?", (report_id,))
                        connection.commit()
        view = store.case_view(report_id)
        self.assertEqual(view["report"]["analysis_state"], "needs_human")
        self.assertIsNone(view["proposal"])
        self.assertEqual(view["report"]["description"], "الوصف غير واضح")

    def test_duplicate_retrieval_is_bounded_and_semantic_ranking_uses_place(self) -> None:
        first, _ = store.submit_report(ReportInput("حفرة", "حفرة بجوار المكتبة", "الرياض", "الروابي", "المكتبة"), "hash-1")
        second, _ = store.submit_report(ReportInput("تلف طريق", "تلف قرب المكتبة", "الرياض", "الروابي", "المكتبة"), "hash-2")
        with database._connection() as connection:
            connection.execute("INSERT INTO report_features (report_id,embedding_json,asset_type,created_at) VALUES (?,?,'roads_sidewalks','2026-09-30')",
                               (first, "[1.0,0.0]"))
            connection.commit()
        self.assertEqual(len(store.candidate_reports(second, limit=1)), 1)
        ranked = rank_candidates(second, [1.0, 0.0], "roads_sidewalks")
        self.assertEqual(ranked[0]["report_id"], first)
        self.assertGreaterEqual(ranked[0]["score"], 0.72)

    def test_same_district_and_category_without_same_place_is_not_duplicate(self) -> None:
        first, _ = store.submit_report(ReportInput("حفرة", "حفرة عند المدرسة", "الرياض", "الروابي"), "hash-1")
        second, _ = store.submit_report(ReportInput("حفرة", "حفرة بجوار المكتبة", "الرياض", "الروابي"), "hash-2")
        with database._connection() as connection:
            connection.execute("INSERT INTO report_features (report_id,embedding_json,asset_type,created_at) VALUES (?,?,'roads_sidewalks','2026-09-30')",
                               (first, "[1.0,0.0]"))
            connection.commit()
        self.assertEqual(rank_candidates(second, [1.0, 0.0], "roads_sidewalks"), [])


if __name__ == "__main__":
    unittest.main()
