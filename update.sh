#!/usr/bin/env bash
#
# RathausRot – Update-Skript
# Stoppt den Bot, holt die neueste Version, aktualisiert die Abhängigkeiten
# und startet den Bot wieder. Sicher gegenüber neuen Dependencies.
#
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

cd "$(dirname "$0")"

echo -e "${BOLD}${RED}RathausRot – Update${NC}"
echo ""

if [ ! -d "venv" ]; then
    echo -e "${RED}Fehler: Virtualenv nicht gefunden. Bitte zuerst 'bash install.sh' ausführen.${NC}"
    exit 1
fi

if ! command -v git &>/dev/null; then
    echo -e "${RED}Fehler: git ist nicht installiert.${NC}"
    exit 1
fi

# 1) Bot stoppen (falls er läuft)
echo -e "${BOLD}1/4 Stoppe Bot...${NC}"
bash stop.sh || true
echo ""

# 2) requirements.txt-Prüfsumme vor dem Pull merken
REQ_BEFORE=""
if [ -f "requirements.txt" ]; then
    REQ_BEFORE=$(sha256sum requirements.txt | awk '{print $1}')
fi

# 3) Update holen
echo -e "${BOLD}2/4 Hole Update (git pull)...${NC}"
git pull
echo ""

# 4) Abhängigkeiten nur installieren, wenn sich requirements.txt geändert hat
REQ_AFTER=""
if [ -f "requirements.txt" ]; then
    REQ_AFTER=$(sha256sum requirements.txt | awk '{print $1}')
fi

echo -e "${BOLD}3/4 Prüfe Abhängigkeiten...${NC}"
if [ "$REQ_BEFORE" != "$REQ_AFTER" ]; then
    echo -e "${YELLOW}requirements.txt hat sich geändert – installiere Abhängigkeiten...${NC}"
    venv/bin/pip install --upgrade pip -q
    venv/bin/pip install -r requirements.txt
    echo -e "${GREEN}✓ Abhängigkeiten aktualisiert.${NC}"
else
    echo -e "${GREEN}✓ Keine Änderung an requirements.txt – überspringe pip install.${NC}"
fi
echo ""

# 5) Optionale Konfigurationsprüfung
if [ -f "config.yaml" ]; then
    echo -e "${BOLD}Prüfe Konfiguration...${NC}"
    if ! venv/bin/python -m rathausrot --check-config; then
        echo -e "${YELLOW}Warnung: Konfiguration enthält Probleme (siehe oben).${NC}"
    fi
    echo ""
fi

# 6) Bot wieder starten
echo -e "${BOLD}4/4 Starte Bot...${NC}"
bash start.sh

echo ""
echo -e "${GREEN}${BOLD}✓ Update abgeschlossen.${NC}"
