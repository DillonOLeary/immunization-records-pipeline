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

# The canary runs the day before the run cycle: login plus a read-only
# listing, so MIIC breakage surfaces a day early instead of on run day.
# It launches through exactly the same path as the run cycle (same
# scheduler service account, same args override, same runWithOverrides
# permission), so it also proves the launch itself works — the path that
# failed silently with a 403 on 2026-07-28 and 2026-09-28. It emails no
# one: a canary submits nothing to MIIC.

resource "google_cloud_scheduler_job" "canary" {
  project   = local.project_id
  region    = var.region
  name      = "pipeline-canary"
  schedule  = var.canary_schedule
  time_zone = var.time_zone

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${local.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.pipeline.name}:run"

    body = base64encode(jsonencode({
      overrides = {
        containerOverrides = [
          { args = ["canary"] }
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
