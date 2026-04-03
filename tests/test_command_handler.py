import time
from datetime import datetime
from unittest.mock import MagicMock, patch


from rathausrot.command_handler import CommandHandler, _format_duration


def make_handler(**config_overrides):
    config = {
        "matrix": {"username": "@bot:example.com"},
        "bot": {
            "allowed_users": [],
            "schedule_day": "monday",
            "schedule_time": "08:00",
            "party": "SPD",
        },
        "scraper": {"ratsinfo_url": "http://example.com"},
    }
    config.update(config_overrides)
    scheduler = MagicMock()
    history_mock = MagicMock()
    history_mock.get_recent.return_value = []
    scheduler.history = history_mock
    scheduler.get_next_run_time.return_value = None
    scheduler.get_last_report_chunks.return_value = []
    scheduler.get_pipeline_progress.return_value = {"running": False}
    return CommandHandler(config, scheduler)


# ------------------------------------------------------------------ #
# Authorization
# ------------------------------------------------------------------ #


class TestAuthorization:
    def test_empty_allowed_users_allows_everyone(self):
        handler = make_handler()
        assert handler.is_allowed("@anyone:example.com") is True

    def test_restricted_users(self):
        handler = make_handler(
            bot={
                "allowed_users": ["@admin:example.com"],
                "schedule_day": "monday",
                "schedule_time": "08:00",
                "party": "SPD",
            }
        )
        assert handler.is_allowed("@admin:example.com") is True
        assert handler.is_allowed("@other:example.com") is False

    def test_unauthorized_command_returns_error(self):
        handler = make_handler(
            bot={
                "allowed_users": ["@admin:example.com"],
                "schedule_day": "monday",
                "schedule_time": "08:00",
                "party": "SPD",
            }
        )
        result = handler.handle("@other:example.com", "!hilfe")
        assert result is not None
        assert "Keine Berechtigung" in result


# ------------------------------------------------------------------ #
# XSS Escaping
# ------------------------------------------------------------------ #


class TestXSSEscaping:
    def test_sender_name_escaped(self):
        handler = make_handler(
            bot={
                "allowed_users": ["@legit:example.com"],
                "schedule_day": "monday",
                "schedule_time": "08:00",
                "party": "SPD",
            }
        )
        result = handler.handle("<script>alert(1)</script>", "!hilfe")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_error_message_escaped(self):
        handler = make_handler()
        handler._commands["!hilfe"] = MagicMock(
            side_effect=ValueError("<script>xss</script>")
        )
        result = handler.handle("@user:example.com", "!hilfe")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_verlauf_error_msg_escaped(self):
        handler = make_handler()
        handler.scheduler_ref.history.get_recent.return_value = [
            {
                "ran_at": "2024-01-15 10:00",
                "item_count": 1,
                "success": False,
                "error_msg": "<img src=x onerror=alert(1)>",
            }
        ]
        result = handler.handle("@user:example.com", "!verlauf")
        assert "<img" not in result
        assert "&lt;img" in result


# ------------------------------------------------------------------ #
# Basic Commands
# ------------------------------------------------------------------ #


class TestBasicCommands:
    def test_help_command(self):
        handler = make_handler()
        result = handler.handle("@user:example.com", "!hilfe")
        assert "Verfügbare Befehle" in result

    def test_help_alias(self):
        handler = make_handler()
        result = handler.handle("@user:example.com", "!help")
        assert "Verfügbare Befehle" in result

    def test_non_command_returns_none(self):
        handler = make_handler()
        assert handler.handle("@user:example.com", "hello world") is None

    def test_unknown_command_returns_none(self):
        handler = make_handler()
        assert handler.handle("@user:example.com", "!unknown") is None

    def test_bot_ignores_own_messages(self):
        handler = make_handler()
        assert handler.handle("@bot:example.com", "!hilfe") is None

    def test_version_command(self):
        handler = make_handler()
        result = handler.handle("@user:example.com", "!version")
        assert "RathausRot" in result
        assert "v" in result

    def test_command_with_extra_whitespace(self):
        handler = make_handler()
        result = handler.handle("@user:example.com", "  !hilfe  ")
        assert "Verfügbare Befehle" in result


# ------------------------------------------------------------------ #
# Status Command
# ------------------------------------------------------------------ #


