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
    if default:
        display_question = f"{question} [{default}]: "
    else:
        display_question = f"{question}: "
    if secret:
        value = getpass.getpass(display_question)
    else:
        value = input(display_question).strip()
    if not value and default:
        return default
    return value


def run_wizard(config_manager) -> None:
    print_banner()
    print(colored("Willkommen beim RathausRot Setup-Wizard!", Colors.BOLD))
    print(
        "Dieser Assistent hilft dir bei der Erstkonfiguration.\n"
        "WICHTIG: Das Passwort wird NICHT gespeichert – nur der Access Token.\n"
    )

    while True:
        homeserver = prompt("Matrix Homeserver URL", "https://matrix.org")
        username = prompt("Matrix Benutzername (z.B. @bot:matrix.org)")
        password = prompt("Matrix Passwort", secret=True)

        print(colored("\nVersuche Login...", Colors.YELLOW))
        try:
            from rathausrot.matrix_bot import MatrixBot
            bot = MatrixBot.__new__(MatrixBot)
            # Minimal init for login
            import asyncio
            import nio
            async def do_login():
                client = nio.AsyncClient(homeserver, username)
                resp = await client.login(password)
                await client.close()
                if isinstance(resp, nio.LoginResponse):
                    return resp.access_token
                raise RuntimeError(f"Login fehlgeschlagen: {resp}")
            access_token = asyncio.run(do_login())
            print(colored("✓ Login erfolgreich!", Colors.GREEN))
            break
        except Exception as exc:
            print(colored(f"✗ Login fehlgeschlagen: {exc}", Colors.RED))
            retry = input("Erneut versuchen? [J/n]: ").strip().lower()
            if retry == "n":
                print("Setup abgebrochen.")
                sys.exit(1)

    room_id = prompt("Matrix Raum-ID (z.B. !raum:matrix.org)")
    api_key = prompt("OpenRouter API Key", secret=True)
    model = prompt("LLM Modell", "anthropic/claude-sonnet-4")
    ratsinfo_url = prompt("Ratsinfo URL (z.B. https://ratsinfo.example.de/bi/)")
    interval_str = prompt("Abruf-Intervall in Stunden", "168")
    try:
        interval_hours = int(interval_str)
    except ValueError:
        interval_hours = 168
    party = prompt("Deine Partei (z.B. SPD)")

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
        },
        "bot": {
            "interval_hours": interval_hours,
            "party": party,
            "log_level": "INFO",
            "log_file": "rathausrot.log",
        },
    }

    print(colored("\n--- Zusammenfassung ---", Colors.BOLD))
    print(f"  Homeserver:     {homeserver}")
    print(f"  Benutzername:   {username}")
    print(f"  Raum-ID:        {room_id}")
    print(f"  Modell:         {model}")
    print(f"  Ratsinfo URL:   {ratsinfo_url}")
    print(f"  Intervall:      {interval_hours}h")
    print(f"  Partei:         {party}")
    print(f"  API Key:        {'*' * min(len(api_key), 8)}...")
    print(f"  Access Token:   {'*' * 8}...")
    print()

    confirm = input("Konfiguration speichern? [J/n]: ").strip().lower()
    if confirm == "n":
        print("Abgebrochen.")
        sys.exit(0)

    config_manager.save(config)
    print(colored("\n✓ Konfiguration gespeichert (chmod 600).", Colors.GREEN))
    print("Starte den Bot mit: bash start.sh")
