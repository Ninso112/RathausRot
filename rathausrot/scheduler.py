import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import schedule
import time

from rathausrot.config_manager import ConfigManager
from rathausrot.scraper import RatsinfoScraper
from rathausrot.llm_client import OpenRouterClient
from rathausrot.formatter import MatrixFormatter
from rathausrot.matrix_bot import MatrixBot
from rathausrot.command_handler import CommandHandler

logger = logging.getLogger(__name__)

LAST_RUN_FILE = Path("last_run.txt")


class BotScheduler:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.config = config_manager.load()

    def run_pipeline(self) -> None:
        logger.info("Starting pipeline run")
        try:
            scraper = RatsinfoScraper(self.config)
            llm_client = OpenRouterClient(self.config)
            formatter = MatrixFormatter()
            bot = MatrixBot(self.config)

            items_with_results = []
            for item in scraper.fetch_new_items():
                logger.info("Analyzing item: %s", item.title)
                result = llm_client.analyze_item(item)
                items_with_results.append((item, result))
                scraper.tracker.mark_processed(item.id)

            if not items_with_results:
                logger.info("No new items found")
                self._update_last_run()
                bot.close()
                return

            now = datetime.now()
            kw = now.isocalendar()[1]
            year = now.year
            source_url = self.config.get("scraper", {}).get("ratsinfo_url", "")

            chunks = formatter.format_weekly_report(items_with_results, kw, year, source_url)
            bot.send_chunks(chunks)
            bot.close()

            self._update_last_run()
            logger.info("Pipeline completed: %d items processed", len(items_with_results))
        except Exception as exc:
            logger.error("Pipeline error: %s", exc, exc_info=True)

    def _update_last_run(self) -> None:
        LAST_RUN_FILE.write_text(datetime.now().isoformat())

    def _should_run_on_startup(self) -> bool:
        interval_hours = self.config.get("bot", {}).get("interval_hours", 168)
        if not LAST_RUN_FILE.exists():
            return True
        try:
            last_run_str = LAST_RUN_FILE.read_text().strip()
            last_run = datetime.fromisoformat(last_run_str)
            return datetime.now() - last_run > timedelta(hours=interval_hours)
        except Exception:
            return True

    def start(self, run_now: bool = False) -> None:
        logger.info("Scheduler starting")

        # Start the Matrix command listener in a background thread.
        # It runs its own asyncio loop and responds to !commands in the room.
        listener_bot = MatrixBot(self.config)
        command_handler = CommandHandler(self.config, self)
        listener_bot.start_command_listener(command_handler)

        if run_now or self._should_run_on_startup():
            logger.info("Running pipeline immediately")
            self.run_pipeline()

        schedule.every().monday.at("08:00").do(self.run_pipeline)
        logger.info("Scheduled: every Monday at 08:00")

        while True:
            schedule.run_pending()
            time.sleep(60)
