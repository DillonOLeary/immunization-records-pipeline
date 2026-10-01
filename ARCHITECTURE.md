# Architecture

The pipeline relays immunization records between two systems it does not
own. MIIC (Minnesota's registry, via the AISR bulk interface) owns
immunization truth; Infinite Campus owns student truth. Each scheduled run
submits school rosters to AISR, waits for results, diffs them against
every record already delivered, and puts only the new records in a Google
Drive folder that district staff import from. The one thing the pipeline
owns is knowledge of its own runs: the ledger.

## Constraints

- Student health data. A leak is the worst outcome; simplicity and small
  attack surface win every conflict. No PHI in the repo, logs, or ledger.
- Every roster submission makes MIIC email every nurse in the district.
  A roster goes out at most once per school per period, and `run` is
  never rehearsed (`canary` is the rehearsal).
- A failed run is acceptable; an unnoticed one is not. Every run ends in a
  terminal ledger event, and a failed job or a failed launch alerts.
- One maintainer, small data (monthly, ~8 schools, ~170k known records).
- One GCP project per district: its IAM boundary, data, and blast radius.

## Layout

```
src/mn_immunization/
  domain/                pure: records, IC CSV format, hashing
  sources/aisr/          MIIC protocol: login, actions, parsing, client, port
  sinks/                 Google Drive delivery (drive.py) and its port
  gcp/                   object store, secrets, and the store's port
  ledger/                events, GCS ledger and snapshots, ports
  pipeline/              the application layer
    policy.py            the decider: CycleState -> next Step (pure)
    execute.py           executors and the runner loop
    cycles.py            run, canary, rebaseline
    incremental.py       known set (fail-closed), diff, master commit
    settings.py          every environment variable, parsed once
    services.py          what a cycle is given: ports, settings, clock
    context.py           one run's view: RunContext
  runtime/
    composition.py       the only place adapters are built
    job.py               Cloud Run Job entrypoint
    cli.py               mn-immunization status (read-only)
mock/                    the fake AISR (tests and `uv run mock-server`)
tests/                   mirrors src/; e2e/ runs the job end to end
infra/                   Terraform: one district module per districts/*.json
```

Dependencies point inward: domain imports nothing; adapters import domain
and ports; the pipeline imports only domain and ports; only `runtime/`
builds adapters, reads the environment, or reads the clock.
`tests/test_architecture.py` enforces this, along with the rule that no
exception value ever reaches a log line.

## The run cycle

`policy.decide` is the pipeline on one screen: pure, no I/O, no clock.
The runner (`execute.run_to_completion`) asks it for the next step,
executes it, folds the result into the state, and repeats until `Finish`,
the only step that writes a terminal event.

```
SubmitQueries -> AwaitStaging -> ComputeDiff -> [brake] -> DeliverDiff -> CommitMaster -> Finish
```

- The sanity brake (a diff over max(50, 20% of known)) fires before
  anything is delivered or committed.
- Delivery precedes the master commit, so a failed upload leaves the
  master untouched and the records in the next diff.
- Only schools submitted this period are waited for; staging probes
  tolerate failures until the deadline (20h).
- A school that is stuck or failed to submit lets the others deliver, then
  turns the run's success into RunFailed naming it.

## The ledger

Append-only JSON objects in the district's bucket; no database.

```
ledger/<YYYY>/<MM>/<run_id>/<seq>_<event>.json   one object per event (UTC)
ledger/claims/<period>_query_<school_id>          one roster per school per period
ledger/claims/<YYYY-MM-DD>_diff                   one delivery per date
snapshots/<sha256>.csv                            every committed master
output/all_known_vaccinations.csv                 the master (union of all records)
```

- Claims are create-if-absent objects: exactly one run wins.
- Query claims fail closed. A claim with no QuerySubmitted event is
  *stuck* and never resubmitted; a human checks with MIIC and releases it
  (ONBOARDING). A submission that failed before its upload began releases
  its own claim.
- The diff claim fails open: a lost claim is checked against Delivered
  events, so a crashed claimant cannot suppress a delivery.
- The master only grows (absence is never deletion) and loads fail-closed:
  only a master that never existed is empty; absent-with-snapshots,
  unreadable, or malformed fails the run.
- Periods and file dates use `DISTRICT_TIME_ZONE`; ledger stamps are UTC.

## Drive is the UI

Each diff lands in one folder; staff import it into Infinite Campus and
delete it. A delivered file that disappears is recorded as
ImportConfirmed; one lingering past 7 days is a logged warning. The
`drive.file` scope sees only the pipeline's own files. `rebaseline`
pushes the whole master in chunks to recover from sync trouble; safe
because IC imports are idempotent.

## AISR

- Login scrapes the Keycloak form action and posts back to it, so flow
  parameters can change without breaking it.
- Every call has a timeout. Retries key off HTTP status (502/503/504) and
  only for side-effect-free calls; the roster upload is never retried.
- Errors carry a status, never a response body.
- The canary (scheduled the day before each run) fails on any listing
  error; the run's staging probe tolerates them.
- Open question before any weekly cadence: whether AISR keeps old results
  (probes log entry counts and upload ages to answer it).

## Operations and security

- Cloud Run Job `pipeline-job`, launched by Cloud Scheduler (`run` monthly,
  `canary` the day before). Manual runs: `gcloud run jobs execute`. The
  CLI only reads the ledger.
- Alerts email on a failed job execution and on a failed scheduler launch.
- CI: pytest (including e2e and the architecture rules), ruff,
  basedpyright, pip-audit, gitleaks, terraform validate, CodeQL. Deploys
  build and smoke-test the image, then update the job (via WIF; no
  service-account keys). Today the deploy covers one district.
- Terraform is applied by a human. Service accounts are least-privilege;
  Google's default accounts are stripped of Editor.
- Merging to `main` deploys, so Dependabot PRs are merged by hand.
- PHI stays out of logs by construction (value-free exceptions), by test
  (the architecture rule), and by scan (every e2e test checks logs, output,
  and ledger for the fake AISR's canary PHI).

## Not used, on purpose

Firestore or any database (nothing queries the ledger), an orchestrator
(two runs a month), the `eventsourcing` library (three durable facts do
not need it), pandas (small data, supply-chain surface).
