#!/usr/bin/env bash
# PiKiosk installer
# Run as root: sudo bash install.sh
#
# What this does:
#   1. Installs Cage (Wayland compositor) and Chromium
#   2. Creates a 'kiosk' user with autologin on TTY1
#   3. Installs the launcher and config
#   4. Optionally sets up memory watchdog and display hours
#
# Tested on: Raspberry Pi OS Lite (Debian 13 / Trixie, 32-bit)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="/etc/pikiosk"
KIOSK_USER="kiosk"

# --- Checks ---

if [ "$EUID" -ne 0 ]; then
    echo "Error: run as root (sudo bash install.sh)"
    exit 1
fi

if ! grep -q 'Raspberry Pi' /proc/cpuinfo 2>/dev/null; then
    echo "Warning: this doesn't look like a Raspberry Pi. Continuing anyway."
fi

# --- Packages ---

echo "=== Installing packages ==="
apt-get update -qq
apt-get install -y -qq cage chromium

# CEC control (optional, for display hours)
if command -v cec-client &>/dev/null; then
    echo "  cec-utils already installed"
else
    echo "  Installing cec-utils for HDMI-CEC display control..."
    apt-get install -y -qq cec-utils || echo "  Warning: cec-utils not available, display hours won't work"
fi

# --- Kiosk user ---

echo "=== Setting up kiosk user ==="
if id "$KIOSK_USER" &>/dev/null; then
    echo "  User '$KIOSK_USER' already exists"
else
    useradd -m -s /bin/bash "$KIOSK_USER"
    echo "  Created user '$KIOSK_USER'"
fi

# Required groups for Wayland/DRM access
usermod -aG video,render,input "$KIOSK_USER"
echo "  Added to video, render, input groups"

# --- GPU memory ---

