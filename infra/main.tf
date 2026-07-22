# Root configuration: one district module instance per file in districts/.
# Adding a district is adding one JSON file. Nothing here is applied by CI;
# a human runs plan/apply (see infra/README.md).

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
    prefix = "terraform/rewrite" # separate from the legacy function-era state
  }
}

provider "google" {
  region = var.region
}

locals {
  districts = {
    for f in fileset("${path.module}/districts", "*.json") :
    trimsuffix(f, ".json") => jsondecode(file("${path.module}/districts/${f}"))
  }
}

module "district" {
  source   = "./modules/district"
  for_each = local.districts

  district_name            = each.value.district_name
  project_id               = each.value.project_id
  create_project           = try(each.value.create_project, false)
  billing_account          = try(each.value.billing_account, "")
  region                   = try(each.value.region, var.region)
  image                    = each.value.image
  google_drive_folder_id   = try(each.value.google_drive_folder_id, "")
  query_schedule           = try(each.value.query_schedule, "9 2 28 * *")
  download_schedule        = try(each.value.download_schedule, "9 2 1 * *")
  canary_schedule          = try(each.value.canary_schedule, "9 2 27 * *")
  time_zone                = try(each.value.time_zone, "America/Chicago")
  alert_email              = try(each.value.alert_email, "")
  deployer_service_account = try(each.value.deployer_service_account, "")
}
