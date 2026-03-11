import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import schedule
import time

from rathausrot.config_manager import ConfigManager
from rathausrot.scraper import RatsinfoScraper, RunHistoryTracker, LLMCache
from rathausrot.llm_client import OpenRouterClient, LLMResult
from rathausrot.formatter import MatrixFormatter
from rathausrot.matrix_bot import MatrixBot
from rathausrot.command_handler import CommandHandler

logger = logging.getLogger(__name__)

LAST_RUN_FILE = Path("last_run.txt")


class BotScheduler:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.config = config_manager.load()
        self._bot: Optional[MatrixBot] = None
        self._history = RunHistoryTracker()
        self._llm_cache = LLMCache()
        self._last_report_chunks: List[str] = []

    def run_pipeline(self) -> None:
        logger.info("Starting pipeline run")
        item_count = 0
        try:
            scraper = RatsinfoScraper(self.config)
            llm_client = OpenRouterClient(self.config)
            formatter = MatrixFormatter()

            items_with_results = []
            for item in scraper.fetch_new_items():
                logger.info("Analyzing item: %s", item.title)
                cached = self._llm_cache.get(item.id)
                if cached is not None:
                    logger.info("LLM cache hit for item: %s", item.id)
                    result = LLMResult(**cached)
                else:
                    result = llm_client.analyze_item(item)
                    self._llm_cache.put(item.id, result)
                items_with_results.append((item, result))
                scraper.tracker.mark_processed(item.id)

            if not items_with_results:
                logger.info("No new items found")
                self._update_last_run()
                self._history.record_run(0, True)
                return

            item_count = len(items_with_results)
            now = datetime.now()
            kw = now.isocalendar()[1]
            year = now.year
            source_url = self.config.get("scraper", {}).get("ratsinfo_url", "")

            chunks = formatter.format_weekly_report(items_with_results, kw, year, source_url)
            self._last_report_chunks = chunks
            if self._bot is not None:
                self._bot.send_chunks(chunks)

            self._update_last_run()
            self._history.record_run(item_count, True)
            logger.info("Pipeline completed: %d items processed", item_count)
        except Exception as exc:
            logger.error("Pipeline error: %s", exc, exc_info=True)
            self._history.record_run(item_count, False, str(exc))
            if self._bot is not None:
                try:
                    self._bot.send_message(
                        f"<p>❌ <strong>Pipeline-Fehler</strong></p>"
                        f"<p><code>{exc}</code></p>"
                    )
                except Exception as send_exc:
                    logger.error("Could not send error message: %s", send_exc)

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

    def _setup_schedule(self) -> None:
        day = self.config.get("bot", {}).get("schedule_day", "monday")
        time_str = self.config.get("bot", {}).get("schedule_time", "08:00")
        try:
            getattr(schedule.every(), day).at(time_str).do(self.run_pipeline)
            logger.info("Scheduled: every %s at %s", day, time_str)
        except AttributeError:
            logger.warning("Invalid schedule_day '%s', falling back to monday", day)
            schedule.every().monday.at(time_str).do(self.run_pipeline)

    def get_next_run_time(self) -> Optional[datetime]:
        return schedule.next_run()

    def get_last_report_chunks(self) -> List[str]:
        return self._last_report_chunks

    def start(self, run_now: bool = False) -> None:
        logger.info("Scheduler starting")

        self._bot = MatrixBot(self.config)
        command_handler = CommandHandler(self.config, self, send_extra=self._bot.send_chunks)
        self._bot.start_command_listener(command_handler)

        if run_now or self._should_run_on_startup():
            logger.info("Running pipeline immediately")
            self.run_pipeline()

        self._setup_schedule()

        while True:
            schedule.run_pending()
            time.sleep(60)
