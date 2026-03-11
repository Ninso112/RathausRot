# RathausRot

```
  ____       _   _                    ____       _
 |  _ \ __ _| |_| |__   __ _ _   ___|  _ \ ___ | |_
 | |_) / _` | __| '_ \ / _` | | | / __| |_) / _ \| __|
 |  _ < (_| | |_| | | | (_| | |_| \__ \  _ < (_) | |_
 |_| \_\__,_|\__|_| |_|\__,_|\__,_|___/_| \_\___/ \__|
```

**Kommunalpolitik-Bot für Matrix** – Automatische Analyse von Ratssitzungen mit KI

RathausRot beobachtet das Ratsinfo-System deiner Stadt, analysiert neue Tagesordnungspunkte mit KI und postet einen wöchentlichen Bericht mit Einschätzungen in deinen Matrix-Raum.

---

## Features

- **Automatisches Scraping** – SessionNet und AllRis werden unterstützt
- **KI-Analyse** – Zusammenfassung, Kernpunkte und Abstimmungsempfehlung via OpenRouter
- **Matrix-Integration** – Formatierter HTML-Bericht direkt in deinen Raum
- **PDF-Extraktion** – Anhänge werden automatisch ausgewertet
- **Duplikat-Erkennung** – SQLite-Datenbank verhindert doppelte Meldungen
- **Robots.txt-Respekt** – Ethisches Crawling mit Rate-Limiting
- **Setup-Wizard** – Interaktive Erstkonfiguration in 5 Minuten
- **Sicher** – Passwort wird nie gespeichert, nur Access Token; `config.yaml` mit chmod 600

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

Hinweis: Diese Einschätzungen sind automatisch generierte Prognosen
und stellen keine offiziellen Positionen der Partei dar.
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

---

## Raspberry Pi 4 Hinweise

Der Bot läuft problemlos auf einem Raspberry Pi 4 (2GB+ RAM empfohlen).

```bash
# Auf Raspberry Pi OS (Bookworm) funktioniert libolm direkt:
sudo apt install python3 python3-venv python3-pip libolm-dev

# Bei älteren Versionen ggf. aus source bauen:
# https://gitlab.matrix.org/matrix-org/olm
```

Für den Dauerbetrieb empfiehlt sich ein systemd-Service (siehe unten) oder `screen`/`tmux`.

---

## config.yaml – Erklärung

```yaml
matrix:
  homeserver: "https://matrix.org"  # URL deines Matrix-Servers
  username: "@bot:matrix.org"        # Bot-Account (@user:server)
  access_token: ""                   # Automatisch vom Setup-Wizard befüllt
  room_id: "!raum:matrix.org"        # Zielraum für Berichte

openrouter:
  api_key: "sk-or-..."               # OpenRouter API-Schlüssel
  model: "anthropic/claude-sonnet-4" # KI-Modell (siehe Kosten-Tabelle)
  max_tokens: 1024                   # Maximale Token pro Analyse

scraper:
  ratsinfo_url: "https://..."        # URL des Ratsinfo-Systems
  max_pdf_pages: 10                  # Max. Seiten pro PDF-Anhang
  request_timeout: 30                # HTTP-Timeout in Sekunden

bot:
  interval_hours: 168                # Abruf-Intervall (168 = wöchentlich)
  party: "SPD"                       # Partei für KI-Kontext
  log_level: "INFO"                  # DEBUG, INFO, WARNING, ERROR
  log_file: "rathausrot.log"         # Pfad zur Log-Datei
```

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

## OpenRouter Kosten-Tabelle

| Modell | Input ($/1M) | Output ($/1M) | Empfehlung |
|--------|-------------|---------------|------------|
| `anthropic/claude-haiku-4-5` | ~$0.25 | ~$1.25 | Günstig, gut für einfache Analysen |
| `anthropic/claude-sonnet-4` | ~$3.00 | ~$15.00 | **Empfohlen** – gutes Preis-Leistungs-Verhältnis |
| `anthropic/claude-opus-4` | ~$15.00 | ~$75.00 | Maximale Qualität |
| `google/gemini-flash-1.5` | ~$0.075 | ~$0.30 | Sehr günstig |
| `meta-llama/llama-3.1-8b-instruct` | ~$0.05 | ~$0.05 | Kostenlos-Tier verfügbar |

Bei wöchentlichem Betrieb mit ~10 Tagesordnungspunkten à ~2000 Token: **ca. $0.10–0.30/Monat** mit claude-sonnet-4.

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
A: Der Disclaimer im Bericht weist darauf hin: Es sind automatisch generierte Prognosen. Immer selbst prüfen!

---

## Contributing

Beiträge sind willkommen! Bitte:
1. Fork erstellen
2. Feature-Branch anlegen (`git checkout -b feature/mein-feature`)
3. Änderungen committen
4. Pull Request stellen

---

## Lizenz

GPLv3 – siehe [LICENSE](LICENSE)
