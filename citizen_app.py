from __future__ import annotations

from pathlib import Path
from uuid import uuid4
from html import escape

import streamlit as st

from balagh.database import DATA_DIR, create_report, get_open_reports, get_report, init_db
from balagh.triage import ReportInput, build_case_markdown, triage_report


PROJECT_ROOT = Path(__file__).resolve().parent
UI_DIR = PROJECT_ROOT / "ui"
UPLOAD_DIR = DATA_DIR / "uploads"


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _apply_ui() -> None:
    st.markdown(f"<style>{_load_text(UI_DIR / 'style.css')}</style>", unsafe_allow_html=True)
    st.markdown(_load_text(UI_DIR / "citizen.html"), unsafe_allow_html=True)


def _save_attachment(uploaded_file) -> str | None:
    if uploaded_file is None:
        return None

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(uploaded_file.name).suffix.lower()
    destination = UPLOAD_DIR / f"{uuid4().hex}{suffix}"
    destination.write_bytes(uploaded_file.getbuffer())
    return str(destination)


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


def _status_class(status: str) -> str:
    return {
        "Open": "blue",
        "In Progress": "amber",
        "Resolved": "green",
        "Closed": "gray",
    }.get(status, "gray")


def _summary_card(label: str, value: str, note: str = "") -> str:
    return f"""
    <div class="summary-card">
        <div class="summary-label">{escape(label)}</div>
        <div class="summary-value">{escape(value)}</div>
        <div class="summary-note">{escape(note)}</div>
    </div>
    """


def main() -> None:
    st.set_page_config(
        page_title="بلاغ | بوابة المواطن",
        page_icon="📍",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    init_db()
    _apply_ui()

    st.markdown('<div class="section-heading">كيف نقدر نخدمك؟</div>', unsafe_allow_html=True)
    st.caption("أرسل بلاغًا جديدًا أو تابع بلاغًا سبق رفعه.")

    submit_tab, track_tab = st.tabs(["＋ إرسال بلاغ", "⌕ متابعة بلاغ"])

    with submit_tab:
        st.markdown("### بيانات البلاغ")
        st.caption("اكتب وصفًا واضحًا للمشكلة وحدد موقعها قدر الإمكان.")

        with st.form("citizen_report_form", clear_on_submit=False):
            title = st.text_input(
                "عنوان البلاغ",
                placeholder="مثال: حفرة كبيرة في الشارع",
            )

            description = st.text_area(
                "وصف المشكلة",
                placeholder="ما المشكلة؟ متى بدأت؟ وكيف تؤثر على المكان أو المارة؟",
                height=150,
            )

            c1, c2 = st.columns(2)
            city = c1.text_input("المدينة", placeholder="الرياض")
            district = c2.text_input("الحي", placeholder="الروابي")

            landmark = st.text_input(
                "الموقع أو معلم قريب",
                placeholder="مثال: مقابل المدرسة أو بجوار الحديقة",
            )

            attachment = st.file_uploader(
                "إرفاق صورة",
                type=["png", "jpg", "jpeg", "webp"],
                help="اختياري — الصورة تساعد الموظف على فهم الحالة بشكل أسرع.",
            )

            submitted = st.form_submit_button(
                "إرسال البلاغ",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            if not all([title.strip(), description.strip(), city.strip(), district.strip()]):
                st.error("أكمل عنوان البلاغ والوصف والمدينة والحي.")
            else:
                report = ReportInput(
                    title=title.strip(),
                    description=description.strip(),
                    city=city.strip(),
                    district=district.strip(),
                    landmark=landmark.strip(),
                )

                result = triage_report(
                    report,
                    existing_reports=get_open_reports(),
                    language="Arabic",
                )

                report_id = create_report(
                    report,
                    result,
                    language="Arabic",
                    attachment_path=_save_attachment(attachment),
                )

                st.markdown(
                    f"""
                    <div class="success-panel">
                        <div class="success-icon">✓</div>
                        <div>
                            <div class="success-title">تم استلام بلاغك</div>
                            <div class="success-text">احتفظ برقم المتابعة</div>
                            <div class="tracking-id">BLG-{report_id:05d}</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if result.emergency_warning:
                    st.error(result.emergency_warning)

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(
                        _summary_card("الأولوية الأولية", _priority_ar(result.priority)),
                        unsafe_allow_html=True,
                    )
                with c2:
                    st.markdown(
                        _summary_card("التصنيف الأولي", result.category),
                        unsafe_allow_html=True,
                    )

                st.info(result.acknowledgment)

                case_markdown = build_case_markdown(result, report_id)
                st.download_button(
                    "تحميل ملخص البلاغ",
                    case_markdown.encode("utf-8"),
                    file_name=f"BLG-{report_id:05d}.md",
                    mime="text/markdown",
                    use_container_width=True,
                )

    with track_tab:
        st.markdown("### متابعة حالة البلاغ")
        st.caption("أدخل الرقم الموجود بعد BLG- في رقم المتابعة.")

        with st.container(border=True):
            report_id = st.number_input(
                "رقم البلاغ",
                min_value=1,
                step=1,
                placeholder="مثال: 12",
            )

            lookup = st.button(
                "عرض حالة البلاغ",
                type="primary",
                use_container_width=True,
            )

        if lookup:
            row = get_report(int(report_id))

            if row is None:
                st.error("لم يتم العثور على بلاغ بهذا الرقم.")
            else:
                status_class = _status_class(row["status"])
                st.markdown(
                    f"""
                    <div class="case-result">
                        <div class="case-result-top">
                            <div>
                                <div class="case-number">BLG-{int(row['id']):05d}</div>
                                <div class="case-title">{escape(str(row['title']))}</div>
                                <div class="case-location">{escape(str(row['city']))}، {escape(str(row['district']))}</div>
                            </div>
                            <span class="status-pill {status_class}">{escape(_status_ar(row['status']))}</span>
                        </div>
                        <div class="case-result-grid">
                            <div>
                                <span>الأولوية</span>
                                <strong>{escape(_priority_ar(row['priority']))}</strong>
                            </div>
                            <div>
                                <span>التصنيف</span>
                                <strong>{escape(str(row['category']))}</strong>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )



if __name__ == "__main__":
    main()
