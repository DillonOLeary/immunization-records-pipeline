# Mock AISR server

A fake AISR (MIIC's bulk-query interface) for tests and local development.
It mirrors the production contract the pipeline's adapter depends on,
including the awkward parts: the Keycloak login form carries flow
parameters that must be POSTed back verbatim, the token exchange checks
the redirect URI, and roster uploads must carry the S3 metadata headers.

It is the only fake AISR in the repo. The test suite runs it in-process
(`tests/conftest.py`, fixture `mock_aisr`), and it runs locally on its own:

```sh
uv run mock-server        # http://localhost:8080, log in as test_user / test_password
```

Set `MOCK_SERVER_URL` if the server is reachable at another address; it
appears in redirect and signed URLs, as production's host does.

## Sample data

`sample_data.py` is deterministic (no randomness, no clock), so tests can
assert exact diffs and file hashes. Schools: `2542` and `2543` (a few
students each), `2544` (80 records, enough to trip the pipeline's sanity
brake), and a default for any other id.

Every name, date of birth, and student id is invented and deliberately
distinctive. `CANARY_PHI` collects them all; tests scan logs, stdout, and
ledger events for every value, and any match means record content leaked.

## Faults

`create_mock_app(..., faults=MockFaults(...))`, or mutate
`app.state.faults` in a test, to make one school's signing, upload, or
listing return an HTTP status, or to make a school list no results. Every
successful roster upload is recorded in `app.state.received_uploads` (in
production, each one emails every nurse), which is how tests prove a
roster was or was not submitted.

## Endpoints

- `GET /mock-auth-server/auth/realms/idepc-aisr-realm/protocol/openid-connect/auth`: login form
- `POST /mock-auth-server/auth/realms/idepc-aisr-realm/login-actions/authenticate`: login
- `POST /mock-auth-server/auth/realms/idepc-aisr-realm/protocol/openid-connect/token`: token exchange
- `GET /mock-auth-server/auth/realms/idepc-aisr-realm/protocol/openid-connect/logout`: logout
- `POST /signing/puturl`: signed upload URL
- `PUT /test-s3-put-location`: roster upload
- `GET /school/query/{school_id}`: results listing
- `GET /test-s3-get-location/{school_id}`: results file
- `GET /health`