class TestStatusCommand:
    def test_status_no_last_run(self, tmp_path):
        handler = make_handler()
        fake_file = tmp_path / "last_run.txt"
        with patch("rathausrot.command_handler.CommandHandler._cmd_status") as mock:
            # Call directly to avoid import path issues
            pass
        # Call _cmd_status directly with patched LAST_RUN_FILE
        with patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            result = handler._cmd_status("@user:example.com", "!status")
        assert "Noch nie" in result
        assert "RathausRot Status" in result

    def test_status_with_last_run(self, tmp_path):
        handler = make_handler()
        fake_file = tmp_path / "last_run.txt"
        fake_file.write_text("2024-06-15T10:30:00")
        with patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            result = handler._cmd_status("@user:example.com", "!status")
        assert "15.06.2024 10:30 Uhr" in result

    def test_status_corrupt_last_run(self, tmp_path):
        handler = make_handler()
        fake_file = tmp_path / "last_run.txt"
        fake_file.write_text("not-a-date")
        with patch("rathausrot.scheduler.LAST_RUN_FILE", fake_file):
            result = handler._cmd_status("@user:example.com", "!status")
        assert "Unbekannt" in result

    def test_status_shows_party(self):
        handler = make_handler()
        with patch(
            "rathausrot.scheduler.LAST_RUN_FILE",
            MagicMock(exists=MagicMock(return_value=False)),
        ):
            result = handler._cmd_status("@user:example.com", "!status")
        assert "SPD" in result

    def test_status_scrape_running(self):
        handler = make_handler()
        handler._scrape_running = True
        with patch(
            "rathausrot.scheduler.LAST_RUN_FILE",
            MagicMock(exists=MagicMock(return_value=False)),
        ):
            result = handler._cmd_status("@user:example.com", "!status")
        assert "Scrape läuft" in result


# ------------------------------------------------------------------ #
# Verlauf Command
# ------------------------------------------------------------------ #


class TestVerlaufCommand:
    def test_verlauf_empty(self):
        handler = make_handler()
        result = handler.handle("@user:example.com", "!verlauf")
        assert "Noch keine Läufe" in result

    def test_verlauf_with_entries(self):
        handler = make_handler()
        handler.scheduler_ref.history.get_recent.return_value = [
            {
                "ran_at": "2024-01-15T10:00:00",
                "item_count": 5,
                "success": True,
                "error_msg": "",
            },
            {
                "ran_at": "2024-01-14T09:00:00",
                "item_count": 0,
                "success": False,
                "error_msg": "timeout",
            },
        ]
        result = handler.handle("@user:example.com", "!verlauf")
        assert "Letzte Läufe" in result
        assert "5 Items" in result
        assert "timeout" in result
        assert "✅" in result
        assert "❌" in result

    def test_verlauf_unparseable_date(self):
        handler = make_handler()
        handler.scheduler_ref.history.get_recent.return_value = [
            {"ran_at": "bad-date", "item_count": 1, "success": True, "error_msg": ""},
        ]
        result = handler.handle("@user:example.com", "!verlauf")
        assert "bad-date" in result  # Falls through unparsed


# ------------------------------------------------------------------ #
# Nächste Command
# ------------------------------------------------------------------ #


class TestNaechsteCommand:
    def test_naechste_no_scheduled(self):
        handler = make_handler()
        result = handler.handle("@user:example.com", "!nächste")
        assert "Kein Lauf geplant" in result

    def test_naechste_with_scheduled(self):
        handler = make_handler()
        handler.scheduler_ref.get_next_run_time.return_value = datetime(
            2024, 6, 17, 8, 0
        )
        result = handler.handle("@user:example.com", "!nächste")
        assert "17.06.2024 08:00 Uhr" in result

    def test_nachste_alias(self):
        handler = make_handler()
        result = handler.handle("@user:example.com", "!nachste")
        assert "Kein Lauf geplant" in result or "Nächster Lauf" in result


# ------------------------------------------------------------------ #
# Kalender Command
# ------------------------------------------------------------------ #


class TestKalenderCommand:
    def test_kalender_no_items(self):
        handler = make_handler()
        with patch("rathausrot.scraper.CouncilItemStore") as MockStore:
            MockStore.return_value.get_all_as_items.return_value = []
            result = handler.handle("@user:example.com", "!kalender")
        assert "Keine Termine" in result


# ------------------------------------------------------------------ #
# Stat Command
# ------------------------------------------------------------------ #


class TestStatCommand:
    def test_stat_returns_system_info(self):
        handler = make_handler()
        result = handler.handle("@user:example.com", "!stat")
        assert "Systemstatus" in result
        assert "CPU" in result
        assert "RAM" in result
        assert "Disk" in result
        assert "Bot-Uptime" in result


# ------------------------------------------------------------------ #
# Statistik Command
# ------------------------------------------------------------------ #


class TestStatistikCommand:
    def test_statistik_no_data(self):
        handler = make_handler()
        result = handler.handle("@user:example.com", "!statistik")
        assert "Statistiken" in result or "keine" in result.lower()

    def test_statistik_with_data(self):
        handler = make_handler()
        handler.scheduler_ref.history.get_recent.return_value = [
            {"ran_at": "2024-01-15", "item_count": 5, "success": True, "error_msg": ""},
            {
                "ran_at": "2024-01-14",
                "item_count": 3,
                "success": False,
                "error_msg": "err",
            },
        ]
        result = handler.handle("@user:example.com", "!statistik")
        assert "Statistiken" in result
        assert "50%" in result
        assert "8" in result  # 5 + 3 total items


