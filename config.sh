#!/usr/bin/env bash

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ ! -d "venv" ]; then
    echo -e "${RED}Fehler: Virtualenv nicht gefunden. Bitte zuerst 'bash install.sh' ausführen.${NC}"
    exit 1
fi

if [ -f "config.yaml" ]; then
    venv/bin/python -c "
from rathausrot.config_manager import ConfigManager
from rathausrot.setup_wizard import run_edit_wizard
run_edit_wizard(ConfigManager())
"
else
    venv/bin/python -m rathausrot --setup
fi

# ── Autostart-Frage ──────────────────────────────────────────────────────────
echo ""
read -rp "Soll der Bot beim Systemstart automatisch starten? [j/N] " autostart
if [[ "${autostart,,}" == "j" ]]; then
    SERVICE_DIR="$HOME/.config/systemd/user"
    SERVICE_FILE="$SERVICE_DIR/rathausrot.service"
    mkdir -p "$SERVICE_DIR"
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=RathausRot Kommunalpolitik-Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$PWD
ExecStart=$PWD/venv/bin/python -m rathausrot
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
EOF
    echo -e "${GREEN}Service-Datei erstellt: $SERVICE_FILE${NC}"
    if systemctl --user daemon-reload && systemctl --user enable rathausrot.service; then
        echo -e "${GREEN}✓ Autostart aktiviert (systemctl --user enable rathausrot.service)${NC}"
    else
        echo -e "${YELLOW}Warnung: systemctl --user konnte nicht ausgeführt werden.${NC}"
    fi
    echo ""
    read -rp "Auch ohne aktiven Login starten (loginctl enable-linger)? [j/N] " linger
    if [[ "${linger,,}" == "j" ]]; then
        if loginctl enable-linger "$USER"; then
            echo -e "${GREEN}✓ Linger aktiviert – Bot startet auch ohne aktiven Login.${NC}"
        else
            echo -e "${YELLOW}Warnung: loginctl enable-linger fehlgeschlagen.${NC}"
        fi
    fi
else
    # Disable existing service if present
    if systemctl --user is-enabled rathausrot.service &>/dev/null; then
        systemctl --user disable rathausrot.service
        echo -e "${YELLOW}Autostart deaktiviert (bestehender Service wurde disabled).${NC}"
    fi
fi

echo ""
echo -e "${GREEN}Fertig. Bot starten mit: bash start.sh${NC}"
