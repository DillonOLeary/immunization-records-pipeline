# Architecture

This system relays immunization records between two systems of record it does
not own. MIIC (Minnesota's immunization registry, via the AISR bulk interface)
owns immunization truth. Infinite Campus owns student truth. Once a month the
pipeline submits a roster query to AISR, downloads the results, computes which
vaccination records are new since last month, and delivers a diff file to a
Google Drive folder where a district staff member imports it into Infinite
Campus.

The pipeline owns almost no state. The one thing it does own is knowledge of
its own runs: what was fetched, what was diffed, what was delivered, and
whether a human completed the import. That knowledge is the run ledger, and
it is the backbone of this design.

## Constraints, honestly stated

- Student health data. A leak is the worst possible outcome. Simplicity and
  small attack surface beat features everywhere they conflict.
- One maintainer. Anything that needs babysitting will not get it.
- Two runs a month, eight schools, thousands of records. This is small data.
- Scale honesty: one district today, a second district must not require
  rearchitecting, and roughly 30 districts is plausible by fall 2026. See
  "The 30-district ramp" below for exactly what that changes and what it
  does not.
- Google Drive is the user interface for now. It is a surface the district
  already trusts and already secures. We push it as far as it will go before
  building anything new.
- A failed run is acceptable. An unnoticed failed run is not. Every run must
  end in a recorded success or a recorded, alerting failure.

## The shape

One repo, one Python package, vertical slices inside it. The five-package
workspace split is retired, along with publishing to PyPI (it existed to
serve the split and caused version drift between the published library and
the repo).

```
pyproject.toml                  one uv project, one lockfile
src/mn_immunization/
  domain/                       pure logic, no I/O, no pandas
    records.py                  VaccinationRecord, RecordSet (dedupe, union, diff)
    ic_format.py                render/parse Infinite Campus CSV
  sources/
    aisr/                       the hard-won MIIC protocol knowledge
      authenticate.py           Keycloak login dance (no hardcoded IDs)
      actions.py                bulk query upload, results download (retries)
      parsing.py                AISR results file -> RecordSet
      client.py                 session-scoped AisrClient (login/logout)
      port.py                   ImmunizationSource protocol
  sinks/
    drive.py                    Google Drive upload (the import queue)
  gcp/
    storage.py                  Cloud Storage helpers
    secrets.py                  Secret Manager access
  ledger/
    events.py                   event types (dataclasses, JSON-serialized)
    gcs_ledger.py               append-only ledger on GCS objects
    memory.py                   in-memory ledger for tests and local runs
    port.py                     RunLedger / SnapshotStore protocols
  pipeline/                     the application layer
    policy.py                   the decider: CycleState, Steps, decide() (pure)
    execute.py                  executors + the runner loop
    cycles.py                   use-case entrypoints and shared scaffolding
    incremental.py              combine, known set, compute_diff, commit_master
    support.py                  run ids, safe appends, claims, brake
    files.py                    file naming conventions
  runtime/                      entrypoints only
    job.py                      Cloud Run Job entrypoint (run|canary|rebaseline)
    cli.py                      mn-immunization status (read-only ledger window)
mock/                           fake AISR server (dev dependency, promoted
                                from minnesota-immunization-mock)
tests/
  domain/                       pure, fast, exhaustive; this is where TDD pays
  contract/                     adapters against the mock AISR server
  e2e/                          full cycle against mock + local fake ledger
infra/                          Terraform module, instantiated per district
```

The dependency rule, same as any hexagonal design: domain imports nothing.
Sources, sinks, and ledger define ports; adapters implement them; only
runtime/composition.py touches both sides. A second SIS (Skyward, JMC) is a
new adapter behind an existing port, not a refactor.

## Domain: dataclasses, not pandas

The previous core routed eight lines of transform logic through pandas and a
layer of closure factories. At thousands of records, pandas buys nothing and
costs a heavy dependency in a codebase where supply chain is a stated risk.

The domain is frozen dataclasses and pure functions:

- `VaccinationRecord`: id_1, id_2, vaccine group, date. Validated at
  construction. Illegal records are unrepresentable past the parsing edge.
- `RecordSet`: an immutable collection with value semantics. Union, dedupe,
  and `diff(known)` are methods with obvious meanings and property-based
  tests.
- Parsing (AISR pipe-delimited CSV in) and rendering (IC headerless CSV out)
  live at the edges and return/accept domain types.

Every observed production bug in the transform path becomes a unit test here.

## The run ledger

Append-only events on GCS. No new database, no new IAM surface: the job's
service account already reads and writes this bucket. Firestore was
considered and rejected for now; nothing needs to query the ledger while
Drive is the UI. The `RunLedger` port keeps that door open. If a frontend
ever needs queries, a Firestore adapter slots in without touching callers.

Layout (GCS objects are immutable; one object per event):

```
gs://<bucket>/ledger/<YYYY>/<MM>/<run_id>/<seq>_<event>.json
gs://<bucket>/ledger/claims/<period>_query           one roster submission per period
gs://<bucket>/ledger/claims/<YYYY-MM-DD>_diff        one delivery per date
gs://<bucket>/snapshots/<sha256>.csv                 known-set snapshots
```

The query claim is what makes reruns safe to fire freely: MIIC emails every
nurse on each roster submission, so a rerun that loses the period claim
skips submission and goes straight to polling and delivery. The period
format is configuration (monthly today, QUERY_PERIOD_FORMAT).

Claims are keyed by run date, not by month. The cadence is configuration
(monthly today, possibly weekly or daily in fall 2026), and the diff-against-
snapshot model does not care how often it runs: each run diffs against the
latest known snapshot and delivers only what is new.

Event catalog:

| Event            | Data                                          |
|------------------|-----------------------------------------------|
| RunStarted       | kind (run/canary/rebaseline), trigger (scheduled/manual) |
| QuerySubmitted   | school_id, query_file_hash                    |
| RecordsFetched   | school_id, content_hash, byte_size            |
| DiffComputed     | new_count, total_count, known_hash, diff_hash |
| Delivered        | file_name, target (drive), remote_id          |
| MasterCommitted  | master_hash, record_count, snapshot_path      |
| ImportConfirmed  | file_name, how (folder move)                  |
| RunSkipped       | reason (e.g. diff already delivered)          |
| RunCompleted     | counts summary                                |
| RunFailed        | step, error class (never record content)      |

Design points:

- The known-vaccination set is not stored in events. The working copy is
  the union master at `output/all_known_vaccinations.csv`, and every
  commit also writes a content-addressed snapshot to `snapshots/`,
  referenced by hash from MasterCommitted. History is never overwritten,
  and any run's diff is reproducible from its inputs.
- Idempotency via claim objects. Before delivering, the run creates
  `ledger/claims/<YYYY-MM-DD>_diff` with an if-generation-match=0
  precondition; exactly one run per date can win. A run that loses the
  claim verifies against recent runs' Delivered events before trusting
  it: a genuine duplicate records RunSkipped and delivers nothing (the
  observed July 1 incident, where two runs delivered the same date's
  diff, stays dead), while a claimant that crashed before uploading does
  not get to suppress the delivery.
- Never fail invisibly. Every entrypoint guarantees a terminal event
  (RunCompleted, RunSkipped, or RunFailed). A Cloud Monitoring alert fires if
  the expected scheduled run has no terminal event by the morning after, and
  on any RunFailed. The alert is the dead man's switch; the ledger is what it
  watches.

## Drive is the UI

The district staff already have a working protocol, and the design adopts
it rather than inventing one: the diff file lands in the Drive folder, a
staff member imports it into Infinite Campus, and then **deletes the file
from Drive** as their own done-signal. Files present in the folder are the
import queue; an empty folder means caught up; a missed period just means
importing every diff file sitting there (each diff is small and disjoint,
which is the whole point of diffs over raw files).

That makes the confirmation signal file *absence*: at the start of each
run, `record_import_confirmations` lists the folder, and a previously
Delivered diff that is gone gets an ImportConfirmed event (how: deleted
from Drive); a diff still present past IMPORT_REMINDER_DAYS (default 7)
is logged as a warning. The check reads the folder through the
drive.file scope, which sees only files this app created, so the listing
is exactly the pipeline's own deliveries and nothing else in the
district's Drive. It is entirely best-effort — a listing failure is
swallowed — because confirmation must never sink a delivery run. (A true
absence *alert* rather than a warning waits for a weekly-or-denser
cadence, per the note in alerts.tf.) Zero new habits, zero new surface.

Drive holds nothing but the import queue. There are no per-school backup
folders (district staff never used them; GCS snapshots are the archive).
Recovery from sync trouble is the manual `rebaseline` cycle: it pushes the
entire known set to the queue as numbered chunk files
(REBASELINE_CHUNK_RECORDS per file, default 10000), staff import them all
and delete each as done. This is safe at any time because Infinite Campus
imports are idempotent: re-importing a known record changes nothing. Which
records share a chunk carries no meaning; chunking only keeps individual
IC uploads a manageable size.

If requirements outgrow this (30 districts likely will), the replacement is
a small web app reading the ledger, and the ledger port is already there.
Going off Google Workspace is acceptable then, not before.

## Runtime: CLI first, one Cloud Run Job

The same code runs three ways, in order of use:

1. `uv run mn-immunization run download --dry-run --against mock` locally.
2. `gcloud run jobs execute` for a manual production run. Recorded in the
   ledger with trigger=manual.
3. Cloud Scheduler triggering the Cloud Run Job on the configured schedule
   (monthly today; a district JSON change to go weekly or daily). One
   trigger runs the whole pipeline: submit roster queries, poll every 4
   hours (POLL_INTERVAL_SECONDS) until MDH stages results or 20 hours pass
   (POLL_DEADLINE_SECONDS), then download, diff, and deliver. Zero staged
   schools at the deadline fails the run loudly; partial staging proceeds
   (missing schools are acceptable and the union master means nothing
   drifts). MDH staged in 15 minutes when measured; the deadline covers a
   bad day.

Cloud Run Jobs replace the two Pub/Sub-triggered gen-2 functions. Batch work
does not need event plumbing: Scheduler invokes the job directly, timeouts
are generous, and the deployable is a container built by CI, which makes the
previous failure mode (hand-zipped working tree, deployed from a directory
that no longer exists) structurally impossible.

Orchestrators (Dagster, Airflow, Composer) were considered and rejected: two
runs a month does not justify a running control plane. The ledger provides
the observability an orchestrator would, without the surface.

## AISR resilience

MIIC has said the website may change. The blast radius is confined to
`sources/aisr/` and detection is moved ahead of the monthly run:

- No hardcoded Keycloak flow parameters. `login()` scrapes the login form's
  action URL from the live page and POSTs back to it verbatim — exactly what
  a browser does — so a MIIC change to `session_code`, `execution`, or
  `tab_id` cannot break login. (An earlier version hand-built the authenticate
  URL with a hardcoded `execution` UUID; that was the fragile path this
  removes.)
- No hardcoded district values in code. `iddis` and the MDH S3 upload host
  live in config (`district.iddis`, `api.s3_upload_host`) and thread through
  as a `DistrictInfo` to the one place that uploads a roster. There is no code
  fallback: a missing key fails the run loudly rather than uploading under the
  wrong district's identity.
- Contract tests run the real adapter against the mock AISR server in CI.
- The canary cycle (login plus a read-only records listing) is a manual
  readiness probe; the same staged-results check runs inside the unified
  cycle's polling loop, so MIIC breakage surfaces as a loud RunFailed on
  run day rather than a silent stall.
- All AISR HTTP calls have explicit timeouts.

## Security model

- Least privilege: the job's service account gets objectAdmin on the one
  data bucket and accessor on its secrets, nothing project-wide. (The current
  deployment grants storage.admin; this is a downgrade on purpose.)
- No service account keys anywhere. GitHub Actions authenticates with
  Workload Identity Federation; humans use their own identities.
- Secrets (AISR credentials, Drive OAuth) live only in Secret Manager.
- No PHI in logs or ledger events, ever. Logs carry counts, hashes, school
  names, and error classes. This is a hard rule enforced in review and by a
  log-scanning test in e2e.
- No PHI in the repo tree, enforced by .gitignore (`config.json`,
  `*_students.csv`, `*.tfvars`) and by keeping rosters and query files only
  in GCS.
- Per-district GCP project isolation stays. It is the strongest tenancy
  boundary available and the compliance story writes itself.
- CI: pytest, ruff (lint and format check), pip-audit, gitleaks, offline
  terraform fmt/validate, and CodeQL (GitHub default setup, python +
  actions) on every PR and push to main. Dependabot automerges patch and
  minor bumps only after the required checks pass; branch protection
  lists those checks.

## The 30-district ramp

Designed in now, because it is cheap:

- Zero district-specific values in code. Everything district-shaped lives in
  one config file per district.
- One GCP project per district, created and managed by Terraform: a project
  factory module plus one `tfvars` file per district. This is the decided
  tenancy model, not a default to outgrow. A district's project is its IAM
  boundary, its secrets, its data, and its blast radius; there is no shared
  project with per-district file prefixes. Cross-district access is
  impossible by construction rather than forbidden by convention, which is
  the strongest security statement available and the one that keeps a
  30-district incident a 1-district incident.
- CI deploys via a matrix over districts. Adding district N is a config PR.

Deliberately deferred until real districts force the question: any control
plane or admin UI, cross-district dashboards, a multi-tenant frontend,
self-service onboarding. The trigger to revisit is operational pain at
roughly 5 to 10 districts, not a number picked today.

## The decider core

The run cycle's core, designed and landed 2026-07-23. It replaced the
previous orchestration script (~700 lines across three modules) with a
decide/execute core, motivated by two real ordering flaws found while
reviewing the old `download_and_deliver` — not by style:

1. **The master was committed before the brake and before delivery.**
   The old processing function uploaded the new master to GCS, and only
   afterwards did the caller check the sanity brake and attempt Drive
   delivery. The brake stood behind the door it guarded: by the time it
   fired, the suspicious flood was already absorbed into the master it
   existed to protect.
2. **Delivery failure was a warning, then "success."** A failed Drive
   upload was caught, logged, and the run still recorded RunCompleted —
   but the master had already absorbed the records, so no future diff
   would ever carry them. They silently never reached the nurses until
   a human noticed and ran a rebaseline.

Both were one disease: a linear script interleaves deciding with
committing, so the order of side effects is whatever the prose happens
to be. The script shape could not distinguish **computed** from
**committed** from **delivered**.

The fix is the decider pattern (decide/evolve/execute, hand-rolled —
see "Rejected" below for why no framework). Three pieces, all in
`pipeline/`:

**State** (`policy.py`) — a frozen dataclass; the named `with_*`
transitions are the fold. Only three facts need durable memory (query
submitted, diff delivered, master committed); fetching, transforming,
and diffing are read-only and cheap, so a resumed run just recomputes
them:

```python
@dataclass(frozen=True)
class CycleState:
    query_submitted: bool = False   # period claim, or QuerySubmitted this run
    staged: int = 0                 # live AISR probe, not from the ledger
    staging_deadline_passed: bool = False
    diff: DiffResult | None = None  # recomputed each execution
    delivered: bool = False
    delivered_elsewhere: bool = False  # date claim lost, Delivered event found
    master_committed: bool = False
```

**Policy** (`policy.py`) — one pure function that *is* the pipeline.
No I/O, no clock, no env. This is the screen a new maintainer reads
instead of this document's prose (abridged here; the real one carries
reasons on every Finish):

