# Infrastructure

One district = one GCP project = one instance of `modules/district`,
declared by one JSON file in `districts/`. CI validates; a human runs
`terraform plan`, reads it, and applies.

- `main.tf`: one district module per `districts/*.json`
- `modules/district/`: project, bucket, secret shells, the job, the run
  and canary schedulers, least-privilege IAM, alerts
- `districts/isd197.json`: the live district
- `districts/sandbox.json.example`: a throwaway project to rehearse in
- `bootstrap/`: one-time Workload Identity setup for keyless CI deploys
- `scripts/setup_google_drive_oauth.py`: mints the Drive secrets

Secret values never enter Terraform state; Terraform creates empty shells.
