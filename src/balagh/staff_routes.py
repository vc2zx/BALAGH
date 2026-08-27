from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from balagh import database
from balagh.auth import verify_staff_access
from balagh.triage import ReportInput, triage_report


staff_bp = Blueprint("staff", __name__, url_prefix="/staff")

ViewFunction = TypeVar("ViewFunction", bound=Callable[..., Any])

STATUS_LABELS = {
    "Open": "مفتوح",
    "In Progress": "قيد المعالجة",
    "Resolved": "تم الحل",
    "Closed": "مغلق",
}
PRIORITY_LABELS = {
    "Low": "منخفضة",
    "Medium": "متوسطة",
    "High": "مرتفعة",
    "Critical": "حرجة",
}
CATEGORY_LABELS = {
    "Traffic Signs & Road Safety": "اللوحات والسلامة المرورية",
    "Roads & Sidewalks": "الطرق والأرصفة",
    "Waste & Cleanliness": "النفايات والنظافة",
    "Street Lighting & Electrical": "إنارة الشوارع والكهرباء",
    "Water & Drainage": "المياه والصرف",
    "Accessibility": "إمكانية الوصول",
    "Public Facilities": "المرافق العامة",
    "Noise & Community Disturbance": "الإزعاج والمخالفات المجتمعية",
    "Needs Human Classification": "يحتاج تصنيفًا بشريًا",
}
CONFIDENCE_LABELS = {
    "High": "عالية",
    "Medium": "متوسطة",
    "Low": "منخفضة",
    "None": "غير متوفرة",
}
DEPARTMENT_LABELS = {
    "Traffic Signs and Road Safety": "قسم اللوحات والسلامة المرورية",
    "Road and Sidewalk Maintenance": "قسم صيانة الطرق والأرصفة",
    "Environmental and Cleaning Services": "قسم الخدمات البيئية والنظافة",
    "Street Lighting and Electrical Safety": "قسم إنارة الشوارع والسلامة الكهربائية",
    "Water and Drainage Operations": "قسم عمليات المياه والصرف",
    "Accessibility and Inclusion Unit": "وحدة إمكانية الوصول والدمج",
    "Public Facilities and Parks": "قسم المرافق العامة والحدائق",
    "Community Compliance": "قسم الامتثال المجتمعي",
    "Triage Review Queue": "مسار مراجعة التصنيف",
}
DECISION_LABELS = {
    "Pending": "بانتظار المراجعة",
    "Approved": "معتمدة",
    "Modified": "معدلة",
    "Rejected": "مرفوضة",
}
ACTOR_LABELS = {
    "system": "النظام",
    "staff": "الموظف",
    "AI": "الذكاء الاصطناعي",
}
ACTION_LABELS = {
    "Report created": "إنشاء البلاغ",
    "Status changed": "تغيير الحالة",
    "Recommendation generated": "إنشاء توصية",
    "AI recommendation reviewed": "مراجعة التوصية",
    "Triage recalculated": "إعادة الفرز الحتمي",
}

RIYADH_TIMEZONE = timezone(timedelta(hours=3), name="Asia/Riyadh")


def _staff_required(view: ViewFunction) -> ViewFunction:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any):
        if not session.get("staff_authenticated"):
            return redirect(url_for("staff.login", next=request.path))
        return view(*args, **kwargs)

    return cast(ViewFunction, wrapped)


def _safe_next_url(candidate: str) -> str:
    if candidate.startswith("/staff/") and not candidate.startswith("//"):
        return candidate
    return url_for("staff.dashboard")


def _records(frame) -> list[dict[str, Any]]:
    clean = frame.astype(object).where(frame.notna(), None)
    return clean.to_dict(orient="records")


def _format_datetime(value: object) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(RIYADH_TIMEZONE).strftime("%Y-%m-%d %H:%M")


def _generate_recommendation(report_id: int):
    """Load the LangGraph workflow only when the employee requests it."""
    from balagh.agents import generate_recommendation

    return generate_recommendation(report_id, language="Arabic")


def _resume_recommendation(thread_id: str, decision: str, reviewer_note: str):
    """Resume the paused LangGraph run only after the employee submits a decision."""
    from balagh.agents import resume_recommendation

    return resume_recommendation(thread_id, decision, reviewer_note)


