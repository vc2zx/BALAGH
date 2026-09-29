# Evaluation protocol and observed results

Accessed/run 30 September 2026. The hand-written, synthetic [Arabic cases](../evaluation/arabic_cases.json) are separate from the [demo seed](../scripts/seed_demo.py). They include ordinary facilities, an unclear report, a mixed road/waste report, explicit and negated danger, one same-place duplicate, and two location negatives. Labels were set before running the current rules. They are author labels, not independent expert adjudication.

Run `uv run python scripts/evaluate_rules.py` from the repository root. Each case is timed once after Python import in the same process; p95 uses nearest rank. These are CPU-only rules timings on this machine, not end-to-end HTTP or model latency.

| Measure | Rules result | Denominator / definition |
| --- | ---: | --- |
| Category accuracy | 17/18 | Exact label match; `Needs Human Classification` is a category. |
| Suggested review queue accuracy | 17/18 | Exact queue string derived from the label. This is not a real municipal routing measurement. |
| Urgent recall | 3/3 | `Critical` among three manually urgent cases. |
| Urgent false-positive rate | 0/15 | `Critical` among 15 nonurgent cases. |
| Duplicate precision | 1/1 | Flagged duplicate was labelled duplicate. |
| Duplicate recall | 1/1 | One labelled duplicate. |
| Ambiguous abstention | 2/3 | Three `Needs Human Classification` cases; E11 was forced into Waste & Cleanliness. |
| Median / p95 rules latency | 0.784 / 2.981 ms | 18 single-call timings in one 30 September run; rerun values will vary. |

**Error example:** E11 mentions both rubbish and a pothole, but the rules choose Waste & Cleanliness rather than asking staff to classify the mixed issue. The category and queue error are the same underlying mistake. Same-district duplicates with distinct explicit landmarks (E17) and different districts (E18) were not flagged. The dataset is too small to estimate field performance, especially duplicate precision/recall with only one positive.

## Workflow and model evidence

The 47 unit tests use mocked model responses. They verify the LangGraph interrupt/resume shape, read-only tool selection, rules guardrails, Flask routes, persistence, lost-checkpoint failure and discard recovery. They are not an accuracy benchmark for Ollama. In an isolated synthetic Flask smoke run using `qwen3:4b-instruct` and `nomic-embed-text`, the final workflow generated a draft, selected `traffic_safety`, retrieved S2/S1/S3, and recorded a staff **rejection** after resume. The [final run evidence](evidence/ollama_final_smoke.json) shows 8.322 s for draft generation and 0.012 s for resume. This is 1/1 successful workflow completion, with no meaningful latency distribution. The [earlier complex run](evidence/ollama_complex_smoke.json) took 21.317 s and produced an unverified department and location detail; a [second simplified run](evidence/ollama_simplified_smoke.json) took 10.019 s. These are uncontrolled smoke runs, not a speed claim.

Source provenance in the final smoke run: 3/3 listed source IDs and URLs correspond to the checked-in notes. Manual inspection found the road-code library directly relevant to traffic safety; Balady and 940 support only general reporting/review context. The output lists source notes rather than attaching a source to each sentence, so **claim-level citation correctness is unmeasured**. Neither a LangSmith trace nor a production integration is evidenced.

Comparison: rules have an 18-case labelled result; the agent workflow has one synthetic completion and no full labelled-set result; a single-model baseline has not been run. Agent category/routing accuracy, urgent recall/FPR, duplicate precision/recall, ambiguous abstention, citation correctness, and median/p95 on the 18 cases are therefore **not measured**. Do not copy rules scores into an agent column. A fair next experiment would replay the same labels and frozen notes through each workflow, have a reviewer score grounded claims, then measure latency on repeated runs after model warm-up.
