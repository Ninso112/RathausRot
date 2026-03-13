import asyncio
import logging
import threading
import time
from typing import List, Optional

import requests as _requests

from rathausrot.utils import strip_html

logger = logging.getLogger(__name__)


class MatrixBot:
    def __init__(self, config: dict):
        self.config = config
        matrix_cfg = config.get("matrix", {})
        self.homeserver = matrix_cfg.get("homeserver", "")
        self.username = matrix_cfg.get("username", "")
        self.access_token = matrix_cfg.get("access_token", "")
        self.room_id = matrix_cfg.get("room_id", "")
        room_ids_list = matrix_cfg.get("room_ids", [])
        if room_ids_list:
            self.room_ids = list(room_ids_list)
        elif self.room_id:
            self.room_ids = [self.room_id]
        else:
            self.room_ids = []
        self._room_ids_set = set(self.room_ids)
        self._client = None

    def _new_client(self):
        import nio
        client = nio.AsyncClient(self.homeserver, self.username)
        client.access_token = self.access_token
        client.user_id = self.username
        return client

    @staticmethod
    def login_with_password(homeserver: str, username: str, password: str) -> str:
        import nio

        async def _login():
            client = nio.AsyncClient(homeserver, username)
            resp = await client.login(password)
            await client.close()
            if isinstance(resp, nio.LoginResponse):
                return resp.access_token
            raise RuntimeError(f"Login failed: {resp}")

        return asyncio.run(_login())

    def send_message(self, html_content: str) -> None:
        plain = strip_html(html_content)

        async def _send_all():
            import nio
            client = self._new_client()
            try:
                content = {
                    "msgtype": "m.text",
                    "body": plain,
                    "format": "org.matrix.custom.html",
                    "formatted_body": html_content,
                }
                for room_id in self.room_ids:
                    resp = await client.room_send(
                        room_id=room_id,
                        message_type="m.room.message",
                        content=content,
                    )
                    if isinstance(resp, nio.RoomSendError):
                        logger.error("Failed to send message to %s: %s", room_id, resp)
                    else:
                        logger.info("Message sent to %s", room_id)
            finally:
                await client.close()

        asyncio.run(_send_all())

    def send_chunks(self, chunks: List[str]) -> None:
        for i, chunk in enumerate(chunks):
            logger.info("Sending chunk %d/%d", i + 1, len(chunks))
            self.send_message(chunk)
            if i < len(chunks) - 1:
                time.sleep(1)

    def send_startup_message(self) -> None:
        self.send_message(
            "<p><strong>🔴 RathausRot ist aktiv</strong></p>"
            "<p>Der Bot wurde gestartet und überwacht das Ratsinfo-System.</p>"
            "<p>Tippe <code>!hilfe</code> für verfügbare Befehle.</p>"
        )

    def send_shutdown_message(self) -> None:
        self.send_message(
            "<p><strong>🔴 RathausRot wird gestoppt</strong></p>"
            "<p>Der Bot wurde heruntergefahren.</p>"
        )

    def send_file(self, url: str, filename: str) -> None:
        """Download a file from *url* and upload it to all Matrix rooms as m.file."""
        try:
            resp = _requests.get(url, timeout=60)
            resp.raise_for_status()
            data = resp.content
        except Exception as exc:
            logger.warning("Could not download file %s: %s", url, exc)
            return

        async def _upload_and_send():
            import nio
            client = self._new_client()
            try:
                up_resp, _ = await client.upload(
                    data,
                    content_type="application/pdf",
                    filename=filename,
                    filesize=len(data),
                )
                if isinstance(up_resp, nio.UploadError):
                    logger.error("Matrix upload failed for %s: %s", filename, up_resp)
                    return
                mxc_url = up_resp.content_uri
                content = {
                    "msgtype": "m.file",
                    "body": filename,
                    "url": mxc_url,
                    "info": {"mimetype": "application/pdf", "size": len(data)},
                }
                for room_id in self.room_ids:
                    send_resp = await client.room_send(
                        room_id=room_id,
                        message_type="m.room.message",
                        content=content,
                    )
                    if isinstance(send_resp, nio.RoomSendError):
                        logger.error("Failed to send file to %s: %s", room_id, send_resp)
                    else:
                        logger.info("File %s sent to %s", filename, room_id)
            finally:
                await client.close()

        asyncio.run(_upload_and_send())

    def close(self) -> None:
        pass  # send_message now creates a fresh client per call; nothing to close

    def run_sync(self, coro):
        return asyncio.run(coro)

    # ------------------------------------------------------------------ #
    # Command listener – runs in a dedicated daemon thread
    # ------------------------------------------------------------------ #

    async def _listen_loop(self, command_handler) -> None:
        """Persistent async sync loop that dispatches incoming chat commands."""
        import nio

        # Use a dedicated client so the listener doesn't interfere with
        # fire-and-forget send_message() calls elsewhere.
        client = nio.AsyncClient(self.homeserver, self.username)
        client.access_token = self.access_token
        client.user_id = self.username

        import time as _time
        startup_ts_ms = int(_time.time() * 1000)

        try:
            # Initial sync BEFORE registering the callback so that timeline
            # events returned by this sync do not trigger command execution.
            logger.info("Command listener: performing initial sync...")
            init_resp = await client.sync(timeout=0, full_state=True)
            if isinstance(init_resp, nio.SyncError):
                logger.error("Initial sync failed, aborting listener: %s", init_resp)
                return
            client.next_batch = init_resp.next_batch

            async def _on_message(room, event):
                if not isinstance(event, nio.RoomMessageText):
                    return
                if room.room_id not in self._room_ids_set:
                    return
                # Ignore events that were sent before this bot instance started
                if event.server_timestamp < startup_ts_ms:
                    logger.debug("Ignoring pre-startup event from %s", event.sender)
                    return
                response_html = command_handler.handle(event.sender, event.body)
                if response_html is None:
                    return
                plain = strip_html(response_html)
                send_resp = await client.room_send(
                    room_id=room.room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.text",
                        "body": plain,
                        "format": "org.matrix.custom.html",
                        "formatted_body": response_html,
                    },
                )
                if isinstance(send_resp, nio.RoomSendError):
                    logger.error("Failed to send command response: %s", send_resp)

            client.add_event_callback(_on_message, nio.RoomMessageText)
            logger.info("Command listener ready – listening for commands")
            await client.sync_forever(timeout=30000, full_state=False)
        except asyncio.CancelledError:
            logger.info("Command listener cancelled")
        except Exception as exc:
            logger.error("Command listener error: %s", exc, exc_info=True)
        finally:
            await client.close()

    def start_command_listener(self, command_handler) -> threading.Thread:
        """Start the Matrix sync/command listener in a daemon background thread.

        The thread runs its own asyncio event loop so it doesn't interfere with
        the synchronous scheduler loop in the main thread.
        """

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._listen_loop(command_handler))
            except Exception as exc:
                logger.error("Command listener thread crashed: %s", exc)
            finally:
                loop.close()

        thread = threading.Thread(target=_run, daemon=True, name="matrix-listener")
        thread.start()
        logger.info("Command listener thread started")
        return thread
