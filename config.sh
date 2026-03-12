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

echo ""
echo -e "${GREEN}Fertig. Bot starten mit: bash start.sh${NC}"
