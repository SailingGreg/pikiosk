# PiKiosk

A lightweight kiosk display server for Raspberry Pi. Turns any Pi into a dedicated fullscreen display for dashboards, signage, event boards, or any web page.

## What it does

PiKiosk sets up a Raspberry Pi to boot directly into a fullscreen Chromium browser pointed at a URL you configure. It handles the fiddly bits — Wayland compositor, autologin, crash recovery, memory management, and network readiness — so you just plug in power and HDMI.

## Hardware

- **Tested on:** Raspberry Pi 3B+ (1GB RAM, wired ethernet)
- **Should work on:** Pi 4, Pi 5 (disable `software_render` in config)
- **Recommended:** Wired ethernet for reliability, heatsink for continuous operation

## Quick start

```bash
# 1. Flash Raspberry Pi OS Lite (32-bit, Debian 13 / Trixie)
#    Boot to console with autologin via raspi-config

# 2. Clone and install
git clone https://github.com/SailingGreg/pikiosk.git
cd pikiosk
sudo bash install.sh

# 3. Set your URL
sudo nano /etc/pikiosk/config.yaml

# 4. Reboot
sudo reboot
```

## Configuration

Edit `/etc/pikiosk/config.yaml`:

```yaml
# URL to display (required)
url: "https://your-dashboard.example.com"

# Browser refresh interval in seconds (0 to disable)
refresh: 120

# Display settings
display:
  gpu_memory: 128          # MB allocated to GPU
  software_render: true    # Required for Pi 3B/3B+, disable for Pi 4/5
  # on: "08:00"            # HDMI-CEC power on schedule (optional)
  # off: "22:00"           # HDMI-CEC standby schedule (optional)

# Network settings
network:
  wait_timeout: 120        # Seconds to wait for network before launching

# Memory watchdog (recommended for 1GB models)
watchdog:
  enabled: true
  threshold: 90            # Restart browser if RAM exceeds this %
  interval: 5              # Check every N minutes
```

## Commands

```bash
pikiosk status     # Check if kiosk is running + memory usage
pikiosk config     # Show current configuration
pikiosk reload     # Restart with updated config
pikiosk stop       # Stop the kiosk display
```

## How it works

1. **Boot:** Pi boots to console, TTY1 autologins as `kiosk` user
2. **Network gate:** Pings the target host until DNS/network is available
3. **Launch:** [Cage](https://github.com/cage-kiosk/cage) (minimal Wayland compositor) starts Chromium in kiosk mode
4. **Crash recovery:** If Cage or Chromium crash, they restart automatically after 5 seconds
5. **Memory watchdog:** Cron job monitors RAM usage and restarts the browser if it exceeds the threshold

Cage was chosen over X11 because it's purpose-built for single-application fullscreen display — minimal overhead, no window management, no desktop environment.

## Pi 3B+ notes

The Pi 3B+ lacks OpenGL ES 3.0 support, so Chromium needs software rendering flags. These are enabled by default (`software_render: true`). Disable this on Pi 4/5 for better performance.

The 1GB RAM limit means Chromium can gradually consume all available memory. The memory watchdog handles this by killing and restarting the browser when usage exceeds the configured threshold.

## Display hours (optional)

If your Pi is connected to a CEC-capable TV/monitor, PiKiosk can turn the display on and off on a schedule:

```yaml
display:
  on: "08:00"
  off: "22:00"
```

Requires `cec-utils` (installed automatically if available).

## SSH access

The kiosk launcher only runs on TTY1 — SSH sessions are unaffected. You can always SSH in to manage the Pi, edit config, or troubleshoot.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Black screen on boot | Check `pikiosk status` via SSH. Verify URL is reachable: `curl -sf <url>` |
| Browser shows white/error page | Network may not be ready. Check `wait_timeout` in config |
| High memory usage / freezing | Enable watchdog or lower threshold |
| No display power control | Install `cec-utils`: `sudo apt install cec-utils` |
| Cage won't start | Verify `kiosk` user is in `video,render,input` groups |

## License

MIT
