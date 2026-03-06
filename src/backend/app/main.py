"""应用入口：组装配置、日志与网关运行时。"""

from fastapi import FastAPI

from app.core.config import load_settings
from app.core.logging import configure_logging
from app.gateway.api import build_api_router
from app.gateway.runtime import GatewayRuntime


def create_app() -> FastAPI:
    # 统一加载环境配置（支持 .env 和 doc/key.txt 兜底读取）。
    settings = load_settings()
    configure_logging(settings.environment)

    app = FastAPI(title=settings.app_name, version="0.1.0")
    # 将网关运行时挂到 app.state，供 API 路由统一访问。
    app.state.runtime = GatewayRuntime.from_settings(settings)
    app.include_router(build_api_router())
    return app


app = create_app()
