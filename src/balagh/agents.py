from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_store
from langgraph.func import entrypoint, task
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command, RetryPolicy, interrupt
from pydantic import BaseModel, Field

from balagh.knowledge import OfficialKnowledgeBase, retrieve_official_sources
from balagh.tools import (
    find_similar_report_candidates,
    get_case_context,
    get_case_history_records,
)
from balagh.triage import DEPARTMENT_LABELS_AR, normalize_text


CategoryName = Literal[
    "Traffic Signs & Road Safety",
    "Roads & Sidewalks",
    "Waste & Cleanliness",
    "Street Lighting & Electrical",
    "Water & Drainage",
    "Accessibility",
    "Public Facilities",
    "Noise & Community Disturbance",
    "Needs Human Classification",
]
PriorityName = Literal["Low", "Medium", "High", "Critical"]
DepartmentName = Literal[
    "Traffic Signs and Road Safety",
    "Road and Sidewalk Maintenance",
    "Environmental and Cleaning Services",
    "Street Lighting and Electrical Safety",
    "Water and Drainage Operations",
    "Accessibility and Inclusion Unit",
    "Public Facilities and Parks",
    "Community Compliance",
    "Triage Review Queue",
]


class RoutingDecision(BaseModel):
    worker: Literal[
        "traffic_safety",
        "municipal_operations",
        "human_classification",
    ]
    needs_human: bool
    rationale: str = Field(min_length=10)


class TriageAudit(BaseModel):
    classification_decision: Literal[
        "Confirmed",
        "Correction Required",
        "Human Review Required",
    ]
    proposed_category: CategoryName
    proposed_priority: PriorityName
    proposed_department: DepartmentName
    confidence: Literal["High", "Medium", "Low", "None"]
    classification_rationale: str = Field(min_length=10)
    risk_assessment: str = Field(min_length=10)
    potential_duplicate_summary: str = Field(min_length=5)
    required_information: list[str] = Field(default_factory=list, max_length=5)
    human_checks: list[str] = Field(default_factory=list, max_length=5)


class ActionPlan(BaseModel):
    next_action: str = Field(min_length=10)
    information_requests: list[str] = Field(default_factory=list, max_length=5)
    escalation_condition: str = Field(min_length=10)
    citizen_update: str = Field(min_length=10)
    employee_checklist: list[str] = Field(default_factory=list, max_length=5)


class HumanReview(BaseModel):
    decision: Literal["Approved", "Modified", "Rejected"]
    reviewer_note: str = ""


@dataclass(frozen=True)
class AgentRecommendation:
    triage_review: str
    coordinator_review: str
    final_recommendation: str
    validation_notes: str
    source_citations: str
    workflow_thread_id: str
    route: str
    tool_calls: str


_MEMORY_NAMESPACE = ("balagh", "human_reviews")
_TRANSIENT_RETRY = RetryPolicy(
    max_attempts=2,
    initial_interval=0.25,
    retry_on=(ConnectionError, TimeoutError, OSError),
)
_CHECKPOINTER = InMemorySaver()
_LONG_TERM_STORE = InMemoryStore()
_DEFAULT_WORKFLOW: Any | None = None


def _ollama_model_name() -> str:
    configured = os.getenv("MODEL", "qwen3:4b-instruct").strip()
    return configured.removeprefix("ollama/")


def _model() -> ChatOllama:
    return ChatOllama(
        model=_ollama_model_name(),
        base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        temperature=0.1,
    )


def _invoke_structured(model: Any, schema: type[BaseModel], prompt: str) -> BaseModel:
    result = model.with_structured_output(schema).invoke(
        [
            (
                "system",
                "أنت وكيل استشاري في نظام بلاغات مرافق عامة. التزم بالحقائق "
                "وبالمخطط المنظم المطلوب، ولا تنفذ أي إجراء.",
            ),
            ("human", prompt),
        ]
    )
    return result if isinstance(result, schema) else schema.model_validate(result)