```python
def decide(state, school_count, brake_fraction):
    if not state.query_submitted:     return SubmitQueries()
    if state.staged < school_count and not state.staging_deadline_passed:
        return AwaitStaging()
    if state.staged == 0:             return Finish("failed", "awaiting_results",
                                                    "NoResultsStaged")
    diff = state.diff
    if diff is None:                  return ComputeDiff()
    if diff.files_transformed == 0 and diff.fetch_failures > 0:
        return Finish("failed", "fetch", "AllDownloadsFailed")
    if diff.new_count == 0:           return Finish("success")
    if suspicious_diff(diff.new_count, diff.known_count, brake_fraction):
        return Finish("blocked", "diff_sanity", "SuspiciousDiffVolume")
    if not state.delivered:           return DeliverDiff(diff)
    if not state.master_committed:    return CommitMaster(diff)
    if state.delivered_elsewhere:     return Finish("skipped")
    return Finish("success")
```

**Runner** (`execute.py`) — a generic loop: decide, execute the one
step, fold what it learned into the state, repeat. Executors are dumb
dispatch onto the adapters; a step that raises becomes a loud RunFailed
naming the step, and nothing after it runs:

| Step          | Executor wraps                                     | Events           |
|---------------|----------------------------------------------------|------------------|
| SubmitQueries | period claim + `submit_roster_queries`             | QuerySubmitted ×N |
| AwaitStaging  | `staged_school_count`, then sleep one interval     | —                |
| ComputeDiff   | fetch + transform + combine + `RecordSet.diff`     | RecordsFetched ×N, DiffComputed |
| DeliverDiff   | date claim + Drive upload                          | Delivered        |
| CommitMaster  | union → master upload + snapshot                   | MasterCommitted  |
| Finish        | terminal event, return status                      | RunCompleted / RunSkipped / RunFailed |

