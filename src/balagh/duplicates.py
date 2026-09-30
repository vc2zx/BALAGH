"""Bounded candidate retrieval followed by local semantic, place and time ranking."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone

from balagh import database, store
from balagh.triage import normalize_text


_PLACE_MARKERS = re.compile(r"(?:عند|قرب|حول|امام|بجوار|بجانب|مقابل|نهاية)\s+((?:\S+\s*){1,4})")
_GENERIC_PLACE_WORDS = {
    "في", "من", "الى", "عند", "قرب", "حول", "امام", "بجوار", "بجانب", "مقابل",
    "الشارع", "الحي", "الطريق", "المكان", "المدخل", "زاوية", "ممشى", "الممشى",
    "مبنى", "المبنى", "حفرة", "كبيره", "كبيرة", "المشكلة", "المشكله", "الارض",
}


def _place_tokens(report: dict) -> set[str]:
    landmark = normalize_text(report.get("landmark") or "")
    snippets = [landmark] if landmark else _PLACE_MARKERS.findall(
        normalize_text(f"{report.get('title') or ''} {report.get('description') or ''}"))
    return {token for snippet in snippets for token in snippet.split()
            if token not in _GENERIC_PLACE_WORDS and len(token) > 2}


def _cosine(first: list[float], second: list[float]) -> float:
    if len(first) != len(second) or not first:
        return 0.0
    numerator = sum(a * b for a, b in zip(first, second))
    denominator = math.sqrt(sum(a * a for a in first) * sum(b * b for b in second))
    return max(0.0, min(1.0, numerator / denominator)) if denominator else 0.0


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    angle = (math.sin(math.radians(lat2 - lat1) / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 12742 * math.asin(min(1.0, math.sqrt(angle)))


def rank_candidates(report_id: int, embedding: list[float], asset_type: str | None,
                    limit: int = 5) -> list[dict]:
    """Unembedded older cases are not silently scored as semantic matches."""
    report = database.get_report(report_id)
    if not report:
        return []
    ranked: list[dict] = []
    for candidate in store.candidate_reports(report_id, limit=60):
        if not candidate["embedding_json"]:
            continue
        try:
            semantic = _cosine(embedding, json.loads(candidate["embedding_json"]))
        except (ValueError, TypeError):
            continue
        if semantic < 0.65:
            continue
        first_tokens, second_tokens = _place_tokens(report), _place_tokens(candidate)
        place = (len(first_tokens & second_tokens) / len(first_tokens | second_tokens)
                 if first_tokens and second_tokens else 0.0)
        has_matching_coordinates = False
        if all(report.get(key) is not None and candidate.get(key) is not None
               for key in ("latitude", "longitude")):
            distance = _distance_km(report["latitude"], report["longitude"],
                                    candidate["latitude"], candidate["longitude"])
            if distance > 2:
                continue
            has_matching_coordinates = True
            place = max(place, max(0.0, 1 - distance / 2))
        if not has_matching_coordinates and place == 0.0:
            continue
        asset = 1.0 if asset_type and candidate["asset_type"] == asset_type else 0.0
        try:
            age_days = max(0, (datetime.now(timezone.utc) -
                    datetime.fromisoformat(candidate["created_at"])).total_seconds() / 86400)
        except ValueError:
            age_days = 90
        recency = max(0.0, 1 - age_days / 90)
        score = 0.60 * semantic + 0.20 * asset + 0.12 * place + 0.08 * recency
        if score >= 0.72:
            ranked.append({"report_id": candidate["id"], "score": round(score, 4),
                           "components": {"semantic": round(semantic, 4),
                                          "asset": asset, "place": round(place, 4),
                                          "recency": round(recency, 4)}})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:max(1, min(limit, 10))]
