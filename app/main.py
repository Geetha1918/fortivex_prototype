"""Starlette application factory and static frontend mounting."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.api.routes import ServiceContainer, routes
from app.config import STATIC_DIR


async def index_page(request):  # type: ignore[no-untyped-def]
    return FileResponse(STATIC_DIR / "index.html")


def create_app(
    db_path: Optional[Path] = None,
    kb_path: Optional[Path] = None,
) -> Starlette:
    """Create and configure the Starlette ASGI application."""

    @asynccontextmanager
    async def lifespan(app: Starlette):
        app.state.services = ServiceContainer(db_path=db_path, kb_path=kb_path)
        yield

    all_routes = [
        Route("/", index_page, methods=["GET"]),
        *routes,
        Mount("/static", app=StaticFiles(directory=str(STATIC_DIR)), name="static"),
    ]

    app = Starlette(debug=False, routes=all_routes, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


app = create_app()
