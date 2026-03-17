from __future__ import annotations

from fastapi import FastAPI

from viewer.api.schemas import HealthResponse


def create_app() -> FastAPI:
    app = FastAPI(title="Articraft Viewer API")

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