@tool
def load_case_record(report_id: int, language: str = "Arabic") -> dict[str, Any]:
    """Load the verified stored facts and deterministic triage for one report ID."""
    return get_case_context(report_id, language=language)


@tool
def search_similar_cases(report_id: int, limit: int = 5) -> list[dict[str, Any]]:
    """Search open reports for possible duplicates of one report ID."""
    return find_similar_report_candidates(report_id, limit=max(1, min(limit, 8)))


@tool
def retrieve_official_guidance(
    report_id: int,
    language: str = "Arabic",
    limit: int = 4,
) -> list[dict[str, str]]:
    """Retrieve semantically relevant chunks from the local official-source vector index."""
    context = get_case_context(report_id, language=language)
    return retrieve_official_sources(context, limit=max(1, min(limit, 6)))


@tool
def recall_human_review_memory(category: str, limit: int = 3) -> list[dict[str, Any]]:
    """Recall prior approved or modified staff reviews for a report category."""
    store = get_store()
    items = store.search(
        _MEMORY_NAMESPACE,
        filter={"category": category},
        limit=max(1, min(limit, 8)),
    )
    return [dict(item.value) for item in items]


READ_ONLY_AGENT_TOOLS = (
    load_case_record,
    search_similar_cases,
    retrieve_official_guidance,
    recall_human_review_memory,
)
_TOOL_BY_NAME = {agent_tool.name: agent_tool for agent_tool in READ_ONLY_AGENT_TOOLS}


def _case_query(context: dict[str, Any]) -> str:
    facts = context["case_facts"]
    preview = context["current_rules_preview"]
    return " ".join(
        str(value or "")
        for value in (
            facts.get("title"),
            facts.get("description"),
            facts.get("city"),
            facts.get("district"),
            preview.get("category"),
            preview.get("department"),
        )
    )


