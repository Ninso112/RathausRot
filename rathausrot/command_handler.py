import logging
import threading
from datetime import datetime
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "<p><strong>🔴 RathausRot – Verfügbare Befehle:</strong></p>"
    "<ul>"
    "<li><code>!scrape</code> – Manuellen Scrape jetzt starten</li>"
    "<li><code>!status</code> – Bot-Status anzeigen</li>"
    "<li><code>!stat</code> – Systemauslastung (CPU, RAM, Disk, Uptime)</li>"
    "<li><code>!version</code> – Version anzeigen</li>"
    "<li><code>!hilfe</code> – Diese Hilfe anzeigen</li>"
    "</ul>"
)


class CommandHandler:
    def __init__(self, config: dict, scheduler_ref):
        self.config = config
        self.scheduler_ref = scheduler_ref
        self.bot_username = config.get("matrix", {}).get("username", "")
        self.allowed_users: list = config.get("bot", {}).get("allowed_users", [])
        self._scrape_lock = threading.Lock()
        self._scrape_running = False
        self._start_time = datetime.now()
        self._commands: Dict[str, Callable] = {
            "!hilfe": self._cmd_help,
            "!help": self._cmd_help,
            "!scrape": self._cmd_scrape,
            "!status": self._cmd_status,
            "!stat": self._cmd_stat,
            "!version": self._cmd_version,
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
            return f"<p>⛔ Keine Berechtigung für <code>{sender}</code>.</p>"
        logger.info("Command '%s' from %s", cmd, sender)
        try:
            return self._commands[cmd](sender, body)
        except Exception as exc:
            logger.error("Error executing command '%s': %s", cmd, exc)
            return f"<p>❌ Fehler beim Ausführen von <code>{cmd}</code>: {exc}</p>"

    # ------------------------------------------------------------------ #
    # Command implementations
    # ------------------------------------------------------------------ #

    def _cmd_help(self, sender: str, body: str) -> str:
        return HELP_TEXT

    def _cmd_scrape(self, sender: str, body: str) -> str:
        with self._scrape_lock:
            if self._scrape_running:
                return "<p>⏳ Ein Scrape-Vorgang läuft bereits. Bitte warten.</p>"
            self._scrape_running = True

        def run():
            try:
                self.scheduler_ref.run_pipeline()
            finally:
                with self._scrape_lock:
                    self._scrape_running = False

        thread = threading.Thread(target=run, daemon=True, name="manual-scrape")
        thread.start()
        return "<p>🔄 Manueller Scrape gestartet. Ergebnisse folgen in Kürze.</p>"

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

        interval = self.config.get("bot", {}).get("interval_hours", 168)
        party = self.config.get("bot", {}).get("party", "–")
        ratsinfo_url = self.config.get("scraper", {}).get("ratsinfo_url", "–")

        with self._scrape_lock:
            running = self._scrape_running
        scrape_status = "⏳ Scrape läuft gerade" if running else "✅ Bereit"

        return (
            "<p><strong>🔴 RathausRot Status</strong></p>"
            "<ul>"
            f"<li><strong>Status:</strong> {scrape_status}</li>"
            f"<li><strong>Letzter Lauf:</strong> {last_run}</li>"
            f"<li><strong>Intervall:</strong> {interval} Stunden</li>"
            f"<li><strong>Partei:</strong> {party}</li>"
            f"<li><strong>Ratsinfo:</strong> {ratsinfo_url}</li>"
            "</ul>"
        )

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

    def _cmd_version(self, sender: str, body: str) -> str:
        from rathausrot import __version__
        return f"<p>🔴 RathausRot v{__version__}</p>"


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
