"""
FastAPI application entry point for the mock AISR server
"""

import uvicorn
from fastapi import FastAPI

from .server import create_mock_app


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    return create_mock_app()


def run():
    """Run the server locally"""
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8080)


# For Cloud Run
app = create_app()