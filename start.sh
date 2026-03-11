#!/usr/bin/env bash

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ ! -d "venv" ]; then
    echo -e "${RED}Fehler: Virtualenv nicht gefunden. Bitte zuerst 'bash install.sh' ausführen.${NC}"
    exit 1
fi

if [ ! -f "config.yaml" ]; then
    echo -e "${RED}Fehler: config.yaml nicht gefunden. Bitte zuerst 'bash config.sh' ausführen.${NC}"
    exit 1
fi

if [ -f "bot.pid" ]; then
    PID=$(cat bot.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo -e "${YELLOW}RathausRot läuft bereits (PID: ${PID}).${NC}"
        exit 0
    else
        echo -e "${YELLOW}Veraltete PID-Datei gefunden – entferne sie.${NC}"
        rm -f bot.pid
    fi
fi

nohup venv/bin/python -m rathausrot >> rathausrot.log 2>&1 &
BOT_PID=$!
echo $BOT_PID > bot.pid

echo -e "${GREEN}RathausRot gestartet (PID: ${BOT_PID}).${NC}"
echo "Log: tail -f rathausrot.log"
