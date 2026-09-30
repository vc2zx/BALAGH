"""Staff decisions are explicit database transactions, not model workflow resumes."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, send_file, session, url_for)

from balagh import database, store
from balagh.auth import authenticate, can_access, consume_rate_limit, get_user
from balagh.catalog import SPECIAL_IDS, catalog, categories, category_label, queue_label


staff_bp = Blueprint("staff", __name__, url_prefix="/staff")
RIYADH_TIMEZONE = timezone(timedelta(hours=3), name="Asia/Riyadh")
STATUS_LABELS = {"Open": "مفتوح", "In Progress": "قيد المعالجة", "Resolved": "تم الحل", "Closed": "مغلق"}
PRIORITY_LABELS = {"Low": "منخفضة", "Medium": "متوسطة", "High": "مرتفعة", "Critical": "حرجة"}
STAGE_LABELS = {"queued": "بانتظار التحليل", "running": "جارٍ التحليل", "proposed": "مقترح للمراجعة",
                "needs_human": "مراجعة بشرية مباشرة", "legacy": "بلاغ سابق"}
RISK_LABELS = {"unreviewed": "لم يُحسم", "possible_current": "خطر آني محتمل",
               "historical_or_negated": "سابق أو منفي", "insufficient_information": "معلومات غير كافية"}
DUPLICATE_LABELS = {"unreviewed": "لم يُحسم", "not_duplicate": "ليس مكررًا",
                    "confirmed_duplicate": "تكرار أكده الموظف"}
DECISION_LABELS = {"Approved": "اعتماد", "Corrected": "تصحيح", "Rejected": "رفض"}


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


def _staff_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any):
        user = get_user(int(session.get("staff_user_id", 0)))
        if user is None:
            session.clear()
            return redirect(url_for("staff.login", next=request.path))
        g.staff_user = user
        return view(*args, **kwargs)
    return wrapped


def _case_or_404(report_id: int, write: bool = False) -> dict:
    case = store.case_view(report_id)
    if case is None:
        abort(404)
    if not can_access(g.staff_user, case["report"]["city_id"], write):
        abort(403)
    return case


def _safe_next(candidate: str) -> str:
    return candidate if candidate.startswith("/staff/") and not candidate.startswith("//") else url_for("staff.dashboard")


@staff_bp.app_context_processor
def helpers() -> dict:
    return {"status_label": lambda value: STATUS_LABELS.get(value, value),
            "priority_label": lambda value: PRIORITY_LABELS.get(value, value),
            "category_label": category_label,
            "queue_label": queue_label,
            "risk_label": lambda value: RISK_LABELS.get(value, value),
            "duplicate_label": lambda value: DUPLICATE_LABELS.get(value, value),
            "decision_label": lambda value: DECISION_LABELS.get(value, value),
            "stage_label": lambda value: STAGE_LABELS.get(value, value),
            "format_datetime": _format_datetime}


@staff_bp.route("/login", methods=["GET", "POST"])
def login():
    if get_user(int(session.get("staff_user_id", 0))):
        return redirect(url_for("staff.dashboard"))
    error = ""
    next_url = request.values.get("next", "")
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        identity = request.remote_addr or "unknown"
        limited = current_app.config.get("RATE_LIMIT_ENABLED", True) and (
            not consume_rate_limit("login-ip", identity, 12, 900) or
            not consume_rate_limit("login-user", username, 8, 900))
        if limited:
            return render_template("staff/login.html", error="محاولات كثيرة. حاول لاحقًا.", next_url=next_url), 429
        user = authenticate(username, request.form.get("password", ""))
        if user:
            session.clear()
            session["staff_user_id"] = user["id"]
            return redirect(_safe_next(next_url))
        error = "بيانات الدخول غير صحيحة."
    return render_template("staff/login.html", error=error, next_url=next_url)


@staff_bp.post("/logout")
@_staff_required
def logout():
    session.clear()
    return redirect(url_for("staff.login"))


@staff_bp.get("/")
@_staff_required
def dashboard():
    city_ids = None if g.staff_user["role"] == "admin" else g.staff_user["city_ids"]
    return render_template("staff/dashboard.html",
                           metrics=store.dashboard_metrics(city_ids),
                           reports=store.search_reports({}, city_ids, page_size=12))


@staff_bp.get("/reports")
@_staff_required
def reports():
    city_ids = None if g.staff_user["role"] == "admin" else g.staff_user["city_ids"]
    filters = {key: request.args.get(key, "").strip() for key in ("q", "status", "analysis_state")}
    page = max(request.args.get("page", 1, type=int), 1)
    rows = store.search_reports(filters, city_ids, page, page_size=26)
    return render_template("staff/reports.html", reports=rows[:25], filters=filters,
                           page=page, has_next=len(rows) > 25,
                           statuses=STATUS_LABELS, stages=STAGE_LABELS)


@staff_bp.get("/reports/<int:report_id>")
@_staff_required
def review(report_id: int):
    case = _case_or_404(report_id)
    with database._connection() as connection:
        history = [dict(row) for row in connection.execute(
            "SELECT created_at,actor,action,details FROM case_history WHERE report_id=? ORDER BY id DESC LIMIT 100",
            (report_id,)).fetchall()]
    city = catalog()["jurisdictions"].get(case["report"]["city_id"], {})
    queue_options = sorted({catalog()["default_queue"], *city.get("queues", {}).values()})
    return render_template("staff/review.html", case=case, report=case["report"],
                           proposal=case["proposal"], safety=case["safety"],
                           decision=case["decision"], duplicates=case["duplicates"],
                           categories=[item for item in categories().values() if item["id"] != "multiple_issues"],
                           queue_options=queue_options,
                           history=history, statuses=STATUS_LABELS,
                           allowed_transitions=sorted(store.STATUS_TRANSITIONS.get(case["report"]["status"], set())),
                           user=g.staff_user)


@staff_bp.post("/reports/<int:report_id>/decision")
@_staff_required
def save_decision(report_id: int):
    case = _case_or_404(report_id, write=True)
    proposal = case["proposal"]
    if proposal and proposal["status"] != "Pending":
        flash("تمت مراجعة هذا المقترح بالفعل.", "error")
        return redirect(url_for("staff.review", report_id=report_id))
    if proposal is None and case["report"]["analysis_state"] != "needs_human":
        flash("انتظر التحليل أو افتح مسار المراجعة البشرية.", "error")
        return redirect(url_for("staff.review", report_id=report_id))
    action = request.form.get("decision", "")
    selected = list(dict.fromkeys(request.form.getlist("category_ids")))
    allowed = set(categories())
    if not selected or "multiple_issues" in selected or any(item not in allowed for item in selected) or (set(selected) & SPECIAL_IDS and len(selected) != 1):
        flash("اختر تصنيفًا صالحًا أو نتيجة تعذر التصنيف.", "error")
        return redirect(url_for("staff.review", report_id=report_id))
    priority = request.form.get("priority", "")
    queue = request.form.get("review_queue", "")
    city = catalog()["jurisdictions"].get(case["report"]["city_id"], {})
    allowed_queues = {catalog()["default_queue"], *city.get("queues", {}).values()}
    if queue not in allowed_queues:
        abort(400)
    reason = request.form.get("reason", "").strip()
    if action == "Rejected":
        selected = ["unknown"]
        queue = catalog()["default_queue"]
        if case["safety"] and case["safety"].get("urgent_review"):
            priority = "Critical"
    if case["safety"] and case["safety"].get("urgent_review") and priority != "Critical" and action != "Corrected":
        flash("خفض مؤشر السلامة يحتاج تصحيحًا معللًا من الموظف.", "error")
        return redirect(url_for("staff.review", report_id=report_id))
    duplicate_target = request.form.get("duplicate_of_report_id", "").strip()
    try:
        store.review(report_id, int(proposal["id"]) if proposal else None,
                     int(g.staff_user["id"]), int(request.form.get("version", "-1")),
                     action, selected, priority, queue,
                     request.form.get("risk_review", "unreviewed"),
                     request.form.get("duplicate_decision", "unreviewed"),
                     int(duplicate_target) if duplicate_target else None, reason)
    except (ValueError, TypeError) as exc:
        flash(str(exc), "error")
    else:
        flash("حُفظ قرار الموظف والحقول المعتمدة في سجل منفصل.", "success")
    return redirect(url_for("staff.review", report_id=report_id))


@staff_bp.post("/reports/<int:report_id>/status")
@_staff_required
def update_status(report_id: int):
    _case_or_404(report_id, write=True)
    try:
        store.change_status(report_id, int(g.staff_user["id"]),
                            int(request.form.get("version", "-1")),
                            request.form.get("status", ""), request.form.get("reason", ""))
    except (ValueError, TypeError) as exc:
        flash(str(exc), "error")
    else:
        flash("حُفظ تغيير الحالة مع اسم الموظف والسبب.", "success")
    return redirect(url_for("staff.review", report_id=report_id))


@staff_bp.get("/reports/<int:report_id>/diagnostics")
@_staff_required
def diagnostics(report_id: int):
    if g.staff_user["role"] != "admin":
        abort(403)
    case = _case_or_404(report_id)
    return current_app.response_class(json.dumps(case, ensure_ascii=False, indent=2,
                                                 default=str), mimetype="application/json")


@staff_bp.get("/reports/<int:report_id>/attachment")
@_staff_required
def attachment(report_id: int):
    case = _case_or_404(report_id)
    stored = case["report"].get("attachment_path")
    if not stored:
        abort(404)
    upload_dir = (database.DATA_DIR / "uploads").resolve()
    path = Path(stored).resolve()
    if upload_dir not in path.parents or not path.is_file():
        abort(404)
    return send_file(path)
