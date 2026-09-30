"""Durable V3 intake, job, proposal, decision, and status operations."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from balagh import database
from balagh.catalog import SPECIAL_IDS, categories, catalog, normalize_district, resolve_city
from balagh.safety import safety_signals
from balagh.triage import ReportInput


STATUS_TRANSITIONS = {
    "Open": {"In Progress"},
    "In Progress": {"Resolved"},
    "Resolved": {"In Progress", "Closed"},
    "Closed": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def submit_report(report: ReportInput, tracking_hash: str,
                  attachment_path: str | None = None,
                  latitude: float | None = None, longitude: float | None = None) -> tuple[int, bool]:
    """Commit the raw intake, independent safety result and queued job together."""
    city_id = resolve_city(report.city)
    safety = safety_signals(report.title, report.description)
    now = _now()
    warning = ("قد يشير الوصف إلى خطر آني. اتصل بخدمة الطوارئ المناسبة فورًا؛ "
               "لا تنتظر مراجعة البلاغ هنا.") if safety["urgent_review"] else None
    with database._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("SELECT id,title,description,city,district,landmark,latitude,longitude FROM reports WHERE tracking_token_hash=?",
                                      (tracking_hash,)).fetchone()
        if existing is not None:
            if (existing["title"], existing["description"], existing["city"],
                existing["district"], existing["landmark"], existing["latitude"], existing["longitude"]) != (
                report.title, report.description, report.city, report.district,
                report.landmark, latitude, longitude):
                raise ValueError("Submission token was reused with different report content")
            connection.commit()
            return int(existing["id"]), False
        cursor = connection.execute("""
            INSERT INTO reports (
                created_at, updated_at, title, description, city, district, landmark,
                category, priority, department, category_confidence, category_evidence,
                status, duplicate_of, duplicate_score, reasoning, missing_information,
                acknowledgment, emergency_warning, language, attachment_path,
                tracking_token_hash, city_id, district_normalized, latitude, longitude,
                intake_mode, analysis_state
            ) VALUES (
                :now, :now, :title, :description, :city, :district, :landmark,
                'Needs Human Classification', :priority, 'Triage Review Queue', 'None', '',
                'Open', NULL, 0, 'Semantic analysis queued', '',
                'تم استلام البلاغ. التحليل المقترح قيد الإعداد ويحتاج مراجعة موظف.',
                :warning, 'Arabic', :attachment, :tracking,
                :city_id, :district_norm, :latitude, :longitude, 'semantic_v3', 'queued'
            )
        """, dict(now=now, title=report.title, description=report.description,
                  city=report.city, district=report.district, landmark=report.landmark,
                  priority="Critical" if safety["urgent_review"] else "Medium",
                  warning=warning, attachment=attachment_path, tracking=tracking_hash,
                  city_id=city_id, district_norm=normalize_district(report.district),
                  latitude=latitude, longitude=longitude))
        report_id = int(cursor.lastrowid)
        connection.execute("INSERT INTO safety_assessments (report_id,created_at,assessment_version,content_json) VALUES (?,?,?,?)",
                           (report_id, now, "safety-1", json.dumps(safety, ensure_ascii=False)))
        connection.execute("INSERT INTO triage_jobs (report_id,state,available_at,updated_at) VALUES (?,'queued',?,?)",
                           (report_id, now, now))
        connection.execute("INSERT INTO case_history (report_id,created_at,actor,action,details) VALUES (?,?,'system','Report received','Analysis queued; no category approved')",
                           (report_id, now))
        connection.commit()
    return report_id, True


def claim_job(worker_id: str, lease_seconds: int = 180) -> int | None:
    now = _now()
    lease = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
    with database._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""UPDATE reports SET analysis_state='needs_human'
            WHERE id IN (SELECT report_id FROM triage_jobs WHERE state='running'
                AND attempts>=3 AND lease_until < ?)""", (now,))
        connection.execute("""UPDATE triage_jobs SET state='failed',lease_until=NULL,
            last_error='Worker lease expired after final attempt',updated_at=?
            WHERE state='running' AND attempts>=3 AND lease_until < ?""", (now, now))
        row = connection.execute("""
            SELECT report_id FROM triage_jobs
            WHERE attempts < 3 AND ((state='queued' AND available_at <= ?)
                OR (state='running' AND lease_until < ?))
            ORDER BY available_at, report_id LIMIT 1
        """, (now, now)).fetchone()
        if row is None:
            connection.commit()
            return None
        report_id = int(row["report_id"])
        connection.execute("""UPDATE triage_jobs SET state='running', attempts=attempts+1,
            lease_until=?,worker_id=?,updated_at=? WHERE report_id=?""",
            (lease, worker_id, now, report_id))
        connection.execute("UPDATE reports SET analysis_state='running' WHERE id=?", (report_id,))
        connection.commit()
        return report_id


