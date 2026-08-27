from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Mapping, Sequence


CATEGORY_RULES: dict[str, dict[str, object]] = {
    "Traffic Signs & Road Safety": {
        "department": "Traffic Signs and Road Safety",
        "keywords": [
            "speed limit sign", "speed limit", "speed sign", "traffic sign",
            "traffic signal", "traffic light", "signal not working",
            "traffic signal not working", "traffic light not working",
            "road sign", "missing sign", "damaged sign", "stop sign",
            "yield sign", "road marking", "lane marking", "pedestrian crossing",
            "signage", "حد السرعة", "لوحة السرعة", "لوحة تحديد السرعة",
            "علامة السرعة", "لوحة مرورية", "اللوحة المرورية", "علامة مرورية",
            "العلامة المرورية", "إشارة مرورية", "اشارة مرورية",
            "إشارة المرور", "اشارة المرور", "إشارة لا تعمل", "اشارة لا تعمل",
            "الإشارة لا تعمل", "الاشارة لا تعمل", "إشارة ماتشتغل",
            "اشارة ماتشتغل", "لوحة مفقودة",
            "علامة مفقودة", "لوحة تالفة", "دهان الطريق", "تخطيط الطريق",
            "خطوط المسارات", "ممر مشاة",
        ],
    },
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

CATEGORY_LABELS_AR = {
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

DEPARTMENT_LABELS_AR = {
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

PRIORITY_LABELS_AR = {
    "Low": "منخفضة",
    "Medium": "متوسطة",
    "High": "مرتفعة",
    "Critical": "حرجة",
}

CONFIDENCE_LABELS_AR = {
    "High": "عالية",
    "Medium": "متوسطة",
    "Low": "منخفضة",
    "None": "غير متوفرة",
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
    category_confidence: str
    category_evidence: list[str]
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


def _category_matches(report: ReportInput) -> tuple[str, str, int, list[str], str]:
    text = normalize_text(
        " ".join([
            report.title,
            report.description,
            report.city,
            report.district,
            report.landmark,
        ])
    )

    text_tokens = set(text.split())
    candidates: list[tuple[int, str, str, list[str]]] = []

    for category, rule in CATEGORY_RULES.items():
        score = 0
        matched: list[str] = []
        seen_keywords: set[str] = set()
        for keyword in rule["keywords"]:
            normalized_keyword = normalize_text(keyword)
            if not normalized_keyword or normalized_keyword in seen_keywords:
                continue
            seen_keywords.add(normalized_keyword)
            is_match = (
                normalized_keyword in text
                if " " in normalized_keyword
                else normalized_keyword in text_tokens
            )
            if is_match:
                score += 3 if " " in normalized_keyword else 1
                matched.append(str(keyword))

        candidates.append((score, category, str(rule["department"]), matched))

    best_score = max((candidate[0] for candidate in candidates), default=0)
    winners = [candidate for candidate in candidates if candidate[0] == best_score]

    if best_score == 0 or len(winners) != 1:
        return (
            "Needs Human Classification",
            "Triage Review Queue",
            best_score,
            [],
            "None",
        )

    score, category, department, evidence = winners[0]
    confidence = "High" if score >= 3 else "Medium"
    return category, department, score, evidence, confidence


def classify_category(report: ReportInput) -> tuple[str, str, int]:
    category, department, score, _evidence, _confidence = _category_matches(report)
    return category, department, score


def assess_priority(
    report: ReportInput,
    category: str,
    language: str = "English",
) -> tuple[str, list[str], str | None]:
    text = normalize_text(" ".join([report.title, report.description, report.landmark]))

    def unique_hits(keywords: Sequence[str]) -> list[str]:
        hits: list[str] = []
        seen: set[str] = set()
        for keyword in keywords:
            normalized_keyword = normalize_text(keyword)
            if normalized_keyword in text and normalized_keyword not in seen:
                seen.add(normalized_keyword)
                hits.append(keyword)
        return hits

    critical_hits = unique_hits(CRITICAL_KEYWORDS)
    if critical_hits:
        warning = (
            "قد يكون البلاغ مرتبطًا بخطر فوري. تواصل مع خدمة الطوارئ المحلية "
            "المناسبة فورًا ولا تنتظر معالجة البلاغ داخل النظام."
        )
        reason = (
            "رُصدت مؤشرات قد تدل على خطر فوري: " + "، ".join(critical_hits[:3])
            if language.lower() == "arabic"
            else "Potential immediate danger was detected: " + ", ".join(critical_hits[:3])
        )
        return "Critical", [reason], warning

    high_hits = unique_hits(HIGH_KEYWORDS)
    if high_hits:
        reason = (
            "رُصد موقع حساس أو ظرف مرتفع التأثير: " + "، ".join(high_hits[:3])
            if language.lower() == "arabic"
            else "A sensitive place or high-impact condition was detected: " + ", ".join(high_hits[:3])
        )
        return "High", [reason], None

    if category in {"Street Lighting & Electrical", "Water & Drainage", "Accessibility"}:
        reason = (
            "قد تؤثر هذه الفئة في السلامة العامة أو الوصول إلى خدمة أساسية."
            if language.lower() == "arabic"
            else f"{category} issues may affect public safety or essential access."
        )
        return (
            "High",
            [reason],
            None,
        )

    if category in {
        "Traffic Signs & Road Safety",
        "Roads & Sidewalks",
        "Waste & Cleanliness",
        "Needs Human Classification",
    }:
        reason = (
            "أُسندت أولوية تشغيلية متوسطة إلى أن يتحقق الموظف من مستوى الخطر والتأثير."
            if language.lower() == "arabic"
            else "A medium operational priority is assigned pending human verification of risk and impact."
        )
        return (
            "Medium",
            [reason],
            None,
        )

    reason = (
        "لم تُرصد مؤشرات خطر فوري."
        if language.lower() == "arabic"
        else "No immediate safety indicator was detected."
    )
    return "Low", [reason], None


def find_missing_information(
    report: ReportInput,
    category: str,
    language: str = "English",
) -> list[str]:
    missing: list[str] = []
    combined = normalize_text(" ".join([report.title, report.description, report.landmark]))

    def message(english: str, arabic: str) -> str:
        return arabic if language.lower() == "arabic" else english

    def has_any(terms: Sequence[str]) -> bool:
        return any(normalize_text(term) in combined for term in terms)

    traffic_signal_terms = [
        "traffic signal", "traffic light", "إشارة المرور", "اشارة المرور",
        "إشارة مرورية", "اشارة مرورية",
    ]
    is_traffic_signal = category == "Traffic Signs & Road Safety" and has_any(
        traffic_signal_terms
    )

    if len(report.description.strip()) < 35 and not is_traffic_signal:
        missing.append(message("More detailed issue description", "وصف أكثر تفصيلًا للمشكلة"))

    if category == "Traffic Signs & Road Safety":
        if is_traffic_signal:
            intersection_terms = [
                "intersection", "cross street", "junction", "اتجاه", "تقاطع",
                "شارع متقاطع", "مسار",
            ]
            if not has_any(intersection_terms):
                missing.append(
                    message(
                        "Intersection or cross street and driving direction",
                        "اسم التقاطع أو الشارع المتقاطع واتجاه السير لتحديد الإشارة بدقة",
                    )
                )
            return missing

        direction_terms = [
            "direction", "northbound", "southbound", "eastbound", "westbound",
            "intersection", "exit", "lane", "اتجاه", "شمال", "جنوب", "شرق",
            "غرب", "تقاطع", "مخرج", "مسار",
        ]
        if not has_any(direction_terms):
            missing.append(
                message(
                    "Driving direction and nearest intersection or exit",
                    "اتجاه السير وأقرب تقاطع أو مخرج لتحديد موقع اللوحة بدقة",
                )
            )
        return missing

    if not report.landmark.strip() and not any(
        term in combined for term in map(normalize_text, LOCATION_TERMS)
    ):
        missing.append(message("Nearby landmark or precise location", "معلم قريب أو موقع أدق"))

    if category in {"Roads & Sidewalks", "Waste & Cleanliness", "Street Lighting & Electrical"}:
        quantity_terms = [
            "large", "small", "meter", "metre", "one", "two", "three",
            "كبيرة", "صغيرة", "متر", "واحد", "اثنان", "ثلاثة", "عدة",
        ]
        if not re.search(r"\d", report.description) and not has_any(quantity_terms):
            missing.append(
                message(
                    "Approximate size or number of affected assets",
                    "الحجم التقريبي أو عدد العناصر المتأثرة",
                )
            )

    if category in {
        "Roads & Sidewalks",
        "Waste & Cleanliness",
        "Street Lighting & Electrical",
        "Water & Drainage",
        "Noise & Community Disturbance",
    }:
        time_terms = [
            "today", "yesterday", "hour", "day", "week", "since",
            "منذ", "اليوم", "امس", "أمس", "ساعة", "يوم", "أسبوع", "اسبوع",
        ]
        if not has_any(time_terms):
            missing.append(message("When the issue started", "وقت بدء المشكلة أو مدة استمرارها"))

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
        category_label = CATEGORY_LABELS_AR.get(category, category)
        priority_label = PRIORITY_LABELS_AR.get(priority, priority)
        department_label = DEPARTMENT_LABELS_AR.get(department, department)
        duplicate_note = (
            f" وتم ربطه مبدئيًا ببلاغ مشابه رقم {duplicate_of}."
            if duplicate_of
            else "."
        )
        return (
            f"تم استلام بلاغك عن «{report.title}» في حي {report.district}. "
            f"صُنّف البلاغ ضمن {category_label} وبأولوية {priority_label}، "
            f"وسيُوجّه إلى {department_label}{duplicate_note}"
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
    (
        category,
        department,
        category_score,
        category_evidence,
        category_confidence,
    ) = _category_matches(report)
    priority, priority_reasons, emergency_warning = assess_priority(
        report,
        category,
        language,
    )
    missing_information = find_missing_information(report, category, language)
    duplicate_of, duplicate_score = detect_duplicate(report, existing_reports or [])

    if language.lower() == "arabic":
        confidence_label = CONFIDENCE_LABELS_AR.get(
            category_confidence,
            category_confidence,
        )
        if category_evidence:
            category_reason = (
                f"ثقة التصنيف الحتمي {confidence_label}؛ "
                "الكلمات المفتاحية المطابقة المستخدمة لاختيار المجال "
                f"(وليست أدلة ميدانية): {'، '.join(category_evidence)}."
            )
        else:
            category_reason = (
                "لم تظهر أدلة نصية كافية لتحديد الفئة، لذلك أُحيل البلاغ "
                "إلى مراجعة التصنيف بدل إسناده إلى فئة عامة افتراضية."
            )
        reasoning_parts = [category_reason, *priority_reasons]
        if duplicate_of:
            reasoning_parts.append(
                f"يوجد بلاغ مشابه محتمل رقم {duplicate_of} بنسبة تشابه {duplicate_score:.0%}."
            )
        else:
            reasoning_parts.append(
                "لم يتجاوز أي بلاغ مفتوح عتبة التكرار "
                f"(أفضل تشابه: {duplicate_score:.0%})."
            )
    else:
        evidence = ", ".join(category_evidence) or "none"
        reasoning_parts = [
            f"Category confidence: {category_confidence}; matched category keywords "
            f"(lexical matches only, not field evidence): {evidence}; "
            f"weighted score: {category_score}.",
            *priority_reasons,
        ]
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
        category_confidence=category_confidence,
        category_evidence=category_evidence,
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
- Category confidence: {result.category_confidence}
- Matched category keywords (lexical matches only): {', '.join(result.category_evidence) or 'None'}
- Potential duplicate: {duplicate}

## Deterministic reasoning
{result.reasoning}

## Missing information
{missing}

## Citizen acknowledgment
{result.acknowledgment}
"""
