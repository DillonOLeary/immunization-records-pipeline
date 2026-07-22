# Three schedules, one job, different args. Cadence is configuration:
# moving to weekly or daily is a district JSON change, not a code change.

locals {
  job_run_uri = "https://run.googleapis.com/v2/projects/${local.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.pipeline.name}:run"

  cycles = {
    query    = var.query_schedule
    download = var.download_schedule
    canary   = var.canary_schedule
  }
}

resource "google_cloud_scheduler_job" "cycle" {
  for_each = local.cycles

  project   = local.project_id
  region    = var.region
  name      = "pipeline-${each.key}"
  schedule  = each.value
  time_zone = var.time_zone

  http_target {
    http_method = "POST"
    uri         = local.job_run_uri

    body = base64encode(jsonencode({
      overrides = {
        containerOverrides = [
          { args = [each.key] }
        ]
      }
    }))

    headers = {
      "Content-Type" = "application/json"
    }

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_project_service.apis]
}
