# Architecture

The pipeline relays immunization records between two systems it does not
own. MIIC (Minnesota's registry, via the AISR bulk interface) owns
immunization truth; Infinite Campus owns student truth. Each period
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
- One maintainer, small data (a period a month or more, ~8 schools, ~180k
  known records).
- One GCP project per district: its IAM boundary, data, and blast radius.

## Layout

```
src/mn_immunization/
  records/               pure: what a record is, IC's CSV format, hashing
  workflow/              the process: periods, decisions, steps
    ports.py             what it needs from outside: Registry, Delivery, ObjectStore, RunLedger
    events.py            the ledger's event types
    policy.py            the decider: CycleState -> next Step (pure)
    history.py           the ledger folded: open periods, submissions, deliveries (pure)
    periods.py           the period key
    runner.py            the loop: decide, execute, terminal event
    steps/               one executor per step: submit, staging, diff, delivery
    known.py             the known set (fail-closed), diff, master commit
    cycles.py            run, tick, canary, rebaseline
    settings.py          every environment variable, parsed once
    services.py          what a cycle is given: ports, settings, clock
    context.py           one execution's view: RunContext
  adapters/              one folder per external system
    miic/                AISR: login, actions, parsing, the Registry
    drive/               the Drive folder: the Delivery
    gcs/                 object store, ledger and snapshots, secrets
  runtime/
    config.py            config.json, bound to its adapters
    composition.py       the only place adapters are built
    job.py               Cloud Run Job entrypoint
    cli.py               mn-immunization status (read-only)
mock/                    the fake AISR (tests and `uv run mock-server`)
tests/                   mirrors src/; e2e/ runs the job end to end
infra/                   Terraform: one district module per districts/*.json
```

Dependencies point inward: records <- workflow <- adapters <- runtime.
`records/` is facts about the data and knows no process. `workflow/` is
the process, and declares what it needs from outside in
`workflow/ports.py`, in its own words. Each adapter implements those ports
for one system and imports nothing of the workflow but them. The
workflow imports no adapter and no third-party package, and only
`runtime/` builds adapters, reads the environment or config, or reads the
clock. `tests/test_architecture.py` enforces this, along with the rule
that no exception value ever reaches a log line.

## Periods, runs, and ticks

A period is the unit of work: each school's roster submitted once, then
results, a diff, a delivery, a master commit. `run` (on the district's
cadence) opens a period and advances it; `tick` (every few hours)
advances whichever period is open. Nothing sleeps: waiting for MDH ends
the execution as RunWaiting and the next tick looks again, so a period
spans as many executions as staging takes (each well under the job's
one-hour timeout). Whether a period is open is a fold over PeriodOpened
and PeriodClosed events (`history.py`, where every read of the past
lives); an idle tick writes nothing.

Every outcome but waiting closes the period, failures included, so a
failure alerts once rather than every tick. `run` reopens a closed
period: rosters already submitted stay submitted, and the staging
deadline starts over. Opening a period closes any other still open as
superseded (AISR lists only the newest results, which carry each
student's full history).

`policy.decide` is the pipeline on one screen: pure, no I/O, no clock.
The runner (`runner.run_to_completion`) asks it for the next step,
executes it, folds the result into the state, and repeats until `Finish`,
the only step that writes a terminal event.

```
SubmitQueries -> AwaitStaging -> ComputeDiff -> [brake] -> DeliverDiff -> CommitMaster -> Finish
```

- The sanity brake (a diff over max(50, 20% of known)) fires before
  anything is delivered or committed.
- Delivery precedes the master commit, so a failed upload leaves the
  master untouched and the records in the next diff.
- Only schools submitted this period are waited for, and only results
  uploaded since a school's submission count as staged: AISR keeps the
  previous results listed for days. Each execution probes once; a failed
  probe waits for the next tick. At the deadline (`POLL_DEADLINE_SECONDS`
  after the period opened, 20h by default) the period goes ahead with
  what is staged, or fails if nothing is.
- A school that is stuck or failed to submit lets the others deliver, then
  turns the run's success into RunFailed naming it.

## The ledger

Append-only JSON objects in the district's bucket; no database.

```
ledger/<YYYY>/<MM>/<run_id>/<seq>_<event>.json   one object per event (UTC)
ledger/claims/<period>_query_<school_id>          one roster per school per period
ledger/claims/<YYYY-MM-DD>_diff_<hash>            one delivery per diff content
snapshots/<sha256>.csv                            every committed master
output/all_known_vaccinations.csv                 the master (union of all records)
```

- Claims are create-if-absent objects: exactly one run wins.
- Query claims fail closed. A claim with no QuerySubmitted event is
  *stuck* and never resubmitted; a human checks with MIIC and releases it
  (ONBOARDING). A submission that failed before its upload began releases
  its own claim.
- The diff claim is keyed by content and fails open: a rerun with the
  same diff skips the upload; a new diff the same day gets its own file
  (`_2.csv`); a crashed claimant cannot suppress a delivery.
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
- AISR lists one results entry per school and keeps the previous one for
  days after a run (seen 2026-10-01), so freshness is judged by upload
  time against the school's submission.

## Operations and security

- Cloud Run Job `pipeline-job`, launched by Cloud Scheduler: `run` on the
  district's cadence, `tick` every 3 hours, `canary` the day before a
  run. Manual runs: `gcloud run jobs execute`. The CLI only reads the
  ledger.
- Alerts email on a failed job execution, on a failed scheduler launch,
  and when the job has not run for 12 hours.
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
