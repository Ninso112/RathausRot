import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from rathausrot.scheduler import BotScheduler


def make_scheduler(config_overrides=None):
    config = {
        "matrix": {"homeserver": "https://m.org", "username": "@bot:m.org",
                    "access_token": "tok", "room_id": "!r:m.org", "room_ids": []},
        "openrouter": {"api_key": "key", "model": "m", "max_tokens": 100, "system_prompt": ""},
        "scraper": {"ratsinfo_url": "http://rats.de", "max_pdf_pages": 5,
                   "request_timeout": 15, "keywords": []},
        "bot": {"interval_hours": 168, "schedule_day": "monday", "schedule_time": "08:00",
               "party": "Test", "log_level": "INFO", "log_file": "test.log",
               "allowed_users": [], "relevance_threshold": 1, "healthcheck_port": 0},
    }
    if config_overrides:
        for k, v in config_overrides.items():
            if isinstance(v, dict) and k in config:
                config[k].update(v)
            else:
                config[k] = v
    cm = MagicMock()
    cm.load.return_value = config
    with patch("rathausrot.scheduler.RunHistoryTracker"), \
         patch("rathausrot.scheduler.LLMCache"), \
         patch("rathausrot.scheduler.RetryQueue"):
        scheduler = BotScheduler(cm)
    return scheduler


# ------------------------------------------------------------------ #
# _should_run_on_startup
# ------------------------------------------------------------------ #

class TestShouldRunOnStartup:
    def test_no_last_run_file(self, tmp_path):
        scheduler = make_scheduler()
        fake_file = tmp_path / "last_run.txt"
        with patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            assert scheduler._should_run_on_startup() is True

    def test_recent_run(self, tmp_path):
        scheduler = make_scheduler()
        fake_file = tmp_path / "last_run.txt"
        fake_file.write_text(datetime.now().isoformat())
        with patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            assert scheduler._should_run_on_startup() is False

    def test_old_run(self, tmp_path):
        scheduler = make_scheduler()
        fake_file = tmp_path / "last_run.txt"
        old = (datetime.now() - timedelta(hours=200)).isoformat()
        fake_file.write_text(old)
        with patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            assert scheduler._should_run_on_startup() is True

    def test_corrupt_last_run_file(self, tmp_path):
        scheduler = make_scheduler()
        fake_file = tmp_path / "last_run.txt"
        fake_file.write_text("not-a-date")
        with patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            assert scheduler._should_run_on_startup() is True


# ------------------------------------------------------------------ #
# _setup_schedule
# ------------------------------------------------------------------ #

class TestSetupSchedule:
    def test_daily_schedule(self):
        scheduler = make_scheduler({"bot": {"schedule_day": "daily", "schedule_time": "09:00"}})
        import schedule as sched_lib
        sched_lib.clear()
        scheduler._setup_schedule()
        assert len(sched_lib.get_jobs()) == 1
        sched_lib.clear()

    def test_weekly_schedule(self):
        scheduler = make_scheduler({"bot": {"schedule_day": "wednesday", "schedule_time": "10:00"}})
        import schedule as sched_lib
        sched_lib.clear()
        scheduler._setup_schedule()
        assert len(sched_lib.get_jobs()) == 1
        sched_lib.clear()

    def test_invalid_day_falls_back_to_monday(self):
        scheduler = make_scheduler({"bot": {"schedule_day": "notaday", "schedule_time": "08:00"}})
        import schedule as sched_lib
        sched_lib.clear()
        scheduler._setup_schedule()
        assert len(sched_lib.get_jobs()) == 1
        sched_lib.clear()


# ------------------------------------------------------------------ #
# run_pipeline
# ------------------------------------------------------------------ #

