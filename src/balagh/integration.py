"""Disabled government integration boundary. No network destination is configured."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ReviewedCaseExport:
    schema_version: str
    local_report_id: int
    staff_decision_id: int
    category_ids: tuple[str, ...]
    priority: str
    city_id: str
    district: str
    description: str
    latitude: float | None
    longitude: float | None
    idempotency_key: str

    @classmethod
    def from_reviewed_case(cls, *, report_id: int, decision_id: int,
                           category_ids: tuple[str, ...], priority: str,
                           city_id: str, district: str, description: str,
                           latitude: float | None, longitude: float | None) -> "ReviewedCaseExport":
        key = hashlib.sha256(f"balagh:v1:{report_id}:{decision_id}".encode()).hexdigest()
        return cls("1", report_id, decision_id, category_ids, priority, city_id,
                   district, description, latitude, longitude, key)


class GovernmentAdapter(Protocol):
    def submit(self, case: ReviewedCaseExport) -> str:
        """Return a partner receipt; retrying the same key must not duplicate a case."""


class DisabledGovernmentAdapter:
    def submit(self, case: ReviewedCaseExport) -> str:
        raise RuntimeError("Government integration is disabled pending partner approval and contract")
