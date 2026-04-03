import getpass
import logging
import sys

logger = logging.getLogger(__name__)


class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def colored(text: str, color: str) -> str:
    if sys.stdout.isatty():
        return f"{color}{text}{Colors.RESET}"
    return text


def print_banner() -> None:
    banner = r"""
  ____       _   _                    ____       _
 |  _ \ __ _| |_| |__   __ _ _   ___|  _ \ ___ | |_
 | |_) / _` | __| '_ \ / _` | | | / __| |_) / _ \| __|
 |  _ < (_| | |_| | | | (_| | |_| \__ \  _ < (_) | |_
 |_| \_\__,_|\__|_| |_|\__,_|\__,_|___/_| \_\___/ \__|
    """
    print(colored(banner, Colors.RED))
    print(colored("  Kommunalpolitik-Bot – Setup Wizard", Colors.BOLD))
    print()


def prompt(question: str, default: str = "", secret: bool = False) -> str:
    display_question = f"{question} [{default}]: " if default else f"{question}: "
    if secret:
        value = getpass.getpass(display_question)
    else:
        value = input(display_question).strip()
    if not value and default:
        return default
    return value


def _do_matrix_login(homeserver: str, username: str) -> str:
    """Interactively log in to Matrix and return the access token."""
    while True:
        pw = prompt("Matrix Passwort", secret=True)
        print(colored("\nVersuche Login...", Colors.YELLOW))
        try:
            import asyncio

            import nio

            async def _do_login(password=pw):
                client = nio.AsyncClient(homeserver, username)
                resp = await client.login(password)
                await client.close()
                if isinstance(resp, nio.LoginResponse):
                    return resp.access_token
                raise RuntimeError(f"Login fehlgeschlagen: {resp}")

            token = asyncio.run(_do_login())
            print(colored("✓ Login erfolgreich!", Colors.GREEN))
            return token
        except Exception as exc:
            print(colored(f"✗ Login fehlgeschlagen: {exc}", Colors.RED))
            retry = input("Erneut versuchen? [J/n]: ").strip().lower()
            if retry == "n":
                print("Setup abgebrochen.")
                sys.exit(1)


def run_wizard(config_manager) -> None:
    print_banner()
    print(colored("Willkommen beim RathausRot Setup-Wizard!", Colors.BOLD))
    print(
        "Dieser Assistent hilft dir bei der Erstkonfiguration.\n"
        "WICHTIG: Das Passwort wird NICHT gespeichert – nur der Access Token.\n"
    )

    homeserver = prompt("Matrix Homeserver URL", "https://matrix.org")
    username = prompt("Matrix Benutzername (z.B. @bot:matrix.org)")
    access_token = _do_matrix_login(homeserver, username)

    room_id = prompt("Matrix Raum-ID (z.B. !raum:matrix.org)")
    api_key = prompt("OpenRouter API Key", secret=True)
    model = prompt("LLM Modell", "anthropic/claude-sonnet-4")
    ratsinfo_url = prompt("Ratsinfo URL (z.B. https://ratsinfo.example.de/bi/)")
    robots_input = prompt("robots.txt respektieren? (j/n)", "j").lower()
    respect_robots_txt = robots_input != "n"
    interval_str = prompt("Abruf-Intervall in Minuten", "360")
    try:
        interval_minutes = int(interval_str)
    except ValueError:
        interval_minutes = 360
    party = prompt("Deine Partei (z.B. Die Linke)")
    relevance_str = prompt("Relevanz-Schwellenwert (1–5, 1 = alles)", "1")
    try:
        relevance_threshold = max(1, min(5, int(relevance_str)))
    except ValueError:
        relevance_threshold = 1
    keywords_input = prompt("Schlüsselwörter (kommasepariert, leer = alle)", "")
    keywords = [kw.strip() for kw in keywords_input.split(",") if kw.strip()]
    allowed_input = prompt("Erlaubte Matrix-IDs (kommasepariert, leer = alle)", "")
    allowed_users = [u.strip() for u in allowed_input.split(",") if u.strip()]
    pdf_input = prompt("PDF-Anhänge als Dateien in Matrix senden? (j/n)", "n").lower()
    send_pdf_attachments = pdf_input == "j"

    config = {
        "matrix": {
            "homeserver": homeserver,
            "username": username,
            "access_token": access_token,
            "room_id": room_id,
        },
        "openrouter": {
            "api_key": api_key,
            "model": model,
            "max_tokens": 1024,
        },
        "scraper": {
            "ratsinfo_url": ratsinfo_url,
            "max_pdf_pages": 10,
            "request_timeout": 30,
            "respect_robots_txt": respect_robots_txt,
            "keywords": keywords,
        },
        "bot": {
            "interval_minutes": interval_minutes,
            "party": party,
            "relevance_threshold": relevance_threshold,
            "allowed_users": allowed_users,
            "send_pdf_attachments": send_pdf_attachments,
            "log_level": "INFO",
            "log_file": "rathausrot.log",
        },
    }

    print(colored("\n--- Zusammenfassung ---", Colors.BOLD))
    print(f"  Homeserver:           {homeserver}")
    print(f"  Benutzername:         {username}")
    print(f"  Raum-ID:              {room_id}")
    print(f"  Modell:               {model}")
    print(f"  Ratsinfo URL:         {ratsinfo_url}")
    print(
        f"  robots.txt:           {'respektieren' if respect_robots_txt else 'ignorieren'}"
    )
    print(f"  Intervall:            {interval_minutes} min")
    print(f"  Partei:               {party}")
    print(f"  Relevanz-Schwelle:    {relevance_threshold}")
    print(f"  Schlüsselwörter:      {', '.join(keywords) if keywords else '(alle)'}")
    print(
        f"  Erlaubte Nutzer:      {', '.join(allowed_users) if allowed_users else '(alle)'}"
    )
    print(f"  PDF-Anhänge senden:   {'ja' if send_pdf_attachments else 'nein'}")
    print(f"  API Key:              {'*' * min(len(api_key), 8)}...")
    print(f"  Access Token:         {'*' * 8}...")
    print()

    confirm = input("Konfiguration speichern? [J/n]: ").strip().lower()
    if confirm == "n":
        print("Abgebrochen.")
        sys.exit(0)

    config_manager.save(config)
    print(colored("\n✓ Konfiguration gespeichert (chmod 600).", Colors.GREEN))
    print("Starte den Bot mit: bash start.sh")


