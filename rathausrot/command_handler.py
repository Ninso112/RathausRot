import html
import logging
import os
import signal
import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "<p><strong>🔴 RathausRot – Verfügbare Befehle:</strong></p>"
    "<ul>"
    "<li><code>!scrape</code> – Manuellen Scrape jetzt starten</li>"
    "<li><code>!abbruch</code> – Laufenden Scrape abbrechen</li>"
    "<li><code>!suche &lt;Begriff&gt;</code> – Gespeicherte Vorlagen durchsuchen</li>"
    "<li><code>!kalender</code> – ICS-Kalender aller gespeicherten Termine herunterladen</li>"
    "<li><code>!status</code> – Bot-Status anzeigen</li>"
    "<li><code>!verlauf</code> – Letzte Scrape-Läufe anzeigen</li>"
    "<li><code>!nächste</code> – Nächsten geplanten Lauf anzeigen</li>"
    "<li><code>!statistik</code> – Scrape-Statistiken anzeigen</li>"
    "<li><code>!stat</code> – Systemauslastung (CPU, RAM, Disk, Uptime)</li>"
    "<li><code>!log [level] [anzahl]</code> – Bot-Logs anzeigen</li>"
    "<li><code>!config</code> – Aktuelle Konfiguration anzeigen</li>"
    "<li><code>!version</code> – Version anzeigen</li>"
    "<li><code>!stop</code> – Bot herunterfahren</li>"
    "<li><code>!hilfe</code> – Diese Hilfe anzeigen</li>"
    "</ul>"
)


