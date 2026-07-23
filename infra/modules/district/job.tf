resource "google_cloud_run_v2_job" "pipeline" {
  project  = local.project_id
  location = var.region
  name     = "pipeline-job"

  template {
    template {
      service_account = google_service_account.job.email
      timeout         = "79200s" # covers the results-polling window
      max_retries     = 0        # reruns are a human decision; the ledger records them

      containers {
        image = var.image

        env {
          name  = "DATA_BUCKET"
          value = google_storage_bucket.data.name
        }
        env {
          name  = "GOOGLE_DRIVE_FOLDER_ID"
          value = var.google_drive_folder_id
        }

        resources {
          limits = {
            memory = "512Mi"
            cpu    = "1"
          }
        }
      }
    }
  }

  lifecycle {
    # CI updates the image tag on deploy; Terraform must not fight it.
    ignore_changes = [template[0].template[0].containers[0].image]
  }

  depends_on = [google_project_service.apis]
}
