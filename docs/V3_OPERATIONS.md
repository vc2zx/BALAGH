# Semantic triage V3: operations and release gate

This is a local research prototype. Use synthetic data until the final gate below is completed by the responsible organization.

## What changed, by phase

1. **Semantic intake:** `semantic.py` makes one local Ollama call with a versioned JSON schema and a catalog of stable IDs. The validator checks exact report quotations, bounded text, permitted IDs, and special outcomes. `safety.py` independently raises conservative review signals; model or schema failure leaves the raw report in a human queue.
2. **Durable review:** schema 3 keeps raw reports, jobs, proposals, safety assessments, decisions, status events, and audit history separate. A unique partial index permits one pending proposal per report. Job leases and retries survive restart. Staff decisions require a named account and optimistic report version. The old process-local LangGraph review remains only for historical legacy data; V3 does not resume it.
3. **Context:** duplicate retrieval is limited by city, district, recent open cases, and a 60-candidate ranking cap. Embeddings, location evidence, asset type, and age influence suggestions. The three checked-in notes have source metadata and a version hash, and retrieval can return no suitable source. Source snippets are context only; no generated operational claim is accepted as a sourced policy. Prior staff decisions are **not** fed to the model as memory.
4. **Controls and interface:** individual staff passwords, roles and city grants, rate limits, 128-bit tracking codes, secure cookie settings, optional HTTPS enforcement, attachment protection, retention command, encrypted backups, indexed pagination, a separate worker, health endpoints, and a disabled government export adapter. No request waits for model inference.

## Migration and local startup

1. Make an encrypted backup of the existing database and upload directory. Test restore into an empty directory before changing a deployment. Preserve the old SQLite file and attachments separately.
2. Install locked dependencies, pull both Ollama models, and keep a private `.env` with a new `FLASK_SECRET_KEY` of at least 32 random bytes. Set `SOURCE_RELEVANCE_THRESHOLD=0.80` when upgrading an older `.env`. Existing `.env` files from V2 may contain `STAFF_ACCESS_CODE`; that code is ignored by V3 and should be removed after account provisioning.
3. Start the web app once. `database.init_db()` creates the schema or applies `migrations/003_semantic.sql` when `PRAGMA user_version` is below 3. It does not rewrite historical category, recommendation, or decision rows. Legacy reports are marked `intake_mode=legacy` and are read-only in the V3 review screen.
4. Run `python -m balagh.staff_admin create-user --username NAME --role admin|reviewer|viewer [--city riyadh] [--city jeddah]`. Admins can view all configured cities; reviewers and viewers require explicit city grants. Disable an account with `disable-user --username NAME`.
5. Run web and worker as separate processes sharing the same `BALAGH_DATA_DIR`. Check `/health/live` and `/health/ready`, submit a synthetic report, wait for the worker, review the proposal, and verify citizen tracking.

For the supplied Compose demo, run `docker compose up -d --build`, then pull models into its local Ollama service with `docker compose exec ollama ollama pull qwen3:4b-instruct` and `docker compose exec ollama ollama pull nomic-embed-text`. Create the first user with `docker compose exec web python -m balagh.staff_admin create-user --username admin --role admin`. Compose binds the web port to host loopback and keeps Ollama internal. The Ollama image uses `latest`; pin and verify an approved digest before an organization deploys it. The Compose configuration has not been validated on a production host.

## Failure, state, and monitoring

New reports immediately receive a tracking code and a durable queued job. One worker claims one job at a time; the model timeout defaults to 25 seconds. A failed job retries up to three claims, then `analysis_state=needs_human` lets staff classify manually. Lease expiry also returns work to the queue. A proposal is committed with its model, prompt, schema, taxonomy, and source-set versions; staff decisions never overwrite it. `Open → In Progress → Resolved → Closed` is the normal status path; `Resolved → In Progress` reopens. Each transition requires a reason and actor. A drafted request for more information is not shown as a sent message because no delivery channel exists.

Monitor queue age and count, failed jobs, ready health, SQLite and upload volume capacity, response latency, unauthorized attempts, and backup success. `/health/ready` verifies schema and database access only; it does not assert model availability or staff coverage. The rate limiter uses SQLite fixed windows. Deploy behind a TLS terminating reverse proxy; set `BALAGH_REQUIRE_HTTPS=1` and `BALAGH_TRUSTED_PROXY_COUNT` to the exact trusted proxy hop count, and restrict direct app access. Keep `.env`, DB, uploads, backup passphrases, and backup files inaccessible to other users. No external tracing is on by default; enabling LangSmith can send report content outside the local host and requires separate approval.

Staff search accepts an exact case number or an indexed **prefix** of title, city, or district; it does not perform an unbounded substring scan. Each page is capped at 25 visible rows. Duplicate retrieval scans at most 60 recent same-city, same-district open candidates before ranking.

## Privacy, backup and restore

The resident form requires title, description, city, district; landmark, coordinates, and image are optional. A tracking code is displayed once and stored only as a hash. It grants access to that report’s tracking view, so residents must keep it private. Staff roles restrict report access to assigned pilot cities; unknown-city cases require an admin. Source notes are local. Images are decoded and re-encoded; do not infer image content from them.

The current optional location control accepts coordinates and checks the configured city bounding box; it does not yet provide a street-level interactive map pin. Staff are told when only text is available and must verify location precision. A map provider, consent and privacy approach, and usability testing are still needed before treating coordinates as reliable operational location evidence.

`python -m balagh.privacy --days 365` previews eligible **closed** cases. Add `--apply` to remove them with related records and orphan uploads. Schedule and verify it under an approved retention policy; it does not delete open cases automatically. Before purge, preserve any records subject to a legal hold. Encrypted backups are separate from retention and must have their own retention/access policy.

```powershell
python -m balagh.backup create --output C:\secure\balagh-2026-09-30.bak
python -m balagh.backup restore --input C:\secure\balagh-2026-09-30.bak --target-dir C:\empty-restore
```

Both commands prompt for a passphrase. Restore rejects a nonempty target. Test a restore and an authenticated report lookup. The backup uses SQLite's online snapshot API plus uploaded files and AES-GCM encryption. It does not capture a simultaneous atomic snapshot of uploads and DB while submissions are active; pause intake or use a storage-level snapshot for a strict recovery point.

## Integration boundary

`integration.py` defines a reviewed-case export contract and an idempotency key. Its adapter is disabled and raises if invoked. A municipality must supply field mappings, permitted statuses, authentication, endpoint and retry rules, privacy terms, authorization, and acceptance tests before a live connection is built. Category IDs and queue names are prototype labels, not a claim of municipal jurisdiction.

## Required before real citizen reports

- Independent Arabic domain reviewers must adjudicate the frozen cases and add representative real-world, privacy-safe cases. Set and meet agreed thresholds for category, urgent recall and false alarms, duplicate suggestions, abstention, source support, and staff correction. The current synthetic comparison cannot establish field performance.
- A responsible service owner must verify pilot jurisdictions, routing queues, emergency wording, source dates and scope, accessibility, Arabic content, case status policy, staffing and after-hours coverage. A general service page cannot support a deadline or mandatory action.
- An organization must run threat modeling, penetration and load tests, check dependency/container provenance, configure TLS and trusted proxies, manage secrets and staff onboarding/offboarding, audit access, define incident response, exercise restore, and approve deletion and external tracing policies. A deployment owner must validate the Compose stack and monitor worker and storage failures.
- Obtain municipality/partner approval and a data-sharing agreement before any government integration. Keep the adapter disabled until its real contract is implemented and tested.
