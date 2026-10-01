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
Sources, sinks, and ledger define ports; adapters implement them; the
pipeline reaches adapters only through ports; only runtime/ reads the
environment or the clock. A second SIS (Skyward, JMC) is a new adapter
behind an existing port, not a refactor. `tests/test_architecture.py`
enforces these rules (and the no-exception-values-in-logs rule) by
reading the code; its `ALLOWED` list names every exception that remains
and can only shrink.

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
gs://<bucket>/ledger/claims/<period>_query_<school_id>  one roster submission per school per period
gs://<bucket>/ledger/claims/<YYYY-MM-DD>_diff           one delivery per date
gs://<bucket>/snapshots/<sha256>.csv                    known-set snapshots
```

Query claims are what make reruns safe to fire freely: MIIC emails every
nurse on each roster submission, so a roster is sent at most once per
school per period, and they fail closed. A school with a QuerySubmitted
event for the period (the event records the period) is done. Otherwise
the run takes the school's claim immediately before its upload, after
login, so a failed login holds nothing. A claim lost without an event
means an earlier run may have uploaded and crashed before recording it:
the school is *stuck*, never resubmitted automatically, and the run
delivers the other schools and then ends RunFailed naming it
(`stuck_schools`). `mn-immunization status` lists stuck claims with the
command to release one; ONBOARDING has the procedure. A claim that cannot
be checked at all is a failure, not a pass (unlike the diff claim below,
where acting twice is the survivable side). The period format is
configuration (monthly today, QUERY_PERIOD_FORMAT). Claims named
`<period>_query` (one per period, before per-school claims) are honored
as "all submitted" for their period.

Diff claims are keyed by run date, not by month. The cadence is configuration
(monthly today, possibly weekly or daily in fall 2026), and the diff-against-
snapshot model does not care how often it runs: each run diffs against the
latest known snapshot and delivers only what is new.

Event catalog:

| Event            | Data                                          |
|------------------|-----------------------------------------------|
| RunStarted       | kind (run/canary/rebaseline), trigger (scheduled/manual) |
| QuerySubmitted   | school_id, query_file_hash, period            |
| RecordsFetched   | school_id, content_hash, byte_size            |
| DiffComputed     | new_count, total_count, known_hash, diff_hash |
| Delivered        | file_name, target (drive), remote_id          |
| MasterCommitted  | master_hash, record_count, snapshot_path      |
| ImportConfirmed  | file_name, how (folder move)                  |
| RunSkipped       | reason (e.g. diff already delivered)          |
| RunCompleted     | counts summary (incl. queries_submitted)      |
| RunFailed        | step, error class (never record content); stuck_schools / failed_schools ids when a roster did not go out |

Design points:

- The known-vaccination set is not stored in events. The working copy is
  the union master at `output/all_known_vaccinations.csv`, and every
  commit also writes a content-addressed snapshot to `snapshots/`,
  referenced by hash from MasterCommitted. History is never overwritten,
  and any run's diff is reproducible from its inputs.
- The master loads fail-closed (`load_known_records`). An empty known set
  exempts a run from the sanity brake and makes every record "new", so
  only a master that has never existed (GCS NotFound and nothing under
  `snapshots/`) may load as empty. Absent-or-empty while snapshots exist
  is MasterMissingError; a transient read error or a single malformed row
  propagates. All three end the run as RunFailed(compute_diff) before
  anything is delivered or committed. The canary reads the master too,
  so this surfaces the day before a run.
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
- The canary cycle (login plus a read-only records listing) runs on its
  own schedule the day before the run cycle (`canary_schedule`), through
  the same scheduler launch path, so both MIIC breakage and a broken launch
  alert a day early; it also runs by hand as a readiness probe. Any
  school's listing failing fails the canary. The same staged-results check
  runs inside the unified cycle's polling loop, where it is tolerant on
  purpose: a failed probe (or one school's failed listing) is logged and
  retried at the next interval, and only nothing staged at the deadline
  fails the run, naming the last probe error if there was one.
- All AISR HTTP calls have explicit timeouts, Keycloak's included.
- Retries key off the HTTP status (502/503/504) or a connection error or
  timeout, never message text, and apply only to calls without side
  effects: signing, listing, downloading. The roster upload is never
  retried: it is what makes MIIC email every nurse, and an unknown outcome
  fails loudly instead of risking a second email.
- `AISRActionFailedError` carries `status_code` and a short description of
  the attempt; no AISR error message includes a response body.
- Each staging probe logs per school how many result entries AISR lists
  and the age of the newest upload (no PHI). "Staged" means the latest
  listed entry has a results file; whether AISR keeps old results between
  runs is not yet known, and must be before any move to a weekly cadence.

## Security model

- Least privilege: the job's service account gets objectAdmin on the one
  data bucket and accessor on its secrets, nothing project-wide; the
  scheduler's can launch the one job. Nothing runs as Google's default
  compute or App Engine service accounts, and the module removes the
  project-wide Editor role Google grants them by default.
- No service account keys anywhere. GitHub Actions authenticates with
  Workload Identity Federation; humans use their own identities.
- Secrets (AISR credentials, Drive OAuth) live only in Secret Manager.
- No PHI in logs or ledger events, ever. Logs carry counts, hashes, school
  names, and error classes. Enforced three ways: exceptions are value-free
  by construction (validation errors carry a field name, never a value;
  AISR errors carry a status, never a body); `tests/test_architecture.py`
  fails on any exception value reaching a log line or f-string; and every
  end-to-end test (`tests/e2e/`) scans all log records, printed output,
  and ledger objects for the fake AISR's canary PHI.
- No PHI in the repo tree, enforced by .gitignore (`config.json`,
  `*_students.csv`, `*.tfvars`) and by keeping rosters and query files only
  in GCS.
- Per-district GCP project isolation stays. It is the strongest tenancy
  boundary available and the compliance story writes itself.
- CI: pytest (including the architecture-rules test), ruff (lint and
  format check), basedpyright (standard mode, over `src/`), pip-audit,
  gitleaks, offline terraform fmt/validate, and CodeQL (GitHub default
  setup, python + actions) on every pull request (stacked ones included)
  and every push to main. Branch protection lists the required checks.
  Dependabot PRs are merged by hand, because merging to main deploys.

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
transitions are the fold. Only three facts need durable memory (rosters
submitted, diff delivered, master committed); fetching, transforming,
and diffing are read-only and cheap, so a resumed run just recomputes
them:

```python
@dataclass(frozen=True)
class CycleState:
    submission: Submission | None = None  # per school: submitted / stuck / failed
    staged: int = 0                 # live AISR probe, not from the ledger
    staging_deadline_passed: bool = False
    probe_error: str = ""           # last failed probe's class, if any
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
def decide(state, brake_fraction):
    sub = state.submission
    if sub is None:                   return SubmitQueries()
    if not sub.submitted:             return Finish("failed", "submit_queries",
                                                    "NoQueriesSubmitted")
    if state.staged < len(sub.submitted) and not state.staging_deadline_passed:
        return AwaitStaging()
    if state.staged == 0:             return Finish("failed", "awaiting_results",
                                                    state.probe_error or "NoResultsStaged")
    diff = state.diff
    if diff is None:                  return ComputeDiff()
    if diff.files_transformed == 0 and diff.fetch_failures > 0:
        return Finish("failed", "fetch", "AllDownloadsFailed")
    if diff.new_count == 0:           return settle(sub, Finish("success"))
    if suspicious_diff(diff.new_count, diff.known_count, brake_fraction):
        return Finish("blocked", "diff_sanity", "SuspiciousDiffVolume")
    if not state.delivered:           return DeliverDiff(diff)
    if not state.master_committed:    return CommitMaster(diff)
    if state.delivered_elsewhere:     return settle(sub, Finish("skipped"))
    return settle(sub, Finish("success"))

