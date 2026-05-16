from dataclasses import dataclass
from typing import Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from backend import config
from backend.api.middleware import setup_middlewares


@dataclass(frozen=True)
class CorsSettings:
    allow_origins: list[str]
    allow_origin_regex: str | None


def build_cors_settings(
    api_port: int,
    configured_origins: Sequence[str] | None = None,
    is_production: bool = False,
) -> CorsSettings:
    default_origins = [
        "http://127.0.0.1",
        "http://localhost",
        f"http://127.0.0.1:{api_port}",
        f"http://localhost:{api_port}",
    ]
    safe_configured = [
        origin
        for origin in (configured_origins or [])
        if origin and (not is_production or "*" not in origin)
    ]
    local_origin_regex = (
        r"^(chrome-extension://.*|ms-office-addin://.*"
        r"|http://127\.0\.0\.1:\d+|http://localhost:\d+)$"
    )
    return CorsSettings(
        allow_origins=safe_configured or default_origins,
        allow_origin_regex=None if is_production else local_origin_regex,
    )


def register_app_middlewares(app: FastAPI) -> None:
    cors = build_cors_settings(
        api_port=config.API_PORT,
        configured_origins=config.CORS_ALLOWED_ORIGINS or [],
        is_production=config.IS_PRODUCTION,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors.allow_origins,
        allow_origin_regex=cors.allow_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    setup_middlewares(app)


__all__ = ["CorsSettings", "build_cors_settings", "register_app_middlewares"]
