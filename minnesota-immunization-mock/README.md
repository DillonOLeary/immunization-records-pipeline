# Minnesota Immunization Mock Server

A mock AISR (Automated Immunization School Registry) server for testing the Minnesota Immunization Records Pipeline. This service provides realistic mock endpoints that replicate the behavior of the actual AISR system, allowing contributors to test the full pipeline without needing access to production systems.

## Features

- **Complete AISR API mock**: Authentication, file upload, and data retrieval endpoints
- **Multi-school support**: Different sample data for different school IDs
- **Realistic data**: Pipe-delimited CSV format matching AISR specifications
- **Public deployment**: No authentication required for testing
- **Cloud Run ready**: Containerized and deployable to Google Cloud

## Quick Start

### Local Development

1. **Install dependencies**:
   ```bash
   cd minnesota-immunization-mock
   uv sync
   ```

2. **Run the server**:
   ```bash
   uv run mock-server
   ```

3. **Access the service**:
   - Server: http://localhost:8080
   - Health check: http://localhost:8080/health
   - Mock login: http://localhost:8080/mock-auth-server/auth/realms/idepc-aisr-realm/protocol/openid-connect/auth

### Testing with the Main Pipeline

1. **Set environment variables** for your cloud functions:
   ```bash
   MOCK_MODE=true
   MOCK_AISR_URL=https://your-mock-server-url.run.app
   ```

2. **Update configuration** in your cloud function to use mock URLs when `MOCK_MODE=true`

3. **Run the pipeline** - it will use the mock server instead of real AISR endpoints

## Cloud Run Deployment

### Prerequisites

- Google Cloud Project with billing enabled
- `gcloud` CLI configured
- Terraform installed

### Deploy Steps

1. **Copy and configure variables**:
   ```bash
   cd terraform
   cp terraform.tfvars.example terraform.tfvars
   # Edit terraform.tfvars with your project ID
   ```

2. **Initialize Terraform**:
   ```bash
   terraform init
   ```

3. **Deploy the infrastructure**:
   ```bash
   terraform plan
   terraform apply
   ```

4. **Build and deploy the container**:
   ```bash
   # Build locally and push to Artifact Registry
   gcloud builds submit --tag us-central1-docker.pkg.dev/YOUR-PROJECT/minnesota-immunization-mock/mock-server:latest ../
   
   # Or use the Cloud Build trigger (requires GitHub integration)
   gcloud builds triggers run minnesota-immunization-mock-build --branch=main
   ```

5. **Get the service URL**:
   ```bash
   terraform output service_url
   ```

### Manual Cloud Run Deployment (Alternative)

If you prefer to skip Terraform:

```bash
# Build and push container
gcloud builds submit --tag gcr.io/YOUR-PROJECT/minnesota-immunization-mock ../

# Deploy to Cloud Run
gcloud run deploy minnesota-immunization-mock \
  --image gcr.io/YOUR-PROJECT/minnesota-immunization-mock \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 10
```

## API Endpoints

### Authentication
- `GET /mock-auth-server/auth/realms/idepc-aisr-realm/protocol/openid-connect/auth` - Login form
- `POST /mock-auth-server/auth/realms/idepc-aisr-realm/login-actions/authenticate` - Login processing
- `POST /mock-auth-server/auth/realms/idepc-aisr-realm/protocol/openid-connect/token` - Token exchange
- `GET /mock-auth-server/auth/realms/idepc-aisr-realm/protocol/openid-connect/logout` - Logout

### File Operations
- `POST /signing/puturl` - Get signed URL for file upload
- `PUT /test-s3-put-location` - Mock S3 file upload
- `GET /test-s3-get-location/{school_id}` - Get vaccination data for specific school

### Data Retrieval
- `GET /school/query/{school_id}` - Get vaccination records list for school
- `GET /health` - Health check endpoint

## Sample Data

The mock server provides realistic sample data:

### School ID 2542 (Friendly Hills Mid)
- 4 sample students with vaccination records
- Mix of COVID-19, Flu, MMR, DTaP, Polio, and Hepatitis B vaccines

### School ID 2543 (Garlough Elementary)
- 3 sample students with vaccination records
- Different student population for testing multi-school scenarios

### Default/Other Schools
- 2 sample students for any other school ID

## Testing Scenarios

### Full Pipeline Test

1. **Upload Phase** (Monday operation):
   - Mock server accepts bulk query file uploads
   - Returns success responses for all schools

2. **Download Phase** (Wednesday operation):
   - Mock server provides vaccination records
   - Returns different data per school ID
   - ETL pipeline processes the mock data

### Error Testing

The mock server can be extended to simulate various error conditions:
- Authentication failures
- File upload errors
- Missing vaccination records
- Network timeouts

## Environment Variables

- `MOCK_SERVER_URL`: Base URL for the mock server (auto-configured in Cloud Run)
- `MOCK_MODE`: Set to `true` in cloud functions to use mock endpoints
- `MOCK_AISR_URL`: URL of the deployed mock server

## Contributing

To add new test scenarios:

1. **Update sample data** in `src/minnesota_immunization_mock/sample_data.py`
2. **Add new endpoints** in `src/minnesota_immunization_mock/server.py`
3. **Update tests** to cover new scenarios
4. **Deploy changes** using the steps above

## Architecture

```
Cloud Functions (with MOCK_MODE=true)
        “
Mock AISR Server (Cloud Run)
        “
Sample Data Generator
        “
Realistic Test Data
```

The mock server replicates the exact API contract of the real AISR system, allowing the pipeline to be tested end-to-end without requiring production credentials or access.

## Cost

The Cloud Run deployment is very cost-effective:
- **No minimum charges** (scales to zero when not in use)
- **Pay per request** only
- **Estimated cost**: <$1/month for typical testing usage

## Security

- **No authentication required** for testing convenience
- **No sensitive data** - all data is synthetic
- **Public access** enabled for contributor testing
- **Stateless design** - no data persistence