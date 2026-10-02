"""A fake AISR: Keycloak login, roster upload, results listing and download.

The one fake the repo has. Tests run it in-process (tests/conftest.py)
and `uv run mock-server` runs it locally. It mirrors the production
contract the adapter depends on, including the parts that make the
adapter's job hard: the login form carries Keycloak flow parameters that
must be POSTed back verbatim, the token exchange checks the redirect URI,
and uploads must carry the S3 metadata headers.

Faults are injectable per school (`MockFaults`, mutable on `app.state`)
so tests can make signing, uploading, or listing fail, make a school list
no results, or serve a results file in a format the parser rejects. Every
successful upload is recorded on `app.state.received_uploads` (school ids,
in order), which is how tests prove a roster was or was not submitted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from .ic import add_ic_routes
from .sample_data import get_sample_vaccination_data

REALM = "/mock-auth-server/auth/realms/idepc-aisr-realm"
REDIRECT_URI = "https://aisr.web.health.state.mn.us/home"
PREVIOUS_UPLOAD_MS = 1_759_300_000_000
"""uploadDateTime for a school with no upload yet: 2025-10-01. Like real
AISR, the fake keeps listing a school's previous results until a new
roster upload replaces them."""

REQUIRED_UPLOAD_HEADERS = {
    "x-amz-meta-classification",
    "x-amz-meta-school_id",
    "x-amz-meta-email_contact",
    "content-type",
    "x-amz-meta-iddis",
    "host",
}


@dataclass
class MockFaults:
    """Per-school failures. Status maps are school id -> HTTP status."""

    puturl_status: dict[str, int] = field(default_factory=dict)
    upload_status: dict[str, int] = field(default_factory=dict)
    listing_status: dict[str, int] = field(default_factory=dict)
    no_results: set[str] = field(default_factory=set)
    malformed_results: set[str] = field(default_factory=set)
    # Keep listing the previous results even after a new upload, as real
    # AISR did on 2026-10-01 in the minutes after a submission.
    stale_listing: set[str] = field(default_factory=set)

    def clear(self) -> None:
        self.puturl_status.clear()
        self.upload_status.clear()
        self.listing_status.clear()
        self.no_results.clear()
        self.malformed_results.clear()
        self.stale_listing.clear()


def _require_bearer(request: Request) -> None:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")


def create_mock_app(
    base_url: str = "http://localhost:8080",
    credentials: tuple[str, str] | None = ("test_user", "test_password"),
    faults: MockFaults | None = None,
) -> FastAPI:
    """Build the fake AISR.

    `base_url` is where the server is reachable; it appears in redirect
    and signed URLs, as it does in production. `credentials` is the one
    accepted (username, password), or None to accept any.
    """
    app = FastAPI(title="Mock AISR Server")
    app.state.faults = faults or MockFaults()
    app.state.received_uploads = []
    app.state.uploaded_at = {}  # school id -> epoch ms of its latest upload
    add_ic_routes(app, base_url)  # a fake Infinite Campus under /campus

    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": "mock-aisr-server"}

    @app.get(f"{REALM}/protocol/openid-connect/auth", response_class=HTMLResponse)
    async def oidc_auth():
        """The Keycloak login page. The form action carries the flow
        parameters, as production's does; the client must POST back to it
        verbatim rather than reconstructing it."""
        flow_params = urlencode(
            {
                "session_code": "mock-session-code",
                "execution": "mock-execution-id",
                "tab_id": "mock-tab-id",
                "client_id": "aisr-app",
            }
        )
        action = f"{REALM}/login-actions/authenticate?{flow_params}"
        return (
            '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
            "<title>Mock AISR Login</title></head><body>"
            f'<form id="kc-form-login" action="{action}" method="post">'
            '<input type="text" name="username" required />'
            '<input type="password" name="password" required />'
            '<button type="submit">Login</button></form></body></html>'
        )

    @app.post(f"{REALM}/login-actions/authenticate")
    async def authenticate(username: str = Form(...), password: str = Form(...)):
        if credentials is not None and (username, password) != credentials:
            return JSONResponse(
                content={"message": "Invalid credentials"}, status_code=401
            )
        response = JSONResponse(
            content={"message": "Login successful"}, status_code=302
        )
        response.set_cookie(
            key="KEYCLOAK_IDENTITY",
            value="mocked-identity-token",
            httponly=True,
            secure=True,
        )
        response.headers["Location"] = f"{base_url}#code=test_code"
        return response

    @app.post(f"{REALM}/protocol/openid-connect/token")
    async def get_access_token(
        grant_type: str = Form(...),
        redirect_uri: str = Form(...),
        code: str = Form(...),
        client_id: str = Form(...),
    ):
        if (
            grant_type == "authorization_code"
            and redirect_uri == REDIRECT_URI
            and code == "test_code"
            and client_id == "aisr-app"
        ):
            return JSONResponse(
                content={"access_token": "mocked-access-token", "token_type": "Bearer"}
            )
        return JSONResponse(content={"error": "invalid_request"}, status_code=400)

    @app.get(f"{REALM}/protocol/openid-connect/logout")
    async def logout(client_id: str):
        if client_id != "aisr-app":
            return JSONResponse(content={"error": "invalid client_id"}, status_code=400)
        response = JSONResponse(content={"message": "Logout successful"})
        response.delete_cookie(key="KEYCLOAK_IDENTITY", httponly=True, secure=True)
        return response

    @app.post("/signing/puturl")
    async def signing_puturl(request: Request):
        _require_bearer(request)
        try:
            data = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON") from exc
        if not {"filePath", "contentType", "schoolId"}.issubset(data):
            raise HTTPException(status_code=400, detail="Missing required fields")
        status = app.state.faults.puturl_status.get(str(data["schoolId"]))
        if status:
            return JSONResponse(content={"error": "injected"}, status_code=status)
        return JSONResponse(content={"url": f"{base_url}/test-s3-put-location"})

    @app.put("/test-s3-put-location")
    async def put_file(request: Request):
        """The S3 upload. In production this is what triggers the MIIC
        email to every nurse, so tests count these."""
        if not await request.body():
            raise HTTPException(status_code=400, detail="Empty request body")
        header_keys = {key.lower() for key in request.headers}
        missing = REQUIRED_UPLOAD_HEADERS - header_keys
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing headers: {missing}")
        school_id = request.headers["x-amz-meta-school_id"]
        status = app.state.faults.upload_status.get(school_id)
        if status:
            return Response(status_code=status)
        app.state.received_uploads.append(school_id)
        app.state.uploaded_at[school_id] = int(time.time() * 1000)
        return Response(status_code=200)

    @app.get("/school/query/{school_id}")
    async def list_results(school_id: str, request: Request):
        _require_bearer(request)
        status = app.state.faults.listing_status.get(school_id)
        if status:
            return JSONResponse(content={"error": "injected"}, status_code=status)
        if school_id in app.state.faults.no_results:
            return []
        url = f"{base_url}/test-s3-get-location/{school_id}"
        return [
            {
                "id": 16386,
                "schoolId": school_id,
                "uploadDateTime": (
                    PREVIOUS_UPLOAD_MS
                    if school_id in app.state.faults.stale_listing
                    else app.state.uploaded_at.get(school_id, PREVIOUS_UPLOAD_MS)
                ),
                "fileName": f"school_{school_id}.csv",
                "s3FileUrl": url,
                "fullVaccineFileUrl": url,
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
    async def get_file(school_id: str):
        if school_id in app.state.faults.malformed_results:
            # What a MIIC format change looks like from here.
            content = "student|shot|when\n1|2|3\n"
        else:
            content = get_sample_vaccination_data(school_id)
        return Response(content=content, media_type="text/csv")

    return app
