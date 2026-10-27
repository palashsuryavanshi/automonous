"""tkinter GUI for the Automonous server console.

Ship with PyInstaller:  pyinstaller --onefile --windowed --name Automonous gui_console.py
Reuses the actions from server_console.py (start/stop/status/backup/restore).
"""

import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import server_console as sc
from server_console import BACKUP_DIR, URL
import updates

_ANSI = re.compile(r"\033\[[0-9;]*m")

COLOR_RUNNING = "#10b981"
COLOR_STOPPED = "#737373"
COLOR_STALE = "#f59e0b"


def _icon_path():
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        for candidate in (base / "logo.ico", base / "static" / "logo.ico"):
            if candidate.exists():
                return candidate
        return base / "logo.ico"
    return Path(__file__).parent / "static" / "logo.ico"


def _apply_icon(root):
    icon = _icon_path()
    if icon.exists():
        try:
            root.iconbitmap(str(icon))
        except Exception:
            pass


def _configure_style(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(".", background="#0a0a0a", foreground="#f5f5f5", font=("Segoe UI", 10))
    style.configure("TFrame", background="#0a0a0a")
    style.configure("TLabel", background="#0a0a0a", foreground="#f5f5f5")
    style.configure("TButton", background="#10b981", foreground="#0a0a0a", font=("Segoe UI", 10, "bold"), borderwidth=0, padding=8)
    style.map("TButton", background=[("active", "#059669"), ("disabled", "#262626")], foreground=[("disabled", "#737373")])


class ServerConsoleGUI:
    def __init__(self, root):
        self.root = root
        root.title("Automonous Server Console")
        root.geometry("980x720")
        root.minsize(860, 620)
        root.configure(bg="#0a0a0a")

        _apply_icon(root)
        _configure_style(root)

        self._log_pos = 0
        self._last_state = None
        self._selected_backup = None

        self._build_ui()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(400, self._auto_start)
        self._refresh_backups()
        self._poll()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        main = tk.Frame(self.root, bg="#0a0a0a")
        main.pack(fill="both", expand=True, padx=16, pady=16)

        # Top banner
        banner = tk.Frame(main, bg="#171717", highlightbackground="#262626", highlightthickness=1)
        banner.pack(fill="x", pady=(0, 16))

        head = tk.Frame(banner, bg="#171717")
        head.pack(fill="x", padx=16, pady=14)

        tk.Label(head, text="AUTOMONOUS CONTROL PANEL (GUI CONSOLE)", bg="#171717", fg="#f5f5f5",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(head, text="Host process supervisor, Flask runtime server, and encrypted credential backup manager.",
                 bg="#171717", fg="#a3a3b3", font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))

        status_row = tk.Frame(banner, bg="#171717")
        status_row.pack(fill="x", padx=16, pady=(0, 14))

        self.status_badge = tk.Label(status_row, text="STOPPED", bg="#262626", fg="#737373",
                                    font=("Consolas", 10, "bold"), padx=10, pady=4)
        self.status_badge.pack(side="left")

        self.feedback_label = tk.Label(status_row, text="", bg="#171717", fg="#10b981", font=("Consolas", 10))
        self.feedback_label.pack(side="right")

        # Primary controls
        controls = tk.Frame(main, bg="#0a0a0a")
        controls.pack(fill="x", pady=(0, 16))

        btn_grid = tk.Frame(controls, bg="#0a0a0a")
        btn_grid.pack(fill="x")

        self.btn_start = tk.Button(btn_grid, text="Start Server", command=self._start,
                                   bg="#10b981", fg="#0a0a0a", font=("Segoe UI", 10, "bold"),
                                   relief="flat", padx=12, pady=8, cursor="hand2")
        self.btn_start.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.btn_stop = tk.Button(btn_grid, text="Stop Server", command=self._stop,
                                  bg="#f43f5e", fg="#ffffff", font=("Segoe UI", 10, "bold"),
                                  relief="flat", padx=12, pady=8, cursor="hand2")
        self.btn_stop.grid(row=0, column=1, sticky="ew", padx=8, pady=4)

        self.btn_browser = tk.Button(btn_grid, text="Open Browser", command=self._open_browser,
                                     bg="#262626", fg="#e5e5e5", font=("Segoe UI", 10, "bold"),
                                     relief="flat", padx=12, pady=8, cursor="hand2")
        self.btn_browser.grid(row=0, column=2, sticky="ew", padx=8, pady=4)

        self.btn_backup = tk.Button(btn_grid, text="Backup Store", command=self._backup,
                                    bg="#262626", fg="#e5e5e5", font=("Segoe UI", 10, "bold"),
                                    relief="flat", padx=12, pady=8, cursor="hand2")
        self.btn_backup.grid(row=0, column=3, sticky="ew", padx=(8, 0), pady=4)

        for i in range(4):
            btn_grid.columnconfigure(i, weight=1)

        # URL bar
        url_bar = tk.Frame(main, bg="#0a0a0a", highlightbackground="#262626", highlightthickness=1)
        url_bar.pack(fill="x", pady=(0, 16))

        self.url_label = tk.Label(url_bar, text=f"Serving at: {URL}    Port: 5000 (TAX_PORT)",
                                  bg="#0a0a0a", fg="#a3a3b3", font=("Consolas", 10), padx=12, pady=8)
        self.url_label.pack(anchor="w")

        # Split layout
        split = tk.Frame(main, bg="#0a0a0a")
        split.pack(fill="both", expand=True)

        # Left column
        left = tk.Frame(split, bg="#0a0a0a")
        left.pack(side="left", fill="both", expand=False, padx=(0, 12))

        backup_card = tk.Frame(left, bg="#171717", highlightbackground="#262626", highlightthickness=1)
        backup_card.pack(fill="both", expand=True)

        bh = tk.Frame(backup_card, bg="#171717")
        bh.pack(fill="x", padx=12, pady=10)
        tk.Label(bh, text="Encrypted Backups (backups/)", bg="#171717", fg="#f5f5f5",
                 font=("Consolas", 10, "bold")).pack(side="left")
        self.backup_count_label = tk.Label(bh, text="0 Available", bg="#171717", fg="#737373", font=("Consolas", 9))
        self.backup_count_label.pack(side="right")

        tk.Label(backup_card, text="Backups store zipped archives of credentials.enc, .secrets/master.key, and secret.key.",
                 bg="#171717", fg="#a3a3b3", font=("Segoe UI", 9), wraplength=360, justify="left").pack(anchor="w", padx=12)

        self.backup_listbox = tk.Listbox(backup_card, bg="#0a0a0a", fg="#e5e5e5", font=("Consolas", 10),
                                        selectbackground="#10b981", selectforeground="#0a0a0a",
                                        highlightthickness=0, relief="flat", height=12)
        self.backup_listbox.pack(fill="both", expand=True, padx=12, pady=10)
        self.backup_listbox.bind("<<ListboxSelect>>", self._on_backup_select)

        self.btn_restore = tk.Button(backup_card, text="Restore Selected", command=self._restore,
                                     bg="#f59e0b", fg="#0a0a0a", font=("Segoe UI", 10, "bold"),
                                     relief="flat", padx=12, pady=8, cursor="hand2")
        self.btn_restore.pack(fill="x", padx=12, pady=(0, 12))

        env_card = tk.Frame(left, bg="#0a0a0a", highlightbackground="#262626", highlightthickness=1)
        env_card.pack(fill="x", pady=(12, 0))

        tk.Label(env_card, text="ENVIRONMENT & PATHS", bg="#0a0a0a", fg="#737373", font=("Consolas", 9, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        env_lines = [
            "BASE_DIR: " + str(BACKUP_DIR.parent),
            "PID_FILE: .server.pid",
            "LOG_FILE: server.log",
            "ENGINE: System Chrome/Edge (Stealth)",
        ]
        for line in env_lines:
            tk.Label(env_card, text=line, bg="#0a0a0a", fg="#a3a3b3", font=("Consolas", 9), anchor="w").pack(anchor="w", padx=12, pady=1)

        tk.Label(env_card, text="", bg="#0a0a0a").pack(pady=4)

        # Right column
        right = tk.Frame(split, bg="#0a0a0a")
        right.pack(side="right", fill="both", expand=True)

        log_card = tk.Frame(right, bg="#171717", highlightbackground="#262626", highlightthickness=1)
        log_card.pack(fill="both", expand=True)

        lh = tk.Frame(log_card, bg="#171717")
        lh.pack(fill="x", padx=12, pady=10)
        tk.Label(lh, text="server.log Output Tail", bg="#171717", fg="#f5f5f5", font=("Consolas", 10, "bold")).pack(side="left")

        self.btn_clear_log = tk.Button(lh, text="Clear", command=self._clear_logs,
                                      bg="#262626", fg="#e5e5e5", font=("Consolas", 9),
                                      relief="flat", padx=8, pady=3, cursor="hand2")
        self.btn_clear_log.pack(side="right")

        self.log_text = tk.Text(log_card, height=20, wrap="word", state="disabled",
                                font=("Consolas", 9), bg="#0a0a0a", fg="#d4d4d8",
                                insertbackground="#d4d4d8", relief="flat", bd=0)
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Switch to web app button
        sw = tk.Button(main, text="Switch to Web App", command=self._open_browser,
                       bg="#262626", fg="#e5e5e5", font=("Consolas", 10),
                       relief="flat", padx=12, pady=6, cursor="hand2")
        sw.pack(anchor="e", pady=(12, 0))

        self._log("Console ready. Project: " + str(BACKUP_DIR.parent), "info")

    # ---------------------------------------------------------------- utils
    def _log(self, message, tag="info"):
        message = _ANSI.sub("", str(message))
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        for btn in (self.btn_browser, self.btn_backup, self.btn_restore):
            btn.configure(state=state)

    def _set_server_buttons(self, running):
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")

    # -------------------------------------------------------------- poller
    def _poll(self):
        ok, msg = sc.server_status()
        message = _ANSI.sub("", msg)

        if "RUNNING" in message:
            state = "running"
            color = COLOR_RUNNING
            badge_text = "RUNNING"
        elif "STALE" in message:
            state = "stale"
            color = COLOR_STALE
            badge_text = "STALE"
        else:
            state = "stopped"
            color = COLOR_STOPPED
            badge_text = "STOPPED"

        self.status_badge.configure(text=badge_text, fg="#0a0a0a" if state == "running" else "#f5f5f5",
                                   bg=color if state == "running" else "#262626")
        self._set_server_buttons(state == "running")

        if state != self._last_state:
            self._log(message, "ok" if state == "running" else ("warn" if state == "stale" else "info"))
            self._last_state = state

        self._tail_log()
        self.root.after(2000, self._poll)

    def _tail_log(self):
        try:
            log_file = BACKUP_DIR.parent / "server.log"
            with open(log_file, "rb") as fh:
                fh.seek(self._log_pos)
                data = fh.read()
                self._log_pos = fh.tell()
            if data:
                text = data.decode("utf-8", "replace").rstrip()
                for line in text.splitlines():
                    if line.strip():
                        self._log(line)
        except OSError:
            pass

    # ------------------------------------------------------------- actions
    def _auto_start(self):
        if sc.running_pid():
            return
        self._log("Server auto-starting...", "info")
        self._start()

    def _start(self):
        self._set_busy(True)
        self._log("Starting server...", "info")
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self):
        ok, msg = sc.start_server()
        self.root.after(0, lambda: (self._log(msg), self._set_busy(False)))

    def _stop(self):
        self._set_busy(True)
        self._log("Stopping server...", "info")
        threading.Thread(target=self._stop_worker, daemon=True).start()

    def _stop_worker(self):
        ok, msg = sc.stop_server()
        self.root.after(0, lambda: (self._log(msg), self._set_busy(False)))

    def _open_browser(self):
        webbrowser.open(URL)

    def _exe_target(self):
        if getattr(sys, "frozen", False):
            return str(Path(sys.executable).absolute())
        local = Path(__file__).parent / "Automonous.exe"
        if local.exists():
            return str(local)
        return None

    def _create_shortcut(self):
        target = self._exe_target()
        if target is None:
            messagebox.showwarning("Shortcut", "Run the built Automonous.exe instead of the script.")
            return

        escaped_target = target.replace("'", "''")
        escaped_workdir = str(Path(target).parent).replace("'", "''")

        script = (
            "$ws = New-Object -ComObject WScript.Shell;"
            "$d = [Environment]::GetFolderPath('Desktop');"
            "$s = $ws.CreateShortcut($d + '\\Automonous.lnk');"
            f"$s.TargetPath = '{escaped_target}';"
            "$s.Arguments = '--launch';"
            f"$s.WorkingDirectory = '{escaped_workdir}';"
            f"$s.IconLocation = '{escaped_target},0';"
            "$s.Description = 'Start the Automonous web app and open it in the browser';"
            "$s.Save(); Write-Output 'ok'"
        )

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=20, creationflags=0x08000000,
            )
        except Exception as exc:
            messagebox.showerror("Shortcut", f"Failed to create shortcut:\n{exc}")
            return

        if result.returncode == 0 and "ok" in result.stdout:
            messagebox.showinfo("Shortcut", "Desktop shortcut created.")
        else:
            messagebox.showerror("Shortcut", "Failed to create shortcut:\n" + result.stderr.strip())

    def _check_updates(self):
        self._log("Checking for updates...", "info")
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        info = updates.check_update()
        if not info:
            self.root.after(0, lambda: self._log("Update check failed (no internet?)."))
            return
        current = updates.APP_VERSION
        latest = info["version"]
        if updates._version_tuple(latest) <= updates._version_tuple(current):
            self.root.after(0, lambda: self._log(f"Already up to date (v{current})."))
            return
        if not info.get("installer"):
            self.root.after(0, lambda: self._log(f"Update available (v{latest}) but no installer found."))
            return
        self.root.after(0, lambda: self._ask_download(info))

    def _ask_download(self, info):
        answer = messagebox.askyesno("Update available",
                                    f"Automonous {info['version']} is available.\nCurrent: {updates.APP_VERSION}\n\nDownload and install now?")
        if not answer:
            self._log("Update skipped.")
            return
        self._log(f"Downloading {info['installer']['name']}...")
        threading.Thread(target=self._download_worker, args=(info,), daemon=True).start()

    def _download_worker(self, info):
        dest = BACKUP_DIR.parent / "updates"
        try:
            path = updates.download_installer(info["installer"]["url"], dest)
        except Exception as exc:
            self.root.after(0, lambda: self._log(f"Download failed: {exc}"))
            return
        self.root.after(0, lambda: self._run_installer(path))

    def _run_installer(self, path):
        sc.stop_server()
        try:
            os.startfile(str(path))
        except Exception as exc:
            messagebox.showerror("Update", f"Failed to start installer:\n{exc}")
            return
        self._log(f"Installer launched: {path.name}.")
        self.root.after(400, self.root.destroy)

    def _backup(self):
        self._set_busy(True)
        threading.Thread(target=self._backup_worker, daemon=True).start()

    def _backup_worker(self):
        ok, msg = sc.create_backup()
        self.root.after(0, lambda: (self._log(msg), self._set_busy(False), self._refresh_backups()))

    def _on_backup_select(self, event=None):
        sel = self.backup_listbox.curselection()
        if sel:
            self._selected_backup = self.backup_listbox.get(sel[0])

    def _refresh_backups(self):
        self.backup_listbox.delete(0, tk.END)
        backups = sc._list_backups()
        for p in backups:
            self.backup_listbox.insert(tk.END, p.name)
        self.backup_count_label.configure(text=f"{len(backups)} Available")
        if backups:
            self.backup_listbox.selection_set(0)
            self._selected_backup = backups[0].name

    def _restore(self):
        if not self._selected_backup:
            messagebox.showwarning("Restore", "Select a backup first.")
            return
        if not messagebox.askyesno("Restore backup",
                                   f"Restore from '{self._selected_backup}'?\nThis overwrites the current credentials.",
                                   icon="warning"):
            return
        self._set_busy(True)
        threading.Thread(target=self._restore_worker, args=(self._selected_backup,), daemon=True).start()

    def _restore_worker(self, name):
        path = BACKUP_DIR / name
        ok, msg = sc.perform_restore(path)
        self.root.after(0, lambda: (self._log(msg), self._set_busy(False), self._refresh_backups()))

    def _clear_logs(self):
        sc.LOG_FILE.write_text("", encoding="utf-8") if sc.LOG_FILE.exists() else None
        self._log_pos = 0
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")
        self._log("Log cleared.")

    def _on_close(self):
        if sc.running_pid():
            answer = messagebox.askyesnocancel(
                "Server is running",
                "The web server is still running.\n\nYes = stop the server, No = keep it running, Cancel = go back.",
            )
            if answer is None:
                return
            if answer:
                ok, msg = sc.stop_server()
                self._log(msg)
        self.root.destroy()

    def _launch_server(self):
        # placeholder for --launch mode handled below
        pass


def _launch_server():
    started = False
    if not sc.running_pid():
        ok, msg = sc.start_server()
        started = ok
        if not ok:
            try:
                app = tk.Tk()
                app.withdraw()
                messagebox.showerror("Automonous", msg, parent=app)
                app.destroy()
            except Exception:
                pass
            return
    for _ in range(20):
        ok, msg = sc.server_status()
        if ok and "responding" in msg:
            break
        time.sleep(0.5)
    webbrowser.open(URL)
    if getattr(sys, "frozen", False) and started:
        while sc.running_pid():
            time.sleep(2)


def _serve_only():
    ok, msg = sc.start_server()
    if not ok and "already" not in msg.lower():
        try:
            app = tk.Tk()
            app.withdraw()
            messagebox.showerror("Automonous", msg, parent=app)
            app.destroy()
        except Exception:
            pass
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
    root = tk.Tk()
    ServerConsoleGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
