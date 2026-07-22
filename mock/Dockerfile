# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Copy pyproject.toml and uv.lock first for better caching
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --locked --no-install-project --no-dev

# Copy the rest of the project source code
COPY . /app

# Install the project
RUN uv sync --locked --no-dev

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Add the src directory to Python path so the module can be found
ENV PYTHONPATH="/app/src:$PYTHONPATH"

# Reset the entrypoint, don't invoke `uv`
ENTRYPOINT []

# Expose port 8080 for Cloud Run
EXPOSE 8080

# Run the FastAPI application
# Use uvicorn directly for production deployment
CMD ["uvicorn", "minnesota_immunization_mock.main:app", "--host", "0.0.0.0", "--port", "8080"]