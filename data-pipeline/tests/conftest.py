"""
Pytest utils
"""

import time
from multiprocessing import Process
from pathlib import Path
from urllib.parse import urlencode

import pytest
import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse


@pytest.fixture(name="folders")
def input_output_logs_folders():
    """
    Allows tests to use input and output folders
    """
    input_folder = Path(".") / "tests" / "test_input"
    output_folder = Path(".") / "tests" / "test_output"
    logs_folder = Path(".") / "tests" / "test_logs"
    metadata_folder = output_folder / "metadata"

    # Create directories
    for folder in [input_folder, output_folder, logs_folder]:
        folder.mkdir(parents=True, exist_ok=True)

    # Yield the folders for test usage
    yield input_folder, output_folder, logs_folder

    # Cleanup after the test
    for folder in [metadata_folder, input_folder, output_folder, logs_folder]:
        if folder.exists():
            for file in folder.iterdir():
                file.unlink()
            folder.rmdir()


@pytest.fixture(scope="session")
def fastapi_server():
    """
    Spins up a FastAPI server for testing.
    """
    app = FastAPI()

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
        <html lang=\"en\">
        <head>
            <meta charset=\"UTF-8\">
            <title>Login</title>
        </head>
        <body>
            <form id=\"kc-form-login\" action=\"{form_action_url}\" method=\"post\">
                <input type=\"text\" name=\"username\" placeholder=\"Username\" required />
                <input type=\"password\" name=\"password\" placeholder=\"Password\" required />
                <button type=\"submit\">Login</button>
            </form>
        </body>
        </html>
        """

    @app.post(
        "/mock-auth-server/auth/realms/idepc-aisr-realm/login-actions/authenticate"
    )
    async def authenticate(username: str = Form(...), password: str = Form(...)):
        """
        Simulates the login authentication endpoint. Validates username and password and returns
        a response with a cookie indicating success or failure.
        """
        if username == "test_user" and password == "test_password":
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
            response.headers["Location"] = "http://127.0.0.1:8000#code=test_code"
            return response
        return JSONResponse(
            content={"message": "Invalid credentials", "is_successful": False},
            status_code=200,
        )

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
        Simulates the token endpoint. Returns a mock access token if the request is valid.
        """
        if (
            grant_type == "authorization_code"
            and redirect_uri == "https://aisr.web.health.state.mn.us/home"
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
        Simulates the request signed URL endpoint. Validates the request and returns a mock URL.
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

        return JSONResponse(
            content={"url": "http://127.0.0.1:8000/test-s3-put-location"},
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
        if not expected_headers.issubset(set(headers.keys())):
            raise HTTPException(status_code=400, detail="Missing required headers")
        return Response(status_code=200)

    def run_server():
        uvicorn.run(app, host="127.0.0.1", port=8000)

    process = Process(target=run_server, daemon=True)
    process.start()

    # Wait for the server to start up
    time.sleep(1)

    yield "http://127.0.0.1:8000"

    process.terminate()
    process.join()
