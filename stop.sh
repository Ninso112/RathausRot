#!/usr/bin/env bash

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

stop_pid() {
    local PID="$1"
    if ! kill -0 "$PID" 2>/dev/null; then
        return 1
    fi
    echo "Sende SIGTERM an PID ${PID}..."
    kill -TERM "$PID"
    local WAITED=0
    while kill -0 "$PID" 2>/dev/null; do
        sleep 1
        WAITED=$((WAITED + 1))
        if [ $WAITED -ge 10 ]; then
            echo -e "${YELLOW}Prozess antwortet nicht – sende SIGKILL.${NC}"
            kill -KILL "$PID" 2>/dev/null || true
            break
        fi
    done
    return 0
}

STOPPED=false

# 1) Versuche über systemctl (falls als User-Service eingerichtet)
for SERVICE_NAME in rathausrot rathausrot-bot; do
    if systemctl --user is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        echo "Stoppe systemd User-Service '${SERVICE_NAME}'..."
        systemctl --user stop "$SERVICE_NAME"
        echo -e "${GREEN}RathausRot (Service) gestoppt.${NC}"
        STOPPED=true
        break
    fi
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        echo "Stoppe systemd System-Service '${SERVICE_NAME}'..."
        sudo systemctl stop "$SERVICE_NAME"
        echo -e "${GREEN}RathausRot (System-Service) gestoppt.${NC}"
        STOPPED=true
        break
    fi
done

# 2) Versuche über bot.pid
if [ "$STOPPED" = false ] && [ -f "bot.pid" ]; then
    PID=$(cat bot.pid)
    if stop_pid "$PID"; then
        STOPPED=true
        echo -e "${GREEN}RathausRot (PID-Datei) gestoppt.${NC}"
    else
        echo -e "${YELLOW}PID ${PID} aus bot.pid läuft nicht mehr. Bereinige.${NC}"
    fi
    rm -f bot.pid
fi

# 3) Fallback: Prozess per Name finden
if [ "$STOPPED" = false ]; then
    PIDS=$(pgrep -f "python.*rathausrot" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        for PID in $PIDS; do
            echo "Gefundener Prozess PID ${PID} – wird beendet..."
            stop_pid "$PID"
        done
        echo -e "${GREEN}RathausRot gestoppt.${NC}"
        STOPPED=true
    fi
fi

if [ "$STOPPED" = false ]; then
    echo -e "${YELLOW}Kein laufender RathausRot-Prozess gefunden.${NC}"
    exit 0
fi

rm -f bot.pid
