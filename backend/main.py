import logging
from pathlib import Path

from fastapi import FastAPI

from backend import config
from backend.app.launcher import run_service
from backend.app.lifespan import create_lifespan
from backend.app.logging_config import configure_logging
from backend.app.middleware import register_app_middlewares
from backend.app.router_registry import register_api_routers
from backend.app.static_mounts import register_static_dashboard_routes
from backend.runtime_version import APP_VERSION, DISPLAY_VERSION

configure_logging(config.LOG_DIR, config.LOG_LEVEL)
logger = logging.getLogger(__name__)

project_root = Path(__file__).resolve().parent.parent
lifespan = create_lifespan(project_root=project_root, logger=logger)

app = FastAPI(
    title=DISPLAY_VERSION + " API",
    description="Enterprise client-ready AI email operations platform",
    version=APP_VERSION,
    lifespan=lifespan,
)

register_app_middlewares(app)
# Single authoritative mount under /api/v1; no legacy /api duplicate.
register_api_routers(app)
register_static_dashboard_routes(app, project_root=project_root)


def main():
    run_service(config, logger=logger)


if __name__ == "__main__":
    main()
