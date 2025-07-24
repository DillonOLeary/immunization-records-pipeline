# Minnesota Immunization Infrastructure

Infrastructure as Code for automated immunization record processing between AISR and school systems.

## Architecture Overview

This system automates the weekly immunization data workflow:
- **Monday**: Upload student query data to AISR
- **Wednesday**: Download vaccination records and transform for school systems
- **Output**: Files delivered to both Google Cloud Storage and Google Drive

## Prerequisites

1. **Google Cloud Project** with billing enabled
2. **Terraform** installed locally
3. **gcloud CLI** installed and authenticated
4. **Google Drive account** for file delivery

## Deployment Guide

### Step 1: Deploy Terraform Infrastructure

1. **Clone and configure**:
   ```bash
   git clone <repo-url>
   cd minnesota-immunization-infra
   cp terraform.tfvars.example terraform.tfvars
   ```

2. **Edit terraform.tfvars**:
   ```hcl
   project_id = "your-gcp-project-id"
   region = "us-central1"
   google_drive_folder_id = ""  # Leave empty for now, fill in Step 3
   ```

3. **Deploy infrastructure**:
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

### Step 2: Configure Google Drive OAuth

Google Drive integration requires OAuth 2.0 credentials for user account access.

#### 2.1 Create OAuth 2.0 Client

1. Go to [Google Cloud Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)
2. Click **"+ CREATE CREDENTIALS"** → **"OAuth 2.0 Client ID"**
3. **Application type**: Select **"Web application"**
4. **Name**: "Immunization Pipeline OAuth Client"
5. **Authorized redirect URIs**: 
   - Click "ADD URI"
   - Enter: `http://localhost:8080/`
   - **This is required for the OAuth setup script to work**
6. Click **"CREATE"**
7. **Download the JSON file**

#### 2.2 Configure OAuth Consent Screen

1. Go to [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent)
2. **User Type**: Choose "Internal" (if using Google Workspace) or "External"
3. Fill in required fields:
   - **App name**: "Minnesota Immunization Pipeline"
   - **User support email**: Your email
   - **Developer contact**: Your email
4. **Scopes**: Add `https://www.googleapis.com/auth/drive.file`
5. **Test users**: Add the Google account you want to use for Drive access
   - Example: `mail@dillonoleary.com`

#### 2.3 Generate OAuth Tokens

Run the OAuth setup script to generate refresh tokens:

```bash
cd minnesota-immunization-infra
uv run scripts/setup_google_drive_oauth.py path/to/your/oauth_credentials.json
```

This will:
1. Open your browser for OAuth flow
2. Let you authenticate with your chosen Google account
3. Generate refresh token and client credentials
4. Show commands to update Secret Manager

#### 2.4 Update Secret Manager

Use the gcloud commands from the script output:

```bash
# Example output from script:
echo "1//04...refresh_token" | gcloud secrets versions add drive-refresh-token --data-file=-
echo "904454...client_id" | gcloud secrets versions add drive-client-id --data-file=-
echo "GOCSPX-...client_secret" | gcloud secrets versions add drive-client-secret --data-file=-
```

### Step 3: Configure Google Drive Folder

1. **Create a Google Drive folder** for immunization records
2. **Copy the folder ID** from the URL:
   - URL: `https://drive.google.com/drive/folders/1ABC123XYZ`
   - Folder ID: `1ABC123XYZ`
3. **Update terraform.tfvars**:
   ```hcl
   google_drive_folder_id = "1ABC123XYZ"
   ```
4. **Redeploy**:
   ```bash
   terraform apply
   ```

### Step 4: Configure AISR Credentials

Add your AISR system credentials to Secret Manager:

```bash
echo "your_aisr_username" | gcloud secrets versions add aisr-username --data-file=-
echo "your_aisr_password" | gcloud secrets versions add aisr-password --data-file=-
```

### Step 5: Upload School Configuration

1. **Create config.json** based on the examples in the cloud function
2. **Upload to Google Cloud Storage**:
   ```bash
   gsutil cp config.json gs://your-project-id-immunization-data/config/config.json
   ```

## Usage

### Manual Testing

Trigger functions manually for testing:

```bash
# Upload function (Monday workflow)
gcloud functions call immunization-upload --region=us-central1

# Download function (Wednesday workflow)  
gcloud functions call immunization-download --region=us-central1
```

### Production Scheduling

Uncomment the Cloud Scheduler resources in `main.tf` and redeploy:

```bash
terraform apply
```

## File Organization

The system automatically organizes files by school:

```
📁 Google Drive Folder
├── 📁 FRIENDLY HILLS MID/
│   ├── 2024-12-20_143022_vaccinations_FRIENDLY_HILLS_MID_20241220_143022_abc123.csv
│   └── ...
├── 📁 GARLOUGH EL/
│   ├── 2024-12-20_143022_vaccinations_GARLOUGH_EL_20241220_143022_def456.csv
│   └── ...
└── 📁 HERITAGE MID/
    └── ...
```

## Troubleshooting

### Google Drive Authentication Issues

1. **"The OAuth client was not found"**:
   - Check OAuth consent screen: Ensure your Google account is added as a test user
   - Verify OAuth client exists in Google Cloud Console → APIs & Services → Credentials
   - Ensure authorized redirect URI includes `http://localhost:8080/`

2. **Test authentication**: Re-run the OAuth setup script or use the test script:
   ```bash
   uv run scripts/test_google_drive_integration.py
   ```

### Function Errors

View logs in Google Cloud Console:
```bash
gcloud functions logs read immunization-download --region=us-central1
```

## Security Notes

- All secrets stored in Google Secret Manager
- HIPAA-compliant storage with encryption at rest
- Minimal IAM permissions (principle of least privilege)
- 3-year data retention policy

## Support

For issues or questions, check the logs first:
- Cloud Functions logs in Google Cloud Console
- Secret Manager for credential issues
- Storage bucket for data delivery verification

## License
[GNU General Public License](../LICENSE)