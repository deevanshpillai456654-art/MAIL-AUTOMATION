import logging
import os

import uvicorn


def select_port(config_module, port_manager, discovery, logger: logging.Logger | None = None) -> int:
    app_logger = logger or logging.getLogger(__name__)
    try:
        if "API_PORT" not in os.environ:
            port = port_manager.find_available_port()
            if port:
                config_module.API_PORT = port
        discovery.write_discovery(config_module.API_PORT, config_module.API_HOST)
    except Exception as e:
        app_logger.warning("Port selection issue: %s", e)
    return config_module.API_PORT


def run_service(config_module, logger: logging.Logger | None = None) -> None:
    from backend.utils.port_manager import discovery, port_manager

    select_port(config_module, port_manager, discovery, logger=logger)
    uvicorn.run(
        "backend.main:app",
        host=config_module.API_HOST,
        port=config_module.API_PORT,
        reload=False,
        log_level=config_module.LOG_LEVEL.lower(),
        workers=1,
        timeout_keep_alive=5,
        backlog=128,
        access_log=False,
    )


__all__ = ["run_service", "select_port"]
