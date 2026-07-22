# Container for the Cloud Run Job. Built and deployed only by CI.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# Lock resolution needs every workspace member's pyproject present.
COPY pyproject.toml uv.lock ./
COPY mock/pyproject.toml mock/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-project --no-install-workspace

COPY src/ src/
RUN uv sync --frozen --no-dev --no-install-workspace

ENTRYPOINT ["uv", "run", "--frozen", "--no-dev", "mn-immunization-job"]
