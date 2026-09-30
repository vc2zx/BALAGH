# BALAGH | بلاغ

BALAGH is an Arabic-first **local research prototype** for civic report intake and staff review. A resident receives a private tracking code immediately. A separate worker asks a local model for one structured semantic proposal, runs independent safety checks, ranks possible duplicates, and retrieves limited source context. A named staff member approves, corrects, or rejects the proposal and separately changes the operational case status. The model never executes a municipal action. No government integration is enabled.

## Local demo

Requires Python 3.10–3.13, [uv](https://docs.astral.sh/uv/), and [Ollama](https://ollama.com/) with `qwen3:4b-instruct` and `nomic-embed-text` pulled. From the repository root, in separate terminals where indicated:

```powershell
ollama pull qwen3:4b-instruct
ollama pull nomic-embed-text
uv sync --locked
uv run python scripts/setup_local.py
uv run python -m balagh.staff_admin create-user --username admin --role admin
uv run flask --app app run --host 127.0.0.1
```

In another terminal:

```powershell
uv run python -m balagh.worker
```

Open `http://127.0.0.1:5000/citizen/` and `http://127.0.0.1:5000/staff/login`. `create-user` prompts for a password without placing it in shell history. `setup_local.py` creates a secret in ignored `.env` and never replaces an existing file. `scripts/seed_demo.py` adds synthetic data. Submit only synthetic reports in a demo.

If the model is unavailable, intake still saves the report and tracking code. The queued job retries up to three times and then becomes a human classification task; no keyword category is passed off as model output. The app starts with automatic, additive SQLite migration from legacy records to schema 3. Historical legacy decisions stay unchanged and are shown as historical records.

## Current workflow

The versioned catalog in `config/catalog.v1.json` defines labels and categories separately from pilot city queues. The model proposes category IDs, exact evidence spans, rationale, uncertainty, missing information, and risk signals. Exact spans and all fields are validated. A deterministic safety signal can raise urgent review independently; it does not prove an event occurred. The model proposal, safety assessment, staff decision, status event, and audit history are separate records. A possible duplicate remains a suggestion; staff may confirm it, and no case is automatically merged or closed.

Citizen tracking shows receipt and staff-reviewed status without presenting a pending proposal as approved. The staff view separates the raw report, proposal, evidence, safety, sources, duplicate candidates, and final decision. An admin-only diagnostics view contains technical fields. Optional coordinates are bounded to configured pilot city boxes; a text-only location is accepted. Image upload validates, decodes, and re-encodes JPEG, PNG, or WebP. This is not image understanding.

## Verify and operate

```powershell
uv run python -m unittest discover -s tests -q
uv run python scripts/compare_triage.py
uv run python -m balagh.privacy --days 365
```

The comparison uses 36 synthetic author-labelled Arabic cases; independent expert review is pending. The frozen set is separate from demo data. See [evaluation](docs/EVALUATION.md), [operations, migration, backup and deployment](docs/V3_OPERATIONS.md), and the [historical SAIF preparation pack](docs/SAIF_2026.md).

BALAGH is **not ready for real citizen reports**. Independent category and safety review, privacy and security review, source validation, operational ownership, incident handling, TLS and infrastructure verification, and a municipal partner agreement remain necessary. See the precise release gate in the operations guide.
