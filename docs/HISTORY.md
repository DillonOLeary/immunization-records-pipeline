# History

Dated decisions, incidents, and progress notes, newest first. ARCHITECTURE.md
describes only what exists; the reasoning trail for how it got that way
lives here. Add an entry whenever a decision lands or an incident happens.

## Log

- 2026-10-01: one fake AISR. The repo had two diverged copies:
  `tests/mock_server.py` (what tests actually used: strict credentials,
  fixed port 8000, `sleep(1)` startup) and the `mock/` package (what the
  README said tests used: any credentials, random sample data, a Cloud Run
  deployment). Now `mock/` is the only one:
  `create_mock_app(base_url, credentials, faults)` with per-school
  injectable faults and a log of received uploads; deterministic sample
  data whose invented names, DOBs, and ids are collected in `CANARY_PHI`
  for leak scans; the test fixture binds a free port and polls `/health`.
  Deleted `tests/mock_server.py`, `mock/main.py` (a hello-world stub),
  `mock/Dockerfile`, and `mock/terraform/`. The old Cloud Run deployment
  of the mock was decommissioned along with its image repository, and
  other unused function-era cloud resources were cleaned up or queued
  for manual cleanup. Lesson: a deploy path deleted from the repo is not
  a deployment deleted from the cloud; decommissioning is its own step.
- 2026-10-01: AISR adapter and loop hardening. (1) The four Keycloak calls
  had no timeout, though this doc claimed all AISR calls did; a hung login
  would have held the job for its 22-hour task timeout. Now `(10, 60)`.
  (2) Retries matched `"502" in str(e)`, and the message included the
  response body, so a body mentioning 502 retried and a 503 phrased
  differently didn't; `AISRActionFailedError` now carries `status_code`
  and the predicate checks it. Signing is retried too (no side effects;
  MIIC emails on upload, not signing); the upload never is. (3) Error
  messages no longer include response bodies (`TokenRequestError`
  either). (4) `_get_put_url` never checked the status, so a failed
  signing surfaced as a JSONDecodeError or a PUT to `None`, escaping the
  per-school `except AISRActionFailedError` and aborting every remaining
  school; it now validates status and URL, and the per-school submit,
  probe, and download loops catch any exception for that school alone.
  (5) A single failed staging probe (one login blip in a 20-hour window)
  used to fail the run; probes are now tolerated until the deadline
  (`CycleState.probe_error`), and the canary is the strict one. (6) The
  login form posts a dict, so the username is encoded (it went in raw).
  (7) A failed logout in `aisr_session`'s `finally` could replace the
  error that ended the session; it is now logged by class and swallowed.
  (8) Observation only: each probe logs per-school entry counts and the
  age of the newest upload, to learn whether AISR keeps old results.
  Deleted the vestigial `AISRFileUploadResponse`/`AISRFileDownloadResponse`
  (always `is_successful=True` or raise) and the dead
  `query_file_path is None` check.
- 2026-10-01: the master loads fail-closed, and three silent-failure paths
  are closed. (1) `load_known_records` used to turn *any* exception into
  an empty known set, and `suspicious_diff` exempts an empty known set
  as a "first run": a transient GCS error, or one malformed row in the
  170k-row master, would have delivered every current record as new and
  then overwritten the union master with only the current set — the
  exact flood the brake exists to stop, with the brake switched off by
  its own exemption. Now only GCS NotFound with nothing under
  `snapshots/` is a first run; absent-or-empty with snapshots is
  MasterMissingError, and every other error propagates to
  RunFailed(compute_diff). A test had encoded the old behavior; it is
  replaced by five cases. (2) A downloaded file that failed to parse was
  logged and dropped without counting, so if MIIC changed its file
  format every school would vanish and the run would record an empty
  "success" each month; parse failures now count toward fetch_failures,
  so all-unparseable is AllDownloadsFailed. (3) An uncaught exception
  printed a traceback ending in its message, and messages can carry
  response bodies or field values; `job.main` now catches, prints only
  the class and the innermost frames (file:line function), and exits 1.
  Also: `RecordValidationError` names the field and never quotes the
  value (a shifted column can put a name in the date field); the
  remaining message-logging sites log the error class; the canary reads
  the master and reports `known_records`, so an unreadable master alerts
  the day before the run; transformed files are processed in sorted
  order, so diff row order is deterministic.