# ------------------------------------------------------------------ #
# Log Command
# ------------------------------------------------------------------ #


class TestLogCommand:
    def test_log_no_handler(self):
        handler = make_handler()
        with patch("rathausrot.utils._memory_handler", None):
            result = handler.handle("@user:example.com", "!log")
        assert "nicht verfügbar" in result

    def test_log_with_entries(self):
        handler = make_handler()
        from rathausrot.utils import MemoryLogHandler

        mem_handler = MemoryLogHandler(max_entries=10)
        mem_handler._buffer.append("2024-01-01 [INFO] test: Hello")
        mem_handler._buffer.append("2024-01-01 [ERROR] test: Bad thing")
        with patch("rathausrot.utils._memory_handler", mem_handler):
            result = handler.handle("@user:example.com", "!log")
        assert "Hello" in result
        assert "Bad thing" in result
        assert "2 Einträge" in result

    def test_log_with_level_filter(self):
        handler = make_handler()
        from rathausrot.utils import MemoryLogHandler

        mem_handler = MemoryLogHandler(max_entries=10)
        mem_handler._buffer.append("2024-01-01 [INFO] test: info msg")
        mem_handler._buffer.append("2024-01-01 [ERROR] test: error msg")
        with patch("rathausrot.utils._memory_handler", mem_handler):
            result = handler.handle("@user:example.com", "!log error")
        assert "error msg" in result
        assert "info msg" not in result

    def test_log_with_count(self):
        handler = make_handler()
        from rathausrot.utils import MemoryLogHandler

        mem_handler = MemoryLogHandler(max_entries=100)
        for i in range(50):
            mem_handler._buffer.append(f"2024-01-01 [INFO] test: msg{i}")
        with patch("rathausrot.utils._memory_handler", mem_handler):
            result = handler.handle("@user:example.com", "!log 5")
        assert "5 Einträge" in result

    def test_log_empty(self):
        handler = make_handler()
        from rathausrot.utils import MemoryLogHandler

        mem_handler = MemoryLogHandler(max_entries=10)
        with patch("rathausrot.utils._memory_handler", mem_handler):
            result = handler.handle("@user:example.com", "!log")
        assert "Keine Log-Einträge" in result

    def test_log_escapes_html(self):
        handler = make_handler()
        from rathausrot.utils import MemoryLogHandler

        mem_handler = MemoryLogHandler(max_entries=10)
        mem_handler._buffer.append("2024-01-01 [INFO] test: <script>alert(1)</script>")
        with patch("rathausrot.utils._memory_handler", mem_handler):
            result = handler.handle("@user:example.com", "!log")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


# ------------------------------------------------------------------ #
# Config Command
# ------------------------------------------------------------------ #


class TestConfigCommand:
    def test_config_shows_settings(self):
        handler = make_handler()
        result = handler.handle("@user:example.com", "!config")
        assert "Konfiguration" in result
        assert "SPD" in result


# ------------------------------------------------------------------ #
# Scrape Race Condition
# ------------------------------------------------------------------ #


class TestScrapeRaceCondition:
    def test_concurrent_scrape_rejected(self):
        handler = make_handler()
        handler.scheduler_ref.run_pipeline = MagicMock(
            side_effect=lambda: time.sleep(0.5)
        )

        result1 = handler.handle("@user:example.com", "!scrape")
        assert "gestartet" in result1

        result2 = handler.handle("@user:example.com", "!scrape")
        assert "läuft bereits" in result2

    def test_scrape_resets_flag_on_completion(self):
        handler = make_handler()
        handler.scheduler_ref.run_pipeline = MagicMock()

        handler.handle("@user:example.com", "!scrape")
        time.sleep(0.1)
        # After completion, should be able to scrape again
        result = handler.handle("@user:example.com", "!scrape")
        assert "gestartet" in result

    def test_scrape_resets_flag_on_error(self):
        handler = make_handler()
        handler.scheduler_ref.run_pipeline = MagicMock(side_effect=RuntimeError("boom"))

        handler.handle("@user:example.com", "!scrape")
        time.sleep(0.1)
        result = handler.handle("@user:example.com", "!scrape")
        assert "gestartet" in result


# ------------------------------------------------------------------ #
# _format_duration
# ------------------------------------------------------------------ #


class TestFormatDuration:
    def test_zero_seconds(self):
        assert _format_duration(0) == "0s"

    def test_seconds_only(self):
        assert _format_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        assert _format_duration(125) == "2m 5s"

    def test_hours_minutes(self):
        assert _format_duration(3661) == "1h 1m 1s"

    def test_days(self):
        assert _format_duration(90061) == "1d 1h 1m 1s"

    def test_exact_hour(self):
        assert _format_duration(3600) == "1h"

    def test_exact_day(self):
        assert _format_duration(86400) == "1d"
