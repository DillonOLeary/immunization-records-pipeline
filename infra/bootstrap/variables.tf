variable "project_id" {
  description = "Project hosting the WIF pool and deployer service account"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository allowed to deploy (owner/name)"
  type        = string
  default     = "DillonOLeary/immunization-records-pipeline"
}
