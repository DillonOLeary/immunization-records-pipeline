# Least privilege, stated precisely:
# - the job's service account can touch objects in the ONE data bucket and
#   read its own secrets; nothing project-wide
# - the scheduler's service account can invoke the ONE job and nothing else

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

resource "google_cloud_run_v2_job_iam_member" "scheduler_invokes_job" {
  project  = local.project_id
  location = var.region
  name     = google_cloud_run_v2_job.pipeline.name
  role     = "roles/run.invoker"
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
