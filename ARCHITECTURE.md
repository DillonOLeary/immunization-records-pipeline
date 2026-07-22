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
    records.py                  VaccinationRecord, RecordSet
    diffing.py                  combine, dedupe, diff against known set
    ic_format.py                render RecordSets to Infinite Campus CSV
  sources/
    aisr/                       the hard-won MIIC protocol knowledge
      authenticate.py           Keycloak login dance (no hardcoded IDs)
      actions.py                bulk query upload, results download
      port.py                   AisrSource protocol
  sinks/
    drive.py                    DeliveryTarget adapter for Google Drive
    port.py                     DeliveryTarget protocol
  ledger/
    events.py                   event types (dataclasses, JSON-serialized)
    gcs_ledger.py               append-only ledger on GCS objects
    port.py                     RunLedger protocol
  runtime/
    config.py                   typed config, loaded from GCS or local file
    composition.py              the only place adapters meet the domain
    cli.py                      mn-immunization run|status|canary commands
    job.py                      Cloud Run Job entrypoint (thin wrapper on cli)
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
gs://<bucket>/ledger/claims/<YYYY-MM>_diff          idempotency claim
gs://<bucket>/snapshots/<sha256>.csv                 known-set snapshots
```

Event catalog:

| Event            | Data                                          |
|------------------|-----------------------------------------------|
| RunStarted       | run_id, kind (query/download), trigger (scheduled/manual) |
| QuerySubmitted   | school_id, query_file_hash                    |
| RecordsFetched   | school_id, count, content_hash, snapshot_path |
| DiffComputed     | month, new_count, known_hash, diff_hash       |
| Delivered        | file_name, drive_file_id                      |
| ImportConfirmed  | file_name, how (folder move), at              |
| RunSkipped       | reason (e.g. diff already delivered)          |
| RunCompleted     | counts summary                                |
| RunFailed        | step, error class (never record content)      |

Design points:

- The known-vaccination set is not stored in events. It is a content-addressed
  snapshot in `snapshots/`; events reference it by hash. This replaces the
  mutable `all_known_vaccinations.csv` master file. History is never
  overwritten, and any month's diff is reproducible from its inputs.
- Idempotency via claim objects. Before computing a month's diff, the run
  creates `ledger/claims/<YYYY-MM>_diff` with an if-generation-match=0
  precondition. Exactly one run per month can win. This kills the observed
  July 1 incident, where a manual run and the scheduled run both delivered a
  file named `2026-07-01_new_vaccinations.csv` and the second was near-empty:
  the losing run now records RunSkipped and delivers nothing.
- Never fail invisibly. Every entrypoint guarantees a terminal event
  (RunCompleted, RunSkipped, or RunFailed). A Cloud Monitoring alert fires if
  the expected scheduled run has no terminal event by the morning after, and
  on any RunFailed. The alert is the dead man's switch; the ledger is what it
  watches.

## Drive is the UI

The Drive folder becomes a small protocol instead of a dumping ground:

```
<district folder>/
  to-import/          the month's diff lands here
  imported/           the human moves the file here after the IC import
  backups/<school>/   full per-school transformed files
```

The human's existing action (move a file between folders) becomes the
confirmation signal. The download run (or the canary) lists `to-import/`;
a file that has been moved to `imported/` gets an ImportConfirmed event; a
file still sitting in `to-import/` after N days triggers an alert. The loop
closes with zero new surface, no frontend, and no new habits beyond one
folder move.

If requirements outgrow this (30 districts likely will), the replacement is
a small web app reading the ledger, and the ledger port is already there.
Going off Google Workspace is acceptable then, not before.

## Runtime: CLI first, one Cloud Run Job

The same code runs three ways, in order of use:

1. `uv run mn-immunization run download --dry-run --against mock` locally.
2. `gcloud run jobs execute` for a manual production run. Recorded in the
   ledger with trigger=manual.
3. Cloud Scheduler triggering the Cloud Run Job on the monthly schedule
   (query on the 28th, download on the 1st).

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

- No hardcoded Keycloak `execution` UUID. The login flow scrapes all flow
  parameters from the live form, every session.
- No hardcoded district values in code. The old core hardcoded the ISD 197
  district code and the MDH S3 host; both move to per-district config.
- Contract tests run the real adapter against the mock AISR server in CI.
- A canary command performs login plus a read-only records listing. Scheduled
  on the 27th, the day before the query run. If MIIC changed something, the
  alert arrives with a day of slack instead of a silent mid-run failure.
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
- CI: pytest + ruff (exists), plus pip-audit, gitleaks, and CodeQL on every
  PR. Dependabot automerges patch and minor bumps only after required checks
  pass; branch protection must list those checks or automerge gates on
  nothing.

## The 30-district ramp

Designed in now, because it is cheap:

- Zero district-specific values in code. Everything district-shaped lives in
  one config file per district.
- Terraform is a module. A district is a `tfvars` file and an apply.
- CI deploys via a matrix over districts. Adding district N is a config PR.
- Ledger and bucket paths carry no assumptions that one project serves one
  district, so consolidation remains possible if project-per-district ever
  becomes the bottleneck.

Deliberately deferred until real districts force the question: any control
plane or admin UI, cross-district dashboards, a multi-tenant frontend,
self-service onboarding. The trigger to revisit is operational pain at
roughly 5 to 10 districts, not a number picked today.

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
