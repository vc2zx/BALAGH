# BALAGH Evaluation Matrix

## Core cases

| Case | Expected deterministic result | Agentic evidence |
| --- | --- | --- |
| Missing speed-limit sign | Traffic Signs & Road Safety, Medium, direction and nearest intersection requested | Supervisor selects `traffic_safety`; road-code chunk is retrieved |
| Non-working traffic signal | Traffic Signs & Road Safety, High, intersection and direction requested | Safety worker and human review are required |
| Ambiguous description | Needs Human Classification | Supervisor can select `human_classification` |
| Immediate hazard phrase | Critical with deterministic warning | Guardrails preserve the warning and require staff assessment |
| Same issue and location | Potential duplicate only | No automatic closure; employee compares both cases |
| Model invents a 48-hour SLA | Unsupported deadline removed | Deterministic guardrail replaces the escalation condition |

## Automated evidence

| Requirement | Test evidence |
| --- | --- |
| Structured outputs and policy guardrails | `tests/test_agents_graph.py` |
| LLM-selected read-only tool calls | `test_functional_workflow_interrupts_resumes_and_shares_memory` |
| Structured supervisor routing | `test_functional_workflow_interrupts_resumes_and_shares_memory` |
| Load, split, embed, store, retrieve | `tests/test_knowledge.py` |
| Checkpointer, interrupt, and Command resume | `test_functional_workflow_interrupts_resumes_and_shares_memory` |
| Cross-thread Store memory | `test_functional_workflow_interrupts_resumes_and_shares_memory` |
| Database and audit history | `tests/test_database.py`, `tests/test_workflow.py` |
| Flask citizen and staff workflows | `tests/test_citizen_routes.py`, `tests/test_staff_routes.py` |
| Regression cases | `tests/test_triage.py` |

## Safety assertions

- The model cannot execute a municipal action.
- Model tools are read-only and active-report arguments are enforced.
- Duplicate similarity is never an automatic closure decision.
- The employee decision is not written if LangGraph resume fails.
- Tracking tokens are stored as hashes.
- `.env`, SQLite files, uploaded attachments, caches, and local virtual environments are excluded from Git.

## Evaluation boundary

The evaluation dataset is intentionally small and targeted to the Capstone scope. It demonstrates workflow behavior and regression safety; it is not a production measurement of policy accuracy, fairness, geographic coverage, or service performance.
