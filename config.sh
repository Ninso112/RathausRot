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
    echo -e "${YELLOW}Warnung: Eine bestehende Konfiguration wurde gefunden.${NC}"
    echo -n "Bestehende Konfiguration wird überschrieben. Fortfahren? [j/N]: "
    read -r CONFIRM
    if [ "${CONFIRM,,}" != "j" ]; then
        echo "Abgebrochen."
        exit 0
    fi
fi

venv/bin/python -m rathausrot --setup

echo ""
echo -e "${GREEN}Konfiguration abgeschlossen.${NC}"
echo "Bot starten mit: bash start.sh"