Guarantees this shape makes structural rather than disciplinary:

- Exactly one terminal event per run: only `Finish` writes them, and
  the loop ends only on `Finish` (or on a step failure, which writes
  its RunFailed in one place in the loop).
- The brake precedes all persistence. Nothing it blocks has happened yet.
- `CommitMaster` is unreachable until `delivered` is true. A failed
  Drive upload fails the run loudly with the master untouched, and the
  next run re-diffs and re-delivers the same records. The silent
  absorption path no longer exists to be written.
- A crash between delivery and commit resumes at commit: the rerun
  loses the date claim, finds the Delivered event, and finishes the
  commit before recording RunSkipped. Redoing the commit is safe
  because the master is a union — idempotent by construction.
- Waiting is not special. `AwaitStaging` is a decide branch; the loop
  owns the interval and deadline (zero schools staged at the deadline
  finishes failed, partial staging proceeds).
- Claims sit exactly where the danger is: the period claim inside
  SubmitQueries, the date claim inside DeliverDiff. Events drive the
  flow; claims cap the blast radius of a lost event, so `append_event`
  stays best-effort throughout.

What survived untouched: `domain/`, `sources/aisr/`, `sinks/drive.py`,
`gcp/`, the ledger adapters, `runtime/` entrypoints, all of `infra/`.
The keep list is exactly the boundary list — these pieces were already
behind ports, which is why they were keepable.

