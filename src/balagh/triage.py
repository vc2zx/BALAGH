from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Mapping, Sequence


CATEGORY_RULES: dict[str, dict[str, object]] = {
    "Roads & Sidewalks": {
        "department": "Road and Sidewalk Maintenance",
        "keywords": [
            "pothole", "road damage", "broken road", "sidewalk", "curb",
            "حفرة", "حفر", "شارع", "طريق", "رصيف", "هبوط", "اسفلت", "أسفلت",
        ],
    },
    "Waste & Cleanliness": {
        "department": "Environmental and Cleaning Services",
        "keywords": [
            "trash", "garbage", "waste", "dumpster", "litter",
            "نفايات", "زبالة", "قمامة", "حاوية", "نظافة", "مخلفات",
        ],
    },
    "Street Lighting & Electrical": {
        "department": "Street Lighting and Electrical Safety",
        "keywords": [
            "street light", "lamp", "dark street", "electric", "wire", "lighting",
            "إنارة", "انارة", "عمود", "كهرباء", "سلك", "اسلاك", "أسلاك", "مظلم",
        ],
    },
    "Water & Drainage": {
        "department": "Water and Drainage Operations",
        "keywords": [
            "water leak", "sewage", "drain", "flood", "pipe",
            "تسرب", "مياه", "صرف", "مجاري", "غرق", "ماسورة", "أنبوب", "انبوب",
        ],
    },
    "Accessibility": {
        "department": "Accessibility and Inclusion Unit",
        "keywords": [
            "wheelchair", "accessible", "accessibility", "ramp", "disabled",
            "إعاقة", "اعاقة", "ذوي الإعاقة", "منحدر", "كرسي متحرك", "وصول",
        ],
    },
    "Public Facilities": {
        "department": "Public Facilities and Parks",
        "keywords": [
            "park", "playground", "bench", "public restroom", "facility",
            "حديقة", "منتزه", "دورة مياه", "مرفق", "ملاعب", "مقعد",
        ],
    },
    "Noise & Community Disturbance": {
        "department": "Community Compliance",
        "keywords": [
            "noise", "loud", "disturbance", "construction noise",
            "إزعاج", "ازعاج", "ضوضاء", "صوت مرتفع", "مزعج",
        ],
    },
}

CRITICAL_KEYWORDS = [
    "fire", "gas leak", "explosion", "electrocution", "live wire", "collapsed",
    "injured", "trapped", "active flooding", "حريق", "تسرب غاز", "انفجار",
    "صعق", "سلك مكشوف", "انهيار", "مصاب", "محاصر", "غرق شديد",
]

HIGH_KEYWORDS = [
    "school", "hospital", "mosque", "traffic signal", "large pothole",
    "sewage overflow", "blocked road", "elderly", "children", "مدرسة",
    "مستشفى", "مسجد", "إشارة", "اشارة", "حفرة كبيرة", "طفح",
    "طريق مغلق", "كبار السن", "أطفال", "اطفال",
]

LOCATION_TERMS = [
    "street", "road", "near", "beside", "opposite", "intersection",
    "شارع", "طريق", "بجوار", "مقابل", "تقاطع", "قرب",
]


@dataclass(frozen=True)
class ReportInput:
    title: str
    description: str
    city: str
    district: str
    landmark: str = ""


@dataclass(frozen=True)
class TriageResult:
    category: str
    priority: str
    department: str
    reasoning: str
    missing_information: list[str]
    duplicate_of: int | None
    duplicate_score: float
    acknowledgment: str
    emergency_warning: str | None


