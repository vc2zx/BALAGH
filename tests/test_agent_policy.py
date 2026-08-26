from __future__ import annotations

import unittest

from balagh.agent_policy import build_agent_case_context


class AgentPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.report = {
            "id": 3,
            "title": "there's no speed limit sign",
            "description": "the speed limit in this road is unknown",
            "city": "riyadh",
            "district": "al malaz",
            "landmark": "abdullah road",
            "category": "Traffic Signs & Road Safety",
            "priority": "Medium",
            "department": "Traffic Signs and Road Safety",
            "category_confidence": "High",
            "category_evidence": "speed limit sign | speed limit",
            "missing_information": "اتجاه السير وأقرب تقاطع أو مخرج",
            "duplicate_of": 2,
            "duplicate_score": 1.0,
            "status": "Open",
        }

    def test_keywords_are_labeled_as_lexical_matches(self) -> None:
        context = build_agent_case_context(self.report, "Arabic")

        self.assertNotIn("category_evidence", context["stored_triage"])
        self.assertEqual(
            context["stored_triage"]["matched_category_keywords"],
            ["speed limit sign", "speed limit"],
        )
        rules = " ".join(context["interpretation_rules"])
        self.assertIn("not observations", rules)
        self.assertIn("does not contradict", rules)

    def test_matching_categories_require_no_correction(self) -> None:
        context = build_agent_case_context(self.report, "Arabic")

        self.assertTrue(
            context["comparison"]["stored_category_matches_current_rules"]
        )
        self.assertIn("no category correction", context["comparison"]["instruction"])

    def test_duplicate_is_only_a_candidate_and_no_sla_is_configured(self) -> None:
        context = build_agent_case_context(self.report, "Arabic")

        duplicate = context["stored_potential_duplicate"]
        self.assertEqual(duplicate["report_id"], 2)
        self.assertIn("Candidate only", duplicate["interpretation"])
        rules = " ".join(context["interpretation_rules"])
        self.assertIn("no configured service-level deadline", rules)


if __name__ == "__main__":
    unittest.main()
