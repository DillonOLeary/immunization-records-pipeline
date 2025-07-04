# Minnesota Immunization Records Pipeline
This data engineering project extracts data from the Minnesota Department of Health Annual Immunization Status Report, transforms it, then uploads it to infinite campus.

# Repo structure
The repo is broken up into 4 workspaces.
1. Core: this handles the main functionality of the etl
2. CLI: This is the command line interface to the core library
3. Cloud Function: This allows the core library to be run as a cloud function on GCP.
4. Terraform: This is the infrastructure as code workspace that can deploy the complete application to GCP.