def complete_job(report_id: int, worker_id: str, proposal: dict, model_version: str,
                 candidates: list[dict] | None = None, embedding: list[float] | None = None,
                 asset_type: str | None = None, source_set_version: str = "none") -> int:
    now = _now()
    with database._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        job = connection.execute("SELECT state,worker_id FROM triage_jobs WHERE report_id=?",
                                 (report_id,)).fetchone()
        if job is None or job["state"] != "running" or job["worker_id"] != worker_id:
            raise ValueError("Job lease is no longer owned by this worker")
        pending = connection.execute("SELECT id FROM triage_proposals WHERE report_id=? AND status='Pending'",
                                     (report_id,)).fetchone()
        if pending is None:
            cursor = connection.execute("""
                INSERT INTO triage_proposals
                (report_id,created_at,model_version,prompt_version,schema_version,
                 taxonomy_version,source_set_version,content_json,status)
                VALUES (?,?,?,?,?,?,?,?,'Pending')
            """, (report_id, now, model_version, proposal["prompt_version"],
                  proposal["schema_version"], proposal["taxonomy_version"],
                  source_set_version, json.dumps(proposal, ensure_ascii=False)))
            proposal_id = int(cursor.lastrowid)
            for candidate in candidates or []:
                connection.execute("""INSERT INTO duplicate_candidates
                    (proposal_id,candidate_report_id,score,components_json) VALUES (?,?,?,?)""",
                    (proposal_id, candidate["report_id"], candidate["score"],
                     json.dumps(candidate.get("components", {}))))
        else:
            proposal_id = int(pending["id"])
        if embedding is not None:
            connection.execute("""INSERT OR REPLACE INTO report_features
                (report_id,embedding_json,asset_type,created_at) VALUES (?,?,?,?)""",
                (report_id, json.dumps(embedding), asset_type, now))
        connection.execute("UPDATE triage_jobs SET state='done',lease_until=NULL,updated_at=? WHERE report_id=?",
                           (now, report_id))
        connection.execute("UPDATE reports SET analysis_state='proposed',updated_at=? WHERE id=?",
                           (now, report_id))
        connection.execute("INSERT INTO case_history (report_id,created_at,actor,action,details) VALUES (?,?,'AI','Semantic proposal generated',?)",
                           (report_id, now, f"Proposal #{proposal_id}; pending staff review"))
        connection.commit()
        return proposal_id


def fail_job(report_id: int, worker_id: str, error: str) -> None:
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    with database._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT attempts FROM triage_jobs WHERE report_id=? AND state='running' AND worker_id=?",
                                 (report_id, worker_id)).fetchone()
        if row is None:
            connection.commit()
            return
        exhausted = int(row["attempts"]) >= 3
        next_attempt = (now_dt + timedelta(seconds=30 * int(row["attempts"]))).isoformat()
        connection.execute("""UPDATE triage_jobs SET state=?,available_at=?,lease_until=NULL,
            last_error=?,updated_at=? WHERE report_id=?""",
            ("failed" if exhausted else "queued", next_attempt, error[:300], now, report_id))
        connection.execute("UPDATE reports SET analysis_state=?,updated_at=? WHERE id=?",
                           ("needs_human" if exhausted else "queued", now, report_id))
        if exhausted:
            connection.execute("INSERT INTO case_history (report_id,created_at,actor,action,details) VALUES (?,?,'system','Analysis unavailable','Human review required')",
                               (report_id, now))
        connection.commit()


