"""pywebview GUI for the Automonous server console.

Ship with PyInstaller:  pyinstaller --onefile --windowed --name Automonous gui_console.py
Reuses the actions from server_console.py (start/stop/status/backup/restore).
"""

import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import server_console as sc
from server_console import BACKUP_DIR, URL
import updates
import webview

_BASE_DIR = (
    Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    if getattr(sys, "frozen", False)
    else Path(__file__).parent
)


class Api:
    def __init__(self):
        self.window = None

    def get_state(self):
        backups = []
        try:
            for p in sc._list_backups():
                backups.append({
                    "filename": p.name,
                    "timestamp": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "sizeBytes": p.stat().st_size,
                })
        except Exception:
            pass

        logs = []
        try:
            if sc.LOG_FILE.exists():
                logs = sc.LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            pass

        return {
            "isRunning": bool(sc.running_pid()),
            "pid": sc.running_pid(),
            "url": sc.URL,
            "port": sc.PORT,
            "baseDir": str(sc.BASE_DIR),
            "browserEngine": "System Chrome/Edge (Stealth)",
            "backups": backups,
            "logs": logs[-300:],
        }

    def start_server(self):
        ok, msg = sc.start_server()
        return msg

    def stop_server(self):
        ok, msg = sc.stop_server()
        return msg

    def open_browser(self):
        webbrowser.open(sc.URL)
        return "Opened browser."

    def create_backup(self):
        ok, msg = sc.create_backup()
        return msg

    def restore_backup(self, filename):
        path = sc.BACKUP_DIR / filename
        ok, msg = sc.perform_restore(path)
        return msg

    def clear_logs(self):
        try:
            if sc.LOG_FILE.exists():
                sc.LOG_FILE.write_text("", encoding="utf-8")
        except Exception:
            pass
        return "Log cleared."

    def check_updates(self):
        info = updates.check_update()
        if not info:
            return "Update check failed (no internet?)."
        current = updates.APP_VERSION
        latest = info["version"]
        if updates._version_tuple(latest) <= updates._version_tuple(current):
            return f"Already up to date (v{current})."
        if not info.get("installer"):
            return f"Update available (v{latest}) but no installer found."
        return f"Update available: v{latest}"


def _launch_server():
    started = False
    if not sc.running_pid():
        ok, msg = sc.start_server()
        started = ok
        if not ok:
            return
    for _ in range(20):
        ok, msg = sc.server_status()
        if ok and "responding" in msg:
            break
        time.sleep(0.5)
    webbrowser.open(sc.URL)
    if getattr(sys, "frozen", False) and started:
        while sc.running_pid():
            time.sleep(2)


def _serve_only():
    ok, msg = sc.start_server()
    if not ok and "already" not in msg.lower():
        return
    while sc.running_pid():
        time.sleep(2)


def main():
    if "--launch" in sys.argv:
        _launch_server()
        return
    if "--serve" in sys.argv:
        _serve_only()
        return

    html_path = _BASE_DIR / "static" / "server_console.html"
    api = Api()
    window = webview.create_window(
        "Automonous Server Console",
        url=str(html_path),
        js_api=api,
        width=1120,
        height=780,
        min_size=(900, 620),
    )
    api.window = window
    webview.start()


if __name__ == "__main__":
    main()
