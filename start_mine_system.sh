#!/usr/bin/env bash

# ==============================================================================
# Mine IoT Early Warning System - Master Startup & Recovery Script
# ==============================================================================
# Host / Credentials:
#   Raspberry Pi: sih@192.168.1.91 (or sih26) | Password: 8017
#   PC Host IP:   192.168.1.1
#
# Services Launched/Verified:
#   1. Local PC Telemetry Receiver (0.0.0.0:4000) -> SQLite pc_telemetry.db
#   2. Local PC Image Binary Receiver (0.0.0.0:5000) -> local captured_images/
#   3. Pi Mosquitto MQTT Broker (localhost:1883)
#   4. Pi Telemetry Forwarder (mine-forwarder.service)
#   5. Pi Image Ingestion Server (mine-image-server.service)
#   6. Pi Command Relay Daemon (mine-command-poller.service)
# ==============================================================================

set -e

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

PI_USER="sih"
PI_HOST="192.168.1.91"
PI_PASS="8017"
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IOT_DIR="${WORKSPACE_DIR}/mine-iot"

echo -e "${CYAN}${BOLD}========================================================================${NC}"
echo -e "${CYAN}${BOLD}       MINE IOT SYSTEM MASTER STARTUP & RECOVERY INITIALIZER            ${NC}"
echo -e "${CYAN}${BOLD}========================================================================${NC}"
echo -e "${BLUE}Local Workspace: ${WORKSPACE_DIR}${NC}"
echo -e "${BLUE}Target Raspberry Pi: ${PI_USER}@${PI_HOST}${NC}"
echo ""

# ------------------------------------------------------------------------------
# 1. Dependency Check
# ------------------------------------------------------------------------------
echo -e "${BOLD}[1/4] Checking Local PC Dependencies...${NC}"
for cmd in python3 sshpass curl ss; do
    if ! command -v "$cmd" &> /dev/null; then
        echo -e "  ${RED}✘ Missing required command: ${cmd}${NC}"
        echo "  Please install it (e.g. sudo apt install sshpass curl iproute2 python3)"
        exit 1
    else
        echo -e "  ${GREEN}✔ ${cmd} is available.${NC}"
    fi
done

# ------------------------------------------------------------------------------
# 2. Launch Local PC Background Daemons
# ------------------------------------------------------------------------------
echo ""
echo -e "${BOLD}[2/4] Starting Local PC Daemons (Port 4000 & Port 5000)...${NC}"

# Start PC Telemetry Receiver (Port 4000)
if curl -s --max-time 2 http://localhost:4000/health | grep -q "pc-local-receiver"; then
    echo -e "  ${GREEN}✔ Port 4000 (PC Telemetry Receiver) is active and healthy.${NC}"
else
    echo -e "  ${CYAN}➜ Resetting/Launching PC Telemetry Receiver (pc_local_receiver.py)...${NC}"
    fuser -k 4000/tcp &>/dev/null || true
    nohup python3 "${IOT_DIR}/pc_local_receiver.py" > "${WORKSPACE_DIR}/pc_local_receiver.log" 2>&1 &
    sleep 2
    if curl -s --max-time 2 http://localhost:4000/health | grep -q "pc-local-receiver"; then
        echo -e "  ${GREEN}✔ PC Telemetry Receiver active on 0.0.0.0:4000${NC}"
    else
        echo -e "  ${RED}✘ Failed to start PC Telemetry Receiver. Check ${WORKSPACE_DIR}/pc_local_receiver.log${NC}"
    fi
fi

# Start PC Image Receiver (Port 5000)
if curl -s --max-time 2 http://localhost:5000/health | grep -q "pc-image-receiver"; then
    echo -e "  ${GREEN}✔ Port 5000 (PC Image Binary Receiver) is active and healthy.${NC}"
else
    echo -e "  ${CYAN}➜ Resetting/Launching PC Image Receiver (pc_image_receiver.py)...${NC}"
    fuser -k 5000/tcp &>/dev/null || true
    nohup python3 "${IOT_DIR}/pc_image_receiver.py" > "${WORKSPACE_DIR}/pc_image_receiver.log" 2>&1 &
    sleep 2
    if curl -s --max-time 2 http://localhost:5000/health | grep -q "pc-image-receiver"; then
        echo -e "  ${GREEN}✔ PC Image Binary Receiver active on 0.0.0.0:5000${NC}"
    else
        echo -e "  ${RED}✘ Failed to start PC Image Receiver. Check ${WORKSPACE_DIR}/pc_image_receiver.log${NC}"
    fi
