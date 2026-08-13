from __future__ import annotations

from pathlib import Path
from html import escape

import streamlit as st

from balagh.agents import generate_recommendation
from balagh.auth import verify_staff_access
from balagh.database import (
    get_agent_recommendation,
    get_case_history,
    get_report,
    get_reports,
    init_db,
    review_agent_recommendation,
    save_agent_recommendation,
    summary_metrics,
    update_report_status,
)


PROJECT_ROOT = Path(__file__).resolve().parent
UI_DIR = PROJECT_ROOT / "ui"


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _apply_ui() -> None:
    st.markdown(f"<style>{_load_text(UI_DIR / 'style.css')}</style>", unsafe_allow_html=True)
    st.markdown(_load_text(UI_DIR / "staff.html"), unsafe_allow_html=True)


def _metric_card(label: str, value: object, accent: str = "green") -> str:
    return f"""
    <div class="metric-card {accent}">
        <div class="metric-label">{escape(str(label))}</div>
        <div class="metric-value">{escape(str(value))}</div>
    </div>
    """


def _authenticated() -> bool:
    if st.session_state.get("staff_authenticated"):
        return True

    _, center, _ = st.columns([1.1, 2, 1.1])
    with center:
        st.markdown(
            """
            <div class="login-intro">
                <div class="login-icon">↳</div>
                <h2>دخول الموظف</h2>
                <p>أدخل رمز الوصول للانتقال إلى لوحة إدارة البلاغات.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("staff_login_form"):
            code = st.text_input(
                "رمز الوصول",
                type="password",
                placeholder="••••••••",
            )
            submitted = st.form_submit_button(
                "دخول إلى النظام",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            if verify_staff_access(code):
                st.session_state["staff_authenticated"] = True
                st.rerun()
            else:
                st.error("رمز الوصول غير صحيح.")

    return False


def _sidebar() -> str:
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-brand">
                <span class="brand-mark">ب</span>
                <div>
                    <strong>بلاغ</strong>
                    <small>بوابة الموظف</small>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.caption("إدارة ومراجعة البلاغات")
        st.divider()

        page = st.radio(
            "التنقل",
            ["لوحة التحكم", "البلاغات", "مراجعة حالة"],
            label_visibility="collapsed",
        )

        st.divider()
        st.caption("AI recommends → Human approves → System records")

        if st.button("تسجيل خروج", use_container_width=True):
            st.session_state["staff_authenticated"] = False
            st.rerun()

    return page


def _page_header(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="page-header">
            <div>
                <h1>{escape(title)}</h1>
                <p>{escape(subtitle)}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _dashboard() -> None:
    _page_header("لوحة التحكم", "نظرة سريعة على حالة البلاغات والتوصيات التي تحتاج مراجعة.")

    metrics = summary_metrics()
    cols = st.columns(5)

    cards = [
        ("إجمالي البلاغات", metrics["total"], "green"),
        ("بلاغات حرجة", metrics["critical"], "red"),
        ("مكررة محتملة", metrics["duplicates"], "amber"),
        ("منتهية", metrics["closed"], "blue"),
        ("بانتظار المراجعة", metrics["pending_ai"], "purple"),
    ]

    for column, (label, value, accent) in zip(cols, cards):
        with column:
            st.markdown(_metric_card(label, value, accent), unsafe_allow_html=True)

    st.markdown("### أحدث البلاغات")
    reports = get_reports(limit=12)

    if reports.empty:
        st.info("لا توجد بلاغات محفوظة.")
        return

    visible = reports[
        ["id", "title", "city", "district", "priority", "status", "created_at"]
    ].copy()
    visible["id"] = visible["id"].map(lambda value: f"BLG-{int(value):05d}")
    visible.columns = ["رقم البلاغ", "العنوان", "المدينة", "الحي", "الأولوية", "الحالة", "تاريخ الإنشاء"]

    st.dataframe(
        visible,
        use_container_width=True,
        hide_index=True,
        height=420,
    )


def _reports_page() -> None:
    _page_header("البلاغات", "ابحث وصفِّ البلاغات قبل فتح الحالة ومراجعتها.")

    reports = get_reports(limit=500)
    if reports.empty:
        st.info("لا توجد بلاغات محفوظة.")
        return

    with st.container(border=True):
        f1, f2, f3 = st.columns(3)

        category = f1.selectbox(
            "التصنيف",
            ["الكل"] + sorted(reports["category"].dropna().unique().tolist()),
        )
        priority = f2.selectbox(
            "الأولوية",
            ["الكل"] + sorted(reports["priority"].dropna().unique().tolist()),
        )
        status = f3.selectbox(
            "الحالة",
            ["الكل"] + sorted(reports["status"].dropna().unique().tolist()),
        )

    filtered = reports.copy()

    if category != "الكل":
        filtered = filtered[filtered["category"] == category]
    if priority != "الكل":
        filtered = filtered[filtered["priority"] == priority]
    if status != "الكل":
        filtered = filtered[filtered["status"] == status]

    st.caption(f"عدد النتائج: {len(filtered)}")

    visible = filtered[
        ["id", "title", "city", "district", "category", "priority", "status", "created_at"]
    ].copy()
    visible["id"] = visible["id"].map(lambda value: f"BLG-{int(value):05d}")
    visible.columns = [
        "رقم البلاغ", "العنوان", "المدينة", "الحي",
        "التصنيف", "الأولوية", "الحالة", "تاريخ الإنشاء"
    ]

    st.dataframe(
        visible,
        use_container_width=True,
        hide_index=True,
        height=560,
    )


def _case_review_page() -> None:
    _page_header(
        "مراجعة الحالة",
        "راجع بيانات البلاغ، ثم اطلب توصية الوكيلين واتخذ القرار النهائي كموظف.",
    )

    reports = get_reports(limit=500)
    if reports.empty:
        st.info("لا توجد بلاغات محفوظة.")
        return

    left, right = st.columns([2.2, 1])

    with right:
        report_id = st.selectbox(
            "البلاغ",
            reports["id"].astype(int).tolist(),
            format_func=lambda value: f"BLG-{int(value):05d}",
        )

    row = get_report(int(report_id))
    if row is None:
        st.error("تعذر تحميل البلاغ.")
        return

    with left:
        st.markdown(
            f"""
            <div class="case-header">
                <div>
                    <div class="case-number">BLG-{int(report_id):05d}</div>
                    <h2>{escape(str(row['title']))}</h2>
                    <p>{escape(str(row['city']))}، {escape(str(row['district']))}</p>
                </div>
                <span class="status-pill blue">{escape(str(row['status']))}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    details_tab, ai_tab, history_tab = st.tabs(
        ["تفاصيل البلاغ", "مراجعة الذكاء الاصطناعي", "سجل الحالة"]
    )

    with details_tab:
        st.markdown("#### وصف البلاغ")
        st.write(row["description"])

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(_metric_card("التصنيف", row["category"], "green"), unsafe_allow_html=True)
        with c2:
            st.markdown(_metric_card("الأولوية", row["priority"], "amber"), unsafe_allow_html=True)
        with c3:
            st.markdown(_metric_card("الجهة", row["department"], "blue"), unsafe_allow_html=True)

        st.markdown("#### نتيجة الفرز الحتمي")
        with st.container(border=True):
            st.write(row["reasoning"])

            if row.get("missing_information"):
                st.warning("معلومات مقترح استكمالها: " + row["missing_information"])

            if row.get("duplicate_of"):
                st.info(
                    f"بلاغ مشابه محتمل: BLG-{int(row['duplicate_of']):05d} "
                    f"— نسبة التشابه {float(row['duplicate_score']):.0%}"
                )

            if row.get("emergency_warning"):
                st.error(row["emergency_warning"])

        st.markdown("#### حالة البلاغ")
        statuses = ["Open", "In Progress", "Resolved", "Closed"]
        current_index = statuses.index(row["status"]) if row["status"] in statuses else 0

        status_col, button_col = st.columns([2, 1])
        new_status = status_col.selectbox(
            "الحالة الجديدة",
            statuses,
            index=current_index,
        )

        if button_col.button(
            "حفظ الحالة",
            type="primary",
            use_container_width=True,
        ):
            if new_status == row["status"]:
                st.info("الحالة لم تتغير.")
            elif update_report_status(int(report_id), new_status, actor="staff"):
                st.success("تم تحديث الحالة وتسجيل التغيير.")
                st.rerun()

    with ai_tab:
        st.markdown(
            """
            <div class="ai-rule">
                <strong>دور الذكاء الاصطناعي:</strong>
                تحليل الحالة وتقديم توصية فقط. القرار التنفيذي يبقى بيد الموظف.
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button(
            "تشغيل Triage Agent و Case Coordinator",
            type="primary",
            use_container_width=True,
        ):
            try:
                with st.spinner("يتم تحليل البلاغ ومراجعة السياق..."):
                    recommendation = generate_recommendation(
                        int(report_id),
                        language="Arabic",
                    )
                    recommendation_id = save_agent_recommendation(
                        int(report_id),
                        recommendation.triage_review,
                        recommendation.coordinator_review,
                        recommendation.final_recommendation,
                    )

                st.success(f"تم إنشاء التوصية #{recommendation_id}.")
                st.rerun()

            except Exception as exc:
                st.error(f"تعذر تشغيل الوكلاء: {exc}")

        stored = get_agent_recommendation(int(report_id))

        if not stored:
            st.info("لم يتم إنشاء توصية ذكاء اصطناعي لهذا البلاغ بعد.")
        else:
            st.markdown("#### توصية النظام")
            st.markdown(
                f"""
                <div class="recommendation-card">
                    <div class="recommendation-status">حالة التوصية: {escape(str(stored['decision']))}</div>
                    <div class="recommendation-text">{escape(str(stored['final_recommendation']))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.expander("تحليل Triage & Routing Agent"):
                st.write(stored["triage_review"])

            with st.expander("تحليل Case Coordinator Agent"):
                st.write(stored["coordinator_review"])

            if stored["decision"] == "Pending":
                st.markdown("#### قرار الموظف")

                decision = st.radio(
                    "القرار",
                    ["Approved", "Modified", "Rejected"],
                    horizontal=True,
                )

                reviewer_note = st.text_area(
                    "ملاحظة القرار",
                    placeholder="اكتب التعديل أو سبب الرفض عند الحاجة.",
                )

                if st.button(
                    "اعتماد قرار الموظف",
                    type="primary",
                    use_container_width=True,
                ):
                    try:
                        review_agent_recommendation(
                            int(stored["id"]),
                            decision,
                            reviewer_note,
                            actor="staff",
                        )
                        st.success("تم تسجيل القرار في سجل الحالة.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

    with history_tab:
        history = get_case_history(int(report_id))

        if history.empty:
            st.info("لا يوجد سجل لهذه الحالة بعد.")
        else:
            st.dataframe(
                history,
                use_container_width=True,
                hide_index=True,
                height=480,
            )


def main() -> None:
    st.set_page_config(
        page_title="بلاغ | بوابة الموظف",
        page_icon="🗂️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    init_db()
    _apply_ui()

    if not _authenticated():
        return

    page = _sidebar()

    if page == "لوحة التحكم":
        _dashboard()
    elif page == "البلاغات":
        _reports_page()
    else:
        _case_review_page()


if __name__ == "__main__":
    main()
