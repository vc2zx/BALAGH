from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, redirect, render_template, request, session, url_for
from werkzeug.datastructures import FileStorage

from balagh import database
from balagh.triage import ReportInput, triage_report


citizen_bp = Blueprint("citizen", __name__, url_prefix="/citizen")

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}


def _tracking_hash(tracking_code: str) -> str:
    normalized = tracking_code.strip().upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _new_tracking_code() -> str:
    return secrets.token_hex(5).upper()


def _save_attachment(upload: FileStorage | None) -> str | None:
    if upload is None or not upload.filename:
        return None

    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS or upload.mimetype not in ALLOWED_IMAGE_MIMES:
        raise ValueError("يجب أن يكون المرفق صورة JPG أو PNG أو WEBP.")

    upload_dir = database.DATA_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / f"{uuid4().hex}{suffix}"
    upload.save(destination)
    return str(destination)


def _required_form_values() -> tuple[dict[str, str], list[str]]:
    values = {
        "title": request.form.get("title", "").strip(),
        "description": request.form.get("description", "").strip(),
        "city": request.form.get("city", "").strip(),
        "district": request.form.get("district", "").strip(),
        "landmark": request.form.get("landmark", "").strip(),
    }
    errors: list[str] = []

    for field, label in {
        "title": "عنوان البلاغ",
        "description": "وصف المشكلة",
        "city": "المدينة",
        "district": "الحي",
    }.items():
        if not values[field]:
            errors.append(f"حقل {label} مطلوب.")

    if len(values["title"]) > 120:
        errors.append("عنوان البلاغ يجب ألا يتجاوز 120 حرفًا.")
    if len(values["description"]) > 3000:
        errors.append("وصف البلاغ يجب ألا يتجاوز 3000 حرف.")

    return values, errors


def _status_ar(status: str) -> str:
    return {
        "Open": "مفتوح",
        "In Progress": "قيد المعالجة",
        "Resolved": "تم الحل",
        "Closed": "مغلق",
    }.get(status, status)


def _priority_ar(priority: str) -> str:
    return {
        "Low": "منخفضة",
        "Medium": "متوسطة",
        "High": "مرتفعة",
        "Critical": "حرجة",
    }.get(priority, priority)


def _category_ar(category: str) -> str:
    return {
        "Roads & Sidewalks": "الطرق والأرصفة",
        "Waste & Cleanliness": "النفايات والنظافة",
        "Street Lighting & Electrical": "إنارة الشوارع والكهرباء",
        "Water & Drainage": "المياه والصرف",
        "Accessibility": "إمكانية الوصول",
        "Public Facilities": "المرافق العامة",
        "Noise & Community Disturbance": "الإزعاج والمخالفات المجتمعية",
        "General Community Services": "الخدمات المجتمعية العامة",
    }.get(category, category)


@citizen_bp.route("/", methods=["GET", "POST"])
def home():
    values = {
        "title": "",
        "description": "",
        "city": "",
        "district": "",
        "landmark": "",
    }
    errors: list[str] = []

    if request.method == "POST":
        values, errors = _required_form_values()

        if not errors:
            try:
                attachment_path = _save_attachment(request.files.get("attachment"))
            except ValueError as exc:
                errors.append(str(exc))
            else:
                report = ReportInput(**values)
                result = triage_report(
                    report,
                    existing_reports=database.get_open_reports(),
                    language="Arabic",
                )
                tracking_code = _new_tracking_code()
                report_id = database.create_report(
                    report,
                    result,
                    language="Arabic",
                    attachment_path=attachment_path,
                    tracking_token_hash=_tracking_hash(tracking_code),
                )
                session["last_submission"] = {
                    "report_id": report_id,
                    "tracking_code": tracking_code,
                }
                return redirect(url_for("citizen.submitted"))

    return render_template("citizen/home.html", values=values, errors=errors)


@citizen_bp.get("/submitted")
def submitted():
    submission = session.get("last_submission")
    if not submission:
        return redirect(url_for("citizen.home"))

    report = database.get_report(int(submission["report_id"]))
    if report is None:
        return redirect(url_for("citizen.home"))

    return render_template(
        "citizen/result.html",
        report=report,
        tracking_code=submission["tracking_code"],
        priority_ar=_priority_ar,
        category_ar=_category_ar,
    )


@citizen_bp.route("/track", methods=["GET", "POST"])
def track():
    tracking_code = ""
    report = None
    error = ""

    if request.method == "POST":
        tracking_code = request.form.get("tracking_code", "").strip().upper()
        if not tracking_code:
            error = "أدخل رمز المتابعة."
        else:
            report = database.get_report_by_tracking_hash(_tracking_hash(tracking_code))
            if report is None:
                error = "لم يتم العثور على بلاغ بهذا الرمز."

    return render_template(
        "citizen/track.html",
        tracking_code=tracking_code,
        report=report,
        error=error,
        status_ar=_status_ar,
        priority_ar=_priority_ar,
        category_ar=_category_ar,
    )


@citizen_bp.app_errorhandler(413)
def attachment_too_large(_error):
    return render_template(
        "citizen/home.html",
        values={"title": "", "description": "", "city": "", "district": "", "landmark": ""},
        errors=["حجم الطلب أكبر من 5 ميجابايت."],
    ), 413
