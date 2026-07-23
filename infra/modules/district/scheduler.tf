# One schedule, one job, the whole pipeline: the run cycle submits roster
# queries, polls until MDH stages results, then downloads and delivers.
# Cadence is configuration: weekly or daily is a district JSON change.

resource "google_cloud_scheduler_job" "run" {
  project   = local.project_id
  region    = var.region
  name      = "pipeline-run"
  schedule  = var.schedule
  time_zone = var.time_zone

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${local.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.pipeline.name}:run"

    body = base64encode(jsonencode({
      overrides = {
        containerOverrides = [
          { args = ["run"] }
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
