#!/usr/bin/env python3
"""PiKiosk Web Admin — auto-generates config UI from YAML."""

import http.server
import json
import os
import re
import subprocess
import yaml

CONFIG_FILE = "/etc/pikiosk/config.yaml"
PORT = int(os.environ.get("PIKIOSK_ADMIN_PORT", 8080))


def parse_config_fields():
    """Parse config.yaml with comments to generate form field descriptors."""
    fields = []
    with open(CONFIG_FILE) as f:
        raw = f.read()
    config = yaml.safe_load(raw)

    lines = raw.splitlines()
    parent = None
    pending_comments = []

    for line in lines:
        stripped = line.strip()

        # Accumulate comments
        if stripped.startswith("#"):
            text = stripped.lstrip("# ").strip()
            if text and not text.startswith("---"):
                pending_comments.append(text)
            continue

        # Skip blanks
        if not stripped:
            pending_comments = []
            continue

        # Parse key: value
        m = re.match(r'^(\s*)([\w_]+)\s*:\s*(.*)', line)
        if not m:
            pending_comments = []
            continue

        indent, key, val_raw = m.group(1), m.group(2), m.group(3).strip()

        # Track parent sections
        if not indent:
            if val_raw == "" or val_raw.startswith("#"):
                parent = key
                pending_comments = []
                continue
            else:
                dotted_key = key
        else:
            dotted_key = f"{parent}.{key}" if parent else key

        # Get value from parsed config
        parts = dotted_key.split(".")
        obj = config
        for p in parts[:-1]:
            obj = obj.get(p, {}) if isinstance(obj, dict) else {}
        value = obj.get(parts[-1], "") if isinstance(obj, dict) else ""

        # Infer type
        field_type = "text"
        if isinstance(value, bool):
            field_type = "checkbox"
        elif isinstance(value, int):
            field_type = "number"
        elif isinstance(value, str) and re.match(r'^\d{2}:\d{2}$', value):
            field_type = "time"

        # Use last comment as label, earlier ones as help
        if pending_comments:
            label = pending_comments[-1]
            help_text = " ".join(pending_comments[:-1]) if len(pending_comments) > 1 else ""
        else:
            label = key.replace("_", " ").title()
            help_text = ""

        fields.append({
            "key": dotted_key,
            "label": label,
            "help": help_text,
            "value": value,
            "type": field_type,
        })
        pending_comments = []

    # Add commented-out keys that are valid but not active
    commented_keys = {
        "display.on": {"label": "Display on time", "help": "HDMI-CEC power on schedule", "type": "time"},
        "display.off": {"label": "Display off time", "help": "HDMI-CEC standby schedule", "type": "time"},
        "network.wait_host": {"label": "Wait host", "help": "Host to ping before launching browser", "type": "text"},
    }
    existing_keys = {f["key"] for f in fields}
    for key, meta in commented_keys.items():
        if key not in existing_keys:
            fields.append({
                "key": key,
                "label": meta["label"],
                "help": meta["help"],
                "value": "",
                "type": meta["type"],
            })

    return fields


