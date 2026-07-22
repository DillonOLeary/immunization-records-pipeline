# One project per district. This is the tenancy boundary: a district's
# project is its IAM boundary, its secrets, its data, and its blast radius.
# Existing districts (ISD 197) set create_project=false and are adopted via
# terraform import.

resource "google_project" "district" {
  count           = var.create_project ? 1 : 0
  name            = var.district_name
  project_id      = var.project_id
  billing_account = var.billing_account

  lifecycle {
    prevent_destroy = true
  }
}

locals {
  project_id = var.create_project ? google_project.district[0].project_id : var.project_id
}

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
  ])

  project            = local.project_id
  service            = each.key
  disable_on_destroy = false
}
