# Minnesota Immunization Infrastructure

This module contains the resources for deploying the Minnesota Immunization Records Pipeline to Google Cloud Platform (GCP) using Terraform.

## Usage

1. **Install Terraform:**  
   [Terraform installation guide](https://learn.hashicorp.com/tutorials/terraform/install-cli)

2. **Initialize Terraform workspace:**
   ```bash
   terraform init
   ```

3. **Review and customize variables:**  
   Copy `terraform.tfvars.example`, rename to `terraform.tfvars`, and edit variables as instructed in example file

4. **Preview changes:**
   ```bash
   terraform plan
   ```

5. **Apply config:**
   ```bash
   terraform apply
   ```

## Prerequisites

- A GCP project with billing enabled
- Sufficient permissions to create resources

## License

[GNU General Public License](../LICENSE)