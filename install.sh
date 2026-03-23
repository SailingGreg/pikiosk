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
apt-get install -y -qq cage chromium bc

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

# --- Web admin UI ---

echo "=== Installing admin web UI ==="
mkdir -p /usr/local/lib/pikiosk
cp "$SCRIPT_DIR/admin.py" /usr/local/lib/pikiosk/admin.py
cp "$SCRIPT_DIR/pikiosk-admin.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable pikiosk-admin
systemctl restart pikiosk-admin
echo "  Admin UI enabled on port 8080"

# --- Apply config (cron jobs, display hours) ---

echo "=== Applying configuration ==="
/usr/local/bin/pikiosk apply

echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit config at /etc/pikiosk/config.yaml or http://$(hostname -I | awk '{print $1}'):8080"
echo "  2. Reboot to start the kiosk: sudo reboot"
echo ""
echo "Useful commands:"
echo "  pikiosk status     — check if kiosk is running"
echo "  pikiosk reload     — restart with updated config"
echo "  pikiosk stop       — stop the kiosk display"
echo "  pikiosk config     — show current configuration"
echo "  pikiosk set <k> <v> — update a config setting"