- 2026-10-01: repo hygiene. Moved the Build order and Progress sections
  here verbatim from ARCHITECTURE.md (all six phases are done; the design
  doc should describe what exists, not narrate how). Removed three
  committed Terraform plan files (`infra/district.plan`, `infra/unify.plan`,
  `infra/bootstrap/bootstrap.plan`): zip archives embedding state and
  config in a public repo. Inspected before removal: email addresses and
  service-account names only; no credentials, billing ids, OAuth client
  ids, or keys, so nothing needs rotating. History not rewritten. `*.plan`
  and `*.tfplan` are now ignored. The provider lock files are now
  committed (`.terraform.lock.hcl` in `infra/` and `infra/bootstrap/`,
  google 8.5.0, linux_amd64 + darwin_arm64 hashes): the constraint is
  `>= 5.30` with no ceiling, so without a lock any `init` could pull an
  unreviewed major version. Deleted `infra/docs/design_philosophy.md`
  (described the retired Pub/Sub + Cloud Functions design; nothing linked
  to it) and untracked `infra/.vscode/settings.json` (personal editor
  config, already gitignored).

## Through 2026-10-01 (moved from ARCHITECTURE.md)

Moved from ARCHITECTURE.md on 2026-10-01 without edits; read their
present-tense claims as of their dates.

### Build order

Each phase leaves production working. The deployed functions keep running
untouched until phase 5.

1. **Consolidate.** One package, tests green, mock promoted, CI simplified
   to a single project. Pure mechanical move, no behavior change.
2. **Domain rewrite.** Dataclasses replace pandas; closure factories are
   replaced with ports and a composition root; every known transform bug
   becomes a test.
3. **Ledger.** GCS event store, claim objects, snapshots. The download flow
   writes events alongside its existing behavior.
4. **Runtime and deploy.** Cloud Run Job + CLI, container built and deployed
   by CI with WIF, Terraform reconciled with reality (monthly schedule, Drive
   env vars, least-privilege IAM). Canary and alerts live.
5. **Cut over.** Scheduler points at the job. Functions disabled, then
   deleted after one clean monthly cycle. Drive folder protocol
   (to-import/imported) starts.
6. **Retire.** Old packages, Pub/Sub topics, publish workflow, and the PyPI
   listing deprecation notice.

### Progress

Live status of the build order. Updated as work lands.

- [x] **Phase 1: Consolidate.** Single package, tests green, mock promoted,
      CI single-project.
- [x] **Phase 2: Domain rewrite.** Dataclasses, ports, composition root.
- [x] **Phase 3: Ledger.** GCS events, claims, snapshots.
- [x] **Phase 4: Runtime and deploy.** Cloud Run Job, CI deploy via WIF,
      Terraform reconciled, canary + alerts.
- [x] **Phase 5: Cut over.** Scheduler moves to the job; Drive folder
      protocol begins.
