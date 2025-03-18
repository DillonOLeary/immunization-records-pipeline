terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 4.34.0"
    }
  }
}

# --------------- Variables ---------------
variable "project_id" {
  description = "The Google Cloud project ID"
  default     = "immunization-records-pipeline"
}

variable "region" {
  description = "The region to deploy resources to"
  default     = "us-central1"
}

# --------------- API Enablement ---------------
locals {
  required_apis = [
    "eventarc.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudfunctions.googleapis.com"
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.required_apis)
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# --------------- IAM & Authentication ---------------
resource "google_service_account" "pipeline_sa" {
  project      = var.project_id
  account_id   = "immunization-pipeline-sa"
  display_name = "Immunization Pipeline Service Account"
}

resource "google_project_iam_binding" "pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  members = ["serviceAccount:${google_service_account.pipeline_sa.email}"]
}

# --------------- Storage ---------------
locals {
  bucket_names = {
    bulk_query   = "${var.project_id}-bulk-query-files"
    aisr_download = "${var.project_id}-aisr-downloads"
    transformed  = "${var.project_id}-transformed-output"
    function     = "${var.project_id}-function-source"
  }
}

resource "google_storage_bucket" "buckets" {
  for_each                  = local.bucket_names
  project                   = var.project_id
  name                      = each.value
  location                  = "US"
  uniform_bucket_level_access = true
}

# Grant bucket access to the function service account
resource "google_storage_bucket_iam_member" "bucket_access" {
  for_each = local.bucket_names
  bucket   = google_storage_bucket.buckets[each.key].name
  role     = "roles/storage.objectAdmin"
  member   = "serviceAccount:${google_service_account.pipeline_sa.email}"
}

# --------------- Pub/Sub Topic ---------------
resource "google_pubsub_topic" "pipeline_topic" {
  project = var.project_id
  name    = "immunization-pipeline-topic"
}

# --------------- Cloud Function ---------------
data "archive_file" "function_zip" {
  type        = "zip"
  output_path = "/tmp/function-source.zip"
  source_dir  = "${path.module}/../function-source/"
}

resource "google_storage_bucket_object" "function_code" {
  name   = "function-source-${data.archive_file.function_zip.output_md5}.zip"
  bucket = google_storage_bucket.buckets["function"].name
  source = data.archive_file.function_zip.output_path
}

resource "google_cloudfunctions2_function" "pipeline_function" {
  project     = var.project_id
  name        = "immunization-data-pipeline"
  location    = var.region
  description = "Function to process immunization data pipeline"
  
  depends_on = [google_project_service.apis]

  build_config {
    runtime     = "python311"
    entry_point = "process_pipeline"
    source {
      storage_source {
        bucket = google_storage_bucket.buckets["function"].name
        object = google_storage_bucket_object.function_code.name
      }
    }
  }

  service_config {
    max_instance_count = 3
    min_instance_count = 0
    available_memory   = "512M"
    timeout_seconds    = 540 # 9 minutes
    environment_variables = {
      BULK_QUERY_BUCKET    = google_storage_bucket.buckets["bulk_query"].name
      AISR_DOWNLOADS_BUCKET = google_storage_bucket.buckets["aisr_download"].name
      TRANSFORMED_BUCKET   = google_storage_bucket.buckets["transformed"].name
    }
    ingress_settings               = "ALLOW_INTERNAL_ONLY"
    all_traffic_on_latest_revision = true
    service_account_email          = google_service_account.pipeline_sa.email
  }
  
  event_trigger {
    trigger_region = var.region
    event_type     = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic   = google_pubsub_topic.pipeline_topic.id
    retry_policy   = "RETRY_POLICY_RETRY"
  }
}

# --------------- Cloud Scheduler ---------------
resource "google_cloud_scheduler_job" "pipeline_scheduler" {
  project     = var.project_id
  name        = "immunization-pipeline-scheduler"
  description = "Trigger the immunization data pipeline function every other Monday"
  schedule    = "40 0 * * 1"  # Run every Monday around midnight FIXME add jitter if there are more users
  time_zone   = "America/Chicago"
  region      = var.region

  pubsub_target {
    topic_name = google_pubsub_topic.pipeline_topic.id
    data       = base64encode("{\"message\": \"Run immunization data pipeline\"}")
    attributes = {
      "x-goog-version" = "v1"
    }
  }
}