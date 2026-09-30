from __future__ import annotations

import hashlib
import hmac
import secrets
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for
from werkzeug.datastructures import FileStorage
from PIL import Image, UnidentifiedImageError

from balagh import database, store
from balagh.auth import consume_rate_limit
from balagh.catalog import category_label, resolve_city, validate_pin
from balagh.triage import ReportInput


citizen_bp = Blueprint("citizen", __name__, url_prefix="/citizen")

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
IMAGE_FORMATS = {
    "JPEG": ({".jpg", ".jpeg"}, "image/jpeg"),
    "PNG": ({".png"}, "image/png"),
    "WEBP": ({".webp"}, "image/webp"),
}


def _tracking_hash(tracking_code: str) -> str:
    normalized = tracking_code.strip().upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _new_tracking_code(nonce: str) -> str:
    return hmac.new(str(current_app.secret_key).encode(), nonce.encode(),
                    hashlib.sha256).hexdigest()[:32].upper()


def _save_attachment(upload: FileStorage | None) -> str | None:
    if upload is None or not upload.filename:
        return None

    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS or upload.mimetype not in ALLOWED_IMAGE_MIMES:
        raise ValueError("يجب أن يكون المرفق صورة JPG أو PNG أو WEBP.")

    try:
        payload = upload.stream.read()
        with Image.open(BytesIO(payload)) as image:
            image.verify()
        with Image.open(BytesIO(payload)) as image:
            if image.format not in IMAGE_FORMATS:
                raise ValueError("تعذر التحقق من نوع الصورة.")
            valid_suffixes, valid_mime = IMAGE_FORMATS[image.format]
            if suffix not in valid_suffixes or upload.mimetype != valid_mime:
                raise ValueError("امتداد الصورة ونوعها الفعلي غير متطابقين.")
            if image.width * image.height > 12_000_000:
                raise ValueError("أبعاد الصورة كبيرة جدًا؛ الحد 12 مليون بكسل.")
            image.load()
            cleaned = image.convert("RGB" if image.format == "JPEG" else "RGBA")
            output = BytesIO()
            cleaned.save(output, format=image.format)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("ملف الصورة غير صالح أو تالف.") from exc

    upload_dir = database.DATA_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / f"{uuid4().hex}{suffix}"
    destination.write_bytes(output.getvalue())
    return str(destination)


def _required_form_values() -> tuple[dict[str, str], list[str]]:
    values = {
        "title": request.form.get("title", "").strip(),
        "description": request.form.get("description", "").strip(),
        "city": request.form.get("city", "").strip(),
        "district": request.form.get("district", "").strip(),
        "landmark": request.form.get("landmark", "").strip(),
        "latitude": request.form.get("latitude", "").strip(),
        "longitude": request.form.get("longitude", "").strip(),
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

    if values["latitude"] or values["longitude"]:
        try:
            latitude, longitude = float(values["latitude"]), float(values["longitude"])
        except ValueError:
            errors.append("أدخل إحداثيين صالحين أو اترك الموقع على الخريطة فارغًا.")
        else:
            if not validate_pin(resolve_city(values["city"]), latitude, longitude):
                errors.append("إحداثيات الموقع خارج حدود المدينة المدعومة أو غير مكتملة.")

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
        "Traffic Signs & Road Safety": "اللوحات والسلامة المرورية",
        "Roads & Sidewalks": "الطرق والأرصفة",
        "Waste & Cleanliness": "النفايات والنظافة",
        "Street Lighting & Electrical": "إنارة الشوارع والكهرباء",
        "Water & Drainage": "المياه والصرف",
        "Accessibility": "إمكانية الوصول",
        "Public Facilities": "المرافق العامة",
        "Noise & Community Disturbance": "الإزعاج والمخالفات المجتمعية",
        "Needs Human Classification": "يحتاج تصنيفًا بشريًا",
    }.get(category, category)


