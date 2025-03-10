variable "project_id" {
  description = "The Google Cloud project ID"
  default     = "immunization-records-pipeline"
}

provider "google" {
  project = "${var.project_id}"
  region  = "us-central1"
}

# Enable required APIs
resource "google_project_service" "scheduler" {
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "storage" {
  service            = "storage.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "cloudfunctions" {
  service            = "cloudfunctions.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "cloudbuild" {
  service            = "cloudbuild.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifactregistry" {
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

# Create storage buckets
resource "google_storage_bucket" "bulk_query_files" {
  name          = "${var.project_id}-bulk-query-files"
  location      = "US"
  force_destroy = true
  
  uniform_bucket_level_access = true
}

resource "google_storage_bucket" "aisr_downloads" {
  name          = "${var.project_id}-aisr-downloads"
  location      = "US"
  force_destroy = true
  
  uniform_bucket_level_access = true
}

resource "google_storage_bucket" "transformed_output" {
  name          = "${var.project_id}-transformed-output"
  location      = "US"
  force_destroy = true
  
  uniform_bucket_level_access = true
}

# Enable Pub/Sub API
resource "google_project_service" "pubsub" {
  service            = "pubsub.googleapis.com"
  disable_on_destroy = false
}
# Create Pub/Sub topic
resource "google_pubsub_topic" "default" {
  name = "pubsub_topic"
}
# Create Pub/Sub subscription
resource "google_pubsub_subscription" "default" {
  name  = "pubsub_subscription"
  topic = google_pubsub_topic.default.name
}
# Create a cron job using Cloud Scheduler
resource "google_cloud_scheduler_job" "default" {
  name        = "test-job"
  description = "test job"
  schedule    = "30 16 * * 7"
  region      = "us-central1"

  pubsub_target {
    topic_name = google_pubsub_topic.default.id
    data       = base64encode("Hello world!")
  }
}