def case_view(report_id: int) -> dict[str, Any] | None:
    with database._connection() as connection:
        report = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if report is None:
            return None
        proposal = connection.execute("SELECT * FROM triage_proposals WHERE report_id=? ORDER BY id DESC LIMIT 1",
                                      (report_id,)).fetchone()
        safety = connection.execute("SELECT * FROM safety_assessments WHERE report_id=? ORDER BY id DESC LIMIT 1",
                                    (report_id,)).fetchone()
        decision = connection.execute("""SELECT d.*,u.username AS reviewer_name FROM staff_decisions d
            JOIN staff_users u ON u.id=d.reviewer_id WHERE d.report_id=? ORDER BY d.id DESC LIMIT 1""",
            (report_id,)).fetchone()
        duplicates = connection.execute("""SELECT candidate_report_id,score,components_json
            FROM duplicate_candidates WHERE proposal_id=? ORDER BY score DESC LIMIT 5""",
            (proposal["id"] if proposal else -1,)).fetchall()
    return {
        "report": dict(report),
        "proposal": {**dict(proposal), "content": json.loads(proposal["content_json"])} if proposal else None,
        "safety": json.loads(safety["content_json"]) if safety else None,
        "decision": {**dict(decision), "category_ids": json.loads(decision["category_ids_json"]),
                     "changed_fields": json.loads(decision["changed_fields_json"])} if decision else None,
        "duplicates": [dict(item) for item in duplicates],
    }


