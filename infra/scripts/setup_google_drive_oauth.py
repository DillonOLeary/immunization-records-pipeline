#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "google-auth-oauthlib",
#     "google-auth",
# ]
# ///
"""
Google Drive OAuth Setup Script
Minnesota Immunization Infrastructure

This script generates the required OAuth credentials for Google Drive integration.
Run this once when setting up the infrastructure or changing Google accounts.

Prerequisites:
1. Terraform infrastructure deployed (creates Secret Manager secrets)
2. Google Cloud Project with Drive API enabled
3. OAuth 2.0 Client ID credentials downloaded as JSON file

Usage (standalone uv script):
    uv run setup_google_drive_oauth.py credentials.json
    
Or with regular Python:
    pip install google-auth-oauthlib google-auth
    python setup_google_drive_oauth.py credentials.json

Output:
    - Refresh token for Google Drive access
    - Client ID and secret for authentication
    - Instructions for adding to Secret Manager
"""

import json
import os
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("❌ Required packages not installed")
    print("Install with: pip install google-auth-oauthlib google-auth")
    sys.exit(1)

# Required scopes for Google Drive file access
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def validate_credentials_file(credentials_file: str) -> dict:
    """Validate and load OAuth credentials file"""
    if not os.path.exists(credentials_file):
        print(f"❌ Credentials file not found: {credentials_file}")
        print("\nTo get this file:")
        print("1. Go to Google Cloud Console")
        print("2. Navigate to APIs & Services > Credentials")  
        print("3. Create OAuth 2.0 Client ID (Web application or Desktop application)")
        print("4. Download the JSON file")
        sys.exit(1)
    
    try:
        with open(credentials_file, 'r') as f:
            creds_data = json.load(f)
        
        # Validate structure - accept both 'web' and 'installed' types
        if 'web' not in creds_data and 'installed' not in creds_data:
            print("❌ Invalid credentials file format")
            print("Expected OAuth 2.0 Client ID credentials (Web application or Desktop application)")
            sys.exit(1)
            
        return creds_data
    except json.JSONDecodeError:
        print(f"❌ Invalid JSON in credentials file: {credentials_file}")
        sys.exit(1)

def generate_oauth_credentials(credentials_file: str) -> tuple[str, str, str]:
    """
    Generate OAuth credentials for Google Drive access
    
    Returns:
        tuple: (refresh_token, client_id, client_secret)
    """
    # Validate credentials file
    validate_credentials_file(credentials_file)
    
    print("🔐 Initializing OAuth flow...")
    print("📱 Your browser will open shortly")
    print("👆 Sign in with the Google account you want to use for Drive access")
    
    # Create the OAuth flow
    flow = InstalledAppFlow.from_client_secrets_file(
        credentials_file, 
        SCOPES
    )
    
    try:
        # Run local server to handle OAuth callback
        creds = flow.run_local_server(
            port=8080,
            prompt='select_account',  # Always show account selection
            open_browser=True
        )
        
        return creds.refresh_token, creds.client_id, creds.client_secret
        
    except Exception as e:
        print(f"❌ OAuth flow failed: {e}")
        print("\nTroubleshooting:")
        print("- Ensure port 8080 is available")
        print("- Check your internet connection")
        print("- Verify the credentials file is valid")
        sys.exit(1)

def display_results(refresh_token: str, client_id: str, client_secret: str):
    """Display the generated credentials and next steps"""
    print("\n" + "="*60)
    print("✅ Google Drive OAuth Setup Complete!")
    print("="*60)
    
    print("\n📋 Generated Credentials:")
    print("-" * 40)
    print(f"Refresh Token: {refresh_token}")
    print(f"Client ID:     {client_id}")
    print(f"Client Secret: {client_secret}")
    
    print("\n🔐 Secret Manager Setup:")
    print("-" * 40)
    print("Add these as secrets in Google Secret Manager:")
    print(f"  drive-refresh-token  → {refresh_token}")
    print(f"  drive-client-id      → {client_id}")
    print(f"  drive-client-secret  → {client_secret}")
    
    print("\n💻 Using gcloud CLI:")
    print("-" * 40)
    print("# Update existing secrets (Terraform creates empty secrets, we add the values)")
    print("# Make sure you've deployed the Terraform stack first!")
    print("# Note: Using 'tr -d \"\\n\"' to remove any trailing newlines")
    print(f'echo "{refresh_token}" | tr -d "\\n" | gcloud secrets versions add drive-refresh-token --data-file=-')
    print(f'echo "{client_id}" | tr -d "\\n" | gcloud secrets versions add drive-client-id --data-file=-')
    print(f'echo "{client_secret}" | tr -d "\\n" | gcloud secrets versions add drive-client-secret --data-file=-')
    
    print("\n📁 Google Drive Setup:")
    print("-" * 40)
    print("1. Create a Google Drive folder for immunization records")
    print("2. Copy the folder ID from the URL")
    print("3. Set GOOGLE_DRIVE_FOLDER_ID environment variable")
    
    print("\n⚠️  Security Notes:")
    print("-" * 40)
    print("- Store these credentials securely")
    print("- Never commit them to version control")
    print("- Refresh tokens don't expire but can be revoked")
    print("- Monitor access in Google Cloud Console")

def main():
    """Main script execution"""
    if len(sys.argv) != 2:
        print("Google Drive OAuth Setup Script")
        print("Minnesota Immunization Infrastructure")
        print("\nUsage:")
        print("  python setup_google_drive_oauth.py <credentials.json>")
        print("\nExample:")
        print("  python setup_google_drive_oauth.py oauth_credentials.json")
        sys.exit(1)
    
    credentials_file = sys.argv[1]
    
    print("🏥 Minnesota Immunization Infrastructure")
    print("🔐 Google Drive OAuth Setup")
    print("=" * 50)
    
    # Generate OAuth credentials
    refresh_token, client_id, client_secret = generate_oauth_credentials(credentials_file)
    
    # Display results and instructions
    display_results(refresh_token, client_id, client_secret)
    
    print("\n✨ Setup complete! The Cloud Function can now access Google Drive.")

if __name__ == "__main__":
    main()