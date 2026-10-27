# Automonous

Local Flask app that manages credentials for government tax portals (GST, Income Tax, Income Tax TDS) and automates login into those portals using Playwright.

Credentials are stored encrypted at rest (Fernet) with an ACL-restricted key, so plaintext passwords never touch the disk.

## Features

- **Multiple portals, multiple accounts** - GST, Income Tax, and Income Tax TDS (with TDS Login and TRACES Login subtypes).
- **Automated login** - Playwright drives the browser through the portal login, including two-step ePortal flows and captcha detection.
- **Encrypted credential store** - AES encryption via `cryptography` (Fernet); a backup key is kept as a fallback.
- **Bulk import** - Load credentials from an `.xlsx` file, with a downloadable template (Portal, Username, Password).
- **Utilities** - Local helpers, currently PDF Merger and PDF to Word (OCR).
- **Server consoles** - Two launchers to run the app and manage backups:
  - `Automonous.exe` - graphical control panel (start/stop, backup/restore, live log).
  - `AutomonousConsole.exe` - menu-driven command-line version.
- **Backup & restore** - One-click zipped backups of the encrypted store plus keys, with validated restore.

## Project structure

```
app.py             Flask app: routes, dashboard, manage & import pages
automation.py      Playwright launcher and login automation
storage.py         Encrypted credential store (Fernet)
importer.py        Excel (.xlsx) template + import parsing
tools/             Portal definitions (gst, incometax, tds)
templates/         Jinja2 templates (base + pages)
server_console.py  Shared console logic (start/stop/status/backup/restore)
gui_console.py     tkinter GUI over server_console.py
requirements.txt   Python dependencies
```

## Requirements

- Python 3.10+
- Windows (taskkill/PID handling is Windows-specific; other platforms need small tweaks in `server_console.py`)

## Setup

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

No browser download is required: Automonous drives the Google Chrome or
Microsoft Edge already installed on the machine (Edge ships with Windows).

For **PDF to Word** OCR, install
[Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki). Automonous looks
for it in the standard `C:\Program Files\Tesseract-OCR\` location, or set the
`TESSERACT_CMD` environment variable.

## Running the app

### From the command line

```powershell
venv\Scripts\python app.py
```

Then open http://127.0.0.1:5000/

### GUI console

Build (or use the prebuilt `Automonous.exe` in the project root):

```powershell
venv\Scripts\pyinstaller.exe --onefile --windowed --name Automonous gui_console.py
```

Double-click the exe. Use the buttons to start/stop the server, open it in a browser, create backups, or restore one. The log pane tails `server.log`.

### CLI console

```powershell
venv\Scripts\pyinstaller.exe --onefile --name AutomonousConsole server_console.py
```

Menu options: start, stop, status, backup, restore. Both exes must stay next to `app.py`, `venv`, and `credentials.enc` (they locate the project from their own location).

## Shipping an installer (setup.exe)

The project can be installed on any Windows machine as a single self-contained
`Automonous-Setup.exe` (bundles Python, Flask, Playwright, openpyxl, cryptography,
the web app, and Chromium so it works with no internet connection).

1. Build the one-dir bundle:
   ```powershell
   venv\Scripts\pyinstaller.exe --noconfirm Automonous.spec
   ```
2. Compile the installer (needs [Inno Setup](https://jrsoftware.org/isinfo.php)):
   ```powershell
   & "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" Automonous.iss
   ```
   Output: `installer\Automonous-Setup.exe` (much smaller now that Chromium is not bundled).

During setup it asks for the usual permissions: install folder, desktop
shortcut, a Windows Firewall rule for TCP port 5000 (Administrator/UAC),
and optional start-at-logon (on by default). Uninstalling removes the
shortcut and the firewall rule but keeps `credentials.enc`/`.secrets` so
your data survives.

Start-up behaviour:
- Opening the GUI console automatically starts the web server (no manual
  "Start Server" click needed).
- The installer's start-at-logon option registers an
  `HKCU\...\CurrentVersion\Run` entry running `Automonous.exe --serve`, so it
  appears under Windows Task Manager > Startup apps and serves the web app
  from logon.

The bundled app never needs the repo's `venv`:
- The GUI console runs the Flask server in-process (no `python.exe` required).
- `--launch` starts the server, opens the browser, and keeps running hidden as
  the server host. `--serve` runs the server hidden with no browser window
  (used by the start-at-logon option).
- Uses the system Chrome/Edge; no `browsers/` folder is needed.

## Browser engine

- Drives the system-installed Google Chrome or Microsoft Edge (Edge ships with
  Windows). No Chromium is bundled or downloaded.
- Prefers Chrome, then Edge, then a manually located binary, then Playwright's
  own Chromium as a last resort.
- Bypasses the ePortal `automation-validator` "Permission Denied" anti-bot check by hiding `navigator.webdriver` (`--disable-blink-features=AutomationControlled` plus a stealth init script).
- Handles the two-step ePortal login (User ID, then password + "confirm secure access" checkbox) and only auto-submits when no captcha is present.

## Updates

- The app checks GitHub (`palashsuryavanshi/automonous`) on the background for
  the latest release.
- When a newer version exists, the web app shows a popup on every page with a
  "Download Installer" link (shown once per browser session).
- The GUI console has a **Check for Updates** button that downloads the new
  installer and launches it (the server and console close to apply it).
- The current release version lives in `updates.py` (`APP_VERSION`) - bump it
  before building a new release so updaters detect it.
- Offline machines fail silently (no popup, button reports a check failure).

## Security notes

- The data file `credentials.enc` and the key file `.secrets\master.key` are created on first run.
- The master key is locked down at the OS level (`icacls`) so only your user account can read it.
- Never move the key out of `.secrets\` - the app reads it from there.
- `.gitignore` excludes `credentials.enc`, `.secrets/`, `secret.key`, `venv/`, the compiled exes, `server.log`, and `backups/` - check before committing.

## Backup & restore

- Backups write `backups\backup-<timestamp>.zip` containing `credentials.enc`, `.secrets\master.key`, and `secret.key`. All three are needed to decrypt your data.
- Restore runs through the console/GUI and validates the archive contents before extracting.
- Store backups somewhere safe - they are your only recovery if the store is damaged.

## Troubleshooting

- **"Permission Denied" on ePortal** - verify chromium is installed (`playwright install chromium`) and the stealth flags are present in `automation.py`.
- **Port already in use** - stop the server from the console/GUI first, or set `TAX_PORT` to another port.
- **Restore won't decrypt** - the backup and the current key must match; restore an older backup only if you also restore its matching key (which the zip includes).