def normalize_text(text: object) -> str:
    value = str(text or "").lower().strip()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("ـ", "")
    value = re.sub(r"[^\w\s\u0600-\u06FF]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _tokens(text: str) -> set[str]:
    stopwords = {
        "the", "a", "an", "and", "or", "in", "on", "at", "to", "of", "report",
        "في", "من", "على", "الى", "إلى", "و", "او", "أو", "بلاغ", "عن",
    }
    aliases = {
        "street": "road",
        "roadway": "road",
        "شارع": "طريق",
        "الشارع": "طريق",
        "الطريق": "طريق",
        "بجوار": "قرب",
        "بالقرب": "قرب",
        "nearby": "near",
        "beside": "near",
    }
    tokens: set[str] = set()
    for token in normalize_text(text).split():
        if len(token) <= 1 or token in stopwords:
            continue
        tokens.add(aliases.get(token, token))
    return tokens


def classify_category(report: ReportInput) -> tuple[str, str, int]:
    text = normalize_text(
        " ".join([
            report.title,
            report.description,
            report.city,
            report.district,
            report.landmark,
        ])
    )

    best_category = "General Community Services"
    best_department = "General Service Coordination"
    best_score = 0

    for category, rule in CATEGORY_RULES.items():
        score = 0
        for keyword in rule["keywords"]:
            normalized_keyword = normalize_text(keyword)
            if normalized_keyword and normalized_keyword in text:
                score += 3 if " " in normalized_keyword else 1

        if score > best_score:
            best_score = score
            best_category = category
            best_department = str(rule["department"])

    return best_category, best_department, best_score


def assess_priority(
    report: ReportInput,
    category: str,
) -> tuple[str, list[str], str | None]:
    text = normalize_text(" ".join([report.title, report.description, report.landmark]))

    critical_hits = [
        keyword for keyword in CRITICAL_KEYWORDS if normalize_text(keyword) in text
    ]
    if critical_hits:
        warning = (
            "قد يكون البلاغ مرتبطًا بخطر فوري. تواصل مع خدمة الطوارئ المحلية "
            "المناسبة فورًا ولا تنتظر معالجة البلاغ داخل النظام."
        )
        return (
            "Critical",
            ["Potential immediate danger was detected: " + ", ".join(critical_hits[:3])],
            warning,
        )

    high_hits = [
        keyword for keyword in HIGH_KEYWORDS if normalize_text(keyword) in text
    ]
    if high_hits:
        return (
            "High",
            ["A sensitive place or high-impact condition was detected: " + ", ".join(high_hits[:3])],
            None,
        )

    if category in {"Street Lighting & Electrical", "Water & Drainage", "Accessibility"}:
        return (
            "High",
            [f"{category} issues may affect public safety or essential access."],
            None,
        )

    if category in {"Roads & Sidewalks", "Waste & Cleanliness"}:
        return (
            "Medium",
            [f"{category} is assigned a normal operational priority."],
            None,
        )

    return "Low", ["No immediate safety indicator was detected."], None


def find_missing_information(report: ReportInput) -> list[str]:
    missing: list[str] = []
    combined = normalize_text(" ".join([report.title, report.description, report.landmark]))

    if len(report.description.strip()) < 35:
        missing.append("More detailed issue description")

    if not report.landmark.strip() and not any(
        term in combined for term in map(normalize_text, LOCATION_TERMS)
    ):
        missing.append("Nearby landmark or precise location")

    if not re.search(r"\d", report.description):
        missing.append("Approximate quantity, size, or number affected")

    time_terms = [
        "today", "yesterday", "hour", "day", "منذ", "اليوم", "امس", "أمس", "ساعة", "يوم",
    ]
    if not any(normalize_text(word) in combined for word in time_terms):
        missing.append("When the issue started")

    return missing


def report_similarity(
    first_title: str,
    first_description: str,
    first_city: str,
    first_district: str,
    second_title: str,
    second_description: str,
    second_city: str,
    second_district: str,
) -> float:
    first_city_norm = normalize_text(first_city)
    second_city_norm = normalize_text(second_city)
    first_district_norm = normalize_text(first_district)
    second_district_norm = normalize_text(second_district)

    if first_city_norm != second_city_norm:
        return 0.0

    if first_district_norm != second_district_norm:
        return 0.0

    location_score = 1.0

    first_text = normalize_text(f"{first_title} {first_description}")
    second_text = normalize_text(f"{second_title} {second_description}")

    sequence_score = SequenceMatcher(None, first_text, second_text).ratio()
    first_tokens = _tokens(first_text)
    second_tokens = _tokens(second_text)
    union = first_tokens | second_tokens
    jaccard = len(first_tokens & second_tokens) / len(union) if union else 0.0

    # Location is intentionally meaningful for civic duplicate detection: two
    # reports in the same district that also describe substantially similar
    # text should rank above generic text matches elsewhere in the city.
    score = (0.35 * sequence_score) + (0.40 * jaccard) + (0.25 * location_score)
    return max(0.0, min(score, 1.0))


def detect_duplicate(
    report: ReportInput,
    existing_reports: Sequence[Mapping[str, object]],
    threshold: float = 0.64,
) -> tuple[int | None, float]:
    best_id: int | None = None
    best_score = 0.0

    for existing in existing_reports:
        score = report_similarity(
            report.title,
            report.description,
            report.city,
            report.district,
            str(existing.get("title", "")),
            str(existing.get("description", "")),
            str(existing.get("city", "")),
            str(existing.get("district", "")),
        )
        if score > best_score:
            best_score = score
            try:
                best_id = int(existing["id"])
            except (KeyError, TypeError, ValueError):
                best_id = None

    if best_score < threshold:
        return None, best_score

    return best_id, best_score


def build_acknowledgment(
    report: ReportInput,
    category: str,
    priority: str,
    department: str,
    duplicate_of: int | None,
    language: str,
) -> str:
    if language.lower() == "arabic":
        duplicate_note = (
            f" وتم ربطه مبدئيًا ببلاغ مشابه رقم {duplicate_of}."
            if duplicate_of
            else "."
        )
        return (
            f"تم استلام بلاغك عن «{report.title}» في حي {report.district}. "
            f"صُنّف البلاغ ضمن {category} وبأولوية {priority}، "
            f"وسيُوجّه إلى {department}{duplicate_note}"
        )

    duplicate_note = (
        f" It was provisionally linked to similar report #{duplicate_of}."
        if duplicate_of
        else ""
    )
    return (
        f"Your report '{report.title}' in {report.district} was received. "
        f"It was classified as {category} with {priority} priority and routed "
        f"to {department}.{duplicate_note}"
    )


def triage_report(
    report: ReportInput,
    existing_reports: Sequence[Mapping[str, object]] | None = None,
    language: str = "English",
) -> TriageResult:
    category, department, category_score = classify_category(report)
    priority, priority_reasons, emergency_warning = assess_priority(report, category)
    missing_information = find_missing_information(report)
    duplicate_of, duplicate_score = detect_duplicate(report, existing_reports or [])

    reasoning_parts = [f"Category evidence score: {category_score}.", *priority_reasons]
    if duplicate_of:
        reasoning_parts.append(
            f"Likely duplicate of report #{duplicate_of} with {duplicate_score:.0%} similarity."
        )
    else:
        reasoning_parts.append(
            f"No open report passed the duplicate threshold (best similarity: {duplicate_score:.0%})."
        )

    acknowledgment = build_acknowledgment(
        report,
        category,
        priority,
        department,
        duplicate_of,
        language,
    )

    return TriageResult(
        category=category,
        priority=priority,
        department=department,
        reasoning=" ".join(reasoning_parts),
        missing_information=missing_information,
        duplicate_of=duplicate_of,
        duplicate_score=duplicate_score,
        acknowledgment=acknowledgment,
        emergency_warning=emergency_warning,
    )


def build_case_markdown(
    result: TriageResult,
    report_id: int | None = None,
) -> str:
    case_id = f"BLG-{report_id:05d}" if report_id else "Preview"
    duplicate = (
        f"BLG-{result.duplicate_of:05d} ({result.duplicate_score:.0%})"
        if result.duplicate_of
        else "None"
    )
    missing = "\n".join(f"- {item}" for item in result.missing_information) or "- None"

    return f"""# BALAGH Case {case_id}

- Category: {result.category}
- Priority: {result.priority}
- Department: {result.department}
- Potential duplicate: {duplicate}

## Deterministic reasoning
{result.reasoning}

## Missing information
{missing}

## Citizen acknowledgment
{result.acknowledgment}
"""