@staff_bp.app_context_processor
def staff_template_helpers() -> dict[str, Any]:
    return {
        "status_label": lambda value: STATUS_LABELS.get(value, value),
        "priority_label": lambda value: PRIORITY_LABELS.get(value, value),
        "category_label": lambda value: CATEGORY_LABELS.get(value, value),
        "confidence_label": lambda value: CONFIDENCE_LABELS.get(value, value),
        "department_label": lambda value: DEPARTMENT_LABELS.get(value, value),
        "decision_label": lambda value: DECISION_LABELS.get(value, value),
        "actor_label": lambda value: ACTOR_LABELS.get(value, value),
        "action_label": lambda value: ACTION_LABELS.get(value, value),
        "format_datetime": _format_datetime,
    }


@staff_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("staff_authenticated"):
        return redirect(url_for("staff.dashboard"))

    next_url = request.values.get("next", "")
    error = ""

    if request.method == "POST":
        code = request.form.get("access_code", "")
        if verify_staff_access(code):
            session.clear()
            session["staff_authenticated"] = True
            return redirect(_safe_next_url(next_url))
        error = "رمز الوصول غير صحيح أو لم يُضبط في ملف البيئة."

    return render_template("staff/login.html", error=error, next_url=next_url)


@staff_bp.post("/logout")
@_staff_required
def logout():
    session.clear()
    return redirect(url_for("staff.login"))


@staff_bp.get("/")
@_staff_required
def dashboard():
    return render_template(
        "staff/dashboard.html",
        metrics=database.summary_metrics(),
        reports=_records(database.get_reports(limit=12)),
    )


@staff_bp.get("/reports")
@_staff_required
def reports():
    frame = database.get_reports(limit=500)
    choices = {
        "categories": sorted(frame["category"].dropna().unique().tolist()),
        "priorities": sorted(frame["priority"].dropna().unique().tolist()),
        "statuses": sorted(frame["status"].dropna().unique().tolist()),
    }
    filters = {
        "q": request.args.get("q", "").strip(),
        "category": request.args.get("category", "").strip(),
        "priority": request.args.get("priority", "").strip(),
        "status": request.args.get("status", "").strip(),
    }

    if filters["q"] and not frame.empty:
        query = filters["q"]
        text_match = (
            frame["title"].str.contains(query, case=False, regex=False, na=False)
            | frame["city"].str.contains(query, case=False, regex=False, na=False)
            | frame["district"].str.contains(query, case=False, regex=False, na=False)
        )
        numeric_query = re.sub(r"^BLG-?", "", query, flags=re.IGNORECASE)
        id_match = (
            frame["id"].eq(int(numeric_query))
            if numeric_query.isdigit()
            else False
        )
        frame = frame[text_match | id_match]

    for column in ("category", "priority", "status"):
        if filters[column]:
            frame = frame[frame[column] == filters[column]]

    return render_template(
        "staff/reports.html",
        reports=_records(frame),
        filters=filters,
        choices=choices,
    )


@staff_bp.get("/reports/<int:report_id>")
@_staff_required
def review(report_id: int):
    report = database.get_report(report_id)
    if report is None:
        abort(404)

    return render_template(
        "staff/review.html",
        report=report,
        recommendation=database.get_agent_recommendation(report_id),
        history=_records(database.get_case_history(report_id)),
        statuses=list(STATUS_LABELS),
    )


@staff_bp.post("/reports/<int:report_id>/status")
@_staff_required
def update_status(report_id: int):
    report = database.get_report(report_id)
    if report is None:
        abort(404)

    new_status = request.form.get("status", "")
    if new_status == report["status"]:
        flash("الحالة لم تتغير.", "info")
    else:
        try:
            database.update_report_status(report_id, new_status, actor="staff")
        except ValueError:
            flash("قيمة الحالة غير مدعومة.", "error")
        else:
            flash("تم تحديث الحالة وتسجيل التغيير.", "success")

    return redirect(url_for("staff.review", report_id=report_id))


