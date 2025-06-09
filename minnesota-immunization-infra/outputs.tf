# Storage bucket name for data
output "data_bucket_name" {
  description = "Name of the storage bucket for immunization data"
  value       = google_storage_bucket.data.name
}

# Cloud Function URLs (for manual testing)
output "upload_function_url" {
  description = "URL of the upload Cloud Function"
  value       = google_cloudfunctions2_function.upload_function.service_config[0].uri
}

output "download_function_url" {
  description = "URL of the download Cloud Function"
  value       = google_cloudfunctions2_function.download_function.service_config[0].uri
}

# Service account email
output "service_account_email" {
  description = "Email of the service account used by Cloud Functions"
  value       = google_service_account.function_sa.email
}