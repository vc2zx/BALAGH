# BALAGH | بلاغ

BALAGH is a local, Arabic-first public issue reporting and staff triage prototype. A resident submits a report and receives a private tracking code. Rules suggest a category, priority, review queue, missing information, and possible duplicate. A staff member may request a local Ollama model review with retrieved source notes, inspect the draft, and approve, modify, or reject it. Staff update the case status separately. No municipal action is executed by the model.

بلاغ نموذج محلي لاستقبال بلاغات المرافق العامة ومساعدة الموظف في فرزها. تظهر للمبلّغ نتيجة أولية ورمز متابعة. يقترح النظام التصنيف والأولوية والمعلومات الناقصة والتشابه المحتمل؛ يراجع الموظف التوصية ويتخذ القرار بنفسه.

## Run locally

Requires Python 3.10–3.13, [uv](https://docs.astral.sh/uv/), and [Ollama](https://ollama.com/). From the repository root:

```powershell
ollama pull qwen3:4b-instruct
ollama pull nomic-embed-text
uv sync --locked
uv run python scripts/setup_local.py
uv run python scripts/seed_demo.py
uv run flask --app app run --host 127.0.0.1
```

`setup_local.py` creates a private `.env` with random local credentials and prints the staff access code. It refuses to replace an existing `.env`. The seed command adds one clearly synthetic report and is safe to rerun. The site starts at `http://127.0.0.1:5000/citizen/`; staff sign in at `http://127.0.0.1:5000/staff/login`. The server is bound to localhost by default. Set `LANGCHAIN_TRACING_V2=true` and a LangSmith API key only if you intentionally want external tracing; there is no saved live LangSmith trace in this repository.

If Ollama is unavailable, citizen submission, rules-based triage, staff status updates, history, and tracking still work. The AI review button shows an error with recovery instructions. Do not describe the rules result as a live model result.

## Architecture and boundaries

`src/balagh/citizen_routes.py` and `staff_routes.py` are Flask routes; `database.py` stores local SQLite reports, recommendations, and history. `triage.py` applies deterministic Arabic/English keyword and location rules. `agents.py` runs a LangGraph Functional API workflow: read-only tools, retrieval from three local notes (`knowledge.py`), a model audit worker chosen by the rules category, a rules-built action plan, `interrupt()` for staff review, and `Command(resume=...)` for the staff decision. The attached notes link to Balady, the Saudi Road Code library, and Riyadh 940; retrieval does not prove that every generated claim is supported by a source.

The checkpoint and cross-thread memory are process-local. After a restart, a pending draft cannot be resumed. The app fails without saving the staff decision; staff can explicitly discard that stale draft and generate a new one. The discard is audited and leaves case status unchanged. For a real deployment, use durable workflow storage, individual staff accounts, appropriate access controls, and an agreed data policy before using real reports.

The current prototype has no government integration, maps, SMS, service-level promise, automatic duplicate closure, or delegated department authority. Category and department labels are prototype suggestions. Demo records are synthetic. Never enter real personal reports into a public demo.

## Verify

```powershell
uv run python -m unittest discover -s tests -q
uv run python scripts/evaluate_rules.py
uv run python scripts/smoke_real_ollama.py
```

The unit suite includes mocked model workflows; the smoke script uses the configured local Ollama models on an isolated synthetic SQLite database and performs a staff rejection. It prints timing and the complete output so unsupported details can be inspected. See [SAIF preparation and measured results](docs/SAIF_2026.md) and [evaluation cases](evaluation/arabic_cases.json). No production accuracy or operational impact is established by these small tests.
