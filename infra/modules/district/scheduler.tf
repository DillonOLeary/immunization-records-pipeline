# Three schedules, one job:
# - run opens a period on the district's cadence (its rosters go to MIIC,
#   which emails the nurses) and advances it as far as it can go;
# - tick advances the open period every few hours: it probes staging and,
#   once results are in, diffs, delivers, and commits. Idle ticks write
#   nothing;
# - canary runs the day before a run and every Monday: every login (MIIC,
#   IC) and read-only checks, so an expired password or a broken export
#   surfaces within a week, not on run day. It emails no one.
# All three launch through the same path (scheduler service account, args
# override, runWithOverrides), so the canary and every tick also prove the
# launch itself works: the path that failed silently with a 403 on
# 2026-07-28 and 2026-09-28. Cadence is configuration: a district JSON
# change.

locals {
  cycles = {
    run    = var.schedule
    tick   = var.tick_schedule
    canary = var.canary_schedule
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
    uri         = "https://run.googleapis.com/v2/projects/${local.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.pipeline.name}:run"

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

moved {
  from = google_cloud_scheduler_job.run
  to   = google_cloud_scheduler_job.cycle["run"]
}

moved {
  from = google_cloud_scheduler_job.canary
  to   = google_cloud_scheduler_job.cycle["canary"]
}
