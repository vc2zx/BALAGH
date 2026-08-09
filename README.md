# BALAGH | بلاغ

**BALAGH** is a local-first community issue triage and multi-agent review system built as a final project for the **SDAIA Agentic AI Program**.

The application provides an Arabic RTL interface for submitting and managing community reports such as road damage, waste and cleanliness issues, street-light failures, water and drainage problems, accessibility barriers, public-facility issues, and neighborhood disturbances.

BALAGH combines a **deterministic Python triage engine** with a **CrewAI multi-agent review layer**. The deterministic layer makes the initial classification, priority, routing, duplicate-detection, and missing-information decisions. CrewAI agents then audit and explain that result rather than replacing it.

---

## Project Overview

A user submits a community report through the Streamlit interface using:

- Report title
- Issue description
- City
- District
- Nearby landmark or more precise location
- Optional image attachment

The system then:

1. Classifies the issue.
2. Assigns a priority level.
3. Routes the report to a responsible service department.
4. Checks for potentially duplicated open reports.
5. Identifies useful missing information.
6. Generates a suggested acknowledgment.
7. Stores the case locally in SQLite.
8. Allows the case status to be tracked.
9. Optionally sends the deterministic result through a three-agent CrewAI review workflow.

---

## Core Triage Engine

The main triage logic is implemented in `src/balagh/core.py`.

### Report Categories

BALAGH currently supports the following rule-based categories:

| Category | Routed Department |
|---|---|
| Roads & Sidewalks | Road and Sidewalk Maintenance |
| Waste & Cleanliness | Environmental and Cleaning Services |
| Street Lighting & Electrical | Street Lighting and Electrical Safety |
| Water & Drainage | Water and Drainage Operations |
| Accessibility | Accessibility and Inclusion Unit |
| Public Facilities | Public Facilities and Parks |
| Noise & Community Disturbance | Community Compliance |
| General Community Services | General Service Coordination |

The classifier uses Arabic and English keywords. Multi-word keyword matches receive a higher evidence score than single-word matches.

### Priority Levels

Reports are assigned one of four priority levels:

- `Critical`
- `High`
- `Medium`
- `Low`

The priority logic is transparent and deterministic.

Examples of conditions that can increase priority include:

- Immediate-danger terms such as fire, gas leak, exposed live wires, collapse, injury, or severe flooding.
- Sensitive locations or high-impact conditions such as schools, hospitals, mosques, traffic signals, blocked roads, children, or elderly people.
- Categories that may affect essential access or public safety, including electrical, water/drainage, and accessibility issues.

Critical reports also generate an emergency warning telling the user not to wait for BALAGH and to contact the appropriate local emergency service.

---

## Duplicate Report Detection

BALAGH checks a new report against existing reports whose status is either `Open` or `In Progress`.

The similarity algorithm uses:

- A same-city requirement.
- District similarity as a location signal.
- `SequenceMatcher` text similarity.
- Token-based Jaccard similarity.

The final score is calculated using:

```text
45% SequenceMatcher similarity
40% token Jaccard similarity
15% location score
```

A report is treated as a likely duplicate when the best score reaches the configured threshold of `0.64`.

This makes the duplicate decision inspectable instead of relying on an LLM to decide whether two reports describe the same issue.

---

## Missing Information Detection

BALAGH also checks whether a report could benefit from additional details.

It can suggest adding:

- A more detailed description.
- A nearby landmark or more precise location.
- An approximate quantity, size, or number affected.
- Information about when the issue started.

These suggestions are shown with the analysis result.

---

## Multi-Agent Review with CrewAI

The multi-agent workflow is implemented in `src/balagh/crew.py`.

BALAGH uses **three CrewAI agents** in a **sequential process**.

### 1. Civic Triage Reviewer

Reviews the deterministic result for consistency.

Responsibilities:

- Audit the category and priority.
- Check the reasoning.
- Identify points that require human confirmation.
- Preserve emergency guidance.
- Avoid inventing facts.

### 2. Service Routing Reviewer

Reviews the operational routing decision.

Responsibilities:

- Check whether the selected department is appropriate.
- Recommend the first internal verification action.
- Recommend how to handle a duplicate report.
- Define an escalation condition.

### 3. Citizen Communication Coordinator

Produces the final communication-oriented output.

Responsibilities:

- Create an internal action summary.
- List information that should be requested from the reporter.
- Create a citizen status update.
- Produce a human-approval checklist.
- Avoid promising unsupported deadlines or outcomes.

### Crew Configuration

The CrewAI workflow uses:

- `Process.sequential`
- `memory=False`
- `allow_delegation=False`
- `temperature=0.2`

The agents receive the deterministic triage result as structured context and review it in sequence.

---

## Local AI Model

BALAGH uses:

**Qwen3 4B Instruct**

through **Ollama**.

The default configuration is stored in `.env.example`:

```env
MODEL=ollama/qwen3:4b-instruct
OLLAMA_HOST=http://localhost:11434
```

No OpenAI or Gemini API key is required.

---

## Application Interface

The Streamlit application is implemented in `app.py` and uses a custom Arabic RTL dashboard.

### Dashboard

Displays:

- Total reports
- Critical reports
- Duplicate reports
- Closed/resolved reports
- Latest reports
- Most frequent categories
- Report-status distribution

### Add Report

Allows the user to enter:

- Title
- Description
- City
- District
- Landmark
- Optional image

The image is saved locally as an attachment. **The current project does not perform computer-vision analysis on the uploaded image.**

### Analysis Result

Displays:

- Category
- Priority
- Responsible department
- Potential duplicate
- Decision reasoning
- Suggested missing information
- Suggested acknowledgment
- Uploaded image, when available

