# Secret shells only; values are set through the console or gcloud, never
# through Terraform (they would land in state).

resource "google_secret_manager_secret" "secrets" {
  for_each = toset([
    "aisr-username",
    "aisr-password",
    "drive-refresh-token",
    "drive-client-id",
    "drive-client-secret",
  ])

  project   = local.project_id
  secret_id = each.key

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}