def review(report_id: int, proposal_id: int | None, reviewer_id: int,
           expected_version: int, decision: str, category_ids: list[str], priority: str,
           review_queue: str, risk_review: str, duplicate_decision: str,
           duplicate_of_report_id: int | None, reason: str) -> int:
    """One atomic human decision; an out-of-date or repeated form cannot overwrite it."""
    if decision not in {"Approved", "Corrected", "Rejected"}:
        raise ValueError("Invalid decision")
    if duplicate_decision not in {"unreviewed", "not_duplicate", "confirmed_duplicate"}:
        raise ValueError("Invalid duplicate decision")
    if risk_review not in {"unreviewed", "possible_current", "historical_or_negated", "insufficient_information"}:
        raise ValueError("Invalid risk review")
    if (duplicate_decision == "confirmed_duplicate") != (duplicate_of_report_id is not None):
        raise ValueError("Confirmed duplicate needs one candidate; other decisions must not include one")
    if priority not in {"Low", "Medium", "High", "Critical"} or not review_queue:
        raise ValueError("Invalid priority or review queue")
    if (not category_ids or len(category_ids) != len(set(category_ids)) or
            "multiple_issues" in category_ids or
            any(category_id not in categories() for category_id in category_ids) or
            (set(category_ids) & SPECIAL_IDS and len(category_ids) != 1)):
        raise ValueError("Invalid category selection")
    if decision in {"Corrected", "Rejected"} and not reason.strip():
        raise ValueError("A correction or rejection requires a reason")
    now = _now()
    with database._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        report = connection.execute("SELECT version,intake_mode,analysis_state,city_id FROM reports WHERE id=?",
                                    (report_id,)).fetchone()
        if report is None or report["intake_mode"] != "semantic_v3":
            raise ValueError("Report is not eligible for V3 review")
        if int(report["version"]) != expected_version:
            raise ValueError("This case changed; reload before saving")
        city = catalog()["jurisdictions"].get(report["city_id"], {})
        allowed_queues = {catalog()["default_queue"], *city.get("queues", {}).values()}
        if review_queue not in allowed_queues:
            raise ValueError("Invalid queue for this jurisdiction")
        if connection.execute("SELECT 1 FROM staff_decisions WHERE report_id=? LIMIT 1", (report_id,)).fetchone():
            raise ValueError("This report already has a staff triage decision")
        proposal = connection.execute("SELECT * FROM triage_proposals WHERE id=? AND report_id=?",
                                      (proposal_id or -1, report_id)).fetchone()
        if proposal_id is not None and (proposal is None or proposal["status"] != "Pending"):
            raise ValueError("Proposal was already reviewed")
        if proposal_id is None and report["analysis_state"] != "needs_human":
            raise ValueError("Manual classification requires an unavailable model result")
        if proposal_id is None and decision == "Approved":
            raise ValueError("There is no model proposal to approve")
        if duplicate_of_report_id is not None:
            candidate = connection.execute("""SELECT 1 FROM duplicate_candidates
                WHERE proposal_id=? AND candidate_report_id=?""",
                (proposal_id, duplicate_of_report_id)).fetchone()
            if candidate is None:
                raise ValueError("Duplicate target was not a candidate for this proposal")
        original = json.loads(proposal["content_json"]) if proposal else {}
        original_for_review = {**original,
            "category_ids": original.get("category_ids") or ([original["outcome"]] if original.get("outcome") in {"unknown", "out_of_scope"} else []),
            "proposed_priority": original.get("effective_priority", original.get("proposed_priority")),
            "duplicate_decision": "unreviewed", "risk_review": "unreviewed"}
        changed = {key: {"from": original_for_review.get(key), "to": value}
                   for key, value in (("category_ids", category_ids),
                                      ("proposed_priority", priority),
                                      ("review_queue", review_queue),
                                      ("risk_review", risk_review),
                                      ("duplicate_decision", duplicate_decision))
                   if original_for_review.get(key) != value}
        if decision == "Approved" and (changed.get("category_ids") or changed.get("proposed_priority") or changed.get("review_queue")):
            raise ValueError("Approval cannot change proposal fields")
        if decision == "Corrected" and not changed:
            raise ValueError("Correction must change at least one field")
        cursor = connection.execute("""INSERT INTO staff_decisions
            (report_id,proposal_id,reviewer_id,created_at,decision,category_ids_json,priority,
             review_queue,risk_review,duplicate_decision,duplicate_of_report_id,reason,changed_fields_json,report_version)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (report_id, proposal_id, reviewer_id, now, decision,
             json.dumps(category_ids), priority, review_queue, risk_review, duplicate_decision,
             duplicate_of_report_id,
             reason.strip(), json.dumps(changed, ensure_ascii=False), expected_version + 1))
        if proposal:
            connection.execute("UPDATE triage_proposals SET status=? WHERE id=? AND status='Pending'",
                               (decision, proposal_id))
        connection.execute("UPDATE reports SET version=version+1,updated_at=? WHERE id=? AND version=?",
                           (now, report_id, expected_version))
        connection.execute("INSERT INTO case_history (report_id,created_at,actor,action,details) VALUES (?,?,?,?,?)",
                           (report_id, now, f"staff:{reviewer_id}", "Staff triage decision",
                            f"{decision}; decision #{cursor.lastrowid}; reason: {reason.strip()}"))
        connection.commit()
        return int(cursor.lastrowid)


def change_status(report_id: int, actor_id: int, expected_version: int,
                  new_status: str, reason: str) -> None:
    if not reason.strip():
        raise ValueError("A status reason is required")
    with database._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT status,version FROM reports WHERE id=?", (report_id,)).fetchone()
        if row is None or int(row["version"]) != expected_version:
            raise ValueError("This case changed; reload before saving")
        if new_status not in STATUS_TRANSITIONS.get(row["status"], set()):
            raise ValueError("Invalid status transition")
        now = _now()
        connection.execute("UPDATE reports SET status=?,version=version+1,updated_at=? WHERE id=?",
                           (new_status, now, report_id))
        connection.execute("""INSERT INTO status_events
            (report_id,actor_id,created_at,prior_status,new_status,reason) VALUES (?,?,?,?,?,?)""",
            (report_id, actor_id, now, row["status"], new_status, reason.strip()))
        connection.execute("INSERT INTO case_history (report_id,created_at,actor,action,details) VALUES (?,?,?,?,?)",
                           (report_id, now, f"staff:{actor_id}", "Status changed",
                            f"{row['status']} -> {new_status}; {reason.strip()}"))
        connection.commit()


def candidate_reports(report_id: int, limit: int = 200) -> list[dict]:
    """Indexed, bounded place/time shortlist; ranking is handled separately."""
    with database._connection() as connection:
        target = connection.execute("SELECT city_id,district_normalized,created_at FROM reports WHERE id=?",
                                    (report_id,)).fetchone()
        if target is None or not target["city_id"]:
            return []
        threshold = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        rows = connection.execute("""SELECT r.id,r.title,r.description,r.landmark,r.latitude,r.longitude,
            r.created_at,f.embedding_json,f.asset_type FROM reports r
            LEFT JOIN report_features f ON f.report_id=r.id
            WHERE r.id!=? AND r.city_id=? AND r.district_normalized=?
              AND r.created_at>=? AND r.status IN ('Open','In Progress')
            ORDER BY r.created_at DESC LIMIT ?""",
            (report_id, target["city_id"], target["district_normalized"], threshold,
             min(max(limit, 1), 200))).fetchall()
        return [dict(row) for row in rows]


def search_reports(filters: dict[str, str], city_ids: list[str] | None,
                   page: int = 1, page_size: int = 25) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    if city_ids is not None:
        if not city_ids:
            return []
        clauses.append("city_id IN (" + ",".join("?" for _ in city_ids) + ")")
        params.extend(city_ids)
    for key in ("status", "analysis_state"):
        if filters.get(key):
            clauses.append(f"{key}=?")
            params.append(filters[key])
    query = filters.get("q", "").strip()
    if query:
        if query.upper().removeprefix("BLG-").isdigit():
            clauses.append("id=?")
            params.append(int(query.upper().removeprefix("BLG-")))
        else:
            prefix_end = query + "\uffff"
            clauses.append("((title>=? AND title<?) OR (city>=? AND city<?) OR (district>=? AND district<?))")
            params.extend([query, prefix_end] * 3)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with database._connection() as connection:
        rows = connection.execute("SELECT id,title,city,district,city_id,status,analysis_state,intake_mode,created_at FROM reports" + where +
                                  " ORDER BY id DESC LIMIT ? OFFSET ?",
                                  (*params, min(max(page_size, 1), 50), (max(page, 1) - 1) * page_size)).fetchall()
    return [dict(row) for row in rows]


def dashboard_metrics(city_ids: list[str] | None) -> dict[str, int]:
    if city_ids is not None and not city_ids:
        return {"total": 0, "urgent": 0, "waiting": 0, "closed": 0}
    where = "" if city_ids is None else "WHERE city_id IN (" + ",".join("?" for _ in city_ids) + ")"
    with database._connection() as connection:
        row = connection.execute(f"""SELECT COUNT(*) AS total,
            SUM(CASE WHEN priority='Critical' THEN 1 ELSE 0 END) AS urgent,
            SUM(CASE WHEN analysis_state IN ('queued','running','needs_human','proposed') THEN 1 ELSE 0 END) AS waiting,
            SUM(CASE WHEN status='Closed' THEN 1 ELSE 0 END) AS closed
            FROM reports {where}""", city_ids or []).fetchone()
    return {key: int(row[key] or 0) for key in ("total", "urgent", "waiting", "closed")}
