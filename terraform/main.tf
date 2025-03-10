provider "google" {
  project = "immunization-records-pipeline"
  region  = "us-central1"
}

# Enable Cloud Scheduler API
resource "google_project_service" "scheduler" {
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
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