@citizen_bp.route("/", methods=["GET", "POST"])
def home():
    values = {
        "title": "",
        "description": "",
        "city": "",
        "district": "",
        "landmark": "",
        "latitude": "", "longitude": "",
    }
    errors: list[str] = []

    if request.method == "GET" and not session.get("submission_nonce"):
        session["submission_nonce"] = secrets.token_urlsafe(24)

    if request.method == "POST":
        if current_app.config.get("RATE_LIMIT_ENABLED", True) and not consume_rate_limit(
            "submit", request.remote_addr or "unknown", 8, 3600
        ):
            return render_template("citizen/home.html", values=values,
                                   errors=["تم تجاوز حد الإرسال المؤقت. حاول لاحقًا."],
                                   submission_nonce=session.get("submission_nonce", "")), 429
        values, errors = _required_form_values()
        submitted_nonce = request.form.get("submission_nonce", "")
        expected_nonce = session.get("submission_nonce", "")
        prior = session.get("last_submission", {})
        prior_code = prior.get("tracking_code", "")
        if not (submitted_nonce and (hmac.compare_digest(submitted_nonce, expected_nonce) if expected_nonce else False)):
            if not (submitted_nonce and prior_code and
                    hmac.compare_digest(prior_code, hmac.new(str(current_app.secret_key).encode(),
                    submitted_nonce.encode(), hashlib.sha256).hexdigest()[:32].upper())):
                errors.append("انتهت صلاحية نموذج الإرسال. حدّث الصفحة وحاول مرة أخرى.")

        if not errors:
            try:
                attachment_path = _save_attachment(request.files.get("attachment"))
            except ValueError as exc:
                errors.append(str(exc))
            else:
                report = ReportInput(**{key: values[key] for key in
                                        ("title", "description", "city", "district", "landmark")})
                tracking_code = _new_tracking_code(submitted_nonce)
                try:
                    report_id, created = store.submit_report(
                        report, _tracking_hash(tracking_code), attachment_path,
                        float(values["latitude"]) if values["latitude"] else None,
                        float(values["longitude"]) if values["longitude"] else None,
                    )
                    if not created and attachment_path:
                        Path(attachment_path).unlink(missing_ok=True)
                except Exception:
                    if attachment_path:
                        Path(attachment_path).unlink(missing_ok=True)
                    current_app.logger.exception("Report creation failed")
                    errors.append("تعذر حفظ البلاغ الآن. حاول مرة أخرى.")
                    return render_template("citizen/home.html", values=values, errors=errors,
                                           submission_nonce=session.get("submission_nonce", "")), 503
                session["last_submission"] = {
                    "report_id": report_id,
                    "tracking_code": tracking_code,
                }
                session["submission_nonce"] = secrets.token_urlsafe(24)
                return redirect(url_for("citizen.submitted"))

    if not session.get("submission_nonce"):
        session["submission_nonce"] = secrets.token_urlsafe(24)
    return render_template("citizen/home.html", values=values, errors=errors,
                           submission_nonce=session.get("submission_nonce", ""))


@citizen_bp.get("/submitted")
def submitted():
    submission = session.get("last_submission")
    if not submission:
        return redirect(url_for("citizen.home"))

    view = store.case_view(int(submission["report_id"]))
    if view is None:
        return redirect(url_for("citizen.home"))

    return render_template(
        "citizen/result.html",
        report=view["report"],
        tracking_code=submission["tracking_code"],
    )


@citizen_bp.route("/track", methods=["GET", "POST"])
def track():
    tracking_code = ""
    report = None
    decision = None
    error = ""

    if request.method == "POST":
        if current_app.config.get("RATE_LIMIT_ENABLED", True) and not consume_rate_limit(
            "track", request.remote_addr or "unknown", 20, 3600
        ):
            return render_template("citizen/track.html", tracking_code="", report=None,
                                   decision=None, error="تم تجاوز حد المحاولات المؤقت. حاول لاحقًا."), 429
        tracking_code = request.form.get("tracking_code", "").strip().upper()
        if not tracking_code:
            error = "أدخل رمز المتابعة."
        else:
            report = database.get_report_by_tracking_hash(_tracking_hash(tracking_code))
            if report is None:
                error = "لم يتم العثور على بلاغ بهذا الرمز."
            else:
                view = store.case_view(int(report["id"]))
                decision = view["decision"] if view else None

    return render_template(
        "citizen/track.html",
        tracking_code=tracking_code,
        report=report,
        decision=decision,
        error=error,
        status_ar=_status_ar,
        priority_ar=_priority_ar,
        category_ar=category_label,
    )


@citizen_bp.app_errorhandler(413)
def attachment_too_large(_error):
    return render_template(
        "citizen/home.html",
        values={"title": "", "description": "", "city": "", "district": "", "landmark": "", "latitude": "", "longitude": ""},
        errors=["حجم الطلب أكبر من 5 ميجابايت."],
    ), 413
