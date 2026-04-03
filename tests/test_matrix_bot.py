import asyncio
import threading
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from rathausrot.matrix_bot import MatrixBot


def make_config(**overrides):
    config = {
        "matrix": {
            "homeserver": "https://matrix.example.com",
            "username": "@bot:example.com",
            "access_token": "test-token",
            "room_id": "!room1:example.com",
            "room_ids": [],
        },
    }
    if overrides:
        for k, v in overrides.items():
            if isinstance(v, dict) and k in config:
                config[k].update(v)
            else:
                config[k] = v
    return config


# ------------------------------------------------------------------ #
# __init__
# ------------------------------------------------------------------ #

class TestMatrixBotInit:
    def test_single_room_id(self):
        bot = MatrixBot(make_config())
        assert bot.room_ids == ["!room1:example.com"]
        assert bot.homeserver == "https://matrix.example.com"
        assert bot.username == "@bot:example.com"

    def test_room_ids_list(self):
        config = make_config(matrix={
            "homeserver": "https://m.org", "username": "@b:m.org",
            "access_token": "tok", "room_id": "!old:m.org",
            "room_ids": ["!r1:m.org", "!r2:m.org"],
        })
        bot = MatrixBot(config)
        assert bot.room_ids == ["!r1:m.org", "!r2:m.org"]

    def test_no_rooms(self):
        config = make_config(matrix={
            "homeserver": "https://m.org", "username": "@b:m.org",
            "access_token": "tok", "room_id": "", "room_ids": [],
        })
        bot = MatrixBot(config)
        assert bot.room_ids == []

    def test_client_initially_none(self):
        bot = MatrixBot(make_config())
        assert bot._client is None


# ------------------------------------------------------------------ #
# send_chunks
# ------------------------------------------------------------------ #

class TestSendChunks:
    def test_send_chunks_calls_send_message(self):
        bot = MatrixBot(make_config())
        bot.send_message = MagicMock()
        chunks = ["<p>chunk1</p>", "<p>chunk2</p>", "<p>chunk3</p>"]
        with patch("time.sleep"):
            bot.send_chunks(chunks)
        assert bot.send_message.call_count == 3

    def test_send_chunks_empty(self):
        bot = MatrixBot(make_config())
        bot.send_message = MagicMock()
        bot.send_chunks([])
        bot.send_message.assert_not_called()

    def test_send_chunks_single(self):
        bot = MatrixBot(make_config())
        bot.send_message = MagicMock()
        bot.send_chunks(["<p>only</p>"])
        bot.send_message.assert_called_once_with("<p>only</p>")


# ------------------------------------------------------------------ #
# send_startup_message / send_shutdown_message
# ------------------------------------------------------------------ #

class TestStartupShutdown:
    def test_startup_message(self):
        bot = MatrixBot(make_config())
        bot.send_message = MagicMock()
        bot.send_startup_message()
        bot.send_message.assert_called_once()
        args = bot.send_message.call_args[0][0]
        assert "RathausRot ist aktiv" in args

    def test_shutdown_message(self):
        bot = MatrixBot(make_config())
        bot.send_message = MagicMock()
        bot.send_shutdown_message()
        bot.send_message.assert_called_once()
        args = bot.send_message.call_args[0][0]
        assert "gestoppt" in args


# ------------------------------------------------------------------ #
# close
# ------------------------------------------------------------------ #

class TestClose:
    def test_close_no_client(self):
        bot = MatrixBot(make_config())
        bot.close()  # Should not raise (no-op)

    def test_close_is_noop(self):
        bot = MatrixBot(make_config())
        mock_client = MagicMock()
        bot._client = mock_client
        bot.close()  # close() is a no-op since clients are per-call


# ------------------------------------------------------------------ #
# run_sync
# ------------------------------------------------------------------ #

class TestRunSync:
    def test_run_sync(self):
        bot = MatrixBot(make_config())

        async def coro():
            return 42

        result = bot.run_sync(coro())
        assert result == 42


# ------------------------------------------------------------------ #
# _new_client
# ------------------------------------------------------------------ #

class TestNewClient:
    def test_creates_new_client(self):
        bot = MatrixBot(make_config())
        mock_nio = MagicMock()
        mock_client = MagicMock()
        mock_nio.AsyncClient.return_value = mock_client

        with patch.dict("sys.modules", {"nio": mock_nio}):
            client = bot._new_client()

        assert client is mock_client
        mock_nio.AsyncClient.assert_called_once()


