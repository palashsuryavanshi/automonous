"""Update check and installer download for Automonous.

Fetches the latest GitHub release, compares it with the locally running
version, and can download the new installer. Uses only the stdlib so it
works in the bundled exes and offline machines fail gracefully.
"""

import json
import os
import threading
import urllib.request
from pathlib import Path

APP_VERSION = "0.3"

GITHUB_REPO = "palashsuryavanshi/Automonous"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

UA = "Mozilla/5.0 (Automonous updater)"

REFRESH_INTERVAL = 3600  # seconds between web-app checks

_lock = threading.Lock()
_cache = {"info": None, "checked_at": 0.0}


def _fetch_latest():
    """Return parsed latest-release info, or None on any failure."""
    try:
        req = urllib.request.Request(RELEASES_API, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    installer = None
    for asset in data.get("assets", []):
        if asset.get("name", "").lower().endswith(".exe"):
            installer = {
                "name": asset["name"],
                "url": asset.get("browser_download_url"),
            }
            break

    return {
        "version": str(data.get("tag_name", "")).lstrip("v"),
        "title": data.get("name") or data.get("tag_name", ""),
        "body": data.get("body") or "",
        "installer": installer,
        "published_at": data.get("published_at", ""),
    }


def _version_tuple(version):
    parts = []
    for chunk in str(version).split("."):
        try:
            parts.append(int(chunk.split("-")[0]))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def latest_release():
    """Cached latest release info (thread-safe). Returns dict or None."""
    with _lock:
        return _cache["info"]


def has_update():
    """True when a newer release exists than the running APP_VERSION."""
    info = latest_release()
    if not info:
        return False
    return _version_tuple(info["version"]) > _version_tuple(APP_VERSION)


def check_update():
    """Force a network check for the latest release. Returns dict or None."""
    info = _fetch_latest()
    with _lock:
        _cache["info"] = info
        _cache["checked_at"] = __import__("time").time()
    return info


def _refresh_loop():
    while True:
        check_update()
        __import__("time").sleep(REFRESH_INTERVAL)


def start_background_refresh():
    """Start a daemon thread that periodically refreshes the cached info."""
    threading.Thread(target=_refresh_loop, daemon=True).start()


def download_installer(url, dest_dir, on_progress=None):
    """Download the installer to dest_dir. Returns the Path of the file."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    name = os.path.basename(url.split("?")[0]) or "Automonous-Setup.exe"
    target = dest_dir / name

    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as response:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        with open(target, "wb") as fh:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                downloaded += len(chunk)
                if on_progress and total:
                    on_progress(downloaded / total)

    return target