# The one data bucket: config, the ledger, and a cache of PHI (rosters,
# the known set) that can be rebuilt from IC and MIIC. Keep as little PHI
# as possible for as short as possible: versioning gives a week to undo an
# accidental overwrite or delete, then old versions go.

resource "google_storage_bucket" "data" {
  project  = local.project_id
  name     = "${local.project_id}-immunization-data"
  location = "US"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

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

  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 7
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
