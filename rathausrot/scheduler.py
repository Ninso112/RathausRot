import html
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import schedule
import time

from rathausrot.config_manager import ConfigManager
from rathausrot.scraper import RatsinfoScraper, RunHistoryTracker, LLMCache, RetryQueue, CouncilItemStore
from rathausrot.llm_client import OpenRouterClient, LLMResult
from rathausrot.formatter import MatrixFormatter
from rathausrot.matrix_bot import MatrixBot
from rathausrot.command_handler import CommandHandler
from rathausrot.healthcheck import start_healthcheck

logger = logging.getLogger(__name__)

LAST_RUN_FILE = Path("last_run.txt")


class BotScheduler:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.config = config_manager.load()
        self._bot: Optional[MatrixBot] = None
        self._history = RunHistoryTracker()
        self._llm_cache = LLMCache()
        self._retry_queue = RetryQueue()
        self._stop_event = threading.Event()
        self._item_store = CouncilItemStore()
        self._progress_lock = threading.Lock()
        self._pipeline_progress: dict = {"running": False}
        self._cancel_event = threading.Event()

    def run_pipeline(self, force: bool = False) -> None:
        logger.info("Starting pipeline run (force=%s)", force)
        item_count = 0
        self._cancel_event.clear()
        with self._progress_lock:
            self._pipeline_progress = {
                "running": True,
                "items_done": 0,
                "items_total": None,
                "current_item": "",
                "started_at": datetime.now(),
            }
        try:
            scraper = RatsinfoScraper(self.config)
            llm_client = OpenRouterClient(self.config)
            formatter = MatrixFormatter()

            relevance_threshold = self.config.get("bot", {}).get("relevance_threshold", 1)
            source_url = self.config.get("scraper", {}).get("ratsinfo_url", "")

            total = scraper.count_upcoming_items()
            with self._progress_lock:
                self._pipeline_progress["items_total"] = total

            # Process retry queue first
            for item in self._retry_queue.get_pending():
                logger.info("Retrying item from queue: %s", item.title)
                result = llm_client.analyze_item(item)
                if result is None:
                    logger.warning("Retry failed for item: %s", item.id)
                    continue
                self._retry_queue.remove(item.id)
                self._llm_cache.put(item.id, result)
                if result.relevance_score < relevance_threshold:
                    logger.debug("Retry item skipped by relevance threshold: %s", item.title)
                    scraper.tracker.mark_processed(item.id)
                    continue
                chunks = formatter.format_single_item_report(item, result, source_url)
                if self._bot is not None:
                    self._bot.send_chunks(chunks)
                item_count += 1
                scraper.tracker.mark_processed(item.id)

            for item in scraper.fetch_new_items(force=force):
                if self._cancel_event.is_set():
                    logger.info("Pipeline cancelled by user")
                    break
                self._item_store.store(item)
                with self._progress_lock:
                    self._pipeline_progress["current_item"] = item.title
                logger.info("Analyzing item: %s", item.title)
                cached = self._llm_cache.get(item.id)
                if cached is not None:
                    logger.info("LLM cache hit for item: %s", item.id)
                    try:
                        result = LLMResult(**cached)
                    except Exception as cache_exc:
                        logger.warning("Corrupt cache entry for %s, re-analyzing: %s", item.id, cache_exc)
                        cached = None
                        result = llm_client.analyze_item(item)
                        self._llm_cache.put(item.id, result)
                else:
                    result = llm_client.analyze_item(item)
                    self._llm_cache.put(item.id, result)
                if result is None:
                    logger.warning("LLM analysis failed, adding to retry queue: %s", item.id)
                    self._retry_queue.add(item)
                else:
                    if result.relevance_score < relevance_threshold:
                        logger.debug("Item skipped by relevance threshold (%d < %d): %s",
                                     result.relevance_score, relevance_threshold, item.title)
                    else:
                        chunks = formatter.format_single_item_report(item, result, source_url)
                        if self._bot is not None:
                            self._bot.send_chunks(chunks)
                        item_count += 1
                    scraper.tracker.mark_processed(item.id)
                with self._progress_lock:
                    self._pipeline_progress["items_done"] += 1

            if item_count == 0:
                logger.info("No new items found")

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
                        f"<p><code>{html.escape(str(exc))}</code></p>"
                    )
                except Exception as send_exc:
                    logger.error("Could not send error message: %s", send_exc)
        finally:
            with self._progress_lock:
                self._pipeline_progress["running"] = False
                self._pipeline_progress["current_item"] = ""

    def cancel_pipeline(self) -> None:
        self._cancel_event.set()

    def get_pipeline_progress(self) -> dict:
        with self._progress_lock:
            return dict(self._pipeline_progress)

    def _update_last_run(self) -> None:
        LAST_RUN_FILE.write_text(datetime.now().isoformat())

    def _should_run_on_startup(self) -> bool:
        interval_minutes = self.config.get("bot", {}).get("interval_minutes", 360)
        if not LAST_RUN_FILE.exists():
            return True
        try:
            last_run_str = LAST_RUN_FILE.read_text().strip()
            last_run = datetime.fromisoformat(last_run_str)
            return datetime.now() - last_run > timedelta(minutes=interval_minutes)
        except Exception:
            return True

    def _setup_schedule(self) -> None:
        interval_minutes = self.config.get("bot", {}).get("interval_minutes", 360)
        schedule.every(interval_minutes).minutes.do(self.run_pipeline)
        logger.info("Scheduled: every %d minutes", interval_minutes)

    def get_next_run_time(self) -> Optional[datetime]:
        return schedule.next_run()

    def start(self, run_now: bool = False) -> None:
        logger.info("Scheduler starting")

        healthcheck_port = self.config.get("bot", {}).get("healthcheck_port", 0)
        start_healthcheck(healthcheck_port, scheduler_ref=self)

        self._bot = MatrixBot(self.config)
        command_handler = CommandHandler(self.config, self, send_extra=self._bot.send_chunks)
        self._bot.start_command_listener(command_handler)

        if run_now or self._should_run_on_startup():
            logger.info("Running pipeline immediately")
            self.run_pipeline()

        self._setup_schedule()

        while not self._stop_event.is_set():
            schedule.run_pending()
            self._stop_event.wait(timeout=10)

    def stop(self) -> None:
        """Signal the scheduler loop to exit."""
        self._stop_event.set()
