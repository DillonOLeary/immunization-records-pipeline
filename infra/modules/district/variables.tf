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

variable "schedule" {
  description = "Cron for run: opens a period (rosters go to MIIC, nurses are emailed)"
  type        = string
  default     = "9 2 28 * *"
}

variable "tick_schedule" {
  description = "Cron for tick: advances the open period (staging, diff, delivery)"
  type        = string
  default     = "17 */3 * * *"
}

variable "canary_schedule" {
  description = "Cron for the read-only canary: the day before the run, and every Monday (day-of-month OR day-of-week)"
  type        = string
  default     = "9 2 27 * 1"
}

variable "time_zone" {
  description = "District time zone: schedulers, roster periods, delivery dates"
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
