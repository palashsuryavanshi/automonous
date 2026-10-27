"""Server console for the Automonous suite.

Launcher-style console app that starts/stops the Flask web server and
provides backup/restore for the encrypted credentials.

Actions return ``(ok, message)`` so they can be reused by both the CLI
menu and the tkinter GUI (``gui_console.py``).
"""

import os
import subprocess
import sys
import threading
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

BASE_DIR = (
    Path(sys.executable).parent
    if getattr(sys, "frozen", False)
    else Path(__file__).parent
)

PID_FILE = BASE_DIR / ".server.pid"
LOG_FILE = BASE_DIR / "server.log"
BACKUP_DIR = BASE_DIR / "backups"

HOST = "127.0.0.1"
PORT = int(os.environ.get("TAX_PORT", "5000"))
URL = f"http://{HOST}:{PORT}/"

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

SERVER_START_CODE = (
    "from app import app; import os;"
    "app.run(host='" + HOST + "', port=" + str(PORT) + ", "
    "debug=False, use_reloader=False)"
)

_RESTORE_NAMES = {
    "credentials.enc",
    ".secrets/master.key",
    "secret.key",
}

_httpd = None


def _in_process():
    """Bundled builds have no venv python, so serve in-process."""
    from werkzeug.serving import make_server

    global _httpd
    if _httpd is not None:
        return _httpd

    from app import app

    _httpd = make_server(HOST, PORT, app, threaded=True)
    thread = threading.Thread(target=_httpd.serve_forever, daemon=True)
    thread.start()
    return _httpd


def _enable_ansi():
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


class Color:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"
    DIM = "\033[2m"


def _ok(msg):
    print(f"{Color.GREEN}{msg}{Color.RESET}")


def _warn(msg):
    print(f"{Color.YELLOW}{msg}{Color.RESET}")


def _err(msg):
    print(f"{Color.RED}{msg}{Color.RESET}")


def resolve_python():
    venv_python = BASE_DIR / "venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return "python"


def _read_pid():
    try:
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid):
    if not pid:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        ).stdout
        return str(pid) in out
    except Exception:
        return False


def running_pid():
    pid = _read_pid()
    return pid if _pid_alive(pid) else None


def start_server():
    """Start the web server if it is not already running."""
    if running_pid():
        return False, "Server is already running."

    if getattr(sys, "frozen", False):
        _in_process()
        PID_FILE.write_text(str(os.getpid()))
        return True, (
            f"Server starting on {URL} (PID {os.getpid()}, in-process)\n"
            f"Log: {LOG_FILE}"
        )

    python = resolve_python()
    if not (BASE_DIR / "app.py").exists():
        return False, "app.py not found next to the console. Wrong location?"

    log = open(LOG_FILE, "a", encoding="utf-8")

    process = subprocess.Popen(
        [python, "-c", SERVER_START_CODE],
        cwd=str(BASE_DIR),
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
    )

    PID_FILE.write_text(str(process.pid))
    return True, (
        f"Server starting on {URL} (PID {process.pid})\n"
        f"Log: {LOG_FILE}"
    )


def stop_server():
    """Stop the web server (and any child processes) if running."""
    pid = running_pid()
    if not pid:
        return False, "Server is not running."

    global _httpd
    if getattr(sys, "frozen", False) and _httpd is not None:
        _httpd.shutdown()
        _httpd = None
        PID_FILE.unlink(missing_ok=True)
        return True, f"Server stopped (PID {pid})."

    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        timeout=10,
        creationflags=CREATE_NO_WINDOW,
    )
    PID_FILE.unlink(missing_ok=True)
    return True, f"Server stopped (PID {pid})."


def server_status():
    """Return (ok, status_text)."""
    pid = running_pid()
    if not pid:
        return False, "Status: STOPPED"

    alive = _pid_alive(pid)
    try:
        with urllib.request.urlopen(URL, timeout=3) as response:
            responding = response.status == 200
    except Exception:
        responding = False

    if alive and responding:
        return True, f"Status: RUNNING (PID {pid}) - responding on {URL}"
    if alive:
        return False, f"Status: RUNNING (PID {pid}) but not responding yet"
    return False, f"Status: STALE PID {pid} - process not found"


def create_backup():
    """Zip the encrypted credentials + keys into backups/."""
    files = [f for f in _RESTORE_NAMES if (BASE_DIR / f).exists()]

    if not files:
        return False, "Nothing to back up: no credentials found."

    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"backup-{stamp}.zip"

    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            zf.write(BASE_DIR / name, name)

    return True, f"Backup created: {backup_path}"


def _list_backups():
    if not BACKUP_DIR.exists():
        return []
    return sorted(
        BACKUP_DIR.glob("backup-*.zip"),
        reverse=True,
    )


def perform_restore(backup_path):
    """Validate and restore a backup zip. Stops the server first."""
    backup_path = Path(backup_path)

    try:
        with zipfile.ZipFile(backup_path) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return False, f"'{backup_path.name}' is not a valid zip file."

    if not names or not names.issubset(_RESTORE_NAMES):
        return False, "Backup contains unexpected files. Restore aborted."

    stop_server()

    with zipfile.ZipFile(backup_path) as zf:
        zf.extractall(BASE_DIR)

    return True, f"Restored from {backup_path.name}."


def restore_backup():
    """Interactive restore for the CLI menu."""
    backups = _list_backups()

    if not backups:
        return False, "No backups found in the backups folder."

    print("\nAvailable backups:")
    for i, path in enumerate(backups, start=1):
        size = path.stat().st_size
        print(f"  [{i}] {path.name}  ({size:,} bytes)")

    try:
        choice = input("\nSelect a backup number (0 to cancel): ").strip()
        if not choice or choice == "0":
            return False, "Cancelled."
        backup_path = backups[int(choice) - 1]
    except (ValueError, IndexError):
        return False, "Invalid selection."

    confirm = input(
        f"Restore '{backup_path.name}'? "
        f"This overwrites current credentials [y/N]: "
    ).strip().lower()
    if confirm != "y":
        return False, "Restore cancelled."

    ok, msg = perform_restore(backup_path)
    if ok:
        msg += " You can now start the server again."
    return ok, msg


def banner():
    print()
    print(f"{Color.CYAN}{Color.BOLD}=== Automonous - Server Console ==={Color.RESET}")
    print(f"{Color.DIM}Project : {BASE_DIR}{Color.RESET}")
    print()


def menu():
    print()
    print("  [1] Start web app server")
    print("  [2] Stop web app server")
    print("  [3] Server status")
    print("  [4] Backup credentials")
    print("  [5] Restore credentials")
    print("  [0] Exit")
    print()


def main():
    _enable_ansi()
    banner()

    while True:
        menu()
        try:
            choice = input("Choose an option: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        print()
        if choice in ("1", "2"):
            ok, msg = start_server() if choice == "1" else stop_server()
            _ok(msg) if ok else _err(msg)
        elif choice == "3":
            ok, msg = server_status()
            _ok(msg) if ok else _warn(msg)
        elif choice == "4":
            ok, msg = create_backup()
            _ok(msg) if ok else _err(msg)
        elif choice == "5":
            ok, msg = restore_backup()
            _ok(msg) if ok else _err(msg)
        elif choice == "0":
            break
        else:
            _err("Unknown option.")
        print()

    print("Goodbye.")


if __name__ == "__main__":
    main()