The analysis can also be downloaded as a Markdown case summary.

### Reports

Provides:

- A table of stored reports.
- Filters for category, priority, and status.
- Duplicate similarity values.
- Status management.

Supported report statuses are:

```text
Open
In Progress
Resolved
Closed
```

### CrewAI Review

Allows a stored report to be selected and reviewed by the three CrewAI agents.

The generated agent review can be displayed and downloaded as Markdown.

### Settings

Shows the current:

- Ollama model.
- Ollama host.
- Agent memory setting.
- Local database location.
- Local image-storage location.

---

## System Architecture

```text
                          ┌─────────────────────┐
                          │      Citizen        │
                          └──────────┬──────────┘
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │ Streamlit Arabic UI │
                          └──────────┬──────────┘
                                     │
                                     ▼
                    ┌────────────────────────────────┐
                    │ Deterministic Python Triage    │
                    │                                │
                    │ • Classification               │
                    │ • Priority assessment          │
                    │ • Department routing           │
                    │ • Duplicate detection          │
                    │ • Missing-info detection       │
                    │ • Suggested acknowledgment     │
                    └──────────┬───────────┬─────────┘
                               │           │
                               │           ▼
                               │    ┌───────────────┐
                               │    │ SQLite        │
                               │    │ Local Storage │
                               │    └───────────────┘
                               │
                               ▼
                    ┌────────────────────────────────┐
                    │ CrewAI Sequential Review       │
                    │                                │
                    │ 1. Civic Triage Reviewer       │
                    │ 2. Service Routing Reviewer    │
                    │ 3. Communication Coordinator   │
                    └──────────┬─────────────────────┘
                               │
                               ▼
                    ┌────────────────────────────────┐
                    │ Final Review / Action Note     │
                    └────────────────────────────────┘
```

---

## Local Data Storage

BALAGH uses SQLite through `src/balagh/db.py`.

The `reports` table stores:

- Report ID
- Creation time
- Title and description
- City and district
- Landmark
- Category
- Priority
- Routed department
- Status
- Duplicate report ID
- Duplicate similarity score
- Decision reasoning
- Missing-information suggestions
- Suggested acknowledgment
- Emergency warning
- Language
- Attachment path

Uploaded images are stored under:

```text
data/uploads/
```

The local database is stored at:

```text
data/balagh.db
```

The `.gitignore` excludes the local database, uploaded images, `.env`, virtual environments, Python cache files, and generated output files.

---

## Technologies

- **Python**
- **CrewAI**
- **Ollama**
- **Qwen3 4B Instruct**
- **Streamlit**
- **SQLite**
- **Pandas**
- **python-dotenv**
- **uv**

Python requirement:

```text
>=3.10,<3.14
```

---

## Project Structure

```text
BALAGH/
├── app.py
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── README.md
│
├── src/
│   └── balagh/
│       ├── __init__.py
│       ├── core.py
│       ├── crew.py
│       ├── db.py
│       └── launcher.py
│
├── data/
│   ├── .gitkeep
│   └── uploads/
│       └── .gitkeep
│
├── outputs/
│   └── .gitkeep
│
└── tests/
    └── test_core.py
```

### Main Files

| File | Responsibility |
|---|---|
| `app.py` | Streamlit UI, navigation, report submission, results, dashboard, report management, and agent-review interface |
| `src/balagh/core.py` | Deterministic classification, priority, routing, duplicate detection, missing-information checks, and acknowledgments |
| `src/balagh/crew.py` | CrewAI agents, tasks, local LLM configuration, and sequential review workflow |
| `src/balagh/db.py` | SQLite schema, report persistence, report retrieval, status updates, and dashboard metrics |
| `src/balagh/launcher.py` | Starts the Streamlit application |
| `tests/test_core.py` | Unit tests for triage, critical-warning, and similarity logic |

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/vc2zx/BALAGH.git
cd BALAGH
```

### 2. Install Ollama

Install Ollama on your machine, then pull the required model:

```bash
ollama pull qwen3:4b-instruct
```

Verify that the model is available:

```bash
ollama list
```

### 3. Install Project Dependencies

Using `uv`:

```bash
uv sync
```

### 4. Create the Environment File

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS/Linux:

```bash
cp .env.example .env
```

The file should contain:

```env
MODEL=ollama/qwen3:4b-instruct
OLLAMA_HOST=http://localhost:11434
```

---

## Running BALAGH

Start the application with:

```bash
uv run streamlit run app.py
```

The launcher entry point can also be used:

```bash
uv run balagh
```

The Streamlit interface is typically available at:

```text
http://localhost:8501
```

---

## Tests

The project includes unit tests for:

- Road-issue classification.
- Critical emergency-warning behavior.
- Report text similarity.

Run the test suite with:

```bash
uv run python -m unittest discover -s tests -v
```

---

## Privacy and Safety

BALAGH follows a local-first design:

- Report data is stored in local SQLite.
- Uploaded images are stored locally.
- Qwen runs locally through Ollama.
- No external commercial LLM API is required.

The system is **not an emergency dispatch service**. When the deterministic engine detects immediate-danger keywords, it displays an emergency warning advising the user to contact the appropriate local emergency service.

---

## Current Limitations

- Classification and priority assessment are currently keyword/rule based.
- Duplicate detection is heuristic text similarity, not semantic embeddings.
- Uploaded images are stored but are not analyzed.
- The project does not perform map/geolocation validation.
- CrewAI review requires the local Ollama service and Qwen model to be running.
- The UI code contains a bulk CSV import page that expects `sample_data/reports_template.csv`; that template is not included in the current project archive and must be restored before using that page.

---

## Author

**Suliman Altayar**

SDAIA Agentic AI Program — Final Project