What was deleted: `download_and_deliver`, `poll_until`, every
guard-plus-terminal-event trio, and the old do-everything processing
function (split into `compute_diff`, reads only, and `commit_master`,
the one durable write). `incremental.py` itself stays as the
diff-processing module — four coherent functions with callers in both
`execute.py` and the rebaseline cycle beat folding 170 lines into the
executors for the sake of a file count. Canary and rebaseline stay as
the linear scripts they are: no ordering hazards, no waiting, nothing
to decide.

Compatibility held through the swap, so cutover was a code change with
no data migration: claim keys, master file path and format, and the
event envelope are all unchanged. One event type was added
(MasterCommitted) and one dropped (Delivered with target "gcs" — the
GCS diff copy is an archive, not a delivery; Delivered always means
the Drive import queue now).

Rejected: the Python `eventsourcing` library. It is an aggregate-OOP
framework built for many long-lived aggregates with concurrent writers,
and it wants a transactional event store — a database this system
deliberately does not have. Adopting it means adding that surface or
writing a custom GCS adapter to fight the framework into our storage.
Event sourcing here is a pattern sized to three durable booleans, not
a framework.

Landed 2026-07-23 in three commits, each leaving production working:
policy pure and wired to nothing first (its decision table encodes
every guarantee above), then the loop and executors replacing the
script, with the compute/commit split pulled forward because the
ordering fix required it. Five days ahead of the first autonomous
scheduled run, which executes on the fixed ordering.

