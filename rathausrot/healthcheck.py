import json
import logging
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health check endpoint."""

    scheduler_ref = None

    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return

        last_run = None
        last_run_file = Path("last_run.txt")
        if last_run_file.exists():
            try:
                last_run = last_run_file.read_text().strip()
            except Exception:
                pass

        scrape_running = False
        if self.scheduler_ref and hasattr(self.scheduler_ref, '_bot'):
            bot = self.scheduler_ref._bot
            if bot and hasattr(bot, '_command_handler'):
                ch = bot._command_handler
                if ch:
                    with ch._scrape_lock:
                        scrape_running = ch._scrape_running

        body = json.dumps({
            "status": "ok",
            "last_run": last_run,
            "scrape_running": scrape_running,
        })

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):
        # Suppress default stderr logging
        logger.debug("Healthcheck: %s", format % args)


def start_healthcheck(port: int, scheduler_ref=None) -> Optional[threading.Thread]:
    """Start the health check HTTP server in a daemon thread. Returns the thread or None."""
    if port <= 0:
        return None

    HealthCheckHandler.scheduler_ref = scheduler_ref

    def _run():
        try:
            server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
            logger.info("Health check server started on port %d", port)
            server.serve_forever()
        except Exception as exc:
            logger.error("Health check server error: %s", exc)

    thread = threading.Thread(target=_run, daemon=True, name="healthcheck")
    thread.start()
    return thread
