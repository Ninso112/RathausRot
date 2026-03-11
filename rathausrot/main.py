import argparse
import logging
import signal
import sys

logger = logging.getLogger(__name__)


def _signal_handler(signum, frame):
    print("\nShutting down RathausRot...")
    sys.exit(0)


def main():
    from rathausrot import __version__
    from rathausrot.utils import setup_logging
    from rathausrot.config_manager import ConfigManager

    parser = argparse.ArgumentParser(
        description="RathausRot – Kommunalpolitik-Bot für Matrix"
    )
    parser.add_argument("--setup", action="store_true", help="Setup-Wizard starten")
    parser.add_argument("--run-now", action="store_true", help="Pipeline sofort ausführen")
    parser.add_argument("--test", action="store_true", help="Testnachricht senden")
    parser.add_argument("--version", action="store_true", help="Version anzeigen")
    args = parser.parse_args()

    if args.version:
        print(f"RathausRot {__version__}")
        sys.exit(0)

    config_manager = ConfigManager()
    setup_logging(
        log_file=config_manager.get("bot", "log_file", default="rathausrot.log"),
        level=config_manager.get("bot", "log_level", default="INFO"),
    )

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    if args.setup:
        from rathausrot.setup_wizard import run_wizard
        run_wizard(config_manager)
        sys.exit(0)

    if not config_manager.is_configured():
        print("Bot ist nicht konfiguriert. Bitte zuerst 'python -m rathausrot --setup' ausführen.")
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
        logger.warning("Could not send startup message: %s", exc)

    scheduler = BotScheduler(config_manager)
    scheduler.start(run_now=args.run_now)
