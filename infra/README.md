# Infrastructure

One district = one GCP project = one instance of `modules/district`,
declared by one JSON file in `districts/`. See ARCHITECTURE.md for the
tenancy reasoning. Terraform is validated in CI but applied only by a
human; CI deploys container images, not infrastructure.

## Layout

- `main.tf` - instantiates the district module for every `districts/*.json`
- `modules/district/` - project, bucket, secrets shells, Cloud Run Job,
  schedulers, least-privilege IAM, alerts
- `districts/isd197.json` - the live district (existing project, adopted)
- `districts/sandbox.json.example` - project-factory dress rehearsal in a
  throwaway project; zero contact with production
- `bootstrap/` - one-time Workload Identity Federation setup so GitHub
  Actions can deploy images without any service-account keys

## Cutover runbook (phase 5, not yet executed)

1. Apply `bootstrap/` (creates the WIF pool and deployer SA). Set the two
   outputs as GitHub repository variables `GCP_WIF_PROVIDER` and
   `GCP_DEPLOYER_SA`, plus `GCP_PROJECT` and `GCP_REGION`. The Deploy
   workflow wakes up on the next push to main.
2. In `infra/`: `terraform init`, then adopt the two things worth keeping
   from the existing project (everything else is asserted fresh; the old
   functions, topics, and schedulers are never imported and die in phase 6):

   ```sh
   terraform import 'module.district["isd197"].google_storage_bucket.data' mn-immun-bd9001-immunization-data
   # one import per secret shell (values stay put; they are never in state):
   terraform import 'module.district["isd197"].google_secret_manager_secret.secrets["aisr-username"]' projects/mn-immun-bd9001/secrets/aisr-username
   # ... repeat for aisr-password and the three drive-* secrets
   ```

3. `terraform plan` and read the whole diff. Apply only when the plan
   creates the new job/schedulers/SAs and touches nothing it shouldn't.
4. Regenerate the known-vaccinations master from a fresh full download
   (record-identity caveat in ARCHITECTURE.md), disable the legacy
   schedulers, and let the new schedules take over.
5. After one clean cycle: phase 6 retires the old functions and topics.

## Secrets

Terraform creates empty secret shells only. Values are entered via console
or `gcloud secrets versions add`; they never appear in Terraform state.
`scripts/setup_google_drive_oauth.py` mints the Drive refresh token.
