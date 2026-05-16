"""Background worker – polls for pending executions and runs them."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

log = logging.getLogger(__name__)
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    log.info("Shutdown signal received")
    _shutdown = True


async def process_pending() -> None:
    """Pick up any pending/running executions and execute them."""
    from platform.ai_automation.backend.db import get_db, init_ai_automation_db
    from platform.ai_automation.engine.executor import WorkflowExecutor

    init_ai_automation_db()
    executor = WorkflowExecutor()
    conn = get_db()

    rows = conn.execute(
        "SELECT id, tenant_id FROM executions WHERE status IN ('pending','running') LIMIT 10"
    ).fetchall()

    for row in rows:
        exec_id = row["id"]
        tenant_id = row["tenant_id"]
        log.info("Processing execution %s", exec_id)
        try:
            await executor.resume_execution(exec_id, tenant_id)
        except Exception as exc:
            log.error("Execution %s failed: %s", exec_id, exc)


async def main_loop() -> None:
    poll_interval = int(os.environ.get("WORKER_POLL_INTERVAL", "5"))
    log.info("AI Automation Worker started (poll_interval=%ds)", poll_interval)

    while not _shutdown:
        try:
            await process_pending()
        except Exception as exc:
            log.error("Worker loop error: %s", exc)
        await asyncio.sleep(poll_interval)

    log.info("Worker stopped cleanly")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        pass
    sys.exit(0)
