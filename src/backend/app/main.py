"""应用入口：组装配置、日志与网关运行时。"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import load_settings
from app.core.logging import configure_logging
from app.core.security import AUTH_EXEMPT_PATHS, authenticate_credentials, gateway_auth_enabled, validate_gateway_settings
from app.gateway.api import build_api_router
from app.gateway.runtime import GatewayRuntime


DEV_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


class GatewayAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        settings = request.app.state.settings
        if request.url.path in AUTH_EXEMPT_PATHS or not gateway_auth_enabled(settings):
            return await call_next(request)

        ok, reason = authenticate_credentials(
            settings=settings,
            headers=request.headers,
            query_params=request.query_params,
        )
        if not ok:
            return JSONResponse(status_code=401, content={"detail": reason or "unauthorized"})

        return await call_next(request)


def create_app() -> FastAPI:
    try:
        settings = load_settings()
        configure_logging(settings.environment)
        diagnostics = validate_gateway_settings(settings)
        if diagnostics["errors"]:
            raise RuntimeError("; ".join(diagnostics["errors"]))
    except Exception as exc:  # noqa: BLE001
        message = f"Gateway startup failed: {exc}"
        logging.getLogger(__name__).exception(message)
        raise RuntimeError(message) from exc

    if diagnostics["warnings"]:
        for warning in diagnostics["warnings"]:
            logging.getLogger(__name__).warning("Gateway config warning: %s", warning)

    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GatewayAuthMiddleware)
    app.state.runtime = GatewayRuntime.from_settings(settings)

    @app.on_event("startup")
    async def _startup() -> None:
        await app.state.runtime.automation_service.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await app.state.runtime.automation_service.stop()

    app.include_router(build_api_router())
    return app


app = create_app()