How to test it is part of the design: `tests/pipeline/test_policy.py`
is the decision table (including a driver proving every start state
reaches exactly one Finish); `tests/pipeline/test_cycle_loop.py` drives
the real loop with stub executors and a fake clock, so polling cadence,
deadline behavior, and every failure path are asserted without a single
GCS or AISR mock.

## Build order

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

## Progress

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

## What was deleted and why

- Five workspaces: drift between them caused the stale-checkout incident and
  the version skew between PyPI and the repo.
- PyPI publishing: served the split, not the mission.
- Closure factories (`pipeline_factory.py`): unnamed boundaries that made
  tests assert plumbing instead of behavior.
- pandas in the domain: heavy dependency, no benefit at this scale.
- The mutable master CSV: replaced by content-addressed snapshots plus the
  ledger.
- Pub/Sub topics and functions-framework: replaced by a directly triggered
  Cloud Run Job.
- Log-and-continue error handling: replaced by the terminal-event guarantee.
- The run cycle's script shape (`download_and_deliver`, `poll_until`): a
  linear script cannot distinguish computed from committed from delivered,
  which hid two real ordering flaws. Replaced by the decider core.
- The Delivered("gcs") event: the GCS diff copy is an archive, not a
  delivery. Delivered means the Drive import queue, which keeps the future
  ImportConfirmed design unambiguous.
- The local transform CLI and its metadata generator: the CLI is a
  read-only status window now; transforming AISR files locally was a
  debugging convenience the mock-plus-pytest path covers, and the
  metadata generator was the last closure factory, writing per-file JSON
  the ledger already supersedes.
- `runtime/main.py` and the INI logging config: an entrypoint wrapper from
  the five-workspace era; the status CLI configures logging in three lines.
- `upload_to_storage` (string upload, zero callers) and `.gcloudignore`
  (deploy is `docker build`, not Cloud Build; `.dockerignore` replaces it).
