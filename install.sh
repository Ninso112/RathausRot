#!/usr/bin/env bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BOLD}${RED}"
echo "  ____       _   _                    ____       _   "
echo " |  _ \ __ _| |_| |__   __ _ _   ___|  _ \ ___ | |_ "
echo " | |_) / _\` | __| '_ \\ / _\` | | | / __| |_) / _ \\| __|"
echo " |  _ < (_| | |_| | | | (_| | |_| \\__ \\  _ < (_) | |_ "
echo " |_| \\_\\__,_|\\__|_| |_|\\__,_|\\__,_|___/_| \\_\\___/ \\__|"
echo -e "${NC}"
echo -e "${BOLD}RathausRot – Installations-Skript${NC}"
echo ""

ALREADY_INSTALLED=false
if [ -f ".installed" ]; then
    ALREADY_INSTALLED=true
    echo -e "${YELLOW}Bot bereits installiert. Überspringe Systempaket-Installation.${NC}"
fi

if [ "$ALREADY_INSTALLED" = false ]; then
    echo -e "${BOLD}Erkenne Linux-Distribution...${NC}"
    if [ -f /etc/os-release ]; then
        source /etc/os-release
    else
        echo -e "${YELLOW}Warnung: /etc/os-release nicht gefunden. Überspringe Systempaket-Installation.${NC}"
        ID=""
        ID_LIKE=""
    fi

    DISTRO_FAMILY=""
    if echo "${ID_LIKE}" | grep -qi "debian" || echo "${ID}" | grep -qi "debian\|ubuntu\|raspbian\|linuxmint"; then
        DISTRO_FAMILY="debian"
    elif echo "${ID_LIKE}" | grep -qi "arch" || echo "${ID}" | grep -qi "^arch$\|manjaro\|endeavouros"; then
        DISTRO_FAMILY="arch"
    elif echo "${ID_LIKE}" | grep -qi "rhel\|fedora" || echo "${ID}" | grep -qi "fedora\|rhel\|centos\|rocky\|almalinux"; then
        DISTRO_FAMILY="fedora"
    elif echo "${ID_LIKE}" | grep -qi "suse" || echo "${ID}" | grep -qi "opensuse"; then
        DISTRO_FAMILY="suse"
    else
        echo -e "${YELLOW}Warnung: Unbekannte Distribution '${ID}'. Bitte installiere manuell:${NC}"
        echo "  python3, python3-venv, python3-pip, libolm-dev (oder äquivalent)"
        DISTRO_FAMILY="unknown"
    fi

    if [ "$DISTRO_FAMILY" != "unknown" ]; then
        echo -e "${BOLD}Installiere Systemabhängigkeiten (${DISTRO_FAMILY})...${NC}"
        case "$DISTRO_FAMILY" in
            debian)
                sudo apt-get update -q
                sudo apt-get install -y python3 python3-venv python3-pip libolm-dev
                ;;
            arch)
                sudo pacman -S --noconfirm python python-pip libolm
                ;;
            fedora)
                if command -v dnf &>/dev/null; then
                    sudo dnf install -y python3 python3-pip libolm-devel
                else
                    sudo yum install -y python3 python3-pip libolm-devel
                fi
                ;;
            suse)
                sudo zypper install -y python3 python3-pip libolm-devel
                ;;
        esac
        echo -e "${GREEN}✓ Systemabhängigkeiten installiert.${NC}"
    fi
fi

echo -e "${BOLD}Prüfe Python-Version...${NC}"
PYTHON_CMD=""
for cmd in python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$cmd" &>/dev/null; then
        VERSION=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        MAJOR=$(echo "$VERSION" | cut -d. -f1)
        MINOR=$(echo "$VERSION" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 9 ]; then
            PYTHON_CMD="$cmd"
            echo -e "${GREEN}✓ Python ${VERSION} gefunden (${cmd}).${NC}"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}Fehler: Python 3.9+ nicht gefunden. Bitte installiere Python 3.9 oder neuer.${NC}"
    exit 1
fi

if [ ! -d "venv" ]; then
    echo -e "${BOLD}Erstelle virtuelle Umgebung...${NC}"
    "$PYTHON_CMD" -m venv venv
    echo -e "${GREEN}✓ Virtualenv erstellt.${NC}"
else
    echo -e "${YELLOW}Virtualenv bereits vorhanden – überspringe.${NC}"
fi

echo -e "${BOLD}Installiere Python-Abhängigkeiten...${NC}"
venv/bin/pip install --upgrade pip -q
venv/bin/pip install -r requirements.txt
echo -e "${GREEN}✓ Python-Abhängigkeiten installiert.${NC}"

if [ "$ALREADY_INSTALLED" = false ]; then
    touch .installed
    echo -e "${GREEN}✓ Installation abgeschlossen!${NC}"
    echo ""
    echo -e "${BOLD}Starte Konfiguration...${NC}"
    bash config.sh
else
    echo -e "${GREEN}✓ Aktualisierung abgeschlossen!${NC}"
    echo ""
    echo "Bot starten:  bash start.sh"
fi
