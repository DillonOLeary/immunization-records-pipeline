# At most a few emails, each only when a human must act, each saying what
# happened and what to do. Nothing on success, nothing while a period
# waits, and no "resolved" follow-ups.
#
# - action_needed: a run or canary failed. The job prints one structured
#   line on failure (runtime/advice.py): its headline is the subject, its
#   fix the body.
# - job_crashed: the backstop for failures that can't explain themselves
#   (out of memory, timeout, a broken image). A handled failure closes its
#   period, so it happens once; a crash leaves the period open and repeats
#   every tick, so two in six hours means something is wrong underneath.
# - scheduler_launch_failed: the scheduler couldn't start the job (the
#   2026-07-28 403): no execution, so no other signal exists.
# - job_silent: no execution at all for 12 hours. Ticks run every 3 hours
#   even when idle, so silence means the scheduler stopped.

locals {
  job_filter = "resource.type = \"cloud_run_job\" AND resource.labels.job_name = \"${google_cloud_run_v2_job.pipeline.name}\""
  status_cmd = "uv run mn-immunization status --bucket ${google_storage_bucket.data.name}"
}

resource "google_monitoring_notification_channel" "email" {
  count = var.alert_email != "" ? 1 : 0

  project      = local.project_id
  display_name = "Pipeline alerts"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }
}

resource "google_monitoring_alert_policy" "action_needed" {
  count = var.alert_email != "" ? 1 : 0

  project      = local.project_id
  display_name = "Immunization pipeline: action needed"
  combiner     = "OR"

  conditions {
    display_name = "A run or canary failed"

    condition_matched_log {
      filter = "${local.job_filter} AND jsonPayload.action_needed:*"
      label_extractors = {
        headline   = "EXTRACT(jsonPayload.action_needed)"
        what_to_do = "EXTRACT(jsonPayload.what_to_do)"
      }
    }
  }

  documentation {
    subject   = "Immunization pipeline: $${log.extracted_label.headline}"
    content   = "$${log.extracted_label.what_to_do}"
    mime_type = "text/markdown"
  }

  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close           = "1800s"
    notification_prompts = ["OPENED"]
  }

  notification_channels = [google_monitoring_notification_channel.email[0].name]

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "job_execution_failed" {
  count = var.alert_email != "" ? 1 : 0

  project      = local.project_id
  display_name = "Immunization pipeline: crashing"
  combiner     = "OR"

  conditions {
    display_name = "Two failed executions within six hours"

    condition_threshold {
      filter          = "${local.job_filter} AND metric.type = \"run.googleapis.com/job/completed_execution_count\" AND metric.labels.result = \"failed\""
      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "0s"

      aggregations {
        alignment_period   = "21600s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  documentation {
    subject   = "Immunization pipeline: crashing without saying why"
    content   = "The job failed twice in six hours without its usual explanation (out of memory, a timeout, or a broken deploy). Open the pipeline-job executions in Cloud Run and read the logs of the latest one. Then run `${local.status_cmd}`."
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close           = "86400s"
    notification_prompts = ["OPENED"]
  }

  notification_channels = [google_monitoring_notification_channel.email[0].name]

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "scheduler_launch_failed" {
  count = var.alert_email != "" ? 1 : 0

  project      = local.project_id
  display_name = "Immunization pipeline: couldn't start"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Scheduler attempt failed"

    condition_matched_log {
      filter = "resource.type = \"cloud_scheduler_job\" AND resource.labels.job_id =~ \"^pipeline-\" AND severity >= ERROR"
    }
  }

  documentation {
    subject   = "Immunization pipeline: the scheduler couldn't start the job"
    content   = "Cloud Scheduler tried to start pipeline-job and was refused, so nothing ran. It's usually a permission: compare infra/modules/district/iam.tf with the project and run terraform apply."
    mime_type = "text/markdown"
  }

  alert_strategy {
    notification_rate_limit {
      period = "3600s"
    }
    auto_close           = "86400s"
    notification_prompts = ["OPENED"]
  }

  notification_channels = [google_monitoring_notification_channel.email[0].name]

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "job_silent" {
  count = var.alert_email != "" ? 1 : 0

  project      = local.project_id
  display_name = "Immunization pipeline: stopped running"
  combiner     = "OR"

  conditions {
    display_name = "No completed Cloud Run job executions"

    condition_absent {
      filter   = "${local.job_filter} AND metric.type = \"run.googleapis.com/job/completed_execution_count\""
      duration = "43200s"

      aggregations {
        alignment_period     = "3600s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  documentation {
    subject   = "Immunization pipeline: stopped running"
    content   = "No execution of pipeline-job in 12 hours, though a tick runs every 3. Check the pipeline-* jobs in Cloud Scheduler (paused or deleted?); terraform apply restores them."
    mime_type = "text/markdown"
  }

  alert_strategy {
    notification_prompts = ["OPENED"]
  }

  notification_channels = [google_monitoring_notification_channel.email[0].name]

  depends_on = [google_project_service.apis]
}