- [x] **Phase 6: Retire.** Old functions, topics, publish workflow, PyPI
      deprecation notice (PyPI notice pending, needs Dillon's login).

Notes:

- 2026-10-01: scheduled canary restored (`pipeline-canary`, default
  `9 2 27 * *`, district-overridable as `canary_schedule`). The alerts.tf
  comment claimed a canary on the 27th, but that scheduler was deleted in
  the unified-cycle cleanup, so nothing launched the job between runs and
  the 2026-10-01 IAM fix had no way to be exercised before the Oct 28 run.
  The canary uses the identical launch path (scheduler SA, args override,
  runWithOverrides), so a forced `gcloud scheduler jobs run
  pipeline-canary` proves the fix today with no MIIC email, and every
  month it proves the launch a day early. The scheduler-launch alert now
  watches both scheduler jobs.
- 2026-10-01: INCIDENT FOLLOW-UP — the 2026-07-28 fix was wrong. The
  2026-09-28 scheduled launch got the same 403 with project-level
  `run.invoker` in place. Real cause: the scheduler body carries
  `overrides.containerOverrides[].args = ["run"]`, and a `jobs:run`
  request with overrides requires `run.jobs.runWithOverrides`, which
  `run.invoker` does not include. Fix: the job-level binding becomes
  `roles/run.jobsExecutorWithOverrides`; the project-level invoker is
  removed. September's cycle ran by hand on 2026-09-27 (Chicago), so no
  data impact. Terraform applied by hand 2026-10-01.
- 2026-07-28: INCIDENT — the first autonomous launch never happened.
  Cloud Scheduler fired on time (07:09:01Z = 2:09am Chicago) and got
  HTTP 403 PERMISSION_DENIED calling the v2 `jobs:run` endpoint, despite
  the job-level `roles/run.invoker` binding for the scheduler SA — the
  v2 API check did not honor it. The job never started, so no RunFailed
  event and no execution metric existed: the failure was invisible to
  the existing alert by construction (the exact gap the alerts.tf
  limitation note described). Data impact: none — July's cycle had
  already completed on the 23rd. Fix (this commit): project-level
  `run.invoker` for the scheduler SA (blast radius unchanged — the
  district project contains exactly one job) and a log-match alert on
  `cloud_scheduler_job` severity>=ERROR, which is the only signal that
  exists when a launch fails. Dillon's call: no July claim backfill, no
  immediate rerun ("it's the summer") — a supervised run comes later;
  note that a manual run before Aug 1 would resubmit July rosters and
  email the nurses, while from Aug 1 submission is the intended monthly
  one. Terraform applied by hand per the usual split (CI validates,
  humans apply).
- 2026-07-23: ImportConfirmed made real (commit 3 of the cleanup sweep).
  The delete-as-ack protocol described under "Drive is the UI" now has
  code: `sinks/drive.py` gained `list_drive_filenames` (drive.file scope,
  so it lists only the pipeline's own deliveries), and
  `record_import_confirmations` runs at the top of each `run` cycle —
  Delivered files gone from the folder get an ImportConfirmed event, ones
  lingering past IMPORT_REMINDER_DAYS get a warning. Best-effort
  throughout: a Drive listing failure is logged and swallowed, never
  sinking the delivery work. The previously-unused `import_confirmed`
  event factory now has a caller. 112 tests.
- 2026-07-23: cleanup sweep making the code match its promises, on
  Dillon's call to "get this code singing." Three commits. (1) Deletions:
  the local transform CLI, its metadata generator (the last closure
  factory), `runtime/main.py` and INI logging — runtime/ is now exactly
  two entrypoints and `mn-immunization` is status-only; plus
  `upload_to_storage`, the tests/cli subprocess suite, a placeholder
  test, `.gcloudignore` (replaced by `.dockerignore`), and a dead mock
  data generator. (2) Truth-making: two ARCHITECTURE.md claims were
  aspirational, now real — login scrapes the form action URL and POSTs
  back verbatim (the hardcoded Keycloak `execution` UUID is gone), and
  `iddis`/`s3_upload_host` are config threaded as `DistrictInfo` with no
  code fallback (the 30-district plan needed both). Also: the login log
  line no longer prints the staff username; RunContext is typed to the
  ledger ports, not the GCS classes. (3) ImportConfirmed made real (see
  its own note). Verified by a manual canary against real AISR before the
  first autonomous run.
- 2026-07-23: output discipline pass, on Dillon's question about the
  print/logger mix. The rule now: print is for program output, logging
  is for diagnostics. The pipeline layer's operator narrative (staging
  counts, delivery confirmations, the BLOCKED line) moved from print to
  the logger; print survives only in runtime entrypoints where the
  printed thing is the program's actual output (job.py's result JSON,
  the CLI status table). job.py points the root log handler at stdout
  because Cloud Run ingests stderr with ERROR severity — routine info
  lines must not read as errors in Cloud Logging. CI's lint job now
  runs `ruff format --check` alongside `ruff check`, so formatting is
  enforced rather than habitual.
