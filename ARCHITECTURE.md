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
  records/               pure: what a record is, the roster layout, IC's CSV format
  workflow/              the process: periods, decisions, steps
    ports.py             what it needs from outside: Registry, Delivery, ObjectStore, RunLedger
    events.py            the ledger's event types
    policy.py            the decider: CycleState -> next Step (pure)
    history.py           the ledger folded: open periods, submissions, deliveries (pure)
    periods.py           the period key
    runner.py            the loop: decide, execute, terminal event
    steps/               one executor per step: submit, staging, diff, delivery
    known.py             the known set (fail-closed), diff, commit
    layout.py            where things live in the bucket
    cycles.py            run, tick, canary, refresh
    settings.py          every environment variable, parsed once
    services.py          what a cycle is given: ports, settings, clock
    context.py           one execution's view: RunContext
  adapters/              one folder per external system
    miic/                AISR: login, actions, parsing, the Registry
    infinite_campus/     IC: login and the roster export, the RosterSource
    drive/               the Drive folder: the Delivery
    gcs/                 object store, ledger, secrets
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
results, a diff, a delivery, a known-set commit. `run` (on the district's
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
- Delivery precedes the commit, so a failed upload leaves the known set
  untouched and the records in the next diff.
- With Infinite Campus configured, each school's roster is exported fresh
  just before its submission and checked (MIIC's layout, not under half
  the students on file). A failed or unfit export sends the roster on
  file and ends the period failed after delivery (RosterRefreshFailed).
  IC logins continue past its device confirmation without trusting the
  device, so each one emails the account owner.
- Only schools submitted this period are waited for, and only results
  uploaded since a school's submission count as staged: AISR keeps the
  previous results listed for days. Each execution probes once; a failed
  probe waits for the next tick. At the deadline (`POLL_DEADLINE_SECONDS`
  after the period opened, 20h by default) the period goes ahead with
  what is staged, or fails if nothing is.
- A school that is stuck or failed to submit lets the others deliver, then
  turns the run's success into RunFailed naming it.

## The ledger

Append-only JSON objects in the district's bucket; no database. The rest
of the bucket is a cache: its PHI can be rebuilt from IC and MIIC.

```
ledger/<YYYY>/<MM>/<run_id>/<seq>_<event>.json   one object per event (UTC)
ledger/claims/<period>_query_<school_id>          one roster per school per period
ledger/claims/<YYYY-MM-DD>_diff_<hash>            one delivery per content
rosters/<school_id>.csv                           each school's latest roster
known/records.csv                                 every record delivered: the only other PHI
known/committed.json                              marker: a count and a hash, no PHI
config/config.json                                schools and AISR settings
```

- Claims are create-if-absent objects: exactly one run wins.
- Query claims fail closed. A claim with no QuerySubmitted event is
  *stuck* and never resubmitted; a human checks with MIIC and releases it
  (ONBOARDING). A submission that failed before its upload began releases
  its own claim.
- The delivery claim is keyed by content and fails open: a rerun with the
  same content skips the upload; a crashed claimant cannot suppress a
  delivery. Every file is recorded as part NN of MM, so a delivery cut
  short is finished by the rerun under the same names.
- The known set only grows between refreshes (absence is never deletion)
  and loads fail-closed: only a set never committed is empty; missing
  with its marker present, unreadable, or malformed fails the run.
- Versioning keeps overwritten or deleted objects for 7 days, then they
  go; Data Access audit logs record every read and write of the bucket.
- Periods and file dates use `DISTRICT_TIME_ZONE`; ledger stamps are UTC.

## Drive is the UI

Deliveries land in one flat folder as files of at most 25,000 rows
(`DELIVERY_FILE_ROWS`), schools mixed, named
`YYYY-MM-DD_HHMM_<new|refresh>_NN-of-MM.csv` in district time. A file
there needs importing into Infinite Campus; staff delete it once done. A
delivered file that disappears is recorded as ImportConfirmed; one
lingering past 7 days is a logged warning. The `drive.file` scope sees
only the pipeline's own files. `refresh` fetches every school's latest
results (no roster goes out), delivers all of them, and rebuilds the known
set; safe any time because IC imports are idempotent.

## AISR

- Login scrapes the Keycloak form action and posts back to it, so flow
  parameters can change without breaking it.
- Every call has a timeout. Retries key off HTTP status (502/503/504) and
  only for side-effect-free calls; the roster upload is never retried.
- Errors carry a status, never a response body.
- A refused login (wrong or expired credentials) fails a period at once;
  only transient errors (timeouts, 5xx) are waited out. The canary (every
  Monday and the day before each run) runs every check, MIIC, the known
  set, and IC, and names each one that fails.
- AISR lists one results entry per school and keeps the previous one for
  days after a run (seen 2026-10-01), so freshness is judged by upload
  time against the school's submission.

## Operations and security

- Cloud Run Job `pipeline-job`, launched by Cloud Scheduler: `run` on the
  district's cadence, `tick` every 3 hours, `canary` every Monday and
  the day before a run. Manual runs: `gcloud run jobs execute`. The CLI only reads the
  ledger.
- Alerts email only when a human must act, and say what happened and
  what to do: a failed run or canary (the job prints a headline and a
  fix, `runtime/advice.py`, which become the email's subject and body),
  a crash that repeats, a failed launch, or 12 hours without any
  execution. Nothing on success or while waiting; no "resolved" emails.
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
