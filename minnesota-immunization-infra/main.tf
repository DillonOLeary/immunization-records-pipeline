terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 4.34.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.0.0"
    }
  }

  # Remote state storage
  backend "gcs" {
    bucket = "mn-immun-bd9001-terraform-state"
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable required APIs
resource "google_project_service" "required_apis" {
  for_each = toset([
    "cloudfunctions.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "storage.googleapis.com",
    "pubsub.googleapis.com",
    "secretmanager.googleapis.com",
    "eventarc.googleapis.com",
    "drive.googleapis.com"
  ])

  project = var.project_id
  service = each.key
  disable_on_destroy = false
}

# Storage bucket for data (HIPAA compliant with Google-managed encryption)
resource "google_storage_bucket" "data" {
  name     = "${var.project_id}-immunization-data"
  location = "US"

  # HIPAA: Uniform bucket-level access
  uniform_bucket_level_access = true

  # HIPAA: Enable versioning for data integrity
  versioning {
    enabled = true
  }

  # Data lifecycle - keep files for 3 years (HIPAA requirement)
  lifecycle_rule {
    condition {
      age = 1095  # 3 years
    }
    action {
      type = "Delete"
    }
  }
}

# Storage bucket for Cloud Function source code
resource "google_storage_bucket" "function_source" {
  name     = "${var.project_id}-function-source"
  location = "US"
}

# Service account for Cloud Functions
resource "google_service_account" "function_sa" {
  account_id   = "immunization-function"
  display_name = "Immunization Pipeline Functions"
}

# COMMENTED OUT - Service account for Google Drive access (not needed for OAuth approach)
# resource "google_service_account" "drive_sa" {
#   account_id   = "immunization-drive"
#   display_name = "Immunization Pipeline Google Drive Access"
# }

# COMMENTED OUT - Create and store service account key for Google Drive (not needed for OAuth approach)
# resource "google_service_account_key" "drive_key" {
#   service_account_id = google_service_account.drive_sa.name
#   public_key_type    = "TYPE_X509_PEM_FILE"
# }

# COMMENTED OUT - Store the service account key in Secret Manager (not needed for OAuth approach)
# resource "google_secret_manager_secret_version" "drive_key_version" {
#   secret      = google_secret_manager_secret.all_secrets["drive-service-account-key"].id
#   secret_data = base64decode(google_service_account_key.drive_key.private_key)
# }

# Grant storage access to service account
resource "google_storage_bucket_iam_member" "function_storage_access" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.admin"
  member = "serviceAccount:${google_service_account.function_sa.email}"
}

# Grant secret access to service account (for AISR credentials and Google Drive OAuth)
resource "google_secret_manager_secret_iam_member" "function_secret_access" {
  for_each = toset(["aisr-username", "aisr-password", "drive-refresh-token", "drive-client-id", "drive-client-secret"])

  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.function_sa.email}"

  depends_on = [google_secret_manager_secret.all_secrets]
}

# Secrets for AISR credentials and Google Drive OAuth (create empty - user fills in via console)
resource "google_secret_manager_secret" "all_secrets" {
  for_each = toset(["aisr-username", "aisr-password", "drive-refresh-token", "drive-client-id", "drive-client-secret"])

  secret_id = each.value

  replication {
    auto {}
  }
}

# Pub/Sub topics for triggering functions
resource "google_pubsub_topic" "upload_trigger" {
  name = "immunization-upload-trigger"
}

resource "google_pubsub_topic" "download_trigger" {
  name = "immunization-download-trigger"
}

# Package function source code
data "archive_file" "function_source" {
  type        = "zip"
  output_path = "function-source.zip"
  source_dir  = var.function_source_dir
}

# Upload function source to bucket
resource "google_storage_bucket_object" "function_code" {
  name   = "function-source-${data.archive_file.function_source.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.function_source.output_path
}

# Cloud Function for upload (triggered every Monday)
resource "google_cloudfunctions2_function" "upload_function" {
  name        = "immunization-upload"
  location    = var.region
  description = "Upload immunization data to AISR"

  build_config {
    runtime     = "python311"
    entry_point = "upload_handler"
    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.function_code.name
      }
    }
  }

  service_config {
    available_memory      = "256M"
    timeout_seconds       = 300
    service_account_email = google_service_account.function_sa.email

    environment_variables = {
      DATA_BUCKET            = google_storage_bucket.data.name
      GOOGLE_DRIVE_FOLDER_ID = var.google_drive_folder_id
    }

    # No secret environment variables needed - Python code uses get_secret() with hardcoded names
  }

  event_trigger {
    trigger_region = var.region
    event_type     = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic   = google_pubsub_topic.upload_trigger.id
  }

  depends_on = [google_project_service.required_apis]
}

# Cloud Function for download (triggered 2 days after upload)
resource "google_cloudfunctions2_function" "download_function" {
  name        = "immunization-download"
  location    = var.region
  description = "Download and transform immunization results"

  build_config {
    runtime     = "python311"
    entry_point = "download_handler"
    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.function_code.name
      }
    }
  }

  service_config {
    available_memory      = "512M"
    timeout_seconds       = 540
    service_account_email = google_service_account.function_sa.email

    environment_variables = {
      DATA_BUCKET            = google_storage_bucket.data.name
      GOOGLE_DRIVE_FOLDER_ID = var.google_drive_folder_id
    }

    # No secret environment variables needed - Python code uses get_secret() with hardcoded names
  }

  event_trigger {
    trigger_region = var.region
    event_type     = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic   = google_pubsub_topic.download_trigger.id
  }

  depends_on = [google_project_service.required_apis]
}

# Cloud Scheduler job - Upload trigger (every Monday at 9am)
# COMMENTED OUT - Disable automatic triggering until ready for production
# resource "google_cloud_scheduler_job" "upload_schedule" {
#   name      = "immunization-upload-schedule"
#   schedule  = "0 9 * * 1"
#   time_zone = "America/Chicago"
#
#   pubsub_target {
#     topic_name = google_pubsub_topic.upload_trigger.id
#     data       = base64encode("{\"action\": \"upload\"}")
#   }
#
#   depends_on = [google_project_service.required_apis]
# }

# Cloud Scheduler job - Download trigger (every Wednesday at 9am, 2 days after Monday)
# COMMENTED OUT - Disable automatic triggering until ready for production
# resource "google_cloud_scheduler_job" "download_schedule" {
#   name      = "immunization-download-schedule"
#   schedule  = "0 9 * * 3"
#   time_zone = "America/Chicago"
#
#   pubsub_target {
#     topic_name = google_pubsub_topic.download_trigger.id
#     data       = base64encode("{\"action\": \"download\"}")
#   }
#
#   depends_on = [google_project_service.required_apis]
# }