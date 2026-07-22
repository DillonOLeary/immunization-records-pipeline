output "project_id" {
  value = local.project_id
}

output "data_bucket" {
  value = google_storage_bucket.data.name
}

output "job_name" {
  value = google_cloud_run_v2_job.pipeline.name
}

output "job_service_account" {
  value = google_service_account.job.email
}
