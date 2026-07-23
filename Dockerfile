# Container for the Cloud Run Job. Built and deployed only by CI.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# Lock resolution needs every workspace member's pyproject present, and
# hatchling needs the README the project metadata declares.
COPY pyproject.toml uv.lock README.md ./
COPY mock/pyproject.toml mock/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-project --no-install-workspace

COPY src/ src/
RUN uv sync --frozen --no-dev

# Run the installed script directly: nothing resolves or builds at runtime.
ENTRYPOINT ["/app/.venv/bin/mn-immunization-job"]
