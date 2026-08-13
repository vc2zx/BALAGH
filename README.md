# BALAGH | بلاغ — V2

BALAGH is a local-first community issue triage and case-coordination prototype.
It separates the **citizen reporting experience** from the **internal staff workflow** and uses AI as decision support rather than an autonomous authority.

> **Core rule:** AI recommends → Human approves → System records.

## What changed in V2

- Separate `citizen_app.py` and `staff_app.py` applications.
- Deterministic safety-sensitive triage remains in Python.
- Two operational CrewAI agents instead of three review-only agents.
- Agents receive read-only tools for case data, similar reports, and case history.
- AI recommendations are stored separately from official case state.
- A staff member must approve, modify, or reject an AI recommendation.
- Every operational action is recorded in an auditable case history.
- Presentation HTML and CSS are separated from Python behavior.

## Architecture

```text
Citizen Portal
    │
    ▼
Deterministic Triage (triage.py)
    │
    ├── classification
    ├── priority
    ├── routing
    ├── missing information
    └── duplicate detection
    │
    ▼
SQLite (database.py)
    │
    ▼
Staff Portal
    │
    ├── Triage & Routing Agent
    │      ├── GetCaseTool
    │      └── FindSimilarReportsTool
    │
    └── Case Coordinator Agent
           ├── GetCaseTool
           └── GetCaseHistoryTool
                  │
                  ▼
           AI Recommendation
                  │
                  ▼
             Human Review
        Approved / Modified / Rejected
                  │
                  ▼
           Database + Audit Trail
```

## Project structure

```text
BALAGH/
├── citizen_app.py
├── staff_app.py
├── pyproject.toml
├── uv.lock
├── README.md
├── .env.example
├── .gitignore
│
├── src/
│   └── balagh/
│       ├── __init__.py
│       ├── triage.py
│       ├── agents.py
│       ├── tools.py
│       ├── database.py
│       └── auth.py
│
├── ui/
│   ├── citizen.html
│   ├── staff.html
│   └── style.css
│
├── data/
│   └── uploads/
│       └── .gitkeep
│
├── docs/
│   └── Project_Presentation.pptx
│
└── tests/
    ├── test_triage.py
    ├── test_database.py
    └── test_workflow.py
```

## Requirements

- Python 3.10–3.13
- `uv`
- Ollama
- Qwen3 4B Instruct (default)

Pull the local model:

```powershell
ollama pull qwen3:4b-instruct
```

Install dependencies:

```powershell
uv sync
```

Create local environment configuration:

```powershell
Copy-Item .env.example .env
```

Change `STAFF_ACCESS_CODE` in `.env` before using the staff portal.

## Run

Citizen portal:

```powershell
uv run streamlit run citizen_app.py --server.port 8501
```

Staff portal in another terminal:

```powershell
uv run streamlit run staff_app.py --server.port 8502
```

## Tests

```powershell
uv run python -m unittest discover -s tests -v
```

The tests do not require Ollama. They test deterministic triage, persistence, and the human approval workflow without invoking an LLM.

## Existing V1 database

`database.py` performs additive SQLite migrations. If `data/balagh.db` from V1 already exists, BALAGH keeps the existing reports and adds the V2 tables/columns it needs.

## Safety and security scope

BALAGH V2 is still a prototype, not a production government system.

- Critical safety detection is deterministic and does not rely on an LLM.
- Agents are advisory and receive no database-write tools.
- Staff authentication is a local prototype access code, not enterprise identity management.
- SQLite is appropriate for the local MVP but not the intended final production datastore.
- Uploaded images are stored but are not analyzed.
- The current system does not validate geolocation against a map service.

The existing V1 presentation should be moved to `docs/Project_Presentation.pptx` when this update is merged, then revised before V2 is presented externally.