@staff_bp.post("/reports/<int:report_id>/retriage")
@_staff_required
def retriage(report_id: int):
    report = database.get_report(report_id)
    if report is None:
        abort(404)

    pending = database.get_agent_recommendation(report_id)
    if pending and pending["decision"] == "Pending":
        flash(
            "راجع التوصية المعلقة أو ارفضها قبل إعادة الفرز حتى لا تبقى توصية قديمة مرتبطة بنتيجة جديدة.",
            "info",
        )
        return redirect(url_for("staff.review", report_id=report_id))

    report_input = ReportInput(
        title=report["title"],
        description=report["description"],
        city=report["city"],
        district=report["district"],
        landmark=report.get("landmark") or "",
    )
    existing = [
        item for item in database.get_open_reports()
        if int(item["id"]) != report_id
    ]
    result = triage_report(
        report_input,
        existing_reports=existing,
        language=report.get("language") or "Arabic",
    )
    database.update_report_triage(report_id, result, actor="staff")
    flash("أُعيد فرز البلاغ بالقواعد الحالية وسُجل التغيير في السجل.", "success")
    return redirect(url_for("staff.review", report_id=report_id))


@staff_bp.post("/reports/<int:report_id>/recommendations")
@_staff_required
def create_recommendation(report_id: int):
    if database.get_report(report_id) is None:
        abort(404)

    stored = database.get_agent_recommendation(report_id)
    if stored and stored["decision"] == "Pending":
        flash(
            "توجد توصية معلقة لهذا البلاغ وتحتاج قرار الموظف أولًا.",
            "info",
        )
        return redirect(url_for("staff.review", report_id=report_id))

    try:
        recommendation = _generate_recommendation(report_id)
        recommendation_id = database.save_agent_recommendation(
            report_id,
            recommendation.triage_review,
            recommendation.coordinator_review,
            recommendation.final_recommendation,
            workflow_name="langgraph-functional-capstone-v2",
            validation_notes=getattr(recommendation, "validation_notes", ""),
            source_citations=getattr(recommendation, "source_citations", ""),
            workflow_thread_id=getattr(recommendation, "workflow_thread_id", ""),
            agent_route=getattr(recommendation, "route", ""),
            tool_calls=getattr(recommendation, "tool_calls", ""),
        )
    except Exception:  # LangGraph/Ollama expose different runtime exception types.
        current_app.logger.exception("Agent recommendation failed for report %s", report_id)
        flash("تعذر تشغيل الوكلاء. راجع سجل الخادم للتفاصيل.", "error")
    else:
        flash(f"تم إنشاء التوصية رقم {recommendation_id} للمراجعة البشرية.", "success")

    return redirect(url_for("staff.review", report_id=report_id))


@staff_bp.post("/reports/<int:report_id>/recommendations/<int:recommendation_id>/review")
@_staff_required
def review_recommendation(report_id: int, recommendation_id: int):
    stored = database.get_agent_recommendation(report_id)
    if stored is None or int(stored["id"]) != recommendation_id:
        abort(404)

    decision = request.form.get("decision", "")
    reviewer_note = request.form.get("reviewer_note", "")

    if decision not in database.ALLOWED_REVIEW_DECISIONS:
        flash("اختر قرارًا مدعومًا.", "error")
        return redirect(url_for("staff.review", report_id=report_id))
    if decision == "Modified" and not reviewer_note.strip():
        flash("اكتب ملاحظة توضّح التعديل المطلوب.", "error")
        return redirect(url_for("staff.review", report_id=report_id))

    workflow_thread_id = str(stored.get("workflow_thread_id") or "").strip()
    try:
        if workflow_thread_id:
            _resume_recommendation(workflow_thread_id, decision, reviewer_note)
        database.review_agent_recommendation(
            recommendation_id,
            decision,
            reviewer_note,
            actor="staff",
            workflow_resume_status=(
                "completed" if workflow_thread_id else "not_applicable"
            ),
        )
    except ValueError:
        flash("تعذر تسجيل القرار؛ ربما سبق أن روجعت التوصية.", "error")
    except Exception:
        current_app.logger.exception(
            "Recommendation workflow resume failed for recommendation %s",
            recommendation_id,
        )
        flash("تعذر استئناف سير المراجعة؛ بقيت التوصية معلقة دون تسجيل القرار.", "error")
    else:
        flash("تم تسجيل قرار الموظف في سجل الحالة.", "success")

    return redirect(url_for("staff.review", report_id=report_id))


@staff_bp.get("/reports/<int:report_id>/attachment")
@_staff_required
def attachment(report_id: int):
    report = database.get_report(report_id)
    if report is None or not report.get("attachment_path"):
        abort(404)

    upload_dir = (database.DATA_DIR / "uploads").resolve()
    attachment_path = Path(report["attachment_path"]).resolve()
    if upload_dir not in attachment_path.parents or not attachment_path.is_file():
        abort(404)

    return send_file(attachment_path)