class TestRunPipeline:
    def test_no_items_found(self, tmp_path):
        scheduler = make_scheduler()
        scheduler._bot = MagicMock()

        mock_scraper = MagicMock()
        mock_scraper.fetch_new_items.return_value = iter([])
        mock_scraper.tracker = MagicMock()

        scheduler._retry_queue.get_pending.return_value = []
        fake_file = tmp_path / "last_run.txt"
        with patch("rathausrot.scheduler.RatsinfoScraper", return_value=mock_scraper), \
             patch("rathausrot.scheduler.OpenRouterClient"), \
             patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            scheduler.run_pipeline()

        scheduler._history.record_run.assert_called_once_with(0, True)

    def test_items_processed_and_sent(self, tmp_path):
        scheduler = make_scheduler()
        scheduler._bot = MagicMock()

        from rathausrot.scraper import CouncilItem
        from rathausrot.llm_client import LLMResult

        item = CouncilItem(id="t1", title="Test", url="http://x", item_type="item",
                           date="2024-01-15", body_text="body", source_system="test")
        result = LLMResult(summary="Summary", verdict="Zustimmung", relevance_score=4)

        mock_scraper = MagicMock()
        mock_scraper.fetch_new_items.return_value = iter([item])
        mock_scraper.tracker = MagicMock()

        mock_llm = MagicMock()
        mock_llm.analyze_item.return_value = result

        scheduler._llm_cache.get.return_value = None
        scheduler._retry_queue.get_pending.return_value = []

        fake_file = tmp_path / "last_run.txt"
        with patch("rathausrot.scheduler.RatsinfoScraper", return_value=mock_scraper), \
             patch("rathausrot.scheduler.OpenRouterClient", return_value=mock_llm), \
             patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            scheduler.run_pipeline()

        scheduler._history.record_run.assert_called_once_with(1, True)
        scheduler._bot.send_chunks.assert_called_once()
        assert len(scheduler._last_report_chunks) > 0

    def test_relevance_threshold_filters_items(self, tmp_path):
        scheduler = make_scheduler({"bot": {"relevance_threshold": 4}})
        scheduler._bot = MagicMock()

        from rathausrot.scraper import CouncilItem
        from rathausrot.llm_client import LLMResult

        item = CouncilItem(id="t1", title="Test", url="http://x", item_type="item",
                           date="", body_text="body", source_system="test")
        low_result = LLMResult(summary="Low", relevance_score=2)

        mock_scraper = MagicMock()
        mock_scraper.fetch_new_items.return_value = iter([item])
        mock_scraper.tracker = MagicMock()

        mock_llm = MagicMock()
        mock_llm.analyze_item.return_value = low_result

        scheduler._llm_cache.get.return_value = None
        scheduler._retry_queue.get_pending.return_value = []

        fake_file = tmp_path / "last_run.txt"
        with patch("rathausrot.scheduler.RatsinfoScraper", return_value=mock_scraper), \
             patch("rathausrot.scheduler.OpenRouterClient", return_value=mock_llm), \
             patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            scheduler.run_pipeline()

        scheduler._history.record_run.assert_called_once_with(0, True)

    def test_llm_failure_adds_to_retry_queue(self, tmp_path):
        scheduler = make_scheduler()
        scheduler._bot = MagicMock()

        from rathausrot.scraper import CouncilItem

        item = CouncilItem(id="t1", title="Test", url="http://x", item_type="item",
                           date="", body_text="body", source_system="test")

        mock_scraper = MagicMock()
        mock_scraper.fetch_new_items.return_value = iter([item])
        mock_scraper.tracker = MagicMock()

        mock_llm = MagicMock()
        mock_llm.analyze_item.return_value = None  # LLM failure

        scheduler._llm_cache.get.return_value = None
        scheduler._retry_queue.get_pending.return_value = []

        fake_file = tmp_path / "last_run.txt"
        with patch("rathausrot.scheduler.RatsinfoScraper", return_value=mock_scraper), \
             patch("rathausrot.scheduler.OpenRouterClient", return_value=mock_llm), \
             patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            scheduler.run_pipeline()

        scheduler._retry_queue.add.assert_called_once_with(item)

    def test_cache_hit(self, tmp_path):
        scheduler = make_scheduler()
        scheduler._bot = MagicMock()

        from rathausrot.scraper import CouncilItem

        item = CouncilItem(id="t1", title="Test", url="http://x", item_type="item",
                           date="", body_text="body", source_system="test")

        mock_scraper = MagicMock()
        mock_scraper.fetch_new_items.return_value = iter([item])
        mock_scraper.tracker = MagicMock()

        mock_llm = MagicMock()

        scheduler._llm_cache.get.return_value = {
            "summary": "Cached", "key_points": [], "verdict": "Zustimmung",
            "verdict_reason": "good", "relevance_score": 3, "tokens_used": 0,
        }
        scheduler._retry_queue.get_pending.return_value = []

        fake_file = tmp_path / "last_run.txt"
        with patch("rathausrot.scheduler.RatsinfoScraper", return_value=mock_scraper), \
             patch("rathausrot.scheduler.OpenRouterClient", return_value=mock_llm), \
             patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            scheduler.run_pipeline()

        mock_llm.analyze_item.assert_not_called()
        scheduler._history.record_run.assert_called_once_with(1, True)

    def test_pipeline_error_sends_error_message(self, tmp_path):
        scheduler = make_scheduler()
        scheduler._bot = MagicMock()

        scheduler._retry_queue.get_pending.return_value = []

        fake_file = tmp_path / "last_run.txt"
        with patch("rathausrot.scheduler.RatsinfoScraper", side_effect=RuntimeError("boom")), \
             patch("rathausrot.scheduler.OpenRouterClient"), \
             patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            scheduler.run_pipeline()

        scheduler._history.record_run.assert_called_once_with(0, False, "boom")
        scheduler._bot.send_message.assert_called_once()
        assert "Pipeline-Fehler" in scheduler._bot.send_message.call_args[0][0]

    def test_pipeline_error_send_failure(self, tmp_path):
        scheduler = make_scheduler()
        scheduler._bot = MagicMock()
        scheduler._bot.send_message.side_effect = Exception("send failed")

        scheduler._retry_queue.get_pending.return_value = []

        fake_file = tmp_path / "last_run.txt"
        with patch("rathausrot.scheduler.RatsinfoScraper", side_effect=RuntimeError("boom")), \
             patch("rathausrot.scheduler.OpenRouterClient"), \
             patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            scheduler.run_pipeline()  # Should not raise

    def test_pipeline_no_bot(self, tmp_path):
        scheduler = make_scheduler()
        scheduler._bot = None

        mock_scraper = MagicMock()
        mock_scraper.fetch_new_items.return_value = iter([])
        mock_scraper.tracker = MagicMock()

        scheduler._retry_queue.get_pending.return_value = []

        fake_file = tmp_path / "last_run.txt"
        with patch("rathausrot.scheduler.RatsinfoScraper", return_value=mock_scraper), \
             patch("rathausrot.scheduler.OpenRouterClient"), \
             patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            scheduler.run_pipeline()  # Should not raise

    def test_retry_queue_processed(self, tmp_path):
        scheduler = make_scheduler()
        scheduler._bot = MagicMock()

        from rathausrot.scraper import CouncilItem
        from rathausrot.llm_client import LLMResult

        retry_item = CouncilItem(id="r1", title="Retry", url="http://x",
                                  item_type="item", date="", body_text="body", source_system="test")
        result = LLMResult(summary="Retried", relevance_score=3)

        mock_scraper = MagicMock()
        mock_scraper.fetch_new_items.return_value = iter([])
        mock_scraper.tracker = MagicMock()

        mock_llm = MagicMock()
        mock_llm.analyze_item.return_value = result

        scheduler._llm_cache.get.return_value = None
        scheduler._retry_queue.get_pending.return_value = [retry_item]

        fake_file = tmp_path / "last_run.txt"
        with patch("rathausrot.scheduler.RatsinfoScraper", return_value=mock_scraper), \
             patch("rathausrot.scheduler.OpenRouterClient", return_value=mock_llm), \
             patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            scheduler.run_pipeline()

        scheduler._retry_queue.remove.assert_called_once_with("r1")
        scheduler._history.record_run.assert_called_once_with(1, True)

    def test_retry_queue_failure_continues(self, tmp_path):
        scheduler = make_scheduler()
        scheduler._bot = MagicMock()

        from rathausrot.scraper import CouncilItem

        retry_item = CouncilItem(id="r1", title="Retry", url="http://x",
                                  item_type="item", date="", body_text="body", source_system="test")

        mock_scraper = MagicMock()
        mock_scraper.fetch_new_items.return_value = iter([])
        mock_scraper.tracker = MagicMock()

        mock_llm = MagicMock()
        mock_llm.analyze_item.return_value = None  # Retry also fails

        scheduler._retry_queue.get_pending.return_value = [retry_item]

        fake_file = tmp_path / "last_run.txt"
        with patch("rathausrot.scheduler.RatsinfoScraper", return_value=mock_scraper), \
             patch("rathausrot.scheduler.OpenRouterClient", return_value=mock_llm), \
             patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            scheduler.run_pipeline()

        scheduler._retry_queue.remove.assert_not_called()


