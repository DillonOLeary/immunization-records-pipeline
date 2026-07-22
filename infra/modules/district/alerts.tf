# Never fail invisibly: any failed job execution alerts immediately.
#
# Known limitation, on purpose: a metric-absence dead-man's switch cannot
# span a monthly cadence (absence windows max out around a day). The canary
# on the 27th covers the AISR-breakage case with a day of slack; a true
# absence alert becomes practical if cadence moves to weekly or daily.

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
