# Evaluation protocol and observed results

## Semantic V3 comparison (30 September 2026)

`scripts/compare_triage.py` replays the [36 frozen synthetic Arabic cases](../evaluation/frozen_arabic_v3.json) through the unchanged rules baseline and one run of the V3 local `qwen3:4b-instruct` pipeline, on the same case order. The model uses `nomic-embed-text` for bounded duplicate ranking and source retrieval. The replay uses an isolated temporary SQLite database; it never reads operational reports. The labels were written by the project author and **have not been independently reviewed**, so these results are diagnostic only. They are not production accuracy estimates.

The machine-readable run, case predictions, dataset hash, and denominators are in [semantic comparison evidence](evidence/semantic_comparison.json). The script measures model pipeline time from job processing through retrieval and duplicate ranking, excluding HTTP form submission and staff review. `urgent` means the independent safety flag for V3; the rules baseline uses `Critical` priority. Exact-set category scoring counts an unavailable model result as incorrect. One report had a model response with an inexact evidence quotation; validation rejected it and the report stayed queued for retry/human review. The evaluation counted that first attempt as unavailable.

| Metric | Rules baseline | Semantic V3 | Denominator / interpretation |
| --- | ---: | ---: | --- |
| Exact category set | 17/36 | 29/36 (35 valid outputs) | Mixed labels require every category. |
| Urgent recall | 1/3 | 3/3 | Three labelled urgent cases. |
| Urgent false positives | 1/33 | 0/33 | Thirty-three labelled nonurgent cases. |
| Unknown/out-of-scope exact result | 4/6 | 3/6 | Six special-outcome cases; the two outcomes are distinct. |
| Unknown/out-of-scope predictions | 21/36 | 6/36 | This is a predicted abstention count, not a correctness rate. |
| Mixed-issue exact result | 0/3 | 3/3 | Three mixed cases. |
| Duplicate precision / recall | 0/0 / 0/1 | 1/1 / 1/1 | One labelled duplicate; rules flagged none. Too few for a reliable rate. |
| Median / p95 processing latency | 1.84 / 3.23 ms | 1931.74 / 3231.02 ms | One local run per case; nearest-rank p95. |

With the stricter 0.80 source threshold, 8 of 35 valid proposals received one source snippet; the other 27 explicitly have no suitable source. This is a retrieval count, **not** a claim-support score. No staff decisions were collected in this replay, so staff correction rate is 0/0 and unmeasured. Full report-to-human-decision latency is also unmeasured; the latency row covers rules computation or the local semantic worker only.

**Error review:** The model can propose an extra category for a single issue, confuse road paint with road damage, assign a road category to an exposed wire, and confuse unknown with out-of-scope. The strict evidence check can reject a useful classification if the model paraphrases a quotation. Staff must inspect every proposal. Source passage entailment and source claim support, staff correction rate, repeated-run stability, accessibility, security, and real-world duplicate performance are **not measured**. External reviewers should adjudicate the labels and predictions before these become acceptance criteria.

### Independent review handoff

Give Arabic-speaking municipal domain reviewers the frozen case text without the author labels or model predictions first. Have at least two reviewers independently mark category IDs, urgency, special outcome, possible duplicate identity, and ambiguous location, plus a reason. Resolve disagreements without showing model predictions, record reviewer IDs and adjudication date, then freeze a new dataset version and rerun both pipelines. Separately have reviewers inspect each retrieved passage and any material operational statement for exact support; record supported/unsupported/unclear. Collect real staff approval/correction decisions only with consent and an approved data policy. Do not use those decisions as positive model memory until provenance and an improvement test are established.

## Historical V2 evidence below

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
