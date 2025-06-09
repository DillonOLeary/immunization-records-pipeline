# Project variables
variable "project_id" {
  description = "The Google Cloud project ID"
  type        = string
}

variable "region" {
  description = "The region to deploy resources to"
  type        = string
  default     = "us-central1"
}

# Function source code location
variable "function_source_dir" {
  description = "Directory containing the function source code"
  type        = string
  default     = "../minnesota-immunization-cloud"
}