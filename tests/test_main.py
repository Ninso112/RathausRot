import sys
from unittest.mock import MagicMock, patch

import pytest


class TestMainVersion:
    def test_version_flag(self, capsys):
        with patch("sys.argv", ["rathausrot", "--version"]):
            with pytest.raises(SystemExit) as exc_info:
                from rathausrot.main import main
                main()
            assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "RathausRot" in captured.out


class TestMainNotConfigured:
    def test_exits_when_not_configured(self, capsys):
        with patch("sys.argv", ["rathausrot"]), \
             patch("rathausrot.config_manager.ConfigManager.is_configured", return_value=False), \
             patch("rathausrot.config_manager.ConfigManager.get", return_value="INFO"), \
             patch("rathausrot.utils.setup_logging"), \
             patch("signal.signal"):
            with pytest.raises(SystemExit) as exc_info:
                from rathausrot.main import main
                main()
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "nicht konfiguriert" in captured.out


class TestSignalHandler:
    def test_signal_handler_calls_stop(self):
        from rathausrot.main import _make_signal_handler
        cm = MagicMock()
        cm.load.return_value = {
            "matrix": {"homeserver": "", "username": "", "access_token": "",
                       "room_id": "", "room_ids": []},
        }
        handler = _make_signal_handler(cm)

        # Import and set the global scheduler ref
        import rathausrot.main as main_mod
        mock_scheduler = MagicMock()
        original = main_mod._scheduler_ref
        main_mod._scheduler_ref = mock_scheduler

        with patch("rathausrot.matrix_bot.MatrixBot") as MockBot:
            MockBot.return_value.send_shutdown_message = MagicMock()
            MockBot.return_value.close = MagicMock()
            with pytest.raises(SystemExit):
                handler(2, None)

        mock_scheduler.stop.assert_called_once()
        main_mod._scheduler_ref = original

    def test_signal_handler_handles_bot_error(self):
        from rathausrot.main import _make_signal_handler
        cm = MagicMock()
        cm.load.side_effect = Exception("config error")
        handler = _make_signal_handler(cm)

        import rathausrot.main as main_mod
        original = main_mod._scheduler_ref
        main_mod._scheduler_ref = None

        with pytest.raises(SystemExit):
            handler(2, None)
        main_mod._scheduler_ref = original


class TestMainSetup:
    def test_setup_flag(self):
        with patch("sys.argv", ["rathausrot", "--setup"]), \
             patch("rathausrot.config_manager.ConfigManager.get", return_value="INFO"), \
             patch("rathausrot.utils.setup_logging"), \
             patch("signal.signal"), \
             patch("rathausrot.setup_wizard.run_wizard") as mock_wizard:
            with pytest.raises(SystemExit) as exc_info:
                from rathausrot.main import main
                main()
            assert exc_info.value.code == 0
            mock_wizard.assert_called_once()


class TestMainTest:
    def test_test_flag(self, capsys):
        with patch("sys.argv", ["rathausrot", "--test"]), \
             patch("rathausrot.config_manager.ConfigManager.get", return_value="INFO"), \
             patch("rathausrot.config_manager.ConfigManager.is_configured", return_value=True), \
             patch("rathausrot.config_manager.ConfigManager.load", return_value={"matrix": {}}), \
             patch("rathausrot.utils.setup_logging"), \
             patch("signal.signal"), \
             patch("rathausrot.matrix_bot.MatrixBot") as MockBot:
            mock_bot = MagicMock()
            MockBot.return_value = mock_bot
            with pytest.raises(SystemExit) as exc_info:
                from rathausrot.main import main
                main()
            assert exc_info.value.code == 0
            mock_bot.send_message.assert_called_once()
            mock_bot.close.assert_called_once()


class TestMainRun:
    def test_run_starts_scheduler(self):
        with patch("sys.argv", ["rathausrot"]), \
             patch("rathausrot.config_manager.ConfigManager.get", return_value="INFO"), \
             patch("rathausrot.config_manager.ConfigManager.is_configured", return_value=True), \
             patch("rathausrot.config_manager.ConfigManager.load", return_value={"matrix": {}}), \
             patch("rathausrot.utils.setup_logging"), \
             patch("signal.signal"), \
             patch("rathausrot.matrix_bot.MatrixBot") as MockBot, \
             patch("rathausrot.scheduler.BotScheduler") as MockSched:
            mock_bot = MagicMock()
            MockBot.return_value = mock_bot
            mock_sched = MagicMock()
            MockSched.return_value = mock_sched

            from rathausrot.main import main
            main()

            mock_bot.send_startup_message.assert_called_once()
            mock_bot.close.assert_called_once()
            mock_sched.start.assert_called_once_with(run_now=False)

    def test_run_handles_startup_message_error(self):
        with patch("sys.argv", ["rathausrot"]), \
             patch("rathausrot.config_manager.ConfigManager.get", return_value="INFO"), \
             patch("rathausrot.config_manager.ConfigManager.is_configured", return_value=True), \
             patch("rathausrot.config_manager.ConfigManager.load", return_value={"matrix": {}}), \
             patch("rathausrot.utils.setup_logging"), \
             patch("signal.signal"), \
             patch("rathausrot.matrix_bot.MatrixBot") as MockBot, \
             patch("rathausrot.scheduler.BotScheduler") as MockSched:
            MockBot.side_effect = Exception("connection failed")
            mock_sched = MagicMock()
            MockSched.return_value = mock_sched

            from rathausrot.main import main
            main()

            mock_sched.start.assert_called_once()

    def test_run_now_flag(self):
        with patch("sys.argv", ["rathausrot", "--run-now"]), \
             patch("rathausrot.config_manager.ConfigManager.get", return_value="INFO"), \
             patch("rathausrot.config_manager.ConfigManager.is_configured", return_value=True), \
             patch("rathausrot.config_manager.ConfigManager.load", return_value={"matrix": {}}), \
             patch("rathausrot.utils.setup_logging"), \
             patch("signal.signal"), \
             patch("rathausrot.matrix_bot.MatrixBot") as MockBot, \
             patch("rathausrot.scheduler.BotScheduler") as MockSched:
            MockBot.return_value = MagicMock()
            mock_sched = MagicMock()
            MockSched.return_value = mock_sched

            from rathausrot.main import main
            main()

            mock_sched.start.assert_called_once_with(run_now=True)