# settle: any stuck or failed school turns success/skip into
# Finish("failed", "submit_queries", "QuerySubmissionIncomplete")
```

**Runner** (`execute.py`) — a generic loop: decide, execute the one
step, fold what it learned into the state, repeat. Executors are dumb
dispatch onto the adapters; a step that raises becomes a loud RunFailed
naming the step, and nothing after it runs:

| Step          | Executor wraps                                     | Events           |
|---------------|----------------------------------------------------|------------------|
| SubmitQueries | per-school claims + roster uploads (`_submit_queries`) | QuerySubmitted ×N |
| AwaitStaging  | `probe_staging` over submitted schools, then sleep one interval | —   |
| ComputeDiff   | fetch + transform + combine + `RecordSet.diff`     | RecordsFetched ×N, DiffComputed |
| DeliverDiff   | date claim + Drive upload                          | Delivered        |
| CommitMaster  | union → master upload + snapshot                   | MasterCommitted  |
| Finish        | terminal event, return status                      | RunCompleted / RunSkipped / RunFailed |

Guarantees this shape makes structural rather than disciplinary:

- Exactly one terminal event per run: only `Finish` writes them, and
  the loop ends only on `Finish` (or on a step failure, which writes
  its RunFailed in one place in the loop).
- The brake precedes all persistence. Nothing it blocks has happened yet.
- A roster that may already have gone out is never sent again, and a
  school that did not go out is never quiet: a stuck or failed school
  lets the others deliver and commit, then turns the run's success into
  RunFailed(submit_queries) naming it. Only submitted schools are waited
  for; if none was, the run fails at once instead of waiting 20 hours.
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

## History

The build order, the dated progress notes, and incident write-ups live in
[docs/HISTORY.md](docs/HISTORY.md). This document describes what exists.

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
