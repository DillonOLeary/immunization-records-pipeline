# Onboarding a district

One district = one GCP project = one `infra/districts/<name>.json` = one
instance of the district Terraform module.

**PHI rule:** real rosters, config, and records never enter this repo (not
commits, issues, or logs). They live only in the district's bucket and
Drive folder.

## 1. AISR access [external]

The district enrolls with MDH for AISR bulk-query access (its MIIC contact
usually starts this; allow days to weeks). You get an AISR username and
password, and the district's MDE number (`iddis`, e.g. `0197`).

## 2. Platform bootstrap [terminal, once ever]

Already done if any district is live.

1. Apply `infra/bootstrap/` (Workload Identity pool and deployer service
   account; no keys exist anywhere). A fork must set `github_repo` first.
2. Set GitHub repository **Variables**: `GCP_WIF_PROVIDER` and
   `GCP_DEPLOYER_SA` (bootstrap outputs), `GCP_PROJECT`, `GCP_REGION`.

## 3. Declare the district [terminal]

1. Copy `infra/districts/sandbox.json.example` to
   `infra/districts/<name>.json`; new districts set `create_project: true`
   and a billing account.
2. `terraform plan` in `infra/`, read the whole diff, apply. Humans apply
   Terraform; CI only validates.

`schedule` is the run cadence (cron, in `time_zone`); `canary_schedule`
defaults to the day before, `tick_schedule` to every 3 hours. Choose the cadence with the district: every
run emails its nurses.

## 4. Secrets [terminal]

Terraform creates empty shells. Fill the AISR ones (values never touch
Terraform state):

```sh
printf '%s' '<value>' | gcloud secrets versions add aisr-username --project <project> --data-file=-
printf '%s' '<value>' | gcloud secrets versions add aisr-password --project <project> --data-file=-
```

## 5. Drive folder [console]

1. Create an OAuth 2.0 Client ID (Desktop app) in the GCP console and
   download its JSON.
2. Run `infra/scripts/setup_google_drive_oauth.py credentials.json`; it
   stores the three `drive-*` secrets.
3. Create the folder in that account's Drive, share it with the district's
   health staff, set `google_drive_folder_id` in the district JSON, and
   re-apply.

## 6. Config and rosters [terminal]

1. Write `config.json` from
   [config/config.json.example](config/config.json.example) (its
   `_instructions` explain how to read school values from AISR) and upload
   it to `gs://<data-bucket>/config/config.json`.
2. Upload each school's roster CSV (exported from Infinite Campus) to the
   path in its `bulk_query_file`.

## 7. Verify [terminal]

```sh
gcloud run jobs execute pipeline-job --args=canary,--trigger,manual \
  --region <region> --project <project>
uv run mn-immunization status --bucket <data-bucket>   # canary -> RunCompleted
```

**Never run `run` as a rehearsal**: it emails every nurse. The first real
run should be the scheduled one, with the district told to expect it.

## Operations

| Task | When | How |
|---|---|---|
| Canary, run, ticks | per schedule | automatic; failures email |
| Import a delivered diff, then delete it from Drive | per delivery | school health staff (the deletion is the acknowledgment) |
| Refresh rosters | before each run | export from IC, upload |
| Respond to an alert | on email | `uv run mn-immunization status --bucket <data-bucket>`; a failed period stays closed until `--args=run,--trigger,manual` reopens it |
| Merge Dependabot PRs | weekly-ish | by hand: merging to `main` deploys |
| Rotate a credential | as needed | add a secret version (steps 4, 5) |
| Drive out of sync | as needed | `gcloud run jobs execute pipeline-job --args=rebaseline,--trigger,manual` |

## Stuck roster claims

A run claims `ledger/claims/<period>_query_<school_id>` just before each
upload and records QuerySubmitted after it. A claim with no record means
the upload may or may not have happened, so runs skip that school rather
than risk emailing every nurse twice, and end failed naming it in
`stuck_schools`. (A failure before the upload began releases the claim
by itself; the next run submits that school.)

`status` lists stuck claims with the exact release command. For each:

1. Ask whether MIIC got that school's roster this period (the nurse got
   the MIIC email; AISR's web app lists the upload).
2. **No:** release the claim with the printed `gcloud storage rm`, then
   `gcloud run jobs execute pipeline-job --args=run,--trigger,manual`.
   Only that school is submitted.
3. **Yes:** leave it. Its results still flow; runs that period keep
   flagging it, which is harmless.

Never release a claim without step 1: releasing one whose roster went out
emails every nurse again.

## Known limits

- Deploys update one district (`GCP_PROJECT`); a second needs the deploy
  to loop over `infra/districts/*.json`.
- All districts' Terraform state lives in the first district's project.