def _execute_selected_tools(
    model: Any,
    *,
    report_id: int,
    language: str,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Let the model choose and call safe read-only case tools."""
    bound_model = model.bind_tools(list(READ_ONLY_AGENT_TOOLS))
    messages: list[Any] = [
        (
            "system",
            "اختر الأدوات المقروءة اللازمة للتحقق من البلاغ. استدعِ أداة واحدة "
            "على الأقل، ولا تستدعِ أدوات تنفيذية أو تغيّر أي بيانات.",
        ),
        (
            "human",
            f"report_id={report_id}; language={language}; case={_case_query(context)}",
        ),
    ]
    response = bound_model.invoke(messages)
    if not list(getattr(response, "tool_calls", []) or []):
        response = bound_model.invoke(
            [
                *messages,
                response,
                (
                    "human",
                    "لم تُحدَّد أداة. صحح الاستجابة باستدعاء أداة قراءة واحدة على الأقل.",
                ),
            ]
        )
    if not list(getattr(response, "tool_calls", []) or []):
        raise ValueError("The model did not select a required read-only tool.")
    outputs: list[dict[str, Any]] = []
    for call in list(getattr(response, "tool_calls", []) or []):
        name = str(call.get("name", ""))
        selected = _TOOL_BY_NAME.get(name)
        if selected is None:
            continue
        arguments = dict(call.get("args") or {})
        if name in {"load_case_record", "search_similar_cases", "retrieve_official_guidance"}:
            arguments["report_id"] = report_id
        if name in {"load_case_record", "retrieve_official_guidance"}:
            arguments.setdefault("language", language)
        if name == "recall_human_review_memory":
            arguments["category"] = context["current_rules_preview"]["category"]
        value = selected.invoke(arguments)
        outputs.append({"tool": name, "arguments": arguments, "result": value})
    return outputs


def _canonical_employee_checks(context: dict[str, Any]) -> list[str]:
    facts = context["case_facts"]
    category = context["current_rules_preview"]["category"]
    case_text = normalize_text(
        f"{facts.get('title') or ''} {facts.get('description') or ''}"
    )
    is_traffic_signal = any(
        term in case_text
        for term in ("traffic signal", "traffic light", "اشارة المرور", "اشارة مرورية")
    )
    checks = [
        "مطابقة الموقع والوصف مع البيانات التي قدّمها المبلّغ قبل الإحالة.",
        "توثيق نتيجة التحقق أو المعاينة في سجل الحالة.",
    ]
    if category == "Traffic Signs & Road Safety":
        checks.insert(
            1,
            (
                "التحقق من التقاطع ونوع عطل إشارة المرور وتوثيق مستوى تأثيره في السلامة."
                if is_traffic_signal
                else "التحقق من المخطط المروري أو المرجع الفني المعتمد قبل تقرير الحاجة إلى اللوحة."
            ),
        )
    if context.get("stored_potential_duplicate"):
        checks.append(
            "مقارنة المشكلة والموقع مع البلاغ المشابه قبل ربطهما؛ لا يُغلق أي بلاغ بسبب التشابه وحده."
        )
    if facts.get("emergency_warning"):
        checks.insert(0, "مراجعة تنبيه السلامة الحتمي فورًا.")
    return checks[:5]


def _canonical_plan(context: dict[str, Any]) -> ActionPlan:
    facts = context["case_facts"]
    preview = context["current_rules_preview"]
    missing = list(preview.get("missing_information") or [])
    location_parts = [
        str(facts.get("landmark") or "").strip(),
        str(facts.get("district") or "").strip(),
        str(facts.get("city") or "").strip(),
    ]
    location = "، ".join(part for part in location_parts if part) or "الموقع المسجل"
    department = preview["department"]
    department_label = DEPARTMENT_LABELS_AR.get(department, department)
    case_text = normalize_text(
        f"{facts.get('title') or ''} {facts.get('description') or ''}"
    )
    is_traffic_signal = any(
        term in case_text
        for term in ("traffic signal", "traffic light", "اشارة المرور", "اشارة مرورية")
    )

    duplicate_instruction = ""
    if context.get("stored_potential_duplicate"):
        duplicate_instruction = (
            " وقبل الربط، يقارن الموظف المشكلة والموقع مع البلاغ المشابه المحتمل."
        )

    if preview["category"] == "Traffic Signs & Road Safety":
        if is_traffic_signal:
            next_action = (
                f"استكمال تحديد التقاطع والاتجاه في {location}، ثم إحالة البلاغ ذي "
                f"الأولوية المرتفعة إلى {department_label} للتحقق الفني والمعاينة "
                f"الميدانية لعطل إشارة المرور واتخاذ إجراء السلامة المناسب."
                f"{duplicate_instruction}"
            )
        else:
            next_action = (
                f"استكمال بيانات تحديد الموقع في {location}، ثم إحالة البلاغ إلى "
                f"{department_label} لمطابقة الموقع مع المخطط المروري المعتمد أو المرجع الفني "
                f"المعتمد وإجراء معاينة ميدانية دون افتراض النتيجة مسبقًا."
                f"{duplicate_instruction}"
            )
    else:
        next_action = (
            f"التحقق من بيانات البلاغ وموقعه في {location}، ثم إحالته إلى "
            f"{department_label} للمعاينة وتحديد الإجراء المناسب وفق المرجع المعتمد."
            f"{duplicate_instruction}"
        )

    if missing:
        citizen_update = (
            f"تم استلام بلاغكم بشأن «{facts.get('title') or 'الملاحظة المسجلة'}» "
            f"في {location}. يرجى تزويدنا بالمعلومات التالية: {', '.join(missing)} "
            "لاستكمال التحقق والإحالة إلى الجهة المختصة."
        )
    else:
        citizen_update = (
            f"تم استلام بلاغكم بشأن «{facts.get('title') or 'الملاحظة المسجلة'}» "
            f"في {location}، وسيُراجع الموظف البيانات قبل إحالتها إلى الجهة المختصة."
        )

    return ActionPlan(
        next_action=next_action,
        information_requests=missing,
        escalation_condition=(
            "يُقترح التصعيد فقط إذا ظهرت معلومات أو معاينة تدل على خطر فوري "
            "أو أثر مرتفع، وبعد تقييم الموظف؛ لا توجد مهلة تصعيد معتمدة داخل هذا النموذج الأولي."
        ),
        citizen_update=citizen_update,
        employee_checklist=_canonical_employee_checks(context),
    )


_UNSUPPORTED_TIME_RULE = re.compile(
    r"\b\d+\s*(?:ساعة|ساعات|يوم|أيام|ايام|hour|hours|day|days)\b",
    flags=re.IGNORECASE,
)
_UNSAFE_CERTAINTY = (
    "لا يشكل خطر",
    "لا يشكّل خطر",
    "لا يمثل خطر",
    "لا يمثّل خطر",
)
_UNSUPPORTED_SIGN_NECESSITY = (
    "تحديد مدى ضرورة وجود لوحة",
    "تحديد ضرورة وجود لوحة",
    "تحديد ما إذا كانت اللوحة مطلوبة",
)


def _apply_guardrails(
    context: dict[str, Any],
    audit: TriageAudit,
    plan: ActionPlan,
) -> tuple[TriageAudit, ActionPlan, list[str]]:
    audit = audit.model_copy(deep=True)
    plan = plan.model_copy(deep=True)
    canonical = _canonical_plan(context)
    notes: list[str] = []
    preview = context["current_rules_preview"]

    if context["comparison"]["stored_category_matches_current_rules"]:
        if audit.classification_decision != "Confirmed":
            notes.append("Classification aligned with matching deterministic results.")
        audit.classification_decision = "Confirmed"
        audit.proposed_category = preview["category"]
        audit.proposed_priority = preview["priority"]
        audit.proposed_department = preview["department"]

    potential_duplicate = context.get("stored_potential_duplicate")
    if potential_duplicate:
        report_id = int(potential_duplicate["report_id"])
        score = float(potential_duplicate.get("similarity_score") or 0)
        audit.potential_duplicate_summary = (
            f"BLG-{report_id:05d} تكرار محتمل بدرجة تشابه {score:.0%}؛ "
            "لا يُعتمد كتكرار إلا بعد مراجعة الموظف للمشكلة والموقع."
        )
    else:
        audit.potential_duplicate_summary = "لا يوجد تكرار محتمل مسجل حاليًا."

    deterministic_missing = list(preview.get("missing_information") or [])
    if audit.required_information != deterministic_missing:
        notes.append("Required information aligned with deterministic case facts.")
    audit.required_information = deterministic_missing
    audit.human_checks = _canonical_employee_checks(context)
    plan.information_requests = deterministic_missing
    plan.employee_checklist = list(audit.human_checks)

    if any(phrase in audit.risk_assessment for phrase in _UNSAFE_CERTAINTY):
        audit.risk_assessment = (
            "لا تتضمن معلومات البلاغ الحالية دليلًا كافيًا لتحديد وجود خطر فوري "
            "أو نفيه؛ يراجع الموظف خصائص الموقع ونتيجة المعاينة."
        )
        notes.append("Unsupported safety certainty replaced.")

    plan_text = plan.model_dump_json()
    if _UNSUPPORTED_TIME_RULE.search(plan_text):
        plan.escalation_condition = canonical.escalation_condition
        notes.append("Invented time-based escalation rule removed.")
    if any(phrase in plan.next_action for phrase in _UNSUPPORTED_SIGN_NECESSITY):
        plan.next_action = canonical.next_action
        notes.append("Unsupported regulatory necessity claim replaced.")
    if any(phrase in plan_text for phrase in _UNSAFE_CERTAINTY):
        plan.escalation_condition = canonical.escalation_condition
        notes.append("Unsupported safety claim removed from the action plan.")
    if "إغلاق" in plan.next_action and potential_duplicate:
        plan.next_action = canonical.next_action
        notes.append("Duplicate-based closure suggestion removed.")

    facts_text = normalize_text(
        " ".join(
            str(context["case_facts"].get(field) or "")
            for field in ("title", "city", "district", "landmark")
        )
    )
    update_text = normalize_text(plan.citizen_update)
    if not any(token and token in update_text for token in facts_text.split()[:8]):
        plan.citizen_update = canonical.citizen_update
        notes.append("Citizen update grounded in stored case facts.")

    return audit, plan, notes


def _memory_values(store: BaseStore, category: str, limit: int = 3) -> list[dict[str, Any]]:
    items = store.search(
        _MEMORY_NAMESPACE,
        filter={"category": category},
        limit=max(1, min(limit, 8)),
    )
    return [dict(item.value) for item in items]


def build_recommendation_workflow(
    model: Any | None = None,
    *,
    checkpointer: Any | None = None,
    store: BaseStore | None = None,
    knowledge_base: OfficialKnowledgeBase | None = None,
):
    """Build the Track B Functional API workflow with persistence and HITL."""
    llm = model or _model()
    workflow_checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
    workflow_store = store if store is not None else InMemoryStore()

    @task
    def load_case_task(report_id: int, language: str) -> dict[str, Any]:
        context = get_case_context(report_id, language=language)
        return {
            "case_context": context,
            "similar_reports": find_similar_report_candidates(report_id, limit=5),
            "case_history": get_case_history_records(report_id),
        }

    @task(retry_policy=_TRANSIENT_RETRY)
    def retrieve_context_task(context: dict[str, Any]) -> list[dict[str, str]]:
        return retrieve_official_sources(
            context,
            limit=4,
            knowledge_base=knowledge_base,
        )

    @task(retry_policy=_TRANSIENT_RETRY)
    def choose_tools_task(
        report_id: int,
        language: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return _execute_selected_tools(
            llm,
            report_id=report_id,
            language=language,
            context=context,
        )

    @task
    def recall_memory_task(category: str) -> list[dict[str, Any]]:
        return _memory_values(get_store(), category)

    @task(retry_policy=_TRANSIENT_RETRY)
    def supervisor_task(payload: dict[str, Any]) -> RoutingDecision:
        prompt = f"""
أنت المشرف في BALAGH. اختر عاملًا متخصصًا واحدًا باستخدام RoutingDecision فقط.

{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}

- traffic_safety لبلاغات اللوحات والإشارات والسلامة المرورية.
- municipal_operations لبقية مرافق البلدية المصنفة.
- human_classification عندما تكون الفئة غير واضحة أو الثقة منخفضة.
- needs_human=true إذا احتاجت النتيجة حكم موظف أو تحققًا ميدانيًا؛ لا تنفذ القرار.
"""
        return RoutingDecision.model_validate(
            _invoke_structured(llm, RoutingDecision, prompt)
        )

    def _audit_prompt(payload: dict[str, Any], worker_instruction: str) -> str:
        return f"""
{worker_instruction}
أعد TriageAudit فقط من الحقائق والسياق التالي:

{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}

- الكلمات المطابقة إشارات لغوية وليست أدلة ميدانية.
- النفي جزء من حقيقة البلاغ.
- إذا تطابقت الفئة المخزنة مع القواعد الحالية فاستخدم Confirmed.
- لا تعتبر التشابه تأكيدًا للتكرار.
- لا تخترع حوادث أو سياسات أو SLA.
- عدم وجود تفاصيل خطر لا يثبت أن الحالة آمنة.
- استخدم المصادر المسترجعة فقط ولا تنسب إليها نصًا غير موجود.
"""

    @task(retry_policy=_TRANSIENT_RETRY)
    def traffic_safety_worker_task(payload: dict[str, Any]) -> TriageAudit:
        return TriageAudit.model_validate(
            _invoke_structured(
                llm,
                TriageAudit,
                _audit_prompt(
                    payload,
                    "أنت عامل تدقيق متخصص في اللوحات والإشارات والسلامة المرورية.",
                ),
            )
        )

    @task(retry_policy=_TRANSIENT_RETRY)
    def municipal_worker_task(payload: dict[str, Any]) -> TriageAudit:
        return TriageAudit.model_validate(
            _invoke_structured(
                llm,
                TriageAudit,
                _audit_prompt(
                    payload,
                    "أنت عامل تدقيق متخصص في تشغيل وصيانة المرافق البلدية.",
                ),
            )
        )

    @task(retry_policy=_TRANSIENT_RETRY)
    def human_classification_worker_task(payload: dict[str, Any]) -> TriageAudit:
        return TriageAudit.model_validate(
            _invoke_structured(
                llm,
                TriageAudit,
                _audit_prompt(
                    payload,
                    "أنت عامل فرز للحالات الغامضة؛ صرّح بحدود المعرفة واطلب مراجعة بشرية.",
                ),
            )
        )

    @task(retry_policy=_TRANSIENT_RETRY)
    def coordinator_task(payload: dict[str, Any]) -> ActionPlan:
        prompt = f"""
أنت منسق الحالة في BALAGH. أعد ActionPlan فقط من نتيجة العامل والحقائق:

{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}

- اقترح خطوة بشرية أو ميدانية ولا تدّع تنفيذها.
- لا تحدد حكمًا تنظيميًا دون مرجع رسمي.
- لا تخترع مدة أو SLA أو حادثًا سابقًا.
- التشابه تكرار محتمل فقط.
- اطلب المعلومات التي تؤثر في الموقع أو المعالجة فقط.
"""
        return ActionPlan.model_validate(_invoke_structured(llm, ActionPlan, prompt))

    @task
    def guardrail_task(
        context: dict[str, Any],
        audit: TriageAudit,
        plan: ActionPlan,
    ) -> dict[str, Any]:
        safe_audit, safe_plan, notes = _apply_guardrails(context, audit, plan)
        return {
            "triage_audit": safe_audit,
            "action_plan": safe_plan,
            "validation_notes": notes,
        }

    @task
    def human_review_task(draft: dict[str, Any]) -> dict[str, Any]:
        return interrupt(
            {
                "type": "staff_recommendation_review",
                "message": "Review the advisory recommendation before recording a decision.",
                "draft": draft,
            }
        )

    @task
    def store_review_task(
        report_id: int,
        category: str,
        thread_id: str,
        review_payload: dict[str, Any],
    ) -> dict[str, Any]:
        review = HumanReview.model_validate(review_payload)
        get_store().put(
            _MEMORY_NAMESPACE,
            f"{thread_id}:{report_id}",
            {
                "report_id": report_id,
                "category": category,
                "decision": review.decision,
                "reviewer_note": review.reviewer_note.strip(),
                "thread_id": thread_id,
            },
        )
        return review.model_dump()

    @entrypoint(checkpointer=workflow_checkpointer, store=workflow_store)
    def recommendation_workflow(
        inputs: dict[str, Any],
        *,
        previous: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        report_id = int(inputs["report_id"])
        language = str(inputs.get("language", "Arabic"))
        thread_id = str(inputs["thread_id"])

        loaded = load_case_task(report_id, language).result()
        context = loaded["case_context"]
        category = context["current_rules_preview"]["category"]
        sources_future = retrieve_context_task(context)
        tool_calls_future = choose_tools_task(report_id, language, context)
        memory_future = recall_memory_task(category)

        sources = sources_future.result()
        tool_calls = tool_calls_future.result()
        memory = memory_future.result()
        routing_payload = {
            "case": context,
            "retrieved_sources": sources,
            "selected_tool_outputs": tool_calls,
            "cross_thread_human_memory": memory,
            "previous_thread_state": previous,
        }
        route = supervisor_task(routing_payload).result()

        worker_payload = {**routing_payload, "supervisor_route": route.model_dump()}
        if route.worker == "traffic_safety":
            audit = traffic_safety_worker_task(worker_payload).result()
        elif route.worker == "human_classification":
            audit = human_classification_worker_task(worker_payload).result()
        else:
            audit = municipal_worker_task(worker_payload).result()

        plan = coordinator_task(
            {
                "case": context,
                "routing": route.model_dump(),
                "triage_audit": audit.model_dump(),
                "retrieved_sources": sources,
                "cross_thread_human_memory": memory,
            }
        ).result()
        guarded = guardrail_task(context, audit, plan).result()
        draft = {
            "report_id": report_id,
            "thread_id": thread_id,
            "route": route.model_dump(),
            "triage_audit": guarded["triage_audit"].model_dump(),
            "action_plan": guarded["action_plan"].model_dump(),
            "validation_notes": guarded["validation_notes"],
            "official_sources": sources,
            "tool_calls": tool_calls,
            "long_term_memory": memory,
        }

        human_review = human_review_task(draft).result()
        recorded_review = store_review_task(
            report_id,
            category,
            thread_id,
            human_review,
        ).result()
        completed = {
            "status": "completed",
            "draft": draft,
            "human_review": recorded_review,
        }
        return entrypoint.final(value=completed, save=completed)

    return recommendation_workflow


def _default_workflow():
    global _DEFAULT_WORKFLOW
    if _DEFAULT_WORKFLOW is None:
        _DEFAULT_WORKFLOW = build_recommendation_workflow(
            checkpointer=_CHECKPOINTER,
            store=_LONG_TERM_STORE,
        )
    return _DEFAULT_WORKFLOW


def _extract_interrupt_draft(result: dict[str, Any]) -> dict[str, Any]:
    interrupts = result.get("__interrupt__") or []
    if not interrupts:
        raise RuntimeError("The recommendation workflow did not reach human review.")
    first = interrupts[0]
    value = getattr(first, "value", first)
    if isinstance(value, dict) and "draft" in value:
        return dict(value["draft"])
    raise RuntimeError("The human-review interrupt did not contain a draft.")


def _render_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- لا توجد."


def render_triage_audit(audit: TriageAudit, route: RoutingDecision | None = None) -> str:
    decision_labels = {
        "Confirmed": "متطابق — لا يلزم تصحيح التصنيف",
        "Correction Required": "يوصى بتصحيح التصنيف",
        "Human Review Required": "يتطلب تصنيفًا بشريًا",
    }
    route_section = ""
    if route is not None:
        route_section = (
            "0. قرار المشرف\n"
            f"- المسار: {route.worker}\n"
            f"- إحالة بشرية: {'نعم' if route.needs_human else 'لا'}\n"
            f"- السبب: {route.rationale}\n\n"
        )
    return f"""{route_section}1. قرار التصنيف
{decision_labels[audit.classification_decision]}
- التصنيف المقترح: {audit.proposed_category}
- الأولوية المقترحة: {audit.proposed_priority}
- الجهة المقترحة: {audit.proposed_department}
- الثقة: {audit.confidence}

2. مبررات التصنيف
{audit.classification_rationale}

3. تقييم الخطر وحدود المعرفة
{audit.risk_assessment}

4. التكرار المحتمل
{audit.potential_duplicate_summary}

5. المعلومات اللازمة
{_render_list(audit.required_information)}

6. نقاط التحقق البشري
{_render_list(audit.human_checks)}"""


def render_action_plan(
    plan: ActionPlan,
    sources: list[dict[str, str]] | None = None,
) -> str:
    source_lines = "\n".join(
        f"- [{source['id']}] {source['organization']} — {source['title']}: {source['url']}"
        for source in (sources or [])
    ) or "- لا توجد مصادر مسترجعة."
    return f"""1. الإجراء التالي المقترح
{plan.next_action}

2. المعلومات المطلوبة من المبلّغ
{_render_list(plan.information_requests)}

3. شرط التصعيد
{plan.escalation_condition}

4. تحديث مقترح للمواطن
{plan.citizen_update}

5. قائمة اعتماد الموظف
{_render_list(plan.employee_checklist)}

6. المصادر الرسمية المسترجعة
{source_lines}

ملاحظة: المصادر مرجعية مساندة، والقرار التنفيذي والتنظيمي يبقى للموظف والجهة المختصة."""


def _draft_to_recommendation(
    draft: dict[str, Any],
    *,
    language: str,
) -> AgentRecommendation:
    audit = TriageAudit.model_validate(draft["triage_audit"])
    plan = ActionPlan.model_validate(draft["action_plan"])
    route = RoutingDecision.model_validate(draft["route"])
    sources = list(draft.get("official_sources") or [])
    triage_review = render_triage_audit(audit, route)
    coordinator_review = render_action_plan(plan, sources)
    header = (
        "توصية الذكاء الاصطناعي — تتطلب اعتماد الموظف"
        if language.lower() == "arabic"
        else "AI RECOMMENDATION — HUMAN APPROVAL REQUIRED"
    )
    return AgentRecommendation(
        triage_review=triage_review,
        coordinator_review=coordinator_review,
        final_recommendation=f"{header}\n\n{coordinator_review}",
        validation_notes=" | ".join(draft.get("validation_notes") or []),
        source_citations=" | ".join(
            f"[{source['id']}] {source['url']}" for source in sources
        ),
        workflow_thread_id=str(draft["thread_id"]),
        route=route.worker,
        tool_calls=" | ".join(
            str(item.get("tool", "")) for item in (draft.get("tool_calls") or [])
        ),
    )


def start_recommendation(
    report_id: int,
    language: str = "Arabic",
    *,
    workflow: Any | None = None,
    thread_id: str | None = None,
) -> AgentRecommendation:
    """Generate a draft and pause the workflow at the staff-review interrupt."""
    active_thread_id = thread_id or f"report-{report_id}-{uuid4().hex}"
    result = (workflow or _default_workflow()).invoke(
        {
            "report_id": report_id,
            "language": language,
            "thread_id": active_thread_id,
        },
        config={"configurable": {"thread_id": active_thread_id}},
    )
    draft = _extract_interrupt_draft(result)
    return _draft_to_recommendation(draft, language=language)


def resume_recommendation(
    thread_id: str,
    decision: str,
    reviewer_note: str = "",
    *,
    workflow: Any | None = None,
) -> dict[str, Any]:
    """Resume a paused recommendation with the employee's explicit decision."""
    review = HumanReview(decision=decision, reviewer_note=reviewer_note)
    result = (workflow or _default_workflow()).invoke(
        Command(resume=review.model_dump()),
        config={"configurable": {"thread_id": thread_id}},
    )
    if not isinstance(result, dict) or result.get("status") != "completed":
        raise RuntimeError("The recommendation workflow did not complete after review.")
    return result


def generate_recommendation(
    report_id: int,
    language: str = "Arabic",
) -> AgentRecommendation:
    """Backward-compatible name for starting the reviewable recommendation workflow."""
    return start_recommendation(report_id, language=language)


def reset_workflow_runtime() -> None:
    """Reset process-local workflow state for isolated tests."""
    global _CHECKPOINTER, _LONG_TERM_STORE, _DEFAULT_WORKFLOW
    _CHECKPOINTER = InMemorySaver()
    _LONG_TERM_STORE = InMemoryStore()
    _DEFAULT_WORKFLOW = None
