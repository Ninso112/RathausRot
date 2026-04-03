import argparse
import logging
import signal
import sys

import threading

logger = logging.getLogger(__name__)


class _Application:
    """Holds references to long-lived application components needed for shutdown."""

    def __init__(self):
        self.config_manager = None
        self.scheduler = None
        self._shutdown_lock = threading.Lock()
        self._shutting_down = False

    def shutdown(self, signum=None, frame=None):
        with self._shutdown_lock:
            if self._shutting_down:
                return
            self._shutting_down = True

        print("\nShutting down RathausRot...")
        if self.scheduler is not None:
            self.scheduler.stop()
        try:
            from rathausrot.matrix_bot import MatrixBot

            if self.config_manager is not None:
                config = self.config_manager.load()
                bot = MatrixBot(config)
                bot.send_shutdown_message()
                bot.close()
        except Exception as exc:
            print(f"Could not send shutdown message: {exc}")
        sys.exit(0)


_app = _Application()


def main():
    from rathausrot import __version__
    from rathausrot.utils import setup_logging
    from rathausrot.config_manager import ConfigManager

    parser = argparse.ArgumentParser(
        description="RathausRot – Kommunalpolitik-Bot für Matrix"
    )
    parser.add_argument("--setup", action="store_true", help="Setup-Wizard starten")
    parser.add_argument(
        "--run-now", action="store_true", help="Pipeline sofort ausführen"
    )
    parser.add_argument("--test", action="store_true", help="Testnachricht senden")
    parser.add_argument("--version", action="store_true", help="Version anzeigen")
    args = parser.parse_args()

    if args.version:
        print(f"RathausRot {__version__}")
        sys.exit(0)

    config_manager = ConfigManager()
    _app.config_manager = config_manager
    setup_logging(
        log_file=config_manager.get("bot", "log_file", default="rathausrot.log"),
        level=config_manager.get("bot", "log_level", default="INFO"),
    )

    signal.signal(signal.SIGTERM, _app.shutdown)
    signal.signal(signal.SIGINT, _app.shutdown)

    if args.setup:
        from rathausrot.setup_wizard import run_wizard

        run_wizard(config_manager)
        sys.exit(0)

    if not config_manager.is_configured():
        print(
            "Bot ist nicht konfiguriert. Bitte zuerst 'python -m rathausrot --setup' ausführen."
        )
        sys.exit(1)

    if args.test:
        from rathausrot.formatter import MatrixFormatter
        from rathausrot.matrix_bot import MatrixBot

        config = config_manager.load()
        formatter = MatrixFormatter()
        bot = MatrixBot(config)
        bot.send_message(formatter.format_test_message())
        bot.close()
        print("Testnachricht gesendet.")
        sys.exit(0)

    from rathausrot.scheduler import BotScheduler

    config = config_manager.load()
    bot = None
    try:
        from rathausrot.matrix_bot import MatrixBot

        bot = MatrixBot(config)
        bot.send_startup_message()
        bot.close()
    except Exception as exc:
        logging.warning("Could not send startup message: %s", exc)

    scheduler = BotScheduler(config_manager)
    _app.scheduler = scheduler
    scheduler.start(run_now=args.run_now)