# ------------------------------------------------------------------ #
# send_message
# ------------------------------------------------------------------ #

class TestLoginWithPassword:
    def test_login_success(self):
        mock_nio = MagicMock()
        mock_client = MagicMock()
        login_resp = MagicMock()
        login_resp.access_token = "new-token-123"

        async def mock_login(password):
            return login_resp

        async def mock_close():
            pass

        mock_client.login = mock_login
        mock_client.close = mock_close
        mock_nio.AsyncClient.return_value = mock_client
        mock_nio.LoginResponse = type(login_resp)

        with patch.dict("sys.modules", {"nio": mock_nio}):
            token = MatrixBot.login_with_password(
                "https://matrix.example.com", "@user:example.com", "secret"
            )
        assert token == "new-token-123"

    def test_login_failure(self):
        mock_nio = MagicMock()
        mock_client = MagicMock()

        class FakeLoginResp:
            pass

        fail_resp = MagicMock()  # not a LoginResponse

        async def mock_login(password):
            return fail_resp

        async def mock_close():
            pass

        mock_client.login = mock_login
        mock_client.close = mock_close
        mock_nio.AsyncClient.return_value = mock_client
        mock_nio.LoginResponse = FakeLoginResp

        with patch.dict("sys.modules", {"nio": mock_nio}):
            with pytest.raises(RuntimeError, match="Login failed"):
                MatrixBot.login_with_password(
                    "https://matrix.example.com", "@user:example.com", "wrong"
                )


class TestSendMessage:
    def test_send_message_to_rooms(self):
        bot = MatrixBot(make_config())

        mock_nio = MagicMock()
        mock_client = MagicMock()

        mock_client.room_send = AsyncMock(return_value=MagicMock())
        mock_client.close = AsyncMock()
        mock_nio.AsyncClient.return_value = mock_client
        mock_nio.RoomSendError = type("RoomSendError", (), {})

        with patch.dict("sys.modules", {"nio": mock_nio}):
            bot.send_message("<p>Hello</p>")

        mock_client.room_send.assert_called_once()

    def test_send_message_logs_error_on_room_send_error(self):
        bot = MatrixBot(make_config())

        mock_nio = MagicMock()
        mock_client = MagicMock()

        class FakeRoomSendError:
            pass

        error_resp = FakeRoomSendError()
        mock_client.room_send = AsyncMock(return_value=error_resp)
        mock_client.close = AsyncMock()
        mock_nio.AsyncClient.return_value = mock_client
        mock_nio.RoomSendError = FakeRoomSendError

        with patch.dict("sys.modules", {"nio": mock_nio}):
            bot.send_message("<p>Hello</p>")

        mock_client.room_send.assert_called_once()

    def test_send_message_no_rooms(self):
        config = make_config(matrix={
            "homeserver": "https://m.org", "username": "@b:m.org",
            "access_token": "tok", "room_id": "", "room_ids": [],
        })
        bot = MatrixBot(config)
        mock_nio = MagicMock()
        mock_client = MagicMock()
        mock_client.room_send = AsyncMock()
        mock_client.close = AsyncMock()
        mock_nio.AsyncClient.return_value = mock_client

        with patch.dict("sys.modules", {"nio": mock_nio}):
            bot.send_message("<p>Hello</p>")
        mock_client.room_send.assert_not_called()


# ------------------------------------------------------------------ #
# start_command_listener
# ------------------------------------------------------------------ #

class TestStartCommandListener:
    def test_starts_daemon_thread(self):
        bot = MatrixBot(make_config())
        handler = MagicMock()

        mock_nio = MagicMock()
        mock_client = MagicMock()

        async def mock_sync(**kwargs):
            return MagicMock(next_batch="token123")

        async def mock_sync_forever(**kwargs):
            # Just return immediately to end the loop
            raise asyncio.CancelledError()

        mock_client.sync = mock_sync
        mock_client.sync_forever = mock_sync_forever
        mock_client.add_event_callback = MagicMock()
        mock_client.close = AsyncMock()
        mock_nio.AsyncClient.return_value = mock_client
        mock_nio.RoomMessageText = type("RoomMessageText", (), {})

        with patch.dict("sys.modules", {"nio": mock_nio}):
            thread = bot.start_command_listener(handler)

        assert thread.daemon is True
        thread.join(timeout=2)
