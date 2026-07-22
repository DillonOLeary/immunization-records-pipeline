# The one data bucket: config, query files, output, ledger, snapshots.

resource "google_storage_bucket" "data" {
  project  = local.project_id
  name     = "${local.project_id}-immunization-data"
  location = "US"

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 1095 # 3 years
    }
    action {
      type = "Delete"
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.apis]
}

resource "google_artifact_registry_repository" "pipeline" {
  project       = local.project_id
  location      = var.region
  repository_id = "pipeline"
  format        = "DOCKER"

  depends_on = [google_project_service.apis]
}
