# Secret shells only; values are set through the console or gcloud, never
# through Terraform (they would land in state).

resource "google_secret_manager_secret" "secrets" {
  for_each = toset([
    "miic-username",
    "miic-password",
    "infinite-campus-username",
    "infinite-campus-password",
    "drive-refresh-token",
    "drive-client-id",
    "drive-client-secret",
    # Old names, kept until the code reads the new ones; then removed.
    "aisr-username",
    "aisr-password",
    "ic-username",
    "ic-password",
  ])

  project   = local.project_id
  secret_id = each.key

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}
