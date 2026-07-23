# One-time bootstrap: lets GitHub Actions authenticate to GCP without any
# service-account keys (Workload Identity Federation). Applied by a human at
# cutover, never by CI. Until then this configuration is validate-only.

terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.30"
    }
  }

  backend "gcs" {
    bucket = "mn-immun-bd9001-terraform-state"
    prefix = "terraform/bootstrap"
  }
}

provider "google" {
  project = var.project_id
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }

  # Only this repository's main branch can assume the deployer identity.
  attribute_condition = "assertion.repository == \"${var.github_repo}\" && assertion.ref == \"refs/heads/main\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = "github-deployer"
  display_name = "GitHub Actions deployer"
}

resource "google_service_account_iam_member" "github_assumes_deployer" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

# The deployer can push images and update the job — nothing else. It gets
# actAs on the job's runtime service account through the district module
# (deployer_service_account in the district JSON), not project-wide.
resource "google_project_iam_member" "deployer_roles" {
  for_each = toset([
    "roles/artifactregistry.writer",
    "roles/run.developer",
  ])

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.deployer.email}"
}