- 2026-07-23: decider core step 3 closed, and this document trued up so
  it reads top to bottom as a description of what exists (history lives
  only in these notes). The step-3 decision: `incremental.py` stays.
  The design called for dissolving it, but after step 2 pulled the
  compute/commit split forward, what remained was a coherent
  four-function diff-processing module with callers in both the
  executors and the rebaseline cycle; folding it into execute.py would
  have traded a clear module for a fatter one. Tidies that were worth
  it: DiffComputed dropped its always-empty snapshot_path field (the
  snapshot reference lives on MasterCommitted, where the snapshot is
  actually written) and stale query/download-era docstrings were fixed.
  Housekeeping in the same pass: dependencies verified current
  (`uv lock --upgrade` changed no versions — dependabot automerge has
  kept the lockfile fresh) and Terraform reconciled against
  mn-immun-bd9001: the only drift was gcloud's client metadata stamped
  on the Cloud Run job by CI deploys, now in `ignore_changes` next to
  the image, after which `terraform plan` reports zero changes.
  110 tests.
- 2026-07-23: decider core step 2 landed — the loop is live. `run_cycle`
  is now three lines: scaffolding, credentials, `run_to_completion`.
  `pipeline/execute.py` holds the executors and the runner loop (the one
  place terminal events are written); `download_and_deliver` and
  `poll_until` are deleted; waiting is a decide branch. The step-3
  compute/commit split was pulled forward because correctness required
  it: `incremental.py` is now `compute_diff` (reads only, temp files,
  best-effort GCS diff archive) and `commit_master` (the one durable
  write, failures propagate). Behavior changes, all deliberate: the
  ordering flaws are dead (brake before any persistence; Drive delivery
  before the master commit, so a failed upload is a loud
  RunFailed(deliver_diff) with the master untouched); a new
  MasterCommitted event records the commit; a missing
  GOOGLE_DRIVE_FOLDER_ID fails before roster submission instead of
  silently skipping delivery after it; a lost date claim is verified
  against recent runs' Delivered events before being trusted, so a
  claimant that crashed before uploading can no longer suppress a
  delivery (fail-open toward delivering, per the claims philosophy);
  and the Delivered("gcs") event is gone — the GCS diff copy is an
  archive, Delivered now always means Drive. Step 3 as designed is
  largely absorbed; what remains is optional tidying. 109 tests.
- 2026-07-23: decider core step 1 landed. `pipeline/policy.py` holds
  CycleState (frozen, with named `with_*` transitions as the fold),
  DiffResult, the six Step types, and `decide` — pure, wired to
  nothing yet; production still runs the script shape until step 2.
  `tests/pipeline/test_policy.py` is the decision table: every ordering
  guarantee from the design is a case, including a driver test proving
  every start state reaches exactly one Finish without repeating a
  step. One deliberate behavior change surfaced by writing the table:
  all schools failing to download was previously a RunCompleted with
  zero files; `decide` calls it RunFailed(fetch, AllDownloadsFailed) —
  an all-failure is a failure, per the never-fail-invisibly rule.
  99 tests.
