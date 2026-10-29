import json
import os
import subprocess
import sys
import time
from pathlib import Path

from cryptography.fernet import Fernet

PROJECT_DIR = (
    Path(sys.executable).parent
    if getattr(sys, "frozen", False)
    else Path(__file__).parent
)

LEGACY_KEY_FILE = PROJECT_DIR / "secret.key"

SECRETS_DIR = PROJECT_DIR / ".secrets"
KEY_FILE = SECRETS_DIR / "master.key"
DATA_FILE = PROJECT_DIR / "credentials.enc"


def _restrict_windows_access(path):
    try:
        if os.name != "nt":
            os.chmod(path, 0o600)
            return

        user = os.environ.get("USERNAME")
        if not user:
            return

        SECRETS_DIR.mkdir(parents=True, exist_ok=True)

        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{user}:F",
            ],
            check=True,
            capture_output=True,
        )
    except Exception as e:
        print("Could not restrict key file permissions:", e)


def get_key():
    if not KEY_FILE.exists():
        SECRETS_DIR.mkdir(parents=True, exist_ok=True)

        if LEGACY_KEY_FILE.exists():
            key = LEGACY_KEY_FILE.read_bytes()
        else:
            key = Fernet.generate_key()

        KEY_FILE.write_bytes(key)
        _restrict_windows_access(KEY_FILE)
    else:
        key = KEY_FILE.read_bytes()

    return key


def _decrypt_raw():
    try:
        return Fernet(get_key()).decrypt(DATA_FILE.read_bytes()).decode(), False
    except Exception:
        if LEGACY_KEY_FILE.exists():
            try:
                raw = Fernet(LEGACY_KEY_FILE.read_bytes()).decrypt(
                    DATA_FILE.read_bytes()
                ).decode()
                return raw, True
            except Exception:
                pass
        raise


def _parse_legacy(raw):
    username, password = raw.split("\n", 1)
    return {"gst": [{"username": username, "password": password}]}


def _backup_unreadable_data():
    try:
        backup = DATA_FILE.with_name(
            f"credentials.enc.bak-{int(time.time())}"
        )
        DATA_FILE.rename(backup)
        print("Backed up unreadable data file to", backup.name)
    except OSError as e:
        print("Could not back up data file:", e)


def load_credentials():
    """Returns the credential store dict keyed by tool key."""
    if not DATA_FILE.exists():
        return {}

    try:
        raw, legacy = _decrypt_raw()
    except Exception:
        _backup_unreadable_data()
        print("Could not decrypt stored credentials. Started fresh.")
        return {}

    try:
        store = json.loads(raw)
    except json.JSONDecodeError:
        store = _parse_legacy(raw)
        legacy = True

    if legacy:
        save_credentials(store)
        _remove_legacy_key()
        print("Migrated credentials to the new encrypted store.")

    return store


def _remove_legacy_key():
    try:
        if LEGACY_KEY_FILE.exists():
            LEGACY_KEY_FILE.unlink()
            print("Removed legacy key file from project folder.")
    except OSError as e:
        print("Could not remove legacy key file:", e)


def save_credentials(store):
    f = Fernet(get_key())
    DATA_FILE.write_bytes(f.encrypt(json.dumps(store).encode()))
    _restrict_windows_access(DATA_FILE)


def add_credential(tool_key, username, password):
    store = load_credentials()
    accounts = store.setdefault(tool_key, [])

    for account in accounts:
        if account["username"] == username:
            account["password"] = password
            break
    else:
        accounts.append({"username": username, "password": password})

    save_credentials(store)


def remove_credential(tool_key, username):
    store = load_credentials()
    store[tool_key] = [
        account
        for account in store.get(tool_key, [])
        if account["username"] != username
    ]
    save_credentials(store)


def get_credential(tool_key, username):
    store = load_credentials()
    for account in store.get(tool_key, []):
        if account["username"] == username:
            return account["username"], account["password"]
    return None