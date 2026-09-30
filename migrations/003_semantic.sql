-- Applied once after the legacy schema. Existing report and recommendation rows are untouched.
BEGIN IMMEDIATE;
ALTER TABLE reports ADD COLUMN city_id TEXT;
ALTER TABLE reports ADD COLUMN district_normalized TEXT;
ALTER TABLE reports ADD COLUMN latitude REAL;
ALTER TABLE reports ADD COLUMN longitude REAL;
ALTER TABLE reports ADD COLUMN version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reports ADD COLUMN intake_mode TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE reports ADD COLUMN analysis_state TEXT NOT NULL DEFAULT 'legacy';
CREATE INDEX IF NOT EXISTS idx_reports_place_recent ON reports(city_id, district_normalized, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_status_recent ON reports(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_title_prefix ON reports(title);
CREATE INDEX IF NOT EXISTS idx_reports_city_prefix ON reports(city);
CREATE INDEX IF NOT EXISTS idx_reports_district_prefix ON reports(district);
CREATE TABLE triage_jobs (
    report_id INTEGER PRIMARY KEY REFERENCES reports(id),
    state TEXT NOT NULL CHECK(state IN ('queued','running','done','failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
    available_at TEXT NOT NULL,
    lease_until TEXT,
    worker_id TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_triage_jobs_claim ON triage_jobs(state, available_at);
CREATE TABLE triage_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES reports(id),
    created_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    source_set_version TEXT NOT NULL,
    content_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('Pending','Approved','Corrected','Rejected','Superseded'))
);
CREATE UNIQUE INDEX idx_proposals_one_pending ON triage_proposals(report_id) WHERE status='Pending';
CREATE INDEX idx_proposals_report ON triage_proposals(report_id, id DESC);
CREATE TABLE safety_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES reports(id),
    created_at TEXT NOT NULL,
    assessment_version TEXT NOT NULL,
    content_json TEXT NOT NULL
);
CREATE TABLE staff_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','reviewer','viewer')),
    city_ids_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL
);
CREATE TABLE staff_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES reports(id),
    proposal_id INTEGER REFERENCES triage_proposals(id),
    reviewer_id INTEGER NOT NULL REFERENCES staff_users(id),
    created_at TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('Approved','Corrected','Rejected')),
    category_ids_json TEXT NOT NULL,
    priority TEXT NOT NULL CHECK(priority IN ('Low','Medium','High','Critical')),
    review_queue TEXT NOT NULL,
    risk_review TEXT NOT NULL CHECK(risk_review IN ('unreviewed','possible_current','historical_or_negated','insufficient_information')),
    duplicate_decision TEXT NOT NULL CHECK(duplicate_decision IN ('unreviewed','not_duplicate','confirmed_duplicate')),
    duplicate_of_report_id INTEGER REFERENCES reports(id),
    reason TEXT NOT NULL,
    changed_fields_json TEXT NOT NULL,
    report_version INTEGER NOT NULL,
    UNIQUE(report_id, report_version)
);
CREATE INDEX idx_decisions_report ON staff_decisions(report_id, id DESC);
CREATE TABLE status_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES reports(id),
    actor_id INTEGER NOT NULL REFERENCES staff_users(id),
    created_at TEXT NOT NULL,
    prior_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE duplicate_candidates (
    proposal_id INTEGER NOT NULL REFERENCES triage_proposals(id),
    candidate_report_id INTEGER NOT NULL REFERENCES reports(id),
    score REAL NOT NULL CHECK(score BETWEEN 0 AND 1),
    components_json TEXT NOT NULL,
    PRIMARY KEY(proposal_id, candidate_report_id)
);
CREATE TABLE report_features (
    report_id INTEGER PRIMARY KEY REFERENCES reports(id),
    embedding_json TEXT,
    asset_type TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE rate_limits (
    key_hash TEXT PRIMARY KEY,
    window_start TEXT NOT NULL,
    attempts INTEGER NOT NULL CHECK(attempts >= 0)
);
PRAGMA user_version=3;
COMMIT;