def get_status():
    """Get kiosk status info."""
    try:
        result = subprocess.run(
            ["pikiosk", "status"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception:
        return "Unable to get status"


HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PiKiosk Admin</title>
<style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           background: #f5f5f5; color: #333; padding: 1rem; max-width: 640px; margin: 0 auto; }
    h1 { font-size: 1.4rem; margin-bottom: 0.5rem; }
    .status { background: #e8f5e9; border: 1px solid #c8e6c9; border-radius: 6px;
              padding: 0.75rem; margin-bottom: 1rem; font-family: monospace;
              font-size: 0.85rem; white-space: pre-line; }
    .status.error { background: #ffebee; border-color: #ffcdd2; }
    .card { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            padding: 1rem; margin-bottom: 0.75rem; }
    .card h2 { font-size: 1rem; color: #666; margin-bottom: 0.75rem;
               border-bottom: 1px solid #eee; padding-bottom: 0.5rem; }
    .field { margin-bottom: 0.75rem; }
    .field:last-child { margin-bottom: 0; }
    .field label { display: block; font-weight: 600; font-size: 0.9rem; margin-bottom: 0.2rem; }
    .field .help { font-size: 0.8rem; color: #888; margin-bottom: 0.3rem; }
    .field input[type="text"], .field input[type="number"], .field input[type="time"] {
        width: 100%; padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px;
        font-size: 0.95rem; }
    .field input:focus { outline: none; border-color: #4a90d9; box-shadow: 0 0 0 2px rgba(74,144,217,0.2); }
    .field.checkbox-field { display: flex; align-items: center; gap: 0.5rem; }
    .field.checkbox-field label { margin-bottom: 0; }
    .field.checkbox-field input { width: 1.2rem; height: 1.2rem; }
    .actions { margin-top: 1rem; display: flex; gap: 0.5rem; }
    button { padding: 0.6rem 1.2rem; border: none; border-radius: 6px; font-size: 0.95rem;
             cursor: pointer; font-weight: 600; }
    .btn-save { background: #4a90d9; color: #fff; }
    .btn-save:hover { background: #357abd; }
    .btn-save:disabled { background: #aaa; cursor: not-allowed; }
    .btn-reload { background: #e0e0e0; color: #333; }
    .btn-reload:hover { background: #d0d0d0; }
    .btn-reboot { background: #f0ad4e; color: #fff; }
    .btn-reboot:hover { background: #ec971f; }
    .btn-shutdown { background: #d9534f; color: #fff; }
    .btn-shutdown:hover { background: #c9302c; }
    .power-actions { margin-top: 1rem; display: flex; gap: 0.5rem; }
    .confirm-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                       background: rgba(0,0,0,0.5); z-index: 100; align-items: center; justify-content: center; }
    .confirm-overlay.show { display: flex; }
    .confirm-box { background: #fff; border-radius: 8px; padding: 1.5rem; max-width: 320px;
                   text-align: center; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
    .confirm-box p { margin-bottom: 1rem; font-size: 1rem; }
    .confirm-box .actions { display: flex; gap: 0.5rem; justify-content: center; }
    .toast { position: fixed; bottom: 1rem; left: 50%; transform: translateX(-50%);
             background: #333; color: #fff; padding: 0.6rem 1.2rem; border-radius: 6px;
             font-size: 0.9rem; opacity: 0; transition: opacity 0.3s; pointer-events: none; }
    .toast.show { opacity: 1; }
</style>
</head>
<body>
<h1>PiKiosk Admin</h1>
<div class="status" id="status">Loading...</div>

<form id="configForm">
%%FIELDS%%
<div class="actions">
    <button type="submit" class="btn-save" id="saveBtn">Save &amp; Apply</button>
    <button type="button" class="btn-reload" onclick="reloadKiosk()">Reload Kiosk</button>
</div>
</form>

<div class="card">
    <h2>System</h2>
    <div class="power-actions">
        <button type="button" class="btn-reboot" onclick="confirmAction('reboot')">Reboot</button>
        <button type="button" class="btn-shutdown" onclick="confirmAction('shutdown')">Shutdown</button>
    </div>
</div>

<div class="confirm-overlay" id="confirmOverlay">
    <div class="confirm-box">
        <p id="confirmMsg"></p>
        <div class="actions">
            <button class="btn-save" id="confirmBtn" onclick="doAction()">Confirm</button>
            <button class="btn-reload" onclick="cancelAction()">Cancel</button>
        </div>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
const originalValues = {};

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-key]').forEach(el => {
        const key = el.dataset.key;
        originalValues[key] = el.type === 'checkbox' ? el.checked : el.value;
    });
    refreshStatus();
});

function showToast(msg, duration) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), duration || 2000);
}

async function refreshStatus() {
    try {
        const r = await fetch('/api/status');
        const data = await r.json();
        const el = document.getElementById('status');
        el.textContent = data.status;
        el.className = data.status.includes('RUNNING') ? 'status' : 'status error';
    } catch(e) {
        document.getElementById('status').textContent = 'Unable to fetch status';
    }
}

document.getElementById('configForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('saveBtn');
    btn.disabled = true;
    btn.textContent = 'Saving...';

    const changes = [];
    document.querySelectorAll('[data-key]').forEach(el => {
        const key = el.dataset.key;
        const val = el.type === 'checkbox' ? el.checked.toString() : el.value;
        const orig = typeof originalValues[key] === 'boolean'
            ? originalValues[key].toString() : (originalValues[key] || '');
        if (val !== orig) {
            changes.push({key, value: val});
        }
    });

    if (changes.length === 0) {
        showToast('No changes to save');
        btn.disabled = false;
        btn.textContent = 'Save & Apply';
        return;
    }

    let errors = [];
    for (const c of changes) {
        try {
            const r = await fetch('/api/set', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(c)
            });
            const data = await r.json();
            if (!data.ok) errors.push(data.error || 'Unknown error');
            else originalValues[c.key] = c.value;
        } catch(e) {
            errors.push(e.message);
        }
    }

    if (errors.length) {
        showToast('Errors: ' + errors.join(', '), 4000);
    } else {
        showToast('Saved ' + changes.length + ' setting(s)');
    }

    btn.disabled = false;
    btn.textContent = 'Save & Apply';
    refreshStatus();
});

let pendingAction = null;

function confirmAction(action) {
    pendingAction = action;
    const msg = action === 'shutdown'
        ? 'Shut down this Pi? You will need physical access to power it back on.'
        : 'Reboot this Pi? It will be unavailable for about a minute.';
    document.getElementById('confirmMsg').textContent = msg;
    document.getElementById('confirmBtn').className = action === 'shutdown' ? 'btn-shutdown' : 'btn-reboot';
    document.getElementById('confirmOverlay').classList.add('show');
}

function cancelAction() {
    pendingAction = null;
    document.getElementById('confirmOverlay').classList.remove('show');
}

async function doAction() {
    const action = pendingAction;
    cancelAction();
    showToast(action === 'shutdown' ? 'Shutting down...' : 'Rebooting...', 5000);
    try {
        await fetch('/api/' + action, {method: 'POST'});
    } catch(e) {
        // Connection will drop on success, so errors are expected
    }
}

async function reloadKiosk() {
    showToast('Reloading kiosk...');
    try {
        const r = await fetch('/api/reload', {method: 'POST'});
        const data = await r.json();
        showToast(data.ok ? 'Kiosk reloading' : ('Error: ' + data.error), 3000);
    } catch(e) {
        showToast('Error: ' + e.message, 3000);
    }
    setTimeout(refreshStatus, 3000);
}
</script>
</body>
</html>"""


def build_field_html(field):
    """Render a single form field."""
    key = field["key"]
    label = field["label"]
    help_text = field["help"]
    value = field["value"]
    ftype = field["type"]

    help_html = f'<div class="help">{help_text}</div>' if help_text else ""

    if ftype == "checkbox":
        checked = "checked" if value else ""
        return f'''<div class="field checkbox-field">
            <input type="checkbox" data-key="{key}" id="f-{key}" {checked}>
            <label for="f-{key}">{label}</label>
            {help_html}
        </div>'''

    value_attr = f'value="{value}"' if value != "" else ""
    return f'''<div class="field">
            <label for="f-{key}">{label}</label>
            {help_html}
            <input type="{ftype}" data-key="{key}" id="f-{key}" {value_attr}>
        </div>'''


def build_html(fields):
    """Build complete HTML from fields, grouped by section."""
    sections = {}
    for f in fields:
        parts = f["key"].split(".")
        section = parts[0] if len(parts) > 1 else "general"
        sections.setdefault(section, []).append(f)

    section_labels = {
        "general": "General",
        "display": "Display",
        "network": "Network",
        "watchdog": "Memory Watchdog",
    }

    fields_html = ""
    for section, section_fields in sections.items():
        label = section_labels.get(section, section.title())
        inner = "\n".join(build_field_html(f) for f in section_fields)
        fields_html += f'<div class="card"><h2>{label}</h2>{inner}</div>\n'

    return HTML_TEMPLATE.replace("%%FIELDS%%", fields_html)


class AdminHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # quiet logs

    def do_GET(self):
        if self.path == "/":
            fields = parse_config_fields()
            html = build_html(fields)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())
        elif self.path == "/api/status":
            status = get_status()
            self.send_json({"status": status})
        elif self.path == "/api/config":
            fields = parse_config_fields()
            self.send_json({"fields": fields})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/set":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                key = body.get("key", "")
                value = body.get("value", "")

                if not key or len(key) > 50 or len(str(value)) > 500:
                    self.send_json({"ok": False, "error": "Invalid input"})
                    return

                result = subprocess.run(
                    ["pikiosk", "set", key, str(value)],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    self.send_json({"ok": True, "output": result.stdout.strip()})
                else:
                    self.send_json({"ok": False, "error": result.stderr.strip() or result.stdout.strip()})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})

        elif self.path == "/api/reload":
            try:
                result = subprocess.run(
                    ["pikiosk", "reload"],
                    capture_output=True, text=True, timeout=10
                )
                self.send_json({"ok": result.returncode == 0, "output": result.stdout.strip()})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})

        elif self.path == "/api/shutdown":
            self.send_json({"ok": True, "output": "Shutting down..."})
            subprocess.Popen(["shutdown", "-h", "now"])

        elif self.path == "/api/reboot":
            self.send_json({"ok": True, "output": "Rebooting..."})
            subprocess.Popen(["shutdown", "-r", "now"])

        else:
            self.send_error(404)

    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    server = http.server.HTTPServer(("0.0.0.0", PORT), AdminHandler)
    print(f"PiKiosk Admin running on http://0.0.0.0:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()


if __name__ == "__main__":
    main()
