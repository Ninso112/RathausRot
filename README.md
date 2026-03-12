# RathausRot

```
  ____       _   _                    ____       _
 |  _ \ __ _| |_| |__   __ _ _   ___|  _ \ ___ | |_
 | |_) / _` | __| '_ \ / _` | | | / __| |_) / _ \| __|
 |  _ < (_| | |_| | | | (_| | |_| \__ \  _ < (_) | |_
 |_| \_\__,_|\__|_| |_|\__,_|\__,_|___/_| \_\___/ \__|
```

**Kommunalpolitik-Bot für Matrix** – Automatische Analyse von Ratssitzungen mit KI

![Python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white)
![Matrix](https://img.shields.io/badge/Matrix-Protocol-0DBD8B?logo=matrix&logoColor=white)
![License](https://img.shields.io/badge/License-GPLv3-blue)
![BeautifulSoup](https://img.shields.io/badge/BeautifulSoup4-Scraping-orange)
![OpenRouter](https://img.shields.io/badge/OpenRouter-LLM_API-6C3483)
![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?logo=sqlite&logoColor=white)
![Schedule](https://img.shields.io/badge/Schedule-Cron--like-green)
![PDF](https://img.shields.io/badge/pdfplumber-PDF_Extraktion-red)

---

> **Hinweis:** Die KI-generierten Analysen und Einschätzungen sind automatische Zusammenfassungen und keine redaktionell geprüften Inhalte. Sie können Fehler, Ungenauigkeiten oder fehlenden Kontext enthalten. Bitte lies immer die Originalvorlagen im Ratsinfo-System und bilde dir deine eigene Meinung – RathausRot ersetzt keine menschliche Bewertung.

---

## Features

### Scraping & Datenerfassung
- **Automatisches Scraping** von SessionNet- und AllRis-Ratsinfo-Systemen
- **PDF-Extraktion** – Anhänge und Vorlagen werden automatisch heruntergeladen und ausgelesen
- **Keyword-Filter** – Optional nur bestimmte Themen verarbeiten
- **Duplikat-Erkennung** – SQLite-Datenbank verhindert doppelte Meldungen
- **Robots.txt-Respekt** – Ethisches Crawling mit Rate-Limiting

### KI-Analyse
- **Zusammenfassung** – Automatische Zusammenfassung von Tagesordnungspunkten via OpenRouter
- **Kernpunkte & Einschätzung** – Relevanz-Bewertung und Abstimmungsempfehlung
- **Konfigurierbarer Relevanz-Schwellenwert** – Nur relevante Items posten
- **Freie Modellwahl** – Claude, Gemini, Llama und weitere über OpenRouter
- **Eigener System-Prompt** möglich

### Matrix-Bot
- **Formatierte HTML-Berichte** direkt in deinen Matrix-Raum
- **Multi-Room-Support** – Berichte in mehrere Räume gleichzeitig senden
- **Chat-Befehle** – Interaktive Steuerung per Chatnachricht (siehe unten)
- **Berechtigungssystem** – Erlaubte Nutzer für Befehle konfigurierbar
- **Startup/Shutdown-Nachrichten** – Bot meldet sich an und ab

### Scheduling & Betrieb
- **Zeitgesteuerter Betrieb** – Wochentag und Uhrzeit konfigurierbar
- **Manueller Scrape** – Per Chat-Befehl oder CLI-Flag `--run-now`
- **Health-Check-Endpoint** – HTTP `/health` für Monitoring
- **Systemstatistiken** – CPU, RAM, Disk und Uptime per Chat abrufbar
- **Log-Einsicht** – Bot-Logs per Chat-Befehl filtern und anzeigen

### Sicherheit & Setup
- **Setup-Wizard** – Interaktive Erstkonfiguration
- **Kein Passwort gespeichert** – Nur Access Token wird in der Config abgelegt
- **Config-Schutz** – `config.yaml` wird mit `chmod 600` geschützt

---

## Chat-Befehle

| Befehl | Beschreibung |
|--------|-------------|
| `!hilfe` | Verfügbare Befehle anzeigen |
| `!scrape` | Manuellen Scrape sofort starten |
| `!status` | Bot-Status anzeigen (Uptime, nächster Lauf) |
| `!verlauf` | Letzte Scrape-Läufe anzeigen |
| `!nächste` | Nächsten geplanten Lauf anzeigen |
| `!zusammenfassung` | Letzten Bericht erneut senden |
| `!statistik` | Scrape-Statistiken anzeigen |
| `!stat` | Systemauslastung (CPU, RAM, Disk, Uptime) |
| `!log [level] [anzahl]` | Bot-Logs anzeigen (z.B. `!log error 20`) |
| `!export` | Letzten Bericht als Datei exportieren |
| `!version` | Version anzeigen |

---

## Beispielausgabe

```
🔴 RathausRot – Wochenbericht KW 15/2024 – Ratsinfo

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Antrag: Erneuerung der Straßenbeleuchtung Innenstadt
Datum: 15.04.2024

Die Verwaltung schlägt die Erneuerung von 120 Straßenlampen durch
energieeffiziente LED-Leuchten vor. Kosten: 280.000 €, davon 60%
durch Bundesfördermittel gedeckt.

• Einsparung von 65% Energiekosten
• Amortisation in 8 Jahren
• Verbesserung der Verkehrssicherheit

Einschätzung: ✅ Zustimmung
Sinnvolle Investition mit klarem Umwelt- und Haushaltsvorteil.

Relevanz: ★★★★☆

─────────────────────────────────────

⚠️ Hinweis: Diese Einschätzungen sind KI-generierte Zusammenfassungen.
Sie ersetzen nicht das Lesen der Originalvorlagen.
```

---

## Voraussetzungen

- **Python 3.9+**
- **libolm-dev** (für Matrix E2E-Verschlüsselung)
- Ein Matrix-Account für den Bot
- Ein [OpenRouter](https://openrouter.ai) API-Schlüssel
- Zugang zum Ratsinfo-System deiner Stadt

### Debian/Ubuntu/Raspberry Pi OS

```bash
sudo apt install python3 python3-venv python3-pip libolm-dev
```

### Arch Linux / Manjaro

```bash
sudo pacman -S python python-pip libolm
```

### Fedora / RHEL

```bash
sudo dnf install python3 python3-pip libolm-devel
```

---

## Installation & Setup

```bash
# 1. Repository klonen
git clone https://github.com/dein-user/rathausrot.git
cd rathausrot

# 2. Installation (automatisch + Setup-Wizard)
bash install.sh

# 3. Bot starten
bash start.sh

# 4. Bot stoppen
bash stop.sh

# 5. Konfiguration ändern
bash config.sh
```

Das Skript `install.sh` erkennt automatisch deine Linux-Distribution, installiert alle Abhängigkeiten und startet den interaktiven Setup-Wizard.

### CLI-Optionen

```bash
python -m rathausrot --setup      # Setup-Wizard starten
python -m rathausrot --run-now    # Pipeline sofort ausführen
python -m rathausrot --test       # Testnachricht an Matrix senden
python -m rathausrot --version    # Version anzeigen
```

---

## Konfiguration

Kopiere `config.example.yaml` nach `config.yaml` und passe die Werte an:

```yaml
matrix:
  homeserver: "https://matrix.org"       # URL deines Matrix-Servers
  username: "@bot:matrix.org"            # Bot-Account
  access_token: ""                       # Wird vom Setup-Wizard befüllt
  room_id: "!raum:matrix.org"            # Zielraum für Berichte

openrouter:
  api_key: "sk-or-..."                   # OpenRouter API-Schlüssel
  model: "anthropic/claude-sonnet-4"     # KI-Modell
  max_tokens: 1024                       # Maximale Token pro Analyse
  system_prompt: ""                      # Eigener Prompt (leer = Default)

scraper:
  ratsinfo_url: "https://ratsinfo.example.de/bi/"
  max_pdf_pages: 10                      # Max. Seiten pro PDF-Anhang
  request_timeout: 30                    # HTTP-Timeout in Sekunden
  keywords: []                           # Keyword-Filter (leer = alles)

bot:
  interval_hours: 168                    # 24 = täglich, 168 = wöchentlich
  schedule_day: "monday"                 # Wochentag ("daily" für täglich)
  schedule_time: "08:00"                 # Uhrzeit
  party: "SPD"                           # Partei für KI-Kontext
  relevance_threshold: 1                 # 1-5 (1 = alles, 5 = nur top)
  healthcheck_port: 0                    # HTTP-Port (0 = deaktiviert)
  log_level: "INFO"
  log_file: "rathausrot.log"
  allowed_users:                         # Wer Befehle nutzen darf
    - "@admin:matrix.org"
```

---

## Raspberry Pi 4

Der Bot läuft problemlos auf einem Raspberry Pi 4 (2GB+ RAM empfohlen).

```bash
# Raspberry Pi OS (Bookworm):
sudo apt install python3 python3-venv python3-pip libolm-dev
```

Für Dauerbetrieb empfiehlt sich ein systemd-Service (siehe unten) oder `screen`/`tmux`.

---

## systemd Service

Für automatischen Start beim Booten:

```ini
# /etc/systemd/system/rathausrot.service
[Unit]
Description=RathausRot Kommunalpolitik-Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/rathausrot
ExecStart=/home/pi/rathausrot/venv/bin/python -m rathausrot
Restart=on-failure
RestartSec=30
StandardOutput=append:/home/pi/rathausrot/rathausrot.log
StandardError=append:/home/pi/rathausrot/rathausrot.log

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable rathausrot
sudo systemctl start rathausrot
sudo systemctl status rathausrot
```

---

## OpenRouter Kosten

| Modell | Input ($/1M) | Output ($/1M) | Empfehlung |
|--------|-------------|---------------|------------|
| `anthropic/claude-haiku-4-5` | ~$0.25 | ~$1.25 | Günstig, gut für einfache Analysen |
| `anthropic/claude-sonnet-4` | ~$3.00 | ~$15.00 | **Empfohlen** – bestes Preis-Leistungs-Verhältnis |
| `anthropic/claude-opus-4` | ~$15.00 | ~$75.00 | Maximale Qualität |
| `google/gemini-flash-1.5` | ~$0.075 | ~$0.30 | Sehr günstig |
| `meta-llama/llama-3.1-8b-instruct` | ~$0.05 | ~$0.05 | Kostenlos-Tier verfügbar |

Bei wöchentlichem Betrieb mit ~10 Tagesordnungspunkten: **ca. $0.10–0.30/Monat** mit Claude Sonnet.

---

## FAQ

**Q: Der Bot findet keine Tagesordnungspunkte.**
A: Prüfe ob die `ratsinfo_url` korrekt ist und ob das System SessionNet oder AllRis verwendet. Schau in `rathausrot.log` für Details.

**Q: Login schlägt fehl.**
A: Stelle sicher, dass dein Matrix-Account keine Zwei-Faktor-Authentifizierung hat. Erstelle ggf. einen dedizierten Bot-Account.

**Q: Kann ich das Intervall ändern?**
A: Ja – ändere `interval_hours` in `config.yaml`. 24 = täglich, 168 = wöchentlich.

**Q: Wie füge ich den Bot zu einem privaten Raum hinzu?**
A: Lade den Bot-Account in den Raum ein, bevor du ihn startest.

**Q: Sind die Analysen verlässlich?**
A: Nein – es sind KI-generierte Zusammenfassungen, die Fehler enthalten können. Lies immer die Originalvorlagen im Ratsinfo-System.

**Q: Kann ich mehrere Räume gleichzeitig bespielen?**
A: Ja – nutze `room_ids` (Liste) statt `room_id` in der Config.

**Q: Wie aktiviere ich den Health-Check?**
A: Setze `healthcheck_port` auf einen Port (z.B. `8080`). Der Endpunkt `/health` gibt JSON mit Status zurück.

---

## Contributing

Beiträge sind willkommen!

1. Fork erstellen
2. Feature-Branch anlegen (`git checkout -b feature/mein-feature`)
3. Änderungen committen
4. Pull Request stellen

---

## Lizenz

GPLv3 – siehe [LICENSE](LICENSE)