echo "=== Configuring GPU memory ==="
GPU_MEM=$(python3 -c "
import yaml
with open('$SCRIPT_DIR/config.yaml') as f:
    c = yaml.safe_load(f)
print(c.get('display', {}).get('gpu_memory', 128))
" 2>/dev/null || echo "128")

CONFIG_TXT="/boot/firmware/config.txt"
if [ -f "$CONFIG_TXT" ]; then
    if grep -q "^gpu_mem=" "$CONFIG_TXT"; then
        sed -i "s/^gpu_mem=.*/gpu_mem=$GPU_MEM/" "$CONFIG_TXT"
    else
        echo "gpu_mem=$GPU_MEM" >> "$CONFIG_TXT"
    fi
    echo "  Set gpu_mem=$GPU_MEM in $CONFIG_TXT"
else
    echo "  Warning: $CONFIG_TXT not found, set gpu_mem=$GPU_MEM manually"
fi

# --- TTY1 autologin ---

echo "=== Configuring TTY1 autologin ==="
OVERRIDE_DIR="/etc/systemd/system/getty@tty1.service.d"
mkdir -p "$OVERRIDE_DIR"
cat > "$OVERRIDE_DIR/autologin.conf" <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $KIOSK_USER --noclear %I \$TERM
EOF
echo "  TTY1 will autologin as '$KIOSK_USER'"

# --- Install config and launcher ---

echo "=== Installing PiKiosk files ==="
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    cp "$SCRIPT_DIR/config.yaml" "$CONFIG_DIR/config.yaml"
    echo "  Installed config to $CONFIG_DIR/config.yaml"
else
    echo "  Config already exists at $CONFIG_DIR/config.yaml (not overwritten)"
fi

# Install launcher script
cp "$SCRIPT_DIR/pikiosk" /usr/local/bin/pikiosk
chmod +x /usr/local/bin/pikiosk
echo "  Installed launcher to /usr/local/bin/pikiosk"

# Install .bash_profile for kiosk user
KIOSK_HOME=$(eval echo "~$KIOSK_USER")
cat > "$KIOSK_HOME/.bash_profile" <<'PROFILE'
# PiKiosk launcher — starts Cage on TTY1 login
# Do not edit manually; managed by pikiosk install

# Guard: only launch on TTY1 console, not SSH
[ "$(tty)" = "/dev/tty1" ] || return
[ -z "$WAYLAND_DISPLAY" ] || return

exec pikiosk start
PROFILE
chown "$KIOSK_USER:$KIOSK_USER" "$KIOSK_HOME/.bash_profile"
echo "  Installed .bash_profile for $KIOSK_USER"

# --- Memory watchdog ---

echo "=== Configuring memory watchdog ==="
WATCHDOG_ENABLED=$(python3 -c "
import yaml
with open('$CONFIG_DIR/config.yaml') as f:
    c = yaml.safe_load(f)
print(c.get('watchdog', {}).get('enabled', True))
" 2>/dev/null || echo "True")

WATCHDOG_THRESHOLD=$(python3 -c "
import yaml
with open('$CONFIG_DIR/config.yaml') as f:
    c = yaml.safe_load(f)
print(c.get('watchdog', {}).get('threshold', 90))
" 2>/dev/null || echo "90")

WATCHDOG_INTERVAL=$(python3 -c "
import yaml
with open('$CONFIG_DIR/config.yaml') as f:
    c = yaml.safe_load(f)
print(c.get('watchdog', {}).get('interval', 5))
" 2>/dev/null || echo "5")

CRON_FILE="/etc/cron.d/pikiosk-watchdog"
if [ "$WATCHDOG_ENABLED" = "True" ]; then
    THRESHOLD_FRAC=$(echo "scale=2; $WATCHDOG_THRESHOLD / 100" | bc)
    cat > "$CRON_FILE" <<EOF
# PiKiosk memory watchdog — restart browser if RAM exceeds ${WATCHDOG_THRESHOLD}%
*/$WATCHDOG_INTERVAL * * * * root free -m | awk '/^Mem/{if(\$3/\$2 > $THRESHOLD_FRAC) system("pkill cage")}'
EOF
    echo "  Watchdog enabled: ${WATCHDOG_THRESHOLD}% threshold, every ${WATCHDOG_INTERVAL}m"
else
    rm -f "$CRON_FILE"
    echo "  Watchdog disabled"
fi

# --- Display hours ---

echo "=== Configuring display hours ==="
DISPLAY_ON=$(python3 -c "
import yaml
with open('$CONFIG_DIR/config.yaml') as f:
    c = yaml.safe_load(f)
d = c.get('display', {})
print(d.get('on', ''))
" 2>/dev/null || echo "")

DISPLAY_OFF=$(python3 -c "
import yaml
with open('$CONFIG_DIR/config.yaml') as f:
    c = yaml.safe_load(f)
d = c.get('display', {})
print(d.get('off', ''))
" 2>/dev/null || echo "")

CRON_DISPLAY="/etc/cron.d/pikiosk-display"
if [ -n "$DISPLAY_ON" ] && [ -n "$DISPLAY_OFF" ]; then
    ON_H=$(echo "$DISPLAY_ON" | cut -d: -f1)
    ON_M=$(echo "$DISPLAY_ON" | cut -d: -f2)
    OFF_H=$(echo "$DISPLAY_OFF" | cut -d: -f1)
    OFF_M=$(echo "$DISPLAY_OFF" | cut -d: -f2)
    cat > "$CRON_DISPLAY" <<EOF
# PiKiosk display hours — HDMI-CEC power control
$ON_M $ON_H * * * root echo "on 0" | cec-client -s -d 1
$OFF_M $OFF_H * * * root echo "standby 0" | cec-client -s -d 1
EOF
    echo "  Display on at $DISPLAY_ON, standby at $DISPLAY_OFF"
else
    rm -f "$CRON_DISPLAY"
    echo "  Display hours not configured (always on)"
fi

echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit /etc/pikiosk/config.yaml to set your URL"
echo "  2. Reboot to start the kiosk: sudo reboot"
echo ""
echo "Useful commands:"
echo "  pikiosk status     — check if kiosk is running"
echo "  pikiosk reload     — restart with updated config"
echo "  pikiosk stop       — stop the kiosk display"
echo "  pikiosk config     — show current configuration"