def run_edit_wizard(config_manager) -> None:
    """Edit individual values of an existing config. Empty input = keep current value."""
    print_banner()
    print(colored("Konfiguration bearbeiten", Colors.BOLD))
    print("Enter drücken = aktuellen Wert behalten.\n")

    config = config_manager.load()
    m = config.get("matrix", {})
    o = config.get("openrouter", {})
    s = config.get("scraper", {})
    b = config.get("bot", {})

    # Matrix
    print(colored("── Matrix ──────────────────────────────", Colors.YELLOW))
    homeserver = prompt("Homeserver URL", m.get("homeserver", "https://matrix.org"))
    username = prompt("Benutzername", m.get("username", ""))

    cur_token = m.get("access_token", "")
    token_hint = (
        f"{'*' * 8}... (Enter = behalten)" if cur_token else "(noch nicht gesetzt)"
    )
    print(f"Access Token: {token_hint}")
    relogin = input("Neu einloggen und Token erneuern? [j/N]: ").strip().lower()
    if relogin == "j":
        access_token = _do_matrix_login(homeserver, username)
    else:
        access_token = cur_token

    room_id = prompt("Raum-ID", m.get("room_id", ""))

    # OpenRouter
    print(colored("\n── OpenRouter ──────────────────────────", Colors.YELLOW))
    cur_key = o.get("api_key", "")
    key_hint = (
        f"{'*' * min(len(cur_key), 8)}... (Enter = behalten)"
        if cur_key
        else "(noch nicht gesetzt)"
    )
    print(f"API Key: {key_hint}")
    new_key = getpass.getpass("Neuer API Key (Enter = behalten): ").strip()
    api_key = new_key if new_key else cur_key
    model = prompt("LLM Modell", o.get("model", "anthropic/claude-sonnet-4"))

    # Scraper
    print(colored("\n── Scraper ─────────────────────────────", Colors.YELLOW))
    ratsinfo_url = prompt("Ratsinfo URL", s.get("ratsinfo_url", ""))
    cur_robots = "j" if s.get("respect_robots_txt", True) else "n"
    robots_input = prompt("robots.txt respektieren? (j/n)", cur_robots).lower()
    respect_robots_txt = robots_input != "n"

    # Bot
    print(colored("\n── Bot ─────────────────────────────────", Colors.YELLOW))
    interval_str = prompt(
        "Abruf-Intervall in Minuten", str(b.get("interval_minutes", 360))
    )
    try:
        interval_minutes = int(interval_str)
    except ValueError:
        interval_minutes = b.get("interval_minutes", 360)
    party = prompt("Partei", b.get("party", "Die Linke"))
    relevance_str = prompt(
        "Relevanz-Schwellenwert (1–5)", str(b.get("relevance_threshold", 1))
    )
    try:
        relevance_threshold = max(1, min(5, int(relevance_str)))
    except ValueError:
        relevance_threshold = b.get("relevance_threshold", 1)
    cur_keywords = ", ".join(s.get("keywords", []))
    keywords_input = prompt(
        "Schlüsselwörter (kommasepariert, leer = alle)", cur_keywords
    )
    keywords = [kw.strip() for kw in keywords_input.split(",") if kw.strip()]
    cur_allowed = ", ".join(b.get("allowed_users", []))
    allowed_input = prompt(
        "Erlaubte Matrix-IDs (kommasepariert, leer = alle)", cur_allowed
    )
    allowed_users = [u.strip() for u in allowed_input.split(",") if u.strip()]
    cur_pdf = "j" if b.get("send_pdf_attachments", False) else "n"
    pdf_input = prompt(
        "PDF-Anhänge als Dateien in Matrix senden? (j/n)", cur_pdf
    ).lower()
    send_pdf_attachments = pdf_input == "j"

    # Merge into existing config
    config["matrix"]["homeserver"] = homeserver
    config["matrix"]["username"] = username
    config["matrix"]["access_token"] = access_token
    config["matrix"]["room_id"] = room_id
    config["openrouter"]["api_key"] = api_key
    config["openrouter"]["model"] = model
    config["scraper"]["ratsinfo_url"] = ratsinfo_url
    config["scraper"]["respect_robots_txt"] = respect_robots_txt
    config["scraper"]["keywords"] = keywords
    config["bot"]["interval_minutes"] = interval_minutes
    config["bot"]["party"] = party
    config["bot"]["relevance_threshold"] = relevance_threshold
    config["bot"]["allowed_users"] = allowed_users
    config["bot"]["send_pdf_attachments"] = send_pdf_attachments

    print(colored("\n--- Geänderte Werte werden gespeichert ---", Colors.BOLD))
    confirm = input("Speichern? [J/n]: ").strip().lower()
    if confirm == "n":
        print("Abgebrochen.")
        sys.exit(0)

    config_manager.save(config)
    print(colored("\n✓ Konfiguration aktualisiert.", Colors.GREEN))
    print("Bot neu starten mit: bash start.sh")