# ------------------------------------------------------------------ #
# Utility methods
# ------------------------------------------------------------------ #

class TestUtilityMethods:
    def test_update_last_run(self, tmp_path):
        scheduler = make_scheduler()
        fake_file = tmp_path / "last_run.txt"
        with patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            scheduler._update_last_run()
        assert fake_file.exists()
        content = fake_file.read_text()
        # Should be a valid ISO datetime
        datetime.fromisoformat(content)

    def test_get_last_report_chunks(self):
        scheduler = make_scheduler()
        assert scheduler.get_last_report_chunks() == []
        scheduler._last_report_chunks = ["<p>test</p>"]
        assert scheduler.get_last_report_chunks() == ["<p>test</p>"]

    def test_get_next_run_time(self):
        scheduler = make_scheduler()
        import schedule as sched_lib
        sched_lib.clear()
        # No jobs scheduled
        result = scheduler.get_next_run_time()
        # May be None if no jobs
        sched_lib.clear()


# ------------------------------------------------------------------ #
# Stop event
# ------------------------------------------------------------------ #

class TestStopEvent:
    def test_stop_sets_event(self):
        scheduler = make_scheduler()
        assert not scheduler._stop_event.is_set()
        scheduler.stop()
        assert scheduler._stop_event.is_set()