- 2026-07-23: decider-core distillation designed (see "The decider
  core"), prompted by Dillon's report that download_and_deliver was too
  big. The review behind it found two live ordering flaws — master
  committed before the brake and before delivery, and Drive delivery
  failure recorded as RunCompleted after the master had already
  absorbed the records — both consequences of a script shape that
  cannot distinguish computed from committed from delivered. The
  `eventsourcing` library was considered and rejected (framework and
  database surface for a job three durable booleans can do); the
  decider pattern is hand-rolled instead. Design written, code not yet
  started; production runs on the current shape until the distillation
  lands, ideally before the July 28 scheduled cycle.
- 2026-07-23: layout re-sort, on Dillon's catchall concern about
  runtime/. The rule is now enforced by the tree: runtime/ holds only
  entrypoints (job, cli, main — "does this file exist only because the
  code has to run somewhere?"); the application layer lives in pipeline/
  (cycles = use-cases, incremental = diff processing, support = shared
  policies, files = naming); adapters live in their slices (sinks/drive,
  gcp/storage, gcp/secrets). The runtime/cloud/ package name — a fossil
  of the Cloud Functions era — is gone. Dependency direction:
  domain <- sources/sinks/gcp/ledger <- pipeline <- runtime. Tests mirror
  the slices. Pure renames; no behavior change.
- 2026-07-23: Drive reduced to the import queue, on Dillon's answer that
  staff never used the per-school backup folders. Deleted: the backup
  upload path, its filename-based school matching (the ugliest surviving
  code), and the Drive folder helpers. Added: the `rebaseline` cycle
  (manual only) pushing the whole known set as size-chunked files, safe
  because IC imports are idempotent — that idempotence is now a recorded
  design fact this system leans on.
- 2026-07-23: first real production cycle verified end to end, nine days
  early: query submitted for 8 schools (MDH staged results in ~15
  minutes), download fetched all 8, diff of 648 new records against
  170,361 known (0.4%, brake untriggered — the feared id-format flood did
  not exist), delivered to Drive. The full run is 13 ledger events.
- 2026-07-23: unified cycle (smell cleanup, at Dillon's request). One
  scheduler now runs the whole pipeline: query, poll, download, deliver.
  The period query claim makes reruns free (no duplicate nurse email);
  the download and canary schedulers are gone; the canary cycle remains
  as a manual probe. Deleted as part of the same pass: the separate
  query/download cycles, the completion-metadata JSONs (the ledger is the
  record), the CLI's bulk-query and get-vaccinations commands and their
  helpers (duplicates of the cycles; manual operation is `gcloud run jobs
  execute`), and the print/logger mix. Cycle scaffolding (ledger, config,
  schools, terminal-event guarantee) lives in one pipeline_run context
  manager. Kept deliberately despite the purge: per-school Drive backup
  uploads and their filename-based school matching — whether anyone uses
  those folders is a question for district staff, and their removal is
  the next easy win if not. Also noted for later: automating the Infinite
  Campus import step to remove the last manual work.
- 2026-07-23: CUTOVER EXECUTED (phases 5 and 6). Bootstrap applied (WIF
  pool + deployer SA, main-branch-only trust); repo variables set; Deploy
  workflow live. District infra applied after importing the data bucket
  and five secret shells; the plan gate caught a real one: the first
  bucket import missed the project attribute, the plan wanted to
  destroy+recreate the data bucket, and lifecycle.prevent_destroy blocked
  it — re-imported with the project-qualified id, clean plan (16 add /
  3 label-only changes / 0 destroy), applied. Container fixed (install at
  build, venv-script entrypoint; the first image failed at start because
  .gcloudignore had excluded the README that hatchling requires). Legacy
  schedulers paused then deleted, along with both Cloud Functions, both
  Pub/Sub topics, and the over-privileged immunization-function service
  account. Verified live: manual canary (login + read-only listing per
  school, ledger events with terminal RunCompleted) and manual download
  cycle (0 files, expected — AISR stages results only after a query
  cycle). First fully scheduled sequence: canary July 27, query July 28
  (the one that emails nurses, untouched by hand), download August 1,
  which performs the master regeneration guarded by the sanity brake.
  Left in place deliberately: the two legacy source-zip buckets
  (harmless, blocked from mass deletion); stale dependabot alerts against
  deleted per-package manifests (dismiss in the GitHub UI); the PyPI
  deprecation notice (needs Dillon's PyPI login). Known minor: the AISR
  login logs the staff username at INFO; operational identity rather than
  student PHI, but worth quieting eventually.
- 2026-07-22 (pre-cutover hardening, after Dillon's review): master file
  semantics changed from master=current to master=union(known, current).
  Absence is never deletion: a school whose download fails keeps its
  records in the master, killing the confirmed drift bug where a failed
  week followed by a good week re-delivered old records as new. Added a
  diff-size sanity brake (suspicious_diff): a diff exceeding
  max(50, 20% of known) blocks Drive delivery and fails the run loudly —
  floods of duplicates must never reach the nurses (first-ever runs with
  an empty known set are exempt; tune or disable via
  DIFF_SANITY_FRACTION). Security review came back clean; its two
  informational notes are fixed (transform-failure logs now carry error
  class only, since parse messages can quote a PHI field value; WIF trust
  now requires refs/heads/main, not just the repository). Operational
  facts recorded: MIIC emails all nurses on every bulk-query upload, so
  the query cycle is never run manually and rehearsals use canary or
  download only; the Drive protocol is delete-as-ack per existing staff
  habit (see "Drive is the UI").
- 2026-07-22: branch `rewrite-2026` created; roster and config removed from
  all working trees; `.gitignore` guards added.
- 2026-07-22: phase 1 done. Five workspaces collapsed into `src/mn_immunization`
  (slices: `etl/` transitional, `sources/aisr/`, `runtime/` with `cloud/`).
  Mock is a uv workspace member sharing the root lockfile. All 53 tests green,
  ruff clean. CI rewritten: test, lint, pip-audit, gitleaks. Publish workflow
  and PyPI ceremony deleted (phase 6 item pulled forward; 0.1.3 stays on PyPI
  for the deployed functions). CLI renamed to `mn-immunization`.
- TODO at merge to main: enable branch protection requiring the `test`,
  `lint`, `audit`, and `gitleaks` checks, so dependabot automerge gates on
  them (today main has no protection at all).
- 2026-07-22: phase 2 done. Domain is pure dataclasses (`records.py`,
  `ic_format.py`); AISR file parsing lives at the AISR edge
  (`sources/aisr/parsing.py`); `AisrClient` + `aisr_session` replace the
  closure factories; `ImmunizationSource` port added. The `etl/` package is
  deleted. pandas, faker, and httpx dropped from dependencies; the suite
  went from 15s to 3s. 54 tests.
- Behavior changes in phase 2, on purpose: the CLI now exits nonzero when
  authentication fails or any school's query/download fails (both previously
  logged and exited 0); the dead `check-errors` subcommand is gone.
- Data caveat for the phase 5 cutover: the old pipeline read ids through
  pandas, which coerced numeric-looking ids (a leading zero would have been
  stripped); the new parser preserves ids verbatim. The known-vaccinations
  master must be regenerated from a fresh full download at cutover (already
  planned as the snapshot bootstrap) so record identities line up.
- 2026-07-22: phase 3 done. `ledger/` holds the event factories (with
  `TERMINAL_TYPES` for the three outcomes), the `RunLedger`/`SnapshotStore`
  ports, the GCS adapters (one JSON object per event; claims via
  if-generation-match=0; content-addressed snapshots), and in-memory
  versions for tests and bucket-less local runs. Both cloud handlers now
  write events and guarantee a terminal event; the download handler claims
  the date's diff before computing it and records RunSkipped when it loses,
  which is the July double-run fix as code. Two softenings until cutover,
  marked in code: ledger appends are best-effort (a ledger write failure
  must not sink a delivery), and a failed claim *check* proceeds rather
  than skips (delivering twice is survivable; delivering never is not).
  Alerting on RunFailed/absent terminal events is phase 4. 65 tests.
- 2026-07-22: phase 4, runtime half done. The handler bodies moved to
  `runtime/cycles.py` (query, download, canary) so the Cloud Run Job, the
  legacy functions, and local runs execute identical code; the functions in
  `runtime/cloud/main.py` are now three-line shims. `mn-immunization-job
  query|download|canary --trigger manual|scheduled` is the container
  entrypoint (Dockerfile at the repo root, built only by CI). The canary
  logs in and lists records read-only per school, touching no PHI. The
  ledger grew its read side (`read_recent_runs`) and the CLI a `status`
  command that prints recent runs and flags any run with no terminal
  event. Remaining for phase 4: the Terraform district module (one project
  per district), the CI deploy workflow via WIF, and monitoring alerts.
  70 tests.
- 2026-07-22: phase 4, infra half written and validated (applied nowhere;
  production stays untouched until phase 5 by Dillon's call). `infra/` is
  the district factory: one module instance per `districts/*.json`, with
  project creation for new districts and adoption for ISD 197. Decided
  stance on the existing console state: assert fresh everything except the
  data bucket and the five secret shells, which get imported at cutover
  because they hold real data and values; the legacy functions, topics,
  and schedulers are never imported and die in phase 6. WIF bootstrap is
  its own root, applied by a human at cutover; the Deploy workflow is
  inert until its outputs become repo variables. Terraform is validated in
  CI (offline) but applied only by a human: CI deploys images, humans
  deploy infrastructure. The dress rehearsal for the project factory is a
  throwaway district JSON (sandbox.json.example) rather than any mock: WIF
  and IAM have no local emulator, and a disposable project exercises the
  real thing with zero production contact. Alert limitation recorded in
  alerts.tf: metric-absence dead-man alerts cannot span a monthly cadence;
  the canary covers pre-run breakage, and a true absence alert becomes
  practical at weekly or daily cadence.
