"""
Mock FastAPI server for testing authentication and file upload.
Enhanced version of the test server with multi-school support.
"""

import os
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from .sample_data import get_sample_vaccination_data


def create_mock_app():
    """
    Creates and configures a FastAPI app with mock endpoints for testing.
    """
    app = FastAPI(
        title="Mock AISR Server",
        description="Mock server for testing Minnesota Immunization Pipeline",
        version="0.1.0"
    )

    @app.get("/health")
    async def health_check():
        """Health check endpoint for Cloud Run"""
        return {"status": "healthy", "service": "mock-aisr-server"}

    @app.get(
        "/mock-auth-server/auth/realms/idepc-aisr-realm/protocol/openid-connect/auth",
        response_class=HTMLResponse,
    )
    async def oidc_auth():
        """
        Simulates an authentication endpoint. Returns an HTML page with a form
        that includes the required `session_code` and `tab_id`.
        """
        encoded_session_and_tab = urlencode(
            {"session_code": "mock-session-code", "tab_id": "mock-tab-id"}
        )
        form_action_url = f"/protocol/openid-connect/login?{encoded_session_and_tab}"

        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Mock AISR Login</title>
        </head>
        <body>
            <h1>Mock AISR Authentication</h1>
            <p>Use any username/password for testing</p>
            <form id="kc-form-login" action="{form_action_url}" method="post">
                <input type="text" name="username" placeholder="Username" required />
                <input type="password" name="password" placeholder="Password" required />
                <button type="submit">Login</button>
            </form>
        </body>
        </html>
        """

    @app.post(
        "/mock-auth-server/auth/realms/idepc-aisr-realm/login-actions/authenticate"
    )
    async def authenticate(username: str = Form(...), password: str = Form(...)):
        """
        Simulates the login authentication endpoint. 
        Accepts any username/password for testing.
        """
        # Accept any credentials for testing
        response = JSONResponse(
            content={"message": "Login successful", "is_successful": True},
            status_code=302,
        )
        response.set_cookie(
            key="KEYCLOAK_IDENTITY",
            value="mocked-identity-token",
            httponly=True,
            secure=True,
        )
        # Use the request host for redirect
        base_url = os.environ.get("MOCK_SERVER_URL", "http://localhost:8080")
        response.headers["Location"] = f"{base_url}#code=test_code"
        return response

    @app.get(
        "/mock-auth-server/auth/realms/idepc-aisr-realm/protocol/openid-connect/logout"
    )
    async def logout(client_id: str):
        """
        Simulates the logout endpoint. Removes the KEYCLOAK_IDENTITY cookie.
        """
        if client_id == "aisr-app":
            response = JSONResponse(
                content={"message": "Logout successful"},
                status_code=200,
            )
            response.delete_cookie(
                key="KEYCLOAK_IDENTITY",
                httponly=True,
                secure=True,
            )
            return response

        return JSONResponse(
            content={"message": "Invalid client_id", "is_successful": False},
            status_code=400,
        )

    @app.post(
        "/mock-auth-server/auth/realms/idepc-aisr-realm/protocol/openid-connect/token"
    )
    async def get_access_token(
        grant_type: str = Form(...),
        redirect_uri: str = Form(...),
        code: str = Form(...),
        client_id: str = Form(...),
    ):
        """
        Simulates the token endpoint. Returns a mock access
        token if the request is valid.
        """
        if (
            grant_type == "authorization_code"
            and code == "test_code"
            and client_id == "aisr-app"
        ):
            return JSONResponse(
                content={"access_token": "mocked-access-token", "token_type": "Bearer"},
                status_code=200,
            )
        return JSONResponse(
            content={
                "error": "invalid_request",
                "error_description": "Invalid token request",
            },
            status_code=400,
        )

    @app.post("/signing/puturl")
    async def signing_puturl(request: Request):
        """
        Simulates the request signed URL endpoint. Validates the
        request and returns a mock URL.
        """
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")

        try:
            data = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

        required_fields = {"filePath", "contentType", "schoolId"}
        if not required_fields.issubset(data.keys()):
            raise HTTPException(status_code=400, detail="Missing required fields")

        # Return a mock S3 URL
        base_url = os.environ.get("MOCK_SERVER_URL", "http://localhost:8080")
        return JSONResponse(
            content={"url": f"{base_url}/test-s3-put-location"},
            status_code=200,
        )

    @app.put("/test-s3-put-location")
    async def put_file(request: Request):
        """
        This endpoint mocks an S3 signed URL upload.
        It accepts a PUT request with file data and custom S3 headers.
        """
        if not await request.body():
            raise HTTPException(status_code=400, detail="Empty request body.")
        
        headers = request.headers
        expected_headers = {
            "x-amz-meta-classification",
            "x-amz-meta-school_id",
            "x-amz-meta-email_contact",
            "content-type",
            "x-amz-meta-iddis",
            "host",
        }
        
        # Check for required headers (case-insensitive)
        header_keys = {k.lower() for k in headers.keys()}
        missing_headers = [h for h in expected_headers if h.lower() not in header_keys]
        
        if missing_headers:
            raise HTTPException(
                status_code=400, 
                detail=f"Missing required headers: {missing_headers}"
            )
        
        return Response(status_code=200)

    @app.get("/school/query/{school_id}")
    async def get_vaccination_records(school_id: str, request: Request):
        """
        Mock endpoint to get vaccination records for a school.
        Returns different data based on school_id.
        """
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")

        # Generate mock data based on school_id
        base_url = os.environ.get("MOCK_SERVER_URL", "http://localhost:8080")
        
        return [
            {
                "id": 16386 + int(school_id),
                "schoolId": school_id,
                "uploadDateTime": 1740764967763,
                "fileName": f"school_{school_id}_test.csv",
                "s3FileUrl": f"{base_url}/test-s3-get-location/{school_id}",
                "fullVaccineFileUrl": f"{base_url}/test-s3-get-location/{school_id}",
                "covidVaccineFileUrl": f"{base_url}/covid/{school_id}.txt",
                "matchFileUrl": f"{base_url}/match/{school_id}.xlsx",
                "statsFileUrl": f"{base_url}/stats/{school_id}.txt",
                "fullVaccineFileName": f"full/school_{school_id}.full.txt",
                "covidVaccineFileName": f"covid/school_{school_id}.covid.txt",
                "matchFileName": f"match/school_{school_id}.match.xlsx",
                "statsFileName": f"stats/school_{school_id}.stats.txt",
                "s3FileName": f"intake/school_{school_id}.csv",
            }
        ]

    @app.get("/test-s3-get-location/{school_id}")
    async def get_file_for_school(school_id: str):
        """
        This endpoint mocks an S3 signed URL download.
        Returns sample vaccination data specific to the school.
        """
        content = get_sample_vaccination_data(school_id)
        return Response(content=content, media_type="text/csv")

    @app.get("/test-s3-get-location")
    async def get_file():
        """
        Default endpoint for backward compatibility.
        """
        content = get_sample_vaccination_data("default")
        return Response(content=content, media_type="text/csv")

    return app