"""Optional OS credential store (Windows Credential Manager, macOS Keychain) for the email app password,
so a forgotten-password reset can still send its code while the vault is locked.
If the `keyring` package is missing this does nothing and the reset screen asks for the settings again."""
from __future__ import annotations
import json

SERVICE, ACCOUNT = "KinKeep Desktop", "smtp"


def _kr():
    import keyring  # optional dependency
    return keyring


def save_smtp(cfg: dict) -> None:
    kr = _kr()
    if cfg:
        kr.set_password(SERVICE, ACCOUNT, json.dumps(cfg))
    else:
        try:
            kr.delete_password(SERVICE, ACCOUNT)
        except Exception:
            pass


def load_smtp() -> dict | None:
    raw = _kr().get_password(SERVICE, ACCOUNT)
    return json.loads(raw) if raw else None
