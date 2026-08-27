from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

import balagh.database as database
from balagh.agent_policy import build_agent_case_context
from balagh.agents import (
    ActionPlan,
    RoutingDecision,
    TriageAudit,
    _canonical_plan,
    _extract_interrupt_draft,
    build_recommendation_workflow,
)
from balagh.triage import ReportInput, triage_report


class _FakeRunnable:
    def __init__(self, output):
        self.output = output

    def invoke(self, _messages):
        return self.output


class _ToolCallRunnable:
    def __init__(self):
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        if self.calls == 1:
            return type("ToolResponse", (), {"tool_calls": []})()
        return type(
            "ToolResponse",
            (),
            {
                "tool_calls": [
                    {
                        "name": "load_case_record",
                        "args": {"report_id": 999, "language": "Arabic"},
                        "id": "case-tool-1",
                    },
                    {
                        "name": "recall_human_review_memory",
                        "args": {"category": "wrong"},
                        "id": "memory-tool-1",
                    },
                ]
            },
        )()


class _FakeModel:
    def bind_tools(self, _tools):
        return _ToolCallRunnable()

    def with_structured_output(self, schema):
        if schema is RoutingDecision:
            return _FakeRunnable(
                RoutingDecision(
                    worker="traffic_safety",
                    needs_human=True,
                    rationale="بلاغ سلامة مرورية يحتاج مراجعة الموظف والمعاينة.",
                )
            )
        if schema is TriageAudit:
            return _FakeRunnable(
                TriageAudit(
                    classification_decision="Correction Required",
                    proposed_category="Traffic Signs & Road Safety",
                    proposed_priority="Medium",
                    proposed_department="Traffic Signs and Road Safety",
                    confidence="High",
                    classification_rationale=(
                        "عبارات اللوحات تحدد مجال البلاغ لكنها ليست مشاهدة ميدانية."
                    ),
                    risk_assessment="غياب اللوحة لا يشكل خطرًا مباشرًا.",
                    potential_duplicate_summary="تكرار مؤكد.",
                    required_information=["اتجاه السير", "أقرب تقاطع"],
                    human_checks=["التحقق من الموقع"],
                )
            )
        return _FakeRunnable(
            ActionPlan(
                next_action=(
                    "التحقق من التكرار ثم إغلاق البلاغ وتحديد مدى ضرورة وجود لوحة سرعة."
                ),
                information_requests=["اتجاه السير", "أقرب تقاطع"],
                escalation_condition="يُصعّد تلقائيًا إذا لم يُعالج خلال 48 ساعة.",
                citizen_update="يرجى التحقق من الموقع في منطقتي الريادة والسلام.",
                employee_checklist=[],
            )
        )


class _FakeKnowledgeBase:
    def retrieve(self, _query: str, *, limit: int = 4):
        return [
            {
                "id": "S2",
                "title": "مكتبة كود الطرق السعودي",
                "organization": "الهيئة العامة للطرق",
                "url": "https://shc.rga.gov.sa/content/roadcodes/ar/road-code-library.html",
                "guidance": "مرجع فني للطرق والسلامة المرورية.",
                "source_file": "saudi-road-code.md",
            }
        ][:limit]


class AgentWorkflowTests(unittest.TestCase):
    def _create_speed_sign_report(self) -> int:
        report = ReportInput(
            title="there's no speed limit sign",
            description="the speed limit in this road is unknown",
            city="riyadh",
            district="al malaz",
            landmark="abdullah road",
        )
        result = triage_report(report, database.get_open_reports(), "Arabic")
        return database.create_report(report, result, "Arabic")

    def test_traffic_signal_plan_uses_the_correct_department_and_action(self) -> None:
        stored_report = {
            "id": 4,
            "title": "اشارة المرور لاتعمل",
            "description": "الاشارة على شارع عنيزة ماتشتغل",
            "city": "الرياض",
            "district": "الروابي",
            "landmark": "مطعم الهدوج",
            "category": "Traffic Signs & Road Safety",
            "priority": "High",
            "department": "Traffic Signs and Road Safety",
            "category_confidence": "High",
        }
        plan = _canonical_plan(build_agent_case_context(stored_report, "Arabic"))

        self.assertIn("قسم اللوحات والسلامة المرورية", plan.next_action)
        self.assertIn("عطل إشارة المرور", plan.next_action)
        self.assertNotIn("الحاجة إلى اللوحة", plan.next_action)
        self.assertNotIn("عدد العناصر", plan.model_dump_json())
        self.assertTrue(plan.employee_checklist)

    def test_functional_workflow_interrupts_resumes_and_shares_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with (
                patch.object(database, "DATA_DIR", temp_path),
                patch.object(database, "DB_PATH", temp_path / "workflow.db"),
            ):
                database.init_db()
                first_report = self._create_speed_sign_report()
                second_report = self._create_speed_sign_report()
                workflow = build_recommendation_workflow(
                    _FakeModel(),
                    checkpointer=InMemorySaver(),
                    store=InMemoryStore(),
                    knowledge_base=_FakeKnowledgeBase(),
                )

                first_config = {"configurable": {"thread_id": "thread-a"}}
                interrupted = workflow.invoke(
                    {
                        "report_id": first_report,
                        "language": "Arabic",
                        "thread_id": "thread-a",
                    },
                    config=first_config,
                )
                draft = _extract_interrupt_draft(interrupted)

                self.assertEqual(draft["route"]["worker"], "traffic_safety")
                self.assertTrue(draft["route"]["needs_human"])
                self.assertEqual(draft["official_sources"][0]["id"], "S2")
                self.assertEqual(
                    {item["tool"] for item in draft["tool_calls"]},
                    {"load_case_record", "recall_human_review_memory"},
                )
                self.assertNotIn(
                    "لا يشكل خطر",
                    draft["triage_audit"]["risk_assessment"],
                )
                self.assertNotRegex(
                    draft["action_plan"]["escalation_condition"],
                    r"48\s*ساعة",
                )

                completed = workflow.invoke(
                    Command(
                        resume={
                            "decision": "Modified",
                            "reviewer_note": "تحقق ميداني أولًا.",
                        }
                    ),
                    config=first_config,
                )
                self.assertEqual(completed["status"], "completed")

                second_config = {"configurable": {"thread_id": "thread-b"}}
                second_interrupted = workflow.invoke(
                    {
                        "report_id": second_report,
                        "language": "Arabic",
                        "thread_id": "thread-b",
                    },
                    config=second_config,
                )
                second_draft = _extract_interrupt_draft(second_interrupted)

                self.assertTrue(second_draft["long_term_memory"])
                self.assertEqual(
                    second_draft["long_term_memory"][0]["thread_id"],
                    "thread-a",
                )
                self.assertIn(
                    "تحقق ميداني",
                    second_draft["long_term_memory"][0]["reviewer_note"],
                )


if __name__ == "__main__":
    unittest.main()
