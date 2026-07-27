# Onboarding a new district

The runbook for standing up the pipeline for a school district, start to
finish. Each step is tagged with where it happens: **[external]** (outside
any system you control), **[console]** (GCP or Google web UI), or
**[terminal]** (this repo).

One district = one GCP project = one JSON file in `infra/districts/` = one
instance of the district Terraform module. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the tenancy reasoning and
[infra/README.md](infra/README.md) for the Terraform layout.

**PHI rule, before anything else:** real rosters, config, and downloaded
records never enter this repo — not in commits, branches, issues, or logs.
They live only in the district's GCS bucket and Drive folder.

## 1. AISR / MIIC access — [external]

The district enrolls with the Minnesota Department of Health for AISR
bulk-query access (the district's MIIC contact usually initiates this).
You come away with:

- an AISR username and password for the pipeline to use
- the district's MDE number (`iddis` in config, e.g. `0197`)

Lead time on MDH is days-to-weeks; start here.

## 2. Platform bootstrap — [terminal, once ever]

Already done if any district is live. A fork must override `github_repo`
in `infra/bootstrap/variables.tf` (only that repo's `main` branch may
deploy).

1. Apply `infra/bootstrap/` (creates the Workload Identity pool and the
   deployer service account — keyless; no SA keys exist anywhere).
2. Set the four GitHub repository **Variables** (not Secrets — none of
   these are credentials): `GCP_WIF_PROVIDER` and `GCP_DEPLOYER_SA` from
   the bootstrap outputs, plus `GCP_PROJECT` and `GCP_REGION`. The Deploy
   workflow wakes up on the next push to `main`.

## 3. Declare the district — [terminal]

1. Copy `infra/districts/sandbox.json.example` to
   `infra/districts/<name>.json`. New districts set
   `create_project: true` with a billing account; the module creates the
   project, bucket, secret shells, Cloud Run Job, scheduler, IAM, and
   alerts.
2. `terraform plan` in `infra/`, read the whole diff, then apply.
   Terraform is applied by a human, never CI — CI only validates offline
   and deploys container images.

The `schedule` field is the district's run cadence (cron, district-local
`time_zone`). Pick it with the district: MIIC emails the school nurses on
every roster submission, so the cadence is a people decision, not just a
technical one.

## 4. Secret values — [terminal]

Terraform created empty shells; fill them (values never touch Terraform
state):

```sh
printf '%s' '<value>' | gcloud secrets versions add aisr-username --project <project> --data-file=-
printf '%s' '<value>' | gcloud secrets versions add aisr-password --project <project> --data-file=-
```

The three `drive-*` secrets come from step 5.

## 5. Google Drive delivery folder — [console]

Where nurses pick up their files; Drive is the UI on purpose.

**Preferred (when a district Workspace admin is available):** a Shared
Drive in the district's own Google Workspace, with the pipeline's job
service account added as a member. Keyless, no OAuth tokens, and the PHI
lives under the district's governance. (Migration planned; the OAuth path
below is what runs today.)

**Current path (OAuth):**

1. In the GCP console, create an OAuth 2.0 Client ID (Desktop app) and
   download its JSON.
2. Run `infra/scripts/setup_google_drive_oauth.py credentials.json` and
   complete the browser flow; it stores `drive-refresh-token`,
   `drive-client-id`, and `drive-client-secret` in Secret Manager.
3. Create the delivery folder in that Google account's Drive, share it
   with the district's health staff, and put its folder id in the
   district JSON (`google_drive_folder_id`), then re-apply Terraform.

## 6. Runtime config and rosters — [terminal]

Both live in the district's data bucket, never in the repo.

1. Author `config.json` from
   [config/config.json.example](config/config.json.example). The school
   `id`/`classification`/`email` values must match AISR exactly; the
   example's `_instructions` document how to read them out of the AISR
   web app (a `discover-schools` helper is planned). `district.iddis` is
   the MDE number from step 1.
2. Upload it: `gsutil cp config.json gs://<data-bucket>/config/config.json`
3. Export each school's roster from Infinite Campus as CSV and upload to
   the blob path named in that school's `bulk_query_file` (e.g.
   `data/queries/<school>.csv`).

## 7. First-run verification — [terminal]

```sh
# read-only probe: logs into AISR and lists records per school, no PHI moved
gcloud run jobs execute pipeline-job --args=canary,--trigger,manual \
  --region <region> --project <project>

# then read the ledger
uv run mn-immunization status --bucket <data-bucket>
```

`status` should show the canary with a terminal RunCompleted event.

**Never run the `run` cycle as a rehearsal**: every roster submission
triggers MIIC emails to all of the district's school nurses. Rehearsals
are `canary` only; the first real `run` should be the scheduled one, with
the district warned to expect the MIIC email.

## Recurring operations

| Task | Cadence | Who / how |
|---|---|---|
| Run cycle (query → poll → deliver) | per district `schedule` | automatic (Cloud Scheduler) |
| Import the delivered diff into Infinite Campus, then delete the file from Drive | per delivery | school health staff — the deletion is the acknowledgment (`ImportConfirmed`); files lingering past 7 days are flagged |
| Refresh roster CSVs as enrollment changes | before each run cycle | manual export + upload today; automation planned for fall 2026 |
| Review and merge Dependabot PRs | weekly-ish | human — deliberately manual, because merging to `main` auto-deploys |
| Check on runs / respond to alerts | on alert email | `uv run mn-immunization status --bucket <data-bucket>` |
| Rotate AISR password / Drive token when needed | on demand | new secret version (step 4 / step 5) |
| Infra changes | on demand | human `terraform apply`; a `rebaseline` run recovers Drive sync trouble |

## Configuration reference

| Layer | Lives in | Set by |
|---|---|---|
| District provisioning (project, image, folder id, schedule, alerts) | `infra/districts/<name>.json` | human + `terraform apply` |
| GitHub↔GCP deploy trust | `infra/bootstrap/` + 4 GitHub repo Variables | human, once |
| Runtime config (schools, `iddis`, API hosts) | `config/config.json` in the data bucket | human authors, uploads |
| Rosters | `data/queries/*.csv` in the data bucket | exported from Infinite Campus |
| Credentials (2 AISR + 3 Drive) | Secret Manager | human adds versions; shells from Terraform |
| Job wiring (bucket, project, folder id env vars) | `infra/modules/district/job.tf` | Terraform |

## Known limits (single-district today)

- The Deploy workflow builds and updates **one** district (the one in the
  GitHub `GCP_PROJECT` variable). A second district gets infrastructure
  but not image updates until deploys become a loop over
  `infra/districts/*.json` with a shared Artifact Registry.
- Terraform state for all districts lives in the first district's
  project (`infra/main.tf` backend). A dedicated admin project is the
  eventual home.