class CommandHandler:
    def __init__(
        self,
        config: dict,
        scheduler_ref,
        send_extra: Optional[Callable[[List[str]], None]] = None,
        send_file_bytes: Optional[Callable] = None,
    ):
        self.config = config
        self.scheduler_ref = scheduler_ref
        self._send_extra = send_extra
        self._send_file_bytes = send_file_bytes
        self.bot_username = config.get("matrix", {}).get("username", "")
        self.allowed_users: list = config.get("bot", {}).get("allowed_users", [])
        self._scrape_lock = threading.Lock()
        self._scrape_running = False
        self._start_time = datetime.now()
        self._commands: Dict[str, Callable] = {
            "!hilfe": self._cmd_help,
            "!help": self._cmd_help,
            "!scrape": self._cmd_scrape,
            "!abbruch": self._cmd_abbruch,
            "!suche": self._cmd_suche,
            "!kalender": self._cmd_kalender,
            "!status": self._cmd_status,
            "!verlauf": self._cmd_verlauf,
            "!nächste": self._cmd_naechste,
            "!nachste": self._cmd_naechste,
            "!stat": self._cmd_stat,
            "!statistik": self._cmd_statistik,
            "!log": self._cmd_log,
            "!version": self._cmd_version,
            "!config": self._cmd_config,
            "!stop": self._cmd_stop,
        }

    def is_allowed(self, sender: str) -> bool:
        """Returns True if sender is authorized. No restriction when allowed_users is empty."""
        if not self.allowed_users:
            return True
        return sender in self.allowed_users

    def handle(self, sender: str, body: str) -> Optional[str]:
        """Parse and execute a command. Returns HTML response string or None."""
        # Never respond to own messages
        if sender == self.bot_username:
            return None
        body = body.strip()
        if not body.startswith("!"):
            return None
        cmd = body.split()[0].lower()
        if cmd not in self._commands:
            return None
        if not self.is_allowed(sender):
            logger.warning("Unauthorized command attempt from %s: %s", sender, cmd)
            return f"<p>⛔ Keine Berechtigung für <code>{html.escape(sender)}</code>.</p>"
        logger.info("Command '%s' from %s", cmd, sender)
        try:
            return self._commands[cmd](sender, body)
        except Exception as exc:
            logger.error("Error executing command '%s': %s", cmd, exc)
            return f"<p>❌ Fehler beim Ausführen von <code>{html.escape(cmd)}</code>: {html.escape(str(exc))}</p>"

    # ------------------------------------------------------------------ #
    # Command implementations
    # ------------------------------------------------------------------ #

    def _cmd_help(self, sender: str, body: str) -> str:
        return HELP_TEXT

    def _cmd_scrape(self, sender: str, body: str) -> str:
        with self._scrape_lock:
            if self._scrape_running:
                return "<p>⏳ Ein Scrape-Vorgang läuft bereits. Bitte warten.</p>"
            if self.scheduler_ref.get_pipeline_progress().get("running", False):
                return "<p>⏳ Der automatische Scrape läuft gerade. Bitte warten.</p>"
            self._scrape_running = True

            def run():
                try:
                    self.scheduler_ref.run_pipeline(force=True)
                finally:
                    with self._scrape_lock:
                        self._scrape_running = False

            thread = threading.Thread(target=run, daemon=True, name="manual-scrape")
            thread.start()
        return "<p>🔄 Manueller Scrape gestartet. Ergebnisse folgen in Kürze.</p>"

    def _cmd_suche(self, sender: str, body: str) -> str:
        parts = body.split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            return "<p>Verwendung: <code>!suche &lt;Suchbegriff&gt;</code></p>"
        query = parts[1].strip()
        from rathausrot.scraper import CouncilItemStore
        results = CouncilItemStore().search(query, limit=10)
        if not results:
            return f"<p>🔍 Keine Ergebnisse für <strong>{html.escape(query)}</strong>.</p>"
        items_html = ""
        for r in results:
            title = html.escape(r["title"])
            url = html.escape(r["url"], quote=True)
            date = html.escape(r["date"]) if r["date"] else "–"
            stored = r["stored_at"][:10] if r["stored_at"] else "–"
            items_html += (
                f'<li><a href="{url}">{title}</a>'
                f' <em>({date}, gespeichert: {stored})</em></li>'
            )
        return (
            f"<p>🔍 <strong>{html.escape(query)}</strong> – {len(results)} Treffer:</p>"
            f"<ul>{items_html}</ul>"
        )

    def _cmd_kalender(self, sender: str, body: str) -> str:
        from rathausrot.scraper import CouncilItemStore
        from rathausrot.calendar_generator import generate_ics
        items = CouncilItemStore().get_all_as_items(limit=500)
        if not items:
            return "<p>📅 Keine Termine gespeichert. Zuerst <code>!scrape</code> ausführen.</p>"
        try:
            ics_data = generate_ics(items)
        except ImportError as exc:
            return f"<p>❌ {html.escape(str(exc))}</p>"
        if self._send_file_bytes is not None:
            def _upload():
                self._send_file_bytes(ics_data, "rathausrot.ics", "text/calendar")
            thread = threading.Thread(target=_upload, daemon=True, name="kalender-upload")
            thread.start()
            return f"<p>📅 Kalender mit {len(items)} Terminen wird hochgeladen…</p>"
        return "<p>❌ Datei-Upload nicht verfügbar.</p>"

    def _cmd_abbruch(self, sender: str, body: str) -> str:
        with self._scrape_lock:
            running = self._scrape_running
        if not running:
            return "<p>ℹ️ Kein Scrape läuft gerade.</p>"
        self.scheduler_ref.cancel_pipeline()
        return "<p>🛑 Abbruch angefordert – das aktuelle Item wird noch fertig verarbeitet.</p>"

    def _cmd_status(self, sender: str, body: str) -> str:
        from rathausrot.scheduler import LAST_RUN_FILE

        last_run = "Noch nie"
        if LAST_RUN_FILE.exists():
            try:
                raw = LAST_RUN_FILE.read_text().strip()
                dt = datetime.fromisoformat(raw)
                last_run = dt.strftime("%d.%m.%Y %H:%M Uhr")
            except Exception:
                last_run = "Unbekannt"

        interval_minutes = self.config.get("bot", {}).get("interval_minutes", 360)
        party = self.config.get("bot", {}).get("party", "–")
        ratsinfo_url = self.config.get("scraper", {}).get("ratsinfo_url", "–")

        with self._scrape_lock:
            running = self._scrape_running

        if running:
            prog = self.scheduler_ref.get_pipeline_progress()
            done = prog.get("items_done", 0)
            total = prog.get("items_total")
            current = prog.get("current_item", "")
            started_at = prog.get("started_at")

            if total is not None and total > 0:
                pct = int(done / total * 100)
                bar_filled = round(pct / 10)
                bar = "█" * bar_filled + "░" * (10 - bar_filled)
                progress_line = f"{done}/{total} Items ({pct}%) [{bar}]"
                if done > 0 and started_at:
                    elapsed = (datetime.now() - started_at).total_seconds()
                    avg = elapsed / done
                    remaining_secs = (total - done) * avg
                    progress_line += f" – noch ca. {_format_duration(remaining_secs)}"
            else:
                progress_line = f"{done} Items analysiert"
                if done > 0 and started_at:
                    elapsed = (datetime.now() - started_at).total_seconds()
                    avg = elapsed / done
                    progress_line += f" (~{avg:.0f}s/Item)"

            scrape_status = f"⏳ Scrape läuft – {progress_line}"
            if current:
                scrape_status += f"<br>&nbsp;&nbsp;<em>Aktuell: {html.escape(current[:70])}</em>"
        else:
            scrape_status = "✅ Bereit"

        return (
            "<p><strong>🔴 RathausRot Status</strong></p>"
            "<ul>"
            f"<li><strong>Status:</strong> {scrape_status}</li>"
            f"<li><strong>Letzter Lauf:</strong> {last_run}</li>"
            f"<li><strong>Intervall:</strong> alle {interval_minutes} Minuten</li>"
            f"<li><strong>Partei:</strong> {party}</li>"
            f"<li><strong>Ratsinfo:</strong> {ratsinfo_url}</li>"
            "</ul>"
        )

    def _cmd_verlauf(self, sender: str, body: str) -> str:
        entries = self.scheduler_ref._history.get_recent(10)
        if not entries:
            return "<p>📋 Noch keine Läufe aufgezeichnet.</p>"

        items_html = ""
        for entry in entries:
            icon = "✅" if entry["success"] else "❌"
            ts = entry["ran_at"]
            try:
                dt = datetime.fromisoformat(ts)
                ts = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                pass
            count_str = f", {entry['item_count']} Items" if entry["item_count"] else ""
            error_str = f" – {html.escape(entry['error_msg'])}" if entry["error_msg"] else ""
            items_html += f"<li>{icon} {ts}{count_str}{error_str}</li>"

        return (
            "<p><strong>📋 Letzte Läufe:</strong></p>"
            f"<ul>{items_html}</ul>"
        )

    def _cmd_naechste(self, sender: str, body: str) -> str:
        next_run = self.scheduler_ref.get_next_run_time()
        if next_run is None:
            return "<p>⏰ Kein Lauf geplant.</p>"
        return f"<p>⏰ Nächster Lauf: <strong>{next_run.strftime('%d.%m.%Y %H:%M')} Uhr</strong></p>"

    def _cmd_stat(self, sender: str, body: str) -> str:
        try:
            import psutil
        except ImportError:
            return (
                "<p>❌ <code>psutil</code> ist nicht installiert.<br>"
                "Installieren mit: <code>pip install psutil</code></p>"
            )

        # CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        cpu_freq_str = f"{cpu_freq.current:.0f} MHz" if cpu_freq else "–"

        # RAM
        ram = psutil.virtual_memory()
        ram_used = ram.used / 1024 ** 3
        ram_total = ram.total / 1024 ** 3
        ram_percent = ram.percent

        # Swap
        swap = psutil.swap_memory()
        swap_used = swap.used / 1024 ** 3
        swap_total = swap.total / 1024 ** 3

        # Disk (Partition mit /)
        disk = psutil.disk_usage("/")
        disk_used = disk.used / 1024 ** 3
        disk_total = disk.total / 1024 ** 3
        disk_percent = disk.percent

        # Systemuptime
        boot_ts = datetime.fromtimestamp(psutil.boot_time())
        sys_uptime = datetime.now() - boot_ts
        sys_uptime_str = _format_duration(sys_uptime.total_seconds())

        # Bot-Uptime (seit Prozessstart des CommandHandlers)
        bot_uptime = datetime.now() - self._start_time
        bot_uptime_str = _format_duration(bot_uptime.total_seconds())

        # CPU-Temperatur (optional, z.B. Raspberry Pi)
        temp_str = ""
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                # Bevorzuge cpu_thermal (RPi) oder coretemp (x86)
                for key in ("cpu_thermal", "coretemp", "k10temp", "acpitz"):
                    if key in temps and temps[key]:
                        t = temps[key][0].current
                        temp_str = f"<li><strong>CPU-Temp:</strong> {t:.1f} °C</li>"
                        break
        except (AttributeError, NotImplementedError):
            pass

        def bar(percent: float, width: int = 10) -> str:
            filled = round(percent / 100 * width)
            return "█" * filled + "░" * (width - filled)

        return (
            "<p><strong>🖥️ RathausRot – Systemstatus</strong></p>"
            "<ul>"
            "<li><strong>Bot:</strong> ✅ Online</li>"
            f"<li><strong>Bot-Uptime:</strong> {bot_uptime_str}</li>"
            f"<li><strong>System-Uptime:</strong> {sys_uptime_str}</li>"
            "</ul>"
            "<p><strong>Hardware:</strong></p>"
            "<ul>"
            f"<li><strong>CPU:</strong> {cpu_percent:.1f}% [{bar(cpu_percent)}] "
            f"({cpu_count} Kerne, {cpu_freq_str})</li>"
            f"<li><strong>RAM:</strong> {ram_used:.1f} / {ram_total:.1f} GB "
            f"({ram_percent:.1f}%) [{bar(ram_percent)}]</li>"
            f"<li><strong>Swap:</strong> {swap_used:.1f} / {swap_total:.1f} GB</li>"
            f"<li><strong>Disk (/):</strong> {disk_used:.1f} / {disk_total:.1f} GB "
            f"({disk_percent:.1f}%) [{bar(disk_percent)}]</li>"
            f"{temp_str}"
            "</ul>"
        )

    def _cmd_statistik(self, sender: str, body: str) -> str:
        entries = self.scheduler_ref._history.get_recent(100)
        if not entries:
            return "<p>📊 Noch keine Statistiken verfügbar.</p>"

        total_runs = len(entries)
        success_runs = sum(1 for e in entries if e["success"])
        total_items = sum(e["item_count"] for e in entries)
        success_rate = (success_runs / total_runs * 100) if total_runs else 0

        return (
            "<p><strong>📊 RathausRot – Statistiken</strong></p>"
            "<ul>"
            f"<li><strong>Gesamte Läufe:</strong> {total_runs}</li>"
            f"<li><strong>Erfolgsrate:</strong> {success_rate:.0f}%</li>"
            f"<li><strong>Items gesamt:</strong> {total_items}</li>"
            "</ul>"
        )

    def _cmd_log(self, sender: str, body: str) -> str:
        from rathausrot.utils import get_memory_handler
        handler = get_memory_handler()
        if handler is None:
            return "<p>Log-Handler nicht verfügbar.</p>"

        args = body.split()[1:]
        level = None
        count = 30
        for arg in args:
            if arg.upper() in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
                level = arg.upper()
            elif arg.isdigit():
                count = min(int(arg), 100)

        entries = handler.get_logs(count=count, level=level)
        if not entries:
            return "<p>Keine Log-Einträge gefunden.</p>"

        escaped = html.escape("\n".join(entries))
        response = f"<p><strong>Logs ({len(entries)} Einträge):</strong></p><pre>{escaped}</pre>"

        # Chunk if too large (>60KB)
        if len(response.encode("utf-8")) > 60000 and self._send_extra is not None:
            from rathausrot.utils import chunk_html
            chunks = chunk_html(response)
            if len(chunks) > 1:
                def send():
                    self._send_extra(chunks[1:])
                thread = threading.Thread(target=send, daemon=True, name="send-logs")
                thread.start()
            return chunks[0]

        return response

    def _cmd_version(self, sender: str, body: str) -> str:
        from rathausrot import __version__
        return f"<p>🔴 RathausRot v{__version__}</p>"

    def _cmd_config(self, sender: str, body: str) -> str:
        s = self.config.get("scraper", {})
        b = self.config.get("bot", {})
        o = self.config.get("openrouter", {})
        ratsinfo_url = html.escape(s.get("ratsinfo_url", "–"))
        model = html.escape(o.get("model", "–"))
        party = html.escape(b.get("party", "–"))
        interval_minutes = b.get("interval_minutes", "–")
        relevance_threshold = b.get("relevance_threshold", 1)
        keywords = s.get("keywords", [])
        keywords_str = html.escape(", ".join(keywords)) if keywords else "(keine)"
        allowed_users = b.get("allowed_users", [])
        allowed_str = html.escape(", ".join(allowed_users)) if allowed_users else "(alle)"
        return (
            "<p><strong>⚙️ RathausRot – Konfiguration</strong></p>"
            "<ul>"
            f"<li><strong>Ratsinfo URL:</strong> {ratsinfo_url}</li>"
            f"<li><strong>Modell:</strong> {model}</li>"
            f"<li><strong>Partei:</strong> {party}</li>"
            f"<li><strong>Intervall:</strong> {interval_minutes} min</li>"
            f"<li><strong>Relevanz-Schwelle:</strong> {relevance_threshold}</li>"
            f"<li><strong>Schlüsselwörter:</strong> {keywords_str}</li>"
            f"<li><strong>Erlaubte Nutzer:</strong> {allowed_str}</li>"
            "</ul>"
        )


    def _cmd_stop(self, sender: str, body: str) -> str:
        logger.info("Stop command received from %s – sending SIGTERM", sender)
        def _shutdown():
            import time
            time.sleep(1)  # Antwort zuerst senden lassen
            os.kill(os.getpid(), signal.SIGTERM)
        thread = threading.Thread(target=_shutdown, daemon=True, name="stop-signal")
        thread.start()
        return "<p>🛑 <strong>RathausRot wird heruntergefahren…</strong></p>"


def _format_duration(seconds: float) -> str:
    """Convert a duration in seconds to a human-readable string."""
    seconds = int(seconds)
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)
