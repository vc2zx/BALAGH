"""Versioned taxonomy and pilot routing configuration; no category is a department."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from balagh.triage import normalize_text


CATALOG_PATH = Path(__file__).resolve().parents[2] / "config" / "catalog.v1.json"
SPECIAL_IDS = {"unknown", "multiple_issues", "out_of_scope"}


@lru_cache(maxsize=1)
def catalog() -> dict:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    ids = [item["id"] for item in data["categories"]]
    if len(ids) != len(set(ids)) or not SPECIAL_IDS.issubset(ids):
        raise ValueError("Category catalog has duplicate or missing special IDs")
    return data


def categories() -> dict[str, dict]:
    return {item["id"]: item for item in catalog()["categories"]}


def category_label(category_id: str, language: str = "ar") -> str:
    return categories().get(category_id, categories()["unknown"])[language]


def queue_label(queue_id: str) -> str:
    return catalog()["queue_labels_ar"].get(queue_id, queue_id)


def resolve_city(value: str) -> str | None:
    normalized = normalize_text(value)
    for city_id, city in catalog()["jurisdictions"].items():
        if normalized in {normalize_text(alias) for alias in city["aliases"]}:
            return city_id
    return None


def normalize_district(value: str) -> str:
    return normalize_text(value)


def validate_pin(city_id: str | None, latitude: float | None, longitude: float | None) -> bool:
    if latitude is None and longitude is None:
        return True
    if city_id is None or latitude is None or longitude is None:
        return False
    south, west, north, east = catalog()["jurisdictions"][city_id]["bbox"]
    return south <= latitude <= north and west <= longitude <= east


def review_queue(city_id: str | None, category_ids: list[str]) -> str:
    if city_id and len(category_ids) == 1:
        return catalog()["jurisdictions"][city_id]["queues"].get(
            category_ids[0], catalog()["default_queue"]
        )
    return catalog()["default_queue"]
