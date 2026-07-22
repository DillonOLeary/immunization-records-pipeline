# These two values become GitHub repository variables (GCP_WIF_PROVIDER and
# GCP_DEPLOYER_SA); the deploy workflow stays inert until they are set.

output "workload_identity_provider" {
  value = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_service_account" {
  value = google_service_account.deployer.email
}
