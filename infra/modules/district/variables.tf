variable "district_name" {
  description = "Human-readable district name"
  type        = string
}

variable "project_id" {
  description = "GCP project id for this district"
  type        = string
}

variable "create_project" {
  description = "Create the project (new districts) or adopt an existing one"
  type        = bool
  default     = false
}

variable "billing_account" {
  description = "Billing account id; required when create_project is true"
  type        = string
  default     = ""
}

variable "region" {
  description = "Region for district resources"
  type        = string
  default     = "us-central1"
}

variable "image" {
  description = "Pipeline job container image (Artifact Registry URL)"
  type        = string
}

variable "google_drive_folder_id" {
  description = "Drive folder receiving delivered files"
  type        = string
  default     = ""
}

variable "query_schedule" {
  description = "Cron for the bulk query cycle"
  type        = string
  default     = "9 2 28 * *"
}

variable "download_schedule" {
  description = "Cron for the download cycle"
  type        = string
  default     = "9 2 1 * *"
}

variable "canary_schedule" {
  description = "Cron for the pre-flight canary (day before the query)"
  type        = string
  default     = "9 2 27 * *"
}

variable "time_zone" {
  description = "Scheduler time zone"
  type        = string
  default     = "America/Chicago"
}

variable "alert_email" {
  description = "Email for failure alerts; empty disables the channel"
  type        = string
  default     = ""
}

variable "deployer_service_account" {
  description = "CI deployer allowed to act as the job SA; empty disables"
  type        = string
  default     = ""
}
