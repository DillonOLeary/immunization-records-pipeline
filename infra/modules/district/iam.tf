# Least privilege, stated precisely:
# - the job's service account can touch objects in the ONE data bucket and
#   read its own secrets; nothing project-wide
# - the scheduler's service account can invoke the ONE job and nothing else
# - Google's default compute and App Engine service accounts hold nothing:
#   Google grants each roles/editor on the whole project, and nothing in
#   this pipeline runs as either

resource "google_service_account" "job" {
  project      = local.project_id
  account_id   = "pipeline-job"
  display_name = "Immunization pipeline job"
}

resource "google_storage_bucket_iam_member" "job_bucket_access" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.job.email}"
}

resource "google_secret_manager_secret_iam_member" "job_secret_access" {
  for_each = google_secret_manager_secret.secrets

  project   = local.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.job.email}"
}

resource "google_service_account" "scheduler" {
  project      = local.project_id
  account_id   = "pipeline-scheduler"
  display_name = "Immunization pipeline scheduler"
}

# The scheduler passes the cycle ("run") as a container args override, and
# any jobs:run request carrying overrides needs run.jobs.runWithOverrides,
# which roles/run.invoker lacks. Incident 2026-07-28 (and again 2026-09-28):
# launches got 403 under run.invoker at both job and project level.
resource "google_cloud_run_v2_job_iam_member" "scheduler_invokes_job" {
  project  = local.project_id
  location = var.region
  name     = google_cloud_run_v2_job.pipeline.name
  role     = "roles/run.jobsExecutorWithOverrides"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

# CI deploys new images to the job, which requires acting as the job's
# runtime service account — granted on this one SA, never project-wide.
resource "google_service_account_iam_member" "deployer_acts_as_job" {
  count = var.deployer_service_account != "" ? 1 : 0

  service_account_id = google_service_account.job.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.deployer_service_account}"
}

# Google grants roles/editor on the project to its default compute and App
# Engine service accounts. Nothing here runs as either (the job and the
# scheduler have their own accounts above), so the grants are only attack
# surface: any workload that ever runs as a default account would get
# editor on the project that holds the data bucket and the secrets.
# Removing them declaratively strips them in every district, including
# ones created later. A no-op where the grant (or the account) is absent.
resource "google_project_iam_member_remove" "default_compute_not_editor" {
  project = local.project_id
  role    = "roles/editor"
  member  = "serviceAccount:${local.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_project_iam_member_remove" "default_appengine_not_editor" {
  project = local.project_id
  role    = "roles/editor"
  member  = "serviceAccount:${local.project_id}@appspot.gserviceaccount.com"
}

# Who read or wrote PHI, and when: Data Access audit logs for Cloud
# Storage (off by default). Pipeline reads and writes land here too; the
# volume is a few hundred entries a day.
resource "google_project_iam_audit_config" "storage_data_access" {
  project = local.project_id
  service = "storage.googleapis.com"

  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }
}
