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
COLOR_STALE = "#f59e0b"
COLOR_STOPPED = "#737373"


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
    style.configure("TEntry", fieldbackground="#171717", foreground="#f5f5f5", bordercolor="#3a3a3a")
    style.configure("TCombobox", fieldbackground="#171717", foreground="#f5f5f5", bordercolor="#3a3a3a")


class ServerConsoleGUI:
    def __init__(self, root):
        self.root = root
        root.title("Automonous - Server Console")
        root.geometry("420x320")
        root.resizable(True, True)

        self._log_pos = 0
        self._last_state = None
        self._log_visible = False

        _apply_icon(root)
        root.configure(bg="#0a0a0a")
        _configure_style(root)
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(400, self._auto_start)
        self._poll()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        header = ttk.Frame(main)
        header.pack(fill="x", pady=(0, 12))

        ttk.Label(
            header, text="Automonous",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left")

        self.status_label = ttk.Label(
            header, text="checking...",
            font=("Segoe UI", 10),
            foreground=COLOR_STOPPED,
        )
        self.status_label.pack(side="right")

        server_frame = ttk.Frame(main)
        server_frame.pack(fill="x", pady=(0, 10))

        self.btn_start = ttk.Button(
            server_frame, text="Start Server",
            command=self._start,
        )
        self.btn_start.pack(fill="x", pady=(0, 4))

        self.btn_stop = ttk.Button(
            server_frame, text="Stop Server",
            command=self._stop,
        )
        self.btn_stop.pack(fill="x")

        actions_frame = ttk.Frame(main)
        actions_frame.pack(fill="x", pady=(6, 12))

        self.btn_browser = ttk.Button(
            actions_frame, text="Open in Browser",
            command=self._open_browser,
        )
        self.btn_browser.pack(side="left", expand=True, fill="x", padx=(0, 4))

        self.btn_backup = ttk.Button(
            actions_frame, text="Backup",
            command=self._backup,
        )
        self.btn_backup.pack(side="left", expand=True, fill="x", padx=4)

        self.btn_restore = ttk.Button(
            actions_frame, text="Restore...",
            command=self._restore,
        )
        self.btn_restore.pack(side="left", expand=True, fill="x", padx=(4, 0))

        self.log_frame = ttk.Frame(main)
        self.log_text = tk.Text(
            self.log_frame, height=8, wrap="word", state="disabled",
            font=("Consolas", 9), bg="#0a0a0a", fg="#d4d4d8",
            insertbackground="#d4d4d8", relief="flat", bd=0,
        )
        scroll = ttk.Scrollbar(self.log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.log_text.tag_configure("info", foreground="#d7dae0")
        self.log_text.tag_configure("ok", foreground="#2ecc71")
        self.log_text.tag_configure("warn", foreground="#f1c40f")
        self.log_text.tag_configure("err", foreground="#e74c3c")
        self.log_text.tag_configure("server", foreground="#7fa8d9")

        footer = ttk.Frame(main)
        footer.pack(fill="x", pady=(6, 0))

        self.btn_shortcut = ttk.Button(
            footer, text="Create Shortcut", command=self._create_shortcut,
        )
        self.btn_shortcut.pack(side="left")

        self.btn_update = ttk.Button(
            footer, text="Check for Updates", command=self._check_updates,
        )
        self.btn_update.pack(side="left", padx=(8, 0))

        self.btn_toggle_log = ttk.Button(
            footer, text="Show Log", command=self._toggle_log,
        )
        self.btn_toggle_log.pack(side="right")

        self._log("Console ready. Project: " + str(BACKUP_DIR), "info")

    def _toggle_log(self):
        if self._log_visible:
            self.log_frame.pack_forget()
            self.btn_toggle_log.configure(text="Show Log")
        else:
            self.log_frame.pack(fill="both", expand=True, after=self.btn_toggle_log.master)
            self.btn_toggle_log.configure(text="Hide Log")
        self._log_visible = not self._log_visible

    # ---------------------------------------------------------------- utils
    def _log(self, message, tag="info"):
        message = _ANSI.sub("", str(message))
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n", tag)
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
        elif "STALE" in message:
            state = "stale"
            color = COLOR_STALE
        else:
            state = "stopped"
            color = COLOR_STOPPED

        self.status_label.configure(foreground=color)
        self.status_label.configure(text="RUNNING" if state == "running"
                                   else ("OFFLINE" if state == "stopped" else "ERROR"))

        self._set_server_buttons(state == "running")

        if state != self._last_state:
            self._log(message, "ok" if state == "running"
                      else ("warn" if state == "stale" else "info"))
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
                        self._log(line, "server")
        except OSError:
            pass

    # ------------------------------------------------------------- actions
    def _auto_start(self):
        """Start the web server automatically when the console opens."""
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
        self.root.after(0, lambda: (self._log(msg, "ok" if ok else "err"),
                                    self._set_busy(False)))

    def _stop(self):
        self._set_busy(True)
        self._log("Stopping server...", "info")
        threading.Thread(target=self._stop_worker, daemon=True).start()

    def _stop_worker(self):
        ok, msg = sc.stop_server()
        self.root.after(0, lambda: (self._log(msg, "ok" if ok else "warn"),
                                    self._set_busy(False)))

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
            messagebox.showwarning(
                "Shortcut",
                "Run the built Automonous.exe instead of the script to "
                "create a shortcut.\n\nBuild it with:\n"
                "pyinstaller --onefile --windowed --name Automonous gui_console.py",
            )
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
            "$s.Description = 'Start the Automonous web app and open it "
            "in the browser';"
            "$s.Save(); Write-Output 'ok'"
        )

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=0x08000000,
            )
        except Exception as exc:
            messagebox.showerror("Shortcut", f"Failed to create shortcut:\n{exc}")
            return

        if result.returncode == 0 and "ok" in result.stdout:
            messagebox.showinfo("Shortcut", "Desktop shortcut created.")
        else:
            messagebox.showerror(
                "Shortcut",
                "Failed to create shortcut:\n" + result.stderr.strip(),
            )

    def _check_updates(self):
        self.btn_update.configure(state="disabled")
        self._log("Checking for updates...", "info")
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        def fail(msg, tag="err"):
            self.root.after(
                0,
                lambda: (self._log(msg, tag),
                         self.btn_update.configure(state="normal")),
            )

        info = updates.check_update()
        if not info:
            fail("Update check failed (no internet?).")
            return

        current = updates.APP_VERSION
        latest = info["version"]

        if updates._version_tuple(latest) <= updates._version_tuple(current):
            fail(f"Already up to date (v{current}).", "ok")
            return

        if not info.get("installer"):
            fail(f"Update available (v{latest}) but no installer found.")
            return

        self.root.after(0, lambda: self._ask_download(info))

    def _ask_download(self, info):
        answer = messagebox.askyesno(
            "Update available",
            f"Automonous {info['version']} is available.\n"
            f"Current version: {updates.APP_VERSION}\n\n"
            "Download and install now?\n"
            "The server and console will close to apply the update.",
        )
        if not answer:
            self._log("Update skipped.", "info")
            self.btn_update.configure(state="normal")
            return
        self._log(f"Downloading {info['installer']['name']}...", "info")
        threading.Thread(target=self._download_worker, args=(info,), daemon=True).start()

    def _download_worker(self, info):
        dest = BACKUP_DIR.parent / "updates"
        try:
            path = updates.download_installer(info["installer"]["url"], dest)
        except Exception as exc:
            self.root.after(
                0,
                lambda: (self._log(f"Download failed: {exc}", "err"),
                         self.btn_update.configure(state="normal")),
            )
            return
        self.root.after(0, lambda: self._run_installer(path))

    def _run_installer(self, path):
        sc.stop_server()
        try:
            os.startfile(str(path))
        except Exception as exc:
            messagebox.showerror("Update", f"Failed to start installer:\n{exc}")
            self.btn_update.configure(state="normal")
            return
        self._log(
            f"Installer launched: {path.name}. "
            "Follow the on-screen prompts.",
            "ok",
        )
        self.root.after(400, self.root.destroy)

    def _backup(self):
        self._set_busy(True)
        threading.Thread(target=self._backup_worker, daemon=True).start()

    def _backup_worker(self):
        ok, msg = sc.create_backup()
        self.root.after(0, lambda: (self._log(msg, "ok" if ok else "err"),
                                    self._set_busy(False)))

    def _restore(self):
        path = filedialog.askopenfilename(
            initialdir=str(BACKUP_DIR),
            title="Select a backup",
            filetypes=[("Backup archive", "backup-*.zip"), ("All files", "*.*")],
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Restore backup",
            f"Restore from '{path.split(chr(92))[-1]}'?\n"
            "This overwrites the current credentials.",
            icon="warning",
        ):
            return
        self._set_busy(True)
        threading.Thread(target=self._restore_worker, args=(path,), daemon=True).start()

    def _restore_worker(self, path):
        ok, msg = sc.perform_restore(path)
        self.root.after(0, lambda: (self._log(msg, "ok" if ok else "err"),
                                    self._set_busy(False)))

    def _on_close(self):
        if sc.running_pid():
            answer = messagebox.askyesnocancel(
                "Server is running",
                "The web server is still running.\n\n"
                "Yes = stop the server, No = keep it running, Cancel = go back.",
            )
            if answer is None:
                return
            if answer:
                ok, msg = sc.stop_server()
                self._log(msg, "ok" if ok else "warn")
        self.root.destroy()


def _launch_server():
    """--launch mode: start the server (if needed) and open the browser."""
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
    """--serve mode: run the server in the background with no UI."""
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