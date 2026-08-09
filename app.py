from __future__ import annotations

import html
import os
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

from balagh.core import (
    ReportInput,
    TriageResult,
    build_case_markdown,
    triage_report,
)
from balagh.crew import generate_agent_review
from balagh.db import (
    fetch_open_reports,
    fetch_report_by_id,
    fetch_reports,
    init_db,
    insert_report,
    summary_metrics,
    update_status,
)


PROJECT_ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(
    page_title="بلاغ | منصة البلاغات المجتمعية",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()


# ---------------------------------------------------------------------
# Theme and layout
# ---------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;600;700;800&display=swap');

    :root {
        --navy: #082b4c;
        --navy-2: #0d365e;
        --green: #0b8f4d;
        --green-2: #14a762;
        --green-soft: #e8f7ef;
        --bg: #f4f7fb;
        --card: #ffffff;
        --text: #17243a;
        --muted: #6b778c;
        --border: #e2e8f0;
        --red: #d92d20;
        --red-soft: #fff0ef;
        --orange: #e68619;
        --orange-soft: #fff5e8;
        --blue: #2563eb;
        --blue-soft: #edf4ff;
    }

    html, body, [class*="css"], .stApp {
        font-family: "Tajawal", sans-serif !important;
    }

    .stApp {
        background: var(--bg);
        color: var(--text);
        direction: rtl;
    }

    header[data-testid="stHeader"] {
        background: rgba(255,255,255,0.96);
        border-bottom: 1px solid var(--border);
        height: 4.25rem;
    }

    .block-container {
        padding-top: 1.35rem;
        padding-bottom: 2.5rem;
        max-width: 1480px;
    }

    section[data-testid="stSidebar"] {
        background:
            radial-gradient(circle at 15% 5%, rgba(20,167,98,.20), transparent 26%),
            linear-gradient(180deg, var(--navy) 0%, #061f38 100%);
        border-left: 1px solid rgba(255,255,255,.08);
        width: 315px !important;
        min-width: 315px !important;
    }

    section[data-testid="stSidebar"] > div {
        padding-top: .75rem;
    }

    section[data-testid="stSidebar"] * {
        color: #ffffff;
    }

    section[data-testid="stSidebar"] .stCaption,
    section[data-testid="stSidebar"] small {
        color: rgba(255,255,255,.72) !important;
    }

    section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        margin-bottom: 0;
    }

    div[role="radiogroup"] {
        gap: .38rem;
    }

    div[role="radiogroup"] label {
        background: transparent;
        border-radius: 12px;
        padding: .76rem .9rem;
        transition: all .18s ease;
        border: 1px solid transparent;
    }

    div[role="radiogroup"] label:hover {
        background: rgba(255,255,255,.08);
        border-color: rgba(255,255,255,.08);
    }

    div[role="radiogroup"] label:has(input:checked) {
        background: linear-gradient(90deg, rgba(20,167,98,.98), rgba(11,143,77,.92));
        box-shadow: 0 10px 24px rgba(0,0,0,.16);
    }

    div[role="radiogroup"] label p {
        font-size: 1.02rem;
        font-weight: 700;
    }

    section[data-testid="stSidebar"] [data-testid="stSelectbox"] div[data-baseweb="select"] > div {
        background: rgba(255,255,255,.10);
        border-color: rgba(255,255,255,.18);
        color: #fff;
    }

    .balagh-brand {
        display: flex;
        align-items: center;
        gap: .9rem;
        padding: .75rem .4rem 1rem .4rem;
        margin-bottom: .6rem;
        border-bottom: 1px solid rgba(255,255,255,.12);
    }

    .balagh-logo {
        width: 62px;
        height: 62px;
        border-radius: 18px;
        display: grid;
        place-items: center;
        background: linear-gradient(145deg, #19b66c, #087943);
        box-shadow: 0 12px 30px rgba(0,0,0,.20);
        border: 2px solid rgba(255,255,255,.25);
        font-size: 30px;
    }

    .balagh-brand h1 {
        margin: 0;
        color: #fff;
        font-size: 1.72rem;
        line-height: 1;
        font-weight: 800;
    }

    .balagh-brand p {
        margin-top: .38rem !important;
        color: rgba(255,255,255,.74);
        font-size: .92rem;
    }

    .privacy-box {
        background: rgba(255,255,255,.08);
        border: 1px solid rgba(255,255,255,.14);
        border-radius: 14px;
        padding: .85rem 1rem;
        margin-top: 1rem;
        color: rgba(255,255,255,.83);
        font-size: .88rem;
        line-height: 1.7;
    }

    .top-shell {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 1rem;
        margin-bottom: 1.15rem;
    }

    .page-title {
        display: flex;
        align-items: center;
        gap: .8rem;
    }

    .page-title-icon {
        width: 48px;
        height: 48px;
        border-radius: 15px;
        display: grid;
        place-items: center;
        color: var(--green);
        background: var(--green-soft);
        font-size: 23px;
        font-weight: 800;
    }

    .page-title h2 {
        margin: 0;
        font-size: 2rem;
        font-weight: 800;
        color: var(--text);
    }

    .page-title p {
        margin: .2rem 0 0 0;
        color: var(--muted);
    }

    .top-meta {
        display: flex;
        align-items: center;
        gap: .55rem;
        color: var(--muted);
        font-size: .9rem;
    }

    .top-chip {
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 999px;
        padding: .48rem .8rem;
        box-shadow: 0 5px 18px rgba(16,24,40,.04);
    }

    .hero-card,
    .panel-card,
    .metric-card,
    .agent-card,
    .result-card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 17px;
        box-shadow: 0 10px 30px rgba(16,24,40,.055);
    }

    .hero-card {
        padding: 1.35rem 1.45rem;
        margin-bottom: 1rem;
        background:
            linear-gradient(135deg, rgba(11,143,77,.06), transparent 38%),
            #fff;
    }

    .hero-card h3 {
        margin: 0 0 .4rem 0;
        font-size: 1.35rem;
        color: var(--text);
    }

    .hero-card p {
        margin: 0;
        color: var(--muted);
        line-height: 1.8;
    }

    .metric-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 1rem;
        margin: 1rem 0 1.2rem 0;
    }

    .metric-card {
        padding: 1.05rem 1.1rem;
        min-height: 135px;
        position: relative;
        overflow: hidden;
    }

    .metric-card::after {
        content: "";
        position: absolute;
        left: -22px;
        bottom: -34px;
        width: 110px;
        height: 110px;
        border-radius: 50%;
        background: rgba(11,143,77,.06);
    }

    .metric-label {
        color: var(--muted);
        font-weight: 700;
        font-size: .95rem;
    }

    .metric-value {
        margin-top: .55rem;
        color: var(--text);
        font-size: 2.18rem;
        font-weight: 800;
        line-height: 1;
    }

    .metric-foot {
        margin-top: .55rem;
        color: var(--muted);
        font-size: .83rem;
    }

    .metric-card.red {
        border-bottom: 4px solid var(--red);
    }

    .metric-card.orange {
        border-bottom: 4px solid var(--orange);
    }

    .metric-card.green {
        border-bottom: 4px solid var(--green);
    }

    .metric-card.blue {
        border-bottom: 4px solid var(--blue);
    }

    .panel-card {
        padding: 1.15rem 1.2rem;
        margin-bottom: 1rem;
    }

    .panel-title {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: .9rem;
    }

    .panel-title h3 {
        margin: 0;
        font-size: 1.2rem;
        color: var(--text);
    }

    .panel-title span {
        color: var(--green);
        font-weight: 700;
        font-size: .92rem;
    }

    .badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: .28rem .62rem;
        border-radius: 999px;
        font-size: .78rem;
        font-weight: 800;
        white-space: nowrap;
    }

    .badge.green { color: #087943; background: #e9f8ef; }
    .badge.red { color: #b42318; background: #ffefed; }
    .badge.orange { color: #b35c00; background: #fff2df; }
    .badge.blue { color: #1d4ed8; background: #edf3ff; }
    .badge.gray { color: #475467; background: #eef2f6; }
    .badge.purple { color: #6941c6; background: #f2edff; }

    .balagh-table {
        width: 100%;
        border-collapse: collapse;
        overflow: hidden;
        border: 1px solid var(--border);
        border-radius: 12px;
    }

    .balagh-table th {
        background: #f8fafc;
        color: #475467;
        font-size: .82rem;
        padding: .72rem .68rem;
        text-align: right;
        border-bottom: 1px solid var(--border);
    }

    .balagh-table td {
        padding: .72rem .68rem;
        border-bottom: 1px solid #edf1f5;
        color: #344054;
        font-size: .88rem;
        vertical-align: middle;
    }

    .balagh-table tr:last-child td {
        border-bottom: 0;
    }

    .case-number {
        color: var(--green);
        font-weight: 800;
    }

    .form-shell {
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 1.35rem;
        box-shadow: 0 10px 30px rgba(16,24,40,.055);
    }

    [data-testid="stForm"] {
        border: 0;
        padding: 0;
    }

    .stTextInput input,
    .stTextArea textarea,
    .stSelectbox div[data-baseweb="select"] > div,
    .stNumberInput input {
        border-radius: 11px !important;
        border-color: #d7dee8 !important;
        background: #fff !important;
    }

    .stTextInput input:focus,
    .stTextArea textarea:focus {
        border-color: var(--green) !important;
        box-shadow: 0 0 0 3px rgba(11,143,77,.11) !important;
    }

    .stButton > button,
    .stDownloadButton > button,
    [data-testid="stFormSubmitButton"] > button {
        border-radius: 10px;
        font-weight: 800;
        min-height: 2.75rem;
        border: 1px solid var(--green);
    }

    .stButton > button[kind="primary"],
    [data-testid="stFormSubmitButton"] > button[kind="primary"] {
        background: linear-gradient(90deg, var(--green), var(--green-2));
        color: white;
        box-shadow: 0 10px 22px rgba(11,143,77,.18);
    }

    .result-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 1rem;
        margin: 1rem 0;
    }

    .result-card {
        text-align: center;
        padding: 1.15rem .8rem;
    }

    .result-card .icon {
        margin: 0 auto .55rem auto;
        width: 56px;
        height: 56px;
        border-radius: 50%;
        display: grid;
        place-items: center;
        font-size: 24px;
        background: var(--green-soft);
    }

    .result-card .label {
        color: var(--muted);
        font-size: .88rem;
        font-weight: 700;
    }

    .result-card .value {
        margin-top: .28rem;
        color: var(--text);
        font-size: 1.25rem;
        font-weight: 800;
    }

    .agent-layout {
        display: grid;
        grid-template-columns: 1.05fr 1fr;
        gap: 1rem;
        align-items: start;
    }

    .agent-card {
        padding: 1rem;
        margin-bottom: .75rem;
        display: flex;
        gap: .9rem;
        align-items: flex-start;
    }

    .agent-avatar {
        min-width: 52px;
        width: 52px;
        height: 52px;
        border-radius: 50%;
        display: grid;
        place-items: center;
        color: white;
        background: linear-gradient(145deg, var(--navy), var(--green));
        font-size: 22px;
        border: 4px solid #e7f6ef;
    }

    .agent-card h4 {
        margin: 0;
        color: var(--text);
        font-size: 1rem;
    }

    .agent-card p {
        margin: .35rem 0 0 0;
        color: var(--muted);
        font-size: .86rem;
        line-height: 1.65;
    }

    .soft-success {
        background: #effaf4;
        border: 1px solid #bce8ce;
        color: #087943;
        border-radius: 13px;
        padding: .9rem 1rem;
        font-weight: 700;
        margin-bottom: 1rem;
    }

    .info-row {
        display: flex;
        gap: .55rem;
        align-items: flex-start;
        padding: .65rem 0;
        border-bottom: 1px solid #edf1f5;
    }

    .info-row:last-child {
        border-bottom: 0;
    }

    .info-row strong {
        color: var(--text);
    }

    .info-row span {
        color: var(--muted);
    }

    [data-testid="stDataFrame"] {
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 14px;
        overflow: hidden;
        box-shadow: 0 8px 22px rgba(16,24,40,.04);
    }

    .footer-note {
        text-align: center;
        color: #98a2b3;
        font-size: .78rem;
        margin-top: 2rem;
        padding-top: 1rem;
        border-top: 1px solid var(--border);
    }

    @media (max-width: 1100px) {
        .metric-grid,
        .result-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .agent-layout {
            grid-template-columns: 1fr;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
NAV_ITEMS = [
    "🏠 لوحة التحكم",
    "➕ إضافة بلاغ",
    "📊 نتيجة التحليل",
    "📋 البلاغات",
    "🧠 مراجعة الوكلاء",
    "📦 رفع مجموعة",
    "⚙️ الإعدادات",
]

if "nav_page" not in st.session_state:
    st.session_state["nav_page"] = NAV_ITEMS[0]

# Streamlit does not allow changing a widget-backed session key after the
# widget has already been created during the same run. Navigation requests
# are therefore queued here and applied before the sidebar radio is built.
if "pending_nav_page" in st.session_state:
    st.session_state["nav_page"] = st.session_state.pop("pending_nav_page")


def page_title(icon: str, title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="top-shell">
          <div class="page-title">
            <div class="page-title-icon">{icon}</div>
            <div>
              <h2>{html.escape(title)}</h2>
              <p>{html.escape(subtitle)}</p>
            </div>
          </div>
          <div class="top-meta">
            <span class="top-chip">🔒 بيانات محلية</span>
            <span class="top-chip">🟢 النظام يعمل</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def badge(text: object, kind: str = "gray") -> str:
    return f'<span class="badge {kind}">{html.escape(str(text))}</span>'


def priority_badge(priority: object) -> str:
    value = str(priority)
    mapping = {
        "Critical": ("حرجة", "red"),
        "High": ("عالية", "red"),
        "Medium": ("متوسطة", "orange"),
        "Low": ("منخفضة", "green"),
    }
    label, kind = mapping.get(value, (value, "gray"))
    return badge(label, kind)


def status_badge(status: object) -> str:
    value = str(status)
    mapping = {
        "Open": ("مفتوح", "green"),
        "In Progress": ("قيد المعالجة", "blue"),
        "Resolved": ("تم الحل", "purple"),
        "Closed": ("مغلق", "gray"),
    }
    label, kind = mapping.get(value, (value, "gray"))
    return badge(label, kind)


def category_badge(category: object) -> str:
    value = str(category)
    mapping = {
        "Roads & Sidewalks": ("طرق وأرصفة", "purple"),
        "Waste & Cleanliness": ("النظافة", "green"),
        "Street Lighting & Electrical": ("الإنارة", "orange"),
        "Water & Drainage": ("المياه", "blue"),
        "Accessibility": ("إتاحة الوصول", "purple"),
        "Public Facilities": ("المرافق العامة", "green"),
        "Noise & Community Disturbance": ("الإزعاج", "orange"),
        "General Community Services": ("خدمات عامة", "gray"),
    }
    label, kind = mapping.get(value, (value, "gray"))
    return badge(label, kind)


def metric_card(label: str, value: object, foot: str, kind: str) -> str:
    return f"""
    <div class="metric-card {kind}">
      <div class="metric-label">{html.escape(label)}</div>
      <div class="metric-value">{html.escape(str(value))}</div>
      <div class="metric-foot">{html.escape(foot)}</div>
    </div>
    """


def render_metrics(metrics: dict[str, int]) -> None:
    st.markdown(
        """
        <div class="metric-grid">
        """
        + metric_card("إجمالي البلاغات", metrics["total"], "جميع البلاغات المسجلة", "green")
        + metric_card("بلاغات حرجة", metrics["critical"], "تتطلب مراجعة عاجلة", "red")
        + metric_card("بلاغات مكررة", metrics["duplicates"], "تم ربطها بحالات مشابهة", "orange")
        + metric_card("بلاغات مغلقة", metrics["closed"], "تمت معالجتها أو إغلاقها", "blue")
        + "</div>",
        unsafe_allow_html=True,
    )


def render_reports_table(frame: pd.DataFrame, limit: int = 6) -> None:
    if frame.empty:
        st.info("لا توجد بلاغات محفوظة حتى الآن.")
        return

    rows = []
    for _, row in frame.head(limit).iterrows():
        duplicate = (
            badge(f"#{int(row['duplicate_of'])}", "red")
            if pd.notna(row.get("duplicate_of"))
            else badge("لا", "green")
        )
        rows.append(
            "<tr>"
            f"<td><span class='case-number'>BLG-{int(row['id']):05d}</span></td>"
            f"<td>{html.escape(str(row['title']))}</td>"
            f"<td>{html.escape(str(row['district']))}</td>"
            f"<td>{category_badge(row['category'])}</td>"
            f"<td>{priority_badge(row['priority'])}</td>"
            f"<td>{status_badge(row['status'])}</td>"
            f"<td>{duplicate}</td>"
            "</tr>"
        )

    table = f"""
    <div class="panel-card">
      <div class="panel-title">
        <h3>أحدث البلاغات</h3>
        <span>عرض مختصر للحالات الأخيرة</span>
      </div>
      <div style="overflow-x:auto">
        <table class="balagh-table">
          <thead>
            <tr>
              <th>رقم البلاغ</th>
              <th>العنوان</th>
              <th>الحي</th>
              <th>التصنيف</th>
              <th>الأولوية</th>
              <th>الحالة</th>
              <th>مشابه</th>
            </tr>
          </thead>
          <tbody>
            {''.join(rows)}
          </tbody>
        </table>
      </div>
    </div>
    """
    st.markdown(table, unsafe_allow_html=True)


def save_attachment(uploaded_file) -> str | None:
    if uploaded_file is None:
        return None

    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("نوع الصورة غير مدعوم.")

    filename = f"{uuid.uuid4().hex}{suffix}"
    target = UPLOAD_DIR / filename
    target.write_bytes(uploaded_file.getbuffer())
    return str(target.relative_to(PROJECT_ROOT))


def triage_from_db_row(row: dict) -> TriageResult:
    missing_raw = str(row.get("missing_information") or "").strip()
    missing = [item.strip() for item in missing_raw.split("|") if item.strip()]
    return TriageResult(
        category=str(row["category"]),
        priority=str(row["priority"]),
        department=str(row["department"]),
        reasoning=str(row["reasoning"]),
        missing_information=missing,
        duplicate_of=int(row["duplicate_of"]) if row.get("duplicate_of") is not None else None,
        duplicate_score=float(row.get("duplicate_score") or 0.0),
        acknowledgment=str(row["acknowledgment"]),
        emergency_warning=str(row["emergency_warning"]) if row.get("emergency_warning") else None,
    )


def show_result(result: TriageResult, report_id: int | None = None, attachment_path: str | None = None) -> None:
    duplicate_value = (
        f"#{result.duplicate_of} ({result.duplicate_score:.0%})"
        if result.duplicate_of
        else "لا يوجد"
    )

    st.markdown(
        """
        <div class="result-grid">
          <div class="result-card">
            <div class="icon">🛣️</div>
            <div class="label">التصنيف</div>
            <div class="value">"""
        + html.escape(result.category)
        + """</div>
          </div>
          <div class="result-card">
            <div class="icon">⚠️</div>
            <div class="label">الأولوية</div>
            <div class="value">"""
        + html.escape(result.priority)
        + """</div>
          </div>
          <div class="result-card">
            <div class="icon">🏛️</div>
            <div class="label">الجهة</div>
            <div class="value">"""
        + html.escape(result.department)
        + """</div>
          </div>
          <div class="result-card">
            <div class="icon">📎</div>
            <div class="label">بلاغ مشابه</div>
            <div class="value">"""
        + html.escape(duplicate_value)
        + """</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if result.emergency_warning:
        st.error(result.emergency_warning)

    left, right = st.columns([1.35, 1])

    with left:
        st.markdown(
            f"""
            <div class="panel-card">
              <div class="panel-title"><h3>ملخص القرار</h3><span>قرار قابل للتفسير</span></div>
              <div class="info-row"><strong>السبب:</strong><span>{html.escape(result.reasoning)}</span></div>
              <div class="info-row"><strong>التوجيه:</strong><span>{html.escape(result.department)}</span></div>
              <div class="info-row"><strong>التشابه:</strong><span>{html.escape(duplicate_value)}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        missing_html = (
            "".join(f"<li>{html.escape(item)}</li>" for item in result.missing_information)
            if result.missing_information
            else "<li>لا توجد معلومات ناقصة أساسية.</li>"
        )
        st.markdown(
            f"""
            <div class="panel-card">
              <div class="panel-title"><h3>معلومات مقترحة للإضافة</h3><span>لتحسين جودة البلاغ</span></div>
              <ul style="line-height:1.9;color:#475467;margin-bottom:0">{missing_html}</ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with right:
        if attachment_path:
            absolute = PROJECT_ROOT / attachment_path
            if absolute.exists():
                st.image(str(absolute), caption="الصورة المرفقة مع البلاغ", use_container_width=True)

        st.markdown(
            """
            <div class="panel-card">
              <div class="panel-title"><h3>الرد المقترح</h3><span>جاهز للمراجعة</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.code(result.acknowledgment, language=None)

    case_md = build_case_markdown(result, language="Arabic", report_id=report_id)
    st.download_button(
        "تحميل ملخص البلاغ",
        case_md.encode("utf-8"),
        file_name=f"balagh_case_{report_id or 'preview'}.md",
        mime="text/markdown",
        use_container_width=True,
    )


# ---------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        """
        <div class="balagh-brand">
          <div class="balagh-logo">✓</div>
          <div>
            <h1>BALAGH | بلاغ</h1>
            <p>منصة فرز البلاغات المجتمعية</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.radio(
        "التنقل",
        NAV_ITEMS,
        key="nav_page",
        label_visibility="collapsed",
    )

    st.markdown(
        """
        <div class="privacy-box">
          <strong>🔒 خصوصية البيانات</strong><br>
          تُحفظ البلاغات والصور محليًا على الجهاز، ولا يتم إرسالها إلى خدمة سحابية.
        </div>
        """,
        unsafe_allow_html=True,
    )

page = st.session_state["nav_page"]


# ---------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------
if page == "🏠 لوحة التحكم":
    page_title("▦", "لوحة التحكم", "متابعة البلاغات والأولويات وحالة المعالجة.")

    st.markdown(
        """
        <div class="hero-card">
          <h3>منصة موحدة للبلاغات المجتمعية</h3>
          <p>
            يستقبل النظام البلاغ، يصنفه، يحدد أولويته، يوجهه للجهة المناسبة،
            ثم يبحث عن الحالات المشابهة لتقليل التكرار وتسريع المتابعة.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metrics = summary_metrics()
    render_metrics(metrics)
    reports = fetch_reports(limit=100)
    render_reports_table(reports, limit=6)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            """
            <div class="panel-card">
              <div class="panel-title"><h3>أكثر التصنيفات ورودًا</h3><span>حسب البلاغات المسجلة</span></div>
            """,
            unsafe_allow_html=True,
        )
        if not reports.empty:
            chart = reports["category"].value_counts().head(7)
            st.bar_chart(chart, horizontal=True, color="#0b8f4d")
        else:
            st.info("لا توجد بيانات كافية.")
        st.markdown("</div>", unsafe_allow_html=True)

    with c2:
        st.markdown(
            """
            <div class="panel-card">
              <div class="panel-title"><h3>حالة البلاغات</h3><span>توزيع مراحل المعالجة</span></div>
            """,
            unsafe_allow_html=True,
        )
        if not reports.empty:
            status_chart = reports["status"].value_counts()
            st.bar_chart(status_chart, color="#2563eb")
        else:
            st.info("لا توجد بيانات كافية.")
        st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------
# New report
# ---------------------------------------------------------------------
elif page == "➕ إضافة بلاغ":
    page_title("＋", "بلاغ جديد", "أدخل تفاصيل المشكلة وسيتم تحليلها وفرزها وحفظها.")

    st.markdown('<div class="form-shell">', unsafe_allow_html=True)
    with st.form("new_report_form", clear_on_submit=False):
        title = st.text_input(
            "عنوان البلاغ *",
            placeholder="مثال: حفرة كبيرة في الشارع",
        )
        description = st.text_area(
            "وصف المشكلة *",
            placeholder="اكتب وصفًا واضحًا للمشكلة وتأثيرها ومتى بدأت...",
            height=170,
        )

        c1, c2 = st.columns(2)
        with c1:
            city = st.text_input("المدينة *", placeholder="الرياض")
        with c2:
            district = st.text_input("الحي *", placeholder="الروابي")

        landmark = st.text_input(
            "معلم قريب أو وصف أدق للموقع",
            placeholder="مثال: بجوار الحديقة أو مقابل المدرسة",
        )

        photo = st.file_uploader(
            "صورة المشكلة (اختياري)",
            type=["png", "jpg", "jpeg", "webp"],
            help="تُحفظ الصورة محليًا مع رقم البلاغ.",
        )

        submitted = st.form_submit_button(
            "تحليل البلاغ وحفظه",
            type="primary",
            use_container_width=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    if submitted:
        if not all([title.strip(), description.strip(), city.strip(), district.strip()]):
            st.error("العنوان والوصف والمدينة والحي مطلوبة.")
        else:
            try:
                attachment_path = save_attachment(photo)
                report = ReportInput(
                    title=title.strip(),
                    description=description.strip(),
                    city=city.strip(),
                    district=district.strip(),
                    landmark=landmark.strip(),
                )
                result = triage_report(
                    report,
                    existing_reports=fetch_open_reports(),
                    language="Arabic",
                )
                report_id = insert_report(
                    report,
                    result,
                    language="Arabic",
                    attachment_path=attachment_path,
                )
                st.session_state["last_result"] = result
                st.session_state["last_report_id"] = report_id
                st.session_state["last_attachment_path"] = attachment_path
                # Queue the destination for the next run instead of changing
                # the radio widget's key after it has already been instantiated.
                st.session_state["pending_nav_page"] = "📊 نتيجة التحليل"
                st.rerun()
            except Exception as exc:
                st.error(f"تعذر حفظ البلاغ: {exc}")


# ---------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------
elif page == "📊 نتيجة التحليل":
    page_title("✓", "نتيجة التحليل", "تم فرز البلاغ وتحديد الأولوية والجهة المختصة.")

    result = st.session_state.get("last_result")
    report_id = st.session_state.get("last_report_id")
    attachment_path = st.session_state.get("last_attachment_path")

    if result is None:
        reports = fetch_reports(limit=100)
        if reports.empty:
            st.info("لا توجد نتيجة لعرضها. أضف بلاغًا جديدًا أولًا.")
        else:
            selected_id = st.selectbox(
                "اختر رقم بلاغ محفوظ",
                reports["id"].astype(int).tolist(),
                format_func=lambda value: f"BLG-{int(value):05d}",
            )
            row = fetch_report_by_id(int(selected_id))
            if row:
                result = triage_from_db_row(row)
                report_id = int(selected_id)
                attachment_path = row.get("attachment_path")

    if result is not None:
        st.markdown(
            f"""
            <div class="soft-success">
              ✓ تم استلام البلاغ وتحليله بنجاح
              {" — رقم البلاغ: BLG-" + str(int(report_id)).zfill(5) if report_id else ""}
            </div>
            """,
            unsafe_allow_html=True,
        )
        show_result(result, report_id, attachment_path)


# ---------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------
elif page == "📋 البلاغات":
    page_title("☷", "البلاغات", "استعراض الحالات وفرزها وتحديث مرحلة المعالجة.")

    reports = fetch_reports(limit=500)
    if reports.empty:
        st.info("لا توجد بلاغات محفوظة.")
    else:
        f1, f2, f3 = st.columns(3)
        with f1:
            category_filter = st.selectbox(
                "التصنيف",
                ["الكل"] + sorted(reports["category"].dropna().unique().tolist()),
            )
        with f2:
            priority_filter = st.selectbox(
                "الأولوية",
                ["الكل"] + sorted(reports["priority"].dropna().unique().tolist()),
            )
        with f3:
            status_filter = st.selectbox(
                "الحالة",
                ["الكل"] + sorted(reports["status"].dropna().unique().tolist()),
            )

        filtered = reports.copy()
        if category_filter != "الكل":
            filtered = filtered[filtered["category"] == category_filter]
        if priority_filter != "الكل":
            filtered = filtered[filtered["priority"] == priority_filter]
        if status_filter != "الكل":
            filtered = filtered[filtered["status"] == status_filter]

        st.dataframe(
            filtered,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.NumberColumn("رقم البلاغ", format="BLG-%05d"),
                "created_at": "تاريخ الإنشاء",
                "title": "العنوان",
                "city": "المدينة",
                "district": "الحي",
                "category": "التصنيف",
                "priority": "الأولوية",
                "department": "الجهة",
                "status": "الحالة",
                "duplicate_of": "بلاغ مشابه",
                "duplicate_score": st.column_config.ProgressColumn(
                    "نسبة التشابه",
                    min_value=0,
                    max_value=1,
                    format="%.0f%%",
                ),
            },
        )

        st.markdown(
            """
            <div class="panel-card">
              <div class="panel-title"><h3>تحديث حالة بلاغ</h3><span>متابعة دورة المعالجة</span></div>
            """,
            unsafe_allow_html=True,
        )
        u1, u2, u3 = st.columns([1, 1.5, 1])
        with u1:
            report_id_value = st.number_input("رقم البلاغ", min_value=1, step=1)
        with u2:
            new_status = st.selectbox(
                "الحالة الجديدة",
                ["Open", "In Progress", "Resolved", "Closed"],
                format_func=lambda value: {
                    "Open": "مفتوح",
                    "In Progress": "قيد المعالجة",
                    "Resolved": "تم الحل",
                    "Closed": "مغلق",
                }[value],
            )
        with u3:
            st.write("")
            st.write("")
            if st.button("تحديث الحالة", type="primary", use_container_width=True):
                if update_status(int(report_id_value), new_status):
                    st.success("تم تحديث الحالة.")
                    st.rerun()
                else:
                    st.error("رقم البلاغ غير موجود.")
        st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------
# CrewAI review
# ---------------------------------------------------------------------
elif page == "🧠 مراجعة الوكلاء":
    page_title("✦", "مراجعة الوكلاء", "ثلاثة وكلاء يراجعون الفرز والتوجيه والرد المقترح.")

    reports = fetch_reports(limit=250)
    if reports.empty:
        st.info("أضف بلاغًا أولًا لتشغيل مراجعة الوكلاء.")
    else:
        selected_id = st.selectbox(
            "اختر البلاغ",
            reports["id"].astype(int).tolist(),
            format_func=lambda value: f"BLG-{int(value):05d}",
        )
        row = fetch_report_by_id(int(selected_id))
        if row:
            result = triage_from_db_row(row)

            st.markdown(
                """
                <div class="agent-layout">
                  <div>
                    <div class="agent-card">
                      <div class="agent-avatar">✓</div>
                      <div>
                        <h4>Civic Triage Reviewer</h4>
                        <p>يراجع صحة التصنيف والأولوية ويحدد ما يحتاج إلى تحقق بشري.</p>
                      </div>
                    </div>
                    <div class="agent-card">
                      <div class="agent-avatar">↗</div>
                      <div>
                        <h4>Service Routing Reviewer</h4>
                        <p>يتحقق من ملاءمة الجهة المختصة ومسار التصعيد الداخلي.</p>
                      </div>
                    </div>
                    <div class="agent-card">
                      <div class="agent-avatar">💬</div>
                      <div>
                        <h4>Citizen Communication Coordinator</h4>
                        <p>ينشئ مذكرة عمل وردًا واضحًا دون اختراع مواعيد أو وعود.</p>
                      </div>
                    </div>
                  </div>
                  <div class="panel-card">
                    <div class="panel-title"><h3>ملخص البلاغ المحدد</h3><span>BLG-"""
                + str(int(selected_id)).zfill(5)
                + """</span></div>
                    <div class="info-row"><strong>التصنيف:</strong><span>"""
                + html.escape(result.category)
                + """</span></div>
                    <div class="info-row"><strong>الأولوية:</strong><span>"""
                + html.escape(result.priority)
                + """</span></div>
                    <div class="info-row"><strong>الجهة:</strong><span>"""
                + html.escape(result.department)
                + """</span></div>
                    <div class="info-row"><strong>الرد:</strong><span>"""
                + html.escape(result.acknowledgment)
                + """</span></div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if st.button("تشغيل مراجعة CrewAI", type="primary", use_container_width=True):
                with st.spinner("الوكلاء يراجعون البلاغ محليًا..."):
                    try:
                        review = generate_agent_review(
                            report_id=int(selected_id),
                            report=result,
                            language="Arabic",
                        )
                        st.session_state[f"review_{selected_id}"] = review
                    except Exception as exc:
                        st.error(
                            "تعذر تشغيل الوكلاء، لكن نتيجة الفرز الأساسية ما زالت محفوظة.\n\n"
                            f"{exc}"
                        )

            review = st.session_state.get(f"review_{selected_id}")
            if review:
                st.markdown(
                    """
                    <div class="soft-success">
                      ✓ اكتملت مراجعة الوكلاء الثلاثة
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown(review)
                st.download_button(
                    "تحميل مراجعة الوكلاء",
                    review.encode("utf-8"),
                    file_name=f"balagh_agent_review_{selected_id}.md",
                    mime="text/markdown",
                    use_container_width=True,
                )


# ---------------------------------------------------------------------
# Batch import
# ---------------------------------------------------------------------
elif page == "📦 رفع مجموعة":
    page_title("⇧", "رفع مجموعة بلاغات", "استيراد عدد كبير من البلاغات من ملف CSV.")

    template_path = PROJECT_ROOT / "sample_data" / "reports_template.csv"
    st.download_button(
        "تحميل قالب CSV",
        template_path.read_bytes(),
        file_name="reports_template.csv",
        mime="text/csv",
    )

    csv_file = st.file_uploader("ملف البلاغات", type=["csv"])
    if csv_file:
        try:
            batch = pd.read_csv(csv_file)
        except Exception as exc:
            st.error(f"خطأ في قراءة الملف: {exc}")
            st.stop()

        required = {"title", "description", "city", "district"}
        missing = required - set(batch.columns)
        if missing:
            st.error("أعمدة ناقصة: " + ", ".join(sorted(missing)))
        else:
            st.dataframe(batch.head(25), use_container_width=True, hide_index=True)

            if st.button("تحليل وحفظ جميع البلاغات", type="primary"):
                outputs: list[dict] = []
                progress = st.progress(0.0)
                total = len(batch)

                for index, row in batch.iterrows():
                    report = ReportInput(
                        title=str(row.get("title", "")).strip(),
                        description=str(row.get("description", "")).strip(),
                        city=str(row.get("city", "")).strip(),
                        district=str(row.get("district", "")).strip(),
                        landmark=str(row.get("landmark", "")).strip()
                        if pd.notna(row.get("landmark", ""))
                        else "",
                    )

                    if not all([report.title, report.description, report.city, report.district]):
                        outputs.append(
                            {
                                "row": index + 1,
                                "status": "Rejected",
                                "reason": "Missing required values",
                            }
                        )
                        continue

                    result = triage_report(
                        report,
                        existing_reports=fetch_open_reports(),
                        language="Arabic",
                    )
                    report_id = insert_report(
                        report,
                        result,
                        language="Arabic",
                        attachment_path=None,
                    )
                    outputs.append(
                        {
                            "row": index + 1,
                            "report_id": report_id,
                            "category": result.category,
                            "priority": result.priority,
                            "department": result.department,
                            "duplicate_of": result.duplicate_of,
                            "duplicate_score": result.duplicate_score,
                            "status": "Saved",
                        }
                    )
                    progress.progress((index + 1) / max(total, 1))

                output_frame = pd.DataFrame(outputs)
                st.success("تمت معالجة المجموعة.")
                st.dataframe(output_frame, use_container_width=True, hide_index=True)
                st.download_button(
                    "تحميل النتائج",
                    output_frame.to_csv(index=False).encode("utf-8-sig"),
                    file_name="balagh_batch_results.csv",
                    mime="text/csv",
                )


# ---------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------
elif page == "⚙️ الإعدادات":
    page_title("⚙", "الإعدادات", "معلومات التشغيل المحلي والخصوصية وإعداد النموذج.")

    model = os.getenv("MODEL", "ollama/qwen3:4b-instruct")
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    st.markdown(
        f"""
        <div class="panel-card">
          <div class="panel-title"><h3>إعدادات الذكاء الاصطناعي</h3><span>تشغيل محلي</span></div>
          <div class="info-row"><strong>الموديل:</strong><span>{html.escape(model)}</span></div>
          <div class="info-row"><strong>خادم Ollama:</strong><span>{html.escape(host)}</span></div>
          <div class="info-row"><strong>الذاكرة:</strong><span>غير مفعلة للوكلاء لتجنب تخزين سياق غير مطلوب</span></div>
        </div>
        <div class="panel-card">
          <div class="panel-title"><h3>الخصوصية</h3><span>Local-first</span></div>
          <div class="info-row"><strong>قاعدة البيانات:</strong><span>SQLite داخل مجلد data</span></div>
          <div class="info-row"><strong>الصور:</strong><span>تُحفظ داخل data/uploads</span></div>
          <div class="info-row"><strong>الاتصال السحابي:</strong><span>غير مطلوب</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.markdown(
    """
    <div class="footer-note">
      بلاغ — منصة محلية لفرز البلاغات المجتمعية باستخدام Python وCrewAI وOllama
    </div>
    """,
    unsafe_allow_html=True,
)
