import json
import logging
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health check endpoint."""

    scheduler_ref = None
    _start_time: float = time.time()

    def do_GET(self):
        if self.path == "/calendar.ics":
            self._serve_calendar()
            return
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
        if self.scheduler_ref and hasattr(self.scheduler_ref, "_bot"):
            bot = self.scheduler_ref._bot
            if bot and hasattr(bot, "_command_handler_ref"):
                ch = bot._command_handler_ref
                if ch:
                    with ch._scrape_lock:
                        scrape_running = ch._scrape_running

        # version
        try:
            from rathausrot import __version__

            version = __version__
        except Exception:
            version = "unknown"

        # uptime
        uptime_seconds = int(time.time() - self.__class__._start_time)

        # next_run
        next_run = None
        if self.scheduler_ref and hasattr(self.scheduler_ref, "get_next_run_time"):
            nr = self.scheduler_ref.get_next_run_time()
            if nr is not None:
                next_run = nr.isoformat()

        # last_run_error
        last_run_error = None
        if self.scheduler_ref and hasattr(self.scheduler_ref, "_history"):
            recent = self.scheduler_ref._history.get_recent(1)
            if recent and not recent[0]["success"]:
                last_run_error = recent[0]["error_msg"] or None

        body = json.dumps(
            {
                "status": "ok",
                "version": version,
                "uptime_seconds": uptime_seconds,
                "last_run": last_run,
                "next_run": next_run,
                "scrape_running": scrape_running,
                "last_run_error": last_run_error,
            }
        )

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _serve_calendar(self):
        try:
            from rathausrot.scraper import CouncilItemStore
            from rathausrot.calendar_generator import generate_ics

            items = CouncilItemStore().get_all_as_items(limit=500)
            ics_data = generate_ics(items)
            self.send_response(200)
            self.send_header("Content-Type", "text/calendar; charset=utf-8")
            self.send_header(
                "Content-Disposition", 'attachment; filename="rathausrot.ics"'
            )
            self.end_headers()
            self.wfile.write(ics_data)
        except Exception as exc:
            logger.error("Calendar endpoint error: %s", exc)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8"))

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