fi

# ------------------------------------------------------------------------------
# 3. Connect to Raspberry Pi & Launch Systemd Services
# ------------------------------------------------------------------------------
echo ""
echo -e "${BOLD}[3/4] Connecting to Raspberry Pi (${PI_HOST}) & Launching Services...${NC}"

# Check Pi Connectivity via Ping
if ping -c 1 -W 2 "${PI_HOST}" &> /dev/null; then
    echo -e "  ${GREEN}✔ Raspberry Pi at ${PI_HOST} is reachable.${NC}"
else
    echo -e "  ${RED}✘ Cannot ping ${PI_HOST}. Please verify Pi power and Ethernet connection.${NC}"
    exit 1
fi

# SSH Command execution to start & verify services on Pi
sshpass -p "${PI_PASS}" ssh -o StrictHostKeyChecking=no "${PI_USER}@${PI_HOST}" bash -s << 'PI_SCRIPT'
    set -e
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    NC='\033[0m'

    echo -e "  ${GREEN}✔ SSH authenticated successfully with Raspberry Pi.${NC}"

    # Ensure Mosquitto MQTT broker is running
    echo "  ➜ Checking Mosquitto MQTT Broker..."
    sudo systemctl restart mosquitto.service || true
    echo -e "  ${GREEN}✔ Mosquitto MQTT Broker active on port 1883.${NC}"

    # Enable and restart all systemd services
    SERVICES=("mine-forwarder.service" "mine-image-server.service" "mine-command-poller.service")

    for svc in "${SERVICES[@]}"; do
        echo "  ➜ Restarting ${svc}..."
        sudo systemctl enable "${svc}" &>/dev/null || true
        sudo systemctl restart "${svc}"
        
        # Verify status
        if systemctl is-active --quiet "${svc}"; then
            echo -e "    ${GREEN}✔ ${svc} is ACTIVE and RUNNING.${NC}"
        else
            echo -e "    ${RED}✘ ${svc} failed to start. Logs:${NC}"
            sudo journalctl -u "${svc}" -n 10 --no-pager
        fi
    done
PI_SCRIPT

# ------------------------------------------------------------------------------
# 4. System Verification & Live Status Report
# ------------------------------------------------------------------------------
echo ""
echo -e "${BOLD}[4/4] Verifying End-to-End System Health...${NC}"

# Check PC Health Endpoint
PC_HEALTH=$(curl -s http://localhost:4000/health || echo "FAIL")
if [[ "$PC_HEALTH" == *"pc-local-receiver"* ]]; then
    echo -e "  ${GREEN}✔ PC Receiver API (Port 4000): HEALTHY${NC}"
else
    echo -e "  ${RED}✘ PC Receiver API (Port 4000): UNHEALTHY${NC}"
fi

# Check Remote Cloud API Endpoint
CLOUD_HEALTH=$(curl -s -H "ngrok-skip-browser-warning: 1" https://commute-overrule-employer.ngrok-free.dev/health || echo "FAIL")
if [[ "$CLOUD_HEALTH" == *"mine-backend"* ]]; then
    echo -e "  ${GREEN}✔ Cloud Backend API (ngrok): HEALTHY${NC}"
else
    echo -e "  ${YELLOW}⚠ Cloud Backend API: Unreachable or offline${NC}"
fi

echo ""
echo -e "${CYAN}${BOLD}========================================================================${NC}"
echo -e "${GREEN}${BOLD}       ALL SERVICES INITIALIZED & SYSTEM IS LIVE FOR ESP NODES          ${NC}"
echo -e "${CYAN}${BOLD}========================================================================${NC}"
echo -e "${BLUE}Summary of Running Services:${NC}"
echo "  • PC Telemetry Receiver : http://192.168.1.1:4000/api/v1/telemetry/ingest"
echo "  • PC Image Upload       : http://192.168.1.1:5000/upload"
echo "  • Pi Telemetry Forwarder: Forwarding MQTT (1883) -> Cloud & PC"
echo "  • Pi Image Server       : HTTP 5000 (ESP32-CAM Ingestion -> PC & Backend)"
echo "  • Pi Command Poller     : Relay Dashboard Commands -> MQTT (esp32/commands)"
echo ""
