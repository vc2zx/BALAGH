# BALAGH | بلاغ

**BALAGH** is a local-first community issue triage and case-coordination prototype built with Python, CrewAI, Ollama, Streamlit, and SQLite.

The system separates the **citizen reporting experience** from the **internal staff workflow** and follows a human-in-the-loop approach:

> **AI recommends → Human approves → System records.**

## Overview

Citizens can submit community reports such as:

- Road and sidewalk issues
- Waste and cleanliness problems
- Street lighting and electrical issues
- Water and drainage problems
- Accessibility barriers
- Public facility issues
- Community disturbances

Each report passes through deterministic triage before being stored and reviewed by staff.

BALAGH can:

1. Classify the issue.
2. Assign an initial priority.
3. Route the report to a service department.
4. Detect potentially duplicated reports.
5. Identify missing information.
6. Store the report and its history.
7. Generate AI-assisted recommendations.
8. Require human review before operational decisions.

## Architecture

```text
Citizen Portal
      │
      ▼
Deterministic Triage
      │
      ├── Classification
      ├── Priority
      ├── Routing
      ├── Missing Information
      └── Duplicate Detection
      │
      ▼
SQLite
      │
      ▼
Staff Portal
      │
      ├── Triage & Routing Agent
      └── Case Coordinator Agent
              │
              ▼
       AI Recommendation
              │
              ▼
         Human Review
              │
              ▼
     Database + Audit Trail
```

## Agentic Workflow

BALAGH uses two CrewAI agents.

### Triage & Routing Agent

Reviews the deterministic triage result and uses:

- `GetCaseTool`
- `FindSimilarReportsTool`

### Case Coordinator Agent

Recommends the next controlled action and uses:

- `GetCaseTool`
- `GetCaseHistoryTool`

All agent tools are **read-only**.

The agents cannot change report status, approve cases, or directly modify operational records.

## Project Structure

```text
BALAGH/
├── citizen_app.py
├── staff_app.py
├── src/
│   └── balagh/
│       ├── triage.py
│       ├── agents.py
│       ├── tools.py
│       ├── database.py
│       └── auth.py
├── ui/
│   ├── citizen.html
│   ├── staff.html
│   └── style.css
├── data/
│   └── uploads/
├── tests/
│   ├── test_triage.py
│   ├── test_database.py
│   └── test_workflow.py
├── pyproject.toml
├── uv.lock
└── .env.example
```

## Interfaces

### Citizen Portal

Citizens can:

- Submit reports
- Specify city, district, and landmark
- Upload an optional image
- Receive a tracking number
- Check report status

### Staff Portal

Staff can:

- View dashboard metrics
- Filter reports
- Review case details
- Run AI-assisted analysis
- Approve, modify, or reject recommendations
- Update report status
- Review case history

## Technology Stack

- Python
- CrewAI
- Ollama
- Qwen3
- Streamlit
- SQLite
- Pandas
- HTML / CSS
- uv

## Setup

Install dependencies:

```powershell
uv sync
```

Install the local model:

```powershell
ollama pull qwen3:4b-instruct
```

Create the environment file:

```powershell
Copy-Item .env.example .env
```

Example configuration:

```env
MODEL=ollama/qwen3:4b-instruct
OLLAMA_HOST=http://localhost:11434
STAFF_ACCESS_CODE=your-access-code
```

## Run

Citizen portal:

```powershell
uv run streamlit run citizen_app.py --server.port 8501
```

Staff portal:

```powershell
uv run streamlit run staff_app.py --server.port 8502
```

## Tests

```powershell
uv run python -m unittest discover -s tests -v
```

The current tests cover deterministic triage, SQLite persistence, duplicate similarity, and the human review workflow.

The automated test suite does not currently invoke the local LLM.

## Current Scope

BALAGH is currently a prototype.

Current limitations include:

- Prototype staff authentication
- Local SQLite storage
- Local Ollama inference
- No production identity or role-based access control
- No external government-system integration
- No map-based geolocation validation
- Uploaded images are stored but not analyzed