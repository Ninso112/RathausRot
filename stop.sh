#!/usr/bin/env bash

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ ! -f "bot.pid" ]; then
    echo -e "${YELLOW}Keine bot.pid gefunden – Bot läuft möglicherweise nicht.${NC}"
    exit 0
fi

PID=$(cat bot.pid)

if ! kill -0 "$PID" 2>/dev/null; then
    echo -e "${YELLOW}Prozess ${PID} läuft nicht mehr. Bereinige bot.pid.${NC}"
    rm -f bot.pid
    exit 0
fi

echo "Sende SIGTERM an PID ${PID}..."
kill -TERM "$PID"

WAITED=0
while kill -0 "$PID" 2>/dev/null; do
    sleep 1
    WAITED=$((WAITED + 1))
    if [ $WAITED -ge 10 ]; then
        echo -e "${YELLOW}Prozess antwortet nicht – sende SIGKILL.${NC}"
        kill -KILL "$PID" 2>/dev/null || true
        break
    fi
done

rm -f bot.pid
echo -e "${GREEN}RathausRot gestoppt.${NC}"
