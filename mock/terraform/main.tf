terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

# Configure the Google Cloud Provider
provider "google" {
  project = var.project_id
  region  = var.region
}

# Variables
variable "project_id" {
  description = "Google Cloud Project ID"
  type        = string
}

variable "region" {
  description = "Google Cloud Region"
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Name of the Cloud Run service"
  type        = string
  default     = "minnesota-immunization-mock"
}

# Enable required APIs
resource "google_project_service" "cloud_run_api" {
  service = "run.googleapis.com"
  
  disable_on_destroy = false
}

resource "google_project_service" "cloud_build_api" {
  service = "cloudbuild.googleapis.com"
  
  disable_on_destroy = false
}

resource "google_project_service" "artifact_registry_api" {
  service = "artifactregistry.googleapis.com"
  
  disable_on_destroy = false
}

# Create Artifact Registry repository
resource "google_artifact_registry_repository" "mock_server_repo" {
  location      = var.region
  repository_id = "minnesota-immunization-mock"
  description   = "Repository for mock AISR server container images"
  format        = "DOCKER"
  
  depends_on = [google_project_service.artifact_registry_api]
}

# Note: Build and push container manually using:
# gcloud builds submit --tag us-central1-docker.pkg.dev/PROJECT_ID/minnesota-immunization-mock/mock-server:latest minnesota-immunization-mock/

# Deploy to Cloud Run
resource "google_cloud_run_service" "mock_server" {
  name     = var.service_name
  location = var.region
  
  template {
    spec {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/minnesota-immunization-mock/mock-server:latest"
        
        ports {
          container_port = 8080
        }
        
        
        resources {
          limits = {
            cpu    = "1000m"
            memory = "512Mi"
          }
        }
      }
    }
    
    metadata {
      annotations = {
        "autoscaling.knative.dev/minScale" = "0"
        "autoscaling.knative.dev/maxScale" = "10"
        "run.googleapis.com/cpu-throttling" = "true"
      }
    }
  }
  
  traffic {
    percent         = 100
    latest_revision = true
  }
  
  depends_on = [google_project_service.cloud_run_api]
}

# Generate random suffix for service URL
resource "random_id" "service_suffix" {
  byte_length = 4
}

# Allow unauthenticated access (public)
resource "google_cloud_run_service_iam_binding" "public_access" {
  location = google_cloud_run_service.mock_server.location
  service  = google_cloud_run_service.mock_server.name
  role     = "roles/run.invoker"
  members  = ["allUsers"]
}

# Outputs
output "service_url" {
  description = "URL of the deployed mock server"
  value       = google_cloud_run_service.mock_server.status[0].url
}

output "service_name" {
  description = "Name of the Cloud Run service"
  value       = google_cloud_run_service.mock_server.name
}

output "artifact_registry_url" {
  description = "URL of the Artifact Registry repository"
  value       = google_artifact_registry_repository.mock_server_repo.name
}