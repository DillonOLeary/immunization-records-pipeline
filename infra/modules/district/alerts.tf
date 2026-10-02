# Never fail invisibly: any failed job execution alerts immediately, and
# any failed *launch* (scheduler couldn't start the job at all) alerts too.
# The second alert exists because of the 2026-07-28 incident: the scheduler
# got a 403 launching the job, the job never started, so no RunFailed event
# and no execution metric existed — the failure was invisible to the first
# alert by construction.
#
# And because ticks launch every few hours, silence is a signal too: a
# third alert fires when the job has not completed any execution for
# twelve hours (a deleted or paused scheduler, a broken launch path).

resource "google_monitoring_notification_channel" "email" {
  count = var.alert_email != "" ? 1 : 0

  project      = local.project_id
  display_name = "Pipeline alerts"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }
}

resource "google_monitoring_alert_policy" "job_execution_failed" {
  count = var.alert_email != "" ? 1 : 0

  project      = local.project_id
  display_name = "Pipeline job execution failed"
  combiner     = "OR"

  conditions {
    display_name = "Failed Cloud Run job execution"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_job\" AND resource.labels.job_name = \"${google_cloud_run_v2_job.pipeline.name}\" AND metric.type = \"run.googleapis.com/job/completed_execution_count\" AND metric.labels.result = \"failed\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email[0].name]

  depends_on = [google_project_service.apis]
}

# Log-match alert: Cloud Scheduler writes AttemptFinished at severity ERROR
# when the launch call fails (e.g. the 2026-07-28 403). This is the only
# signal that exists when the job never starts.
resource "google_monitoring_alert_policy" "scheduler_launch_failed" {
  count = var.alert_email != "" ? 1 : 0

  project      = local.project_id
  display_name = "Pipeline scheduler failed to launch the job"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Scheduler attempt failed"

    condition_matched_log {
      filter = "resource.type = \"cloud_scheduler_job\" AND resource.labels.job_id =~ \"^pipeline-\" AND severity >= ERROR"
    }
  }

  alert_strategy {
    notification_rate_limit {
      period = "3600s"
    }
    auto_close = "86400s"
  }

  notification_channels = [google_monitoring_notification_channel.email[0].name]

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "job_silent" {
  count = var.alert_email != "" ? 1 : 0

  project      = local.project_id
  display_name = "Pipeline job has not run for 12 hours"
  combiner     = "OR"

  conditions {
    display_name = "No completed Cloud Run job executions"

    condition_absent {
      filter   = "resource.type = \"cloud_run_job\" AND resource.labels.job_name = \"${google_cloud_run_v2_job.pipeline.name}\" AND metric.type = \"run.googleapis.com/job/completed_execution_count\""
      duration = "43200s"

      aggregations {
        alignment_period     = "3600s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email[0].name]

  depends_on = [google_project_service.apis]
}
