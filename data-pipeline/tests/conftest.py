"""
Pytest utils
"""

import time
from multiprocessing import Process
from pathlib import Path
from urllib.parse import urlencode

import pytest
import uvicorn
from fastapi import FastAPI, Form
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
    Spins up a FastAPI server for integration tests.
    """
    app = FastAPI()

    @app.get(
        "/auth/realms/idepc-aisr-realm/protocol/openid-connect/auth",
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

    @app.post("/auth/realms/idepc-aisr-realm/login-actions/authenticate")
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
            response.headers["Location"] = "http://127.0.0.1:8000?code=test_code"
            return response
        return JSONResponse(
            content={"message": "Invalid credentials", "is_successful": False},
            status_code=200,
        )

    @app.get("/auth/realms/idepc-aisr-realm/protocol/openid-connect/logout")
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

    @app.post("/auth/realms/idepc-aisr-realm/protocol/openid-connect/token")
    async def get_access_token(
        grant_type: str = Form(...), code: str = Form(...), client_id: str = Form(...)
    ):
        """
        Simulates the token endpoint. Returns a mock access token if the request is valid.
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

    def run_server():
        uvicorn.run(app, host="127.0.0.1", port=8000)

    process = Process(target=run_server, daemon=True)
    process.start()

    # Wait for the server to start up
    time.sleep(1)

    yield "http://127.0.0.1:8000"

    process.terminate()
    process.join()
