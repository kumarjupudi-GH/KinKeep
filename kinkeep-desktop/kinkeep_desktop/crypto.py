"""Vault cryptography for KinKeep Desktop.

Design (LUKS-style key slots):
  * A random 256-bit data key (DEK) encrypts the vault with AES-256-GCM.
  * The DEK is stored wrapped (AES-256-GCM) once per "key slot": the master password (Argon2id),
    the recovery key (HKDF, the key itself is 160 bits of entropy), and one slot per family member
    who has been given a login.
  * Changing a password only re-wraps the DEK. Removing a slot removes that person's access to
    *future* saves; anything they already saw cannot be taken back (see docs/SECURITY.md).
No password, key or answer is ever written to disk in clear.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import secrets
import unicodedata

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

APP = "KinKeep"
VAULT_VERSION = 2
# Argon2id: 3 passes, 64 MiB, 4 lanes (OWASP-class interactive setting). Tests override via set_kdf_cost().
KDF_COST = {"t": 3, "m": 65536, "p": 4}
MAX_M, MAX_T = 1 << 20, 12  # refuse absurd parameters from a hostile file (1 GiB, 12 passes)


class VaultError(Exception):
    """Base class: message is safe to show to the user."""


class WrongPassword(VaultError):
    pass


class FormatError(VaultError):
    pass


def set_kdf_cost(t: int, m: int, p: int) -> None:
    KDF_COST.update(t=t, m=m, p=p)


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def unb64(s: str) -> bytes:
    try:
        return base64.b64decode(s.encode("ascii"), validate=True)
    except Exception as e:
        raise FormatError("damaged vault file") from e


def normalize_password(pw: str) -> bytes:
    return unicodedata.normalize("NFKC", pw).encode("utf-8")


def argon2_key(secret: bytes, salt: bytes, t: int, m: int, p: int) -> bytes:
    if not (1 <= t <= MAX_T and 8 * p <= m <= MAX_M and 1 <= p <= 16):
        raise FormatError("unsupported key-derivation settings")
    return Argon2id(salt=salt, length=32, iterations=t, lanes=p, memory_cost=m).derive(secret)


# ---------------------------------------------------------------------------- key slots
def _wrap(kek: bytes, dek: bytes, slot_id: str) -> tuple[bytes, bytes]:
    iv = os.urandom(12)
    return iv, AESGCM(kek).encrypt(iv, dek, b"KinKeep-slot:" + slot_id.encode())


def _unwrap(kek: bytes, iv: bytes, wk: bytes, slot_id: str) -> bytes:
    try:
        return AESGCM(kek).decrypt(iv, wk, b"KinKeep-slot:" + slot_id.encode())
    except InvalidTag:
        raise WrongPassword("That password is not correct.") from None


def make_password_slot(password: str, dek: bytes, slot_id: str, label: str = "", kind: str = "password") -> dict:
    salt = os.urandom(16)
    c = dict(KDF_COST)
    kek = argon2_key(normalize_password(password), salt, c["t"], c["m"], c["p"])
    iv, wk = _wrap(kek, dek, slot_id)
    return {"id": slot_id, "type": kind, "label": label, "kdf": "argon2id", **c, "salt": b64(salt), "iv": b64(iv), "wk": b64(wk)}


def open_password_slot(slot: dict, password: str) -> bytes:
    if slot.get("kdf") != "argon2id":
        raise FormatError("unsupported slot")
    kek = argon2_key(normalize_password(password), unb64(slot["salt"]), int(slot["t"]), int(slot["m"]), int(slot["p"]))
    return _unwrap(kek, unb64(slot["iv"]), unb64(slot["wk"]), slot["id"])


# recovery key: 160 random bits shown as 8 groups of 4 base32 chars, e.g. ABCD-EFGH-...
def new_recovery_key() -> str:
    raw = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    return "-".join(raw[i:i + 4] for i in range(0, 32, 4))


def _rk_bytes(rk: str) -> bytes:
    s = re.sub(r"[^A-Z2-7]", "", rk.upper().replace("0", "O").replace("8", "B"))
    if len(s) != 32:
        raise WrongPassword("That recovery key is not the right length.")
    return base64.b32decode(s)


def make_recovery_slot(recovery_key: str, dek: bytes, slot_id: str = "recovery") -> dict:
    salt = os.urandom(16)
    kek = HKDF(hashes.SHA256(), 32, salt, b"KinKeep recovery key").derive(_rk_bytes(recovery_key))
    iv, wk = _wrap(kek, dek, slot_id)
    return {"id": slot_id, "type": "recovery", "label": "Recovery key", "kdf": "hkdf", "salt": b64(salt), "iv": b64(iv), "wk": b64(wk)}


def open_recovery_slot(slot: dict, recovery_key: str) -> bytes:
    kek = HKDF(hashes.SHA256(), 32, unb64(slot["salt"]), b"KinKeep recovery key").derive(_rk_bytes(recovery_key))
    return _unwrap(kek, unb64(slot["iv"]), unb64(slot["wk"]), slot["id"])


# ---------------------------------------------------------------------------- envelope
def _aad(seq: int) -> bytes:
    return json.dumps({"app": APP, "v": VAULT_VERSION, "seq": seq}, sort_keys=True, separators=(",", ":")).encode()


def seal(payload: dict, dek: bytes, slots: list[dict], seq: int) -> str:
    iv = os.urandom(12)
    ct = AESGCM(dek).encrypt(iv, json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), _aad(seq))
    env = {"app": APP, "v": VAULT_VERSION, "cipher": "AES-256-GCM", "seq": seq, "slots": slots, "iv": b64(iv), "ct": b64(ct)}
    return json.dumps(env, indent=1)


def parse_envelope(text: str) -> dict:
    try:
        e = json.loads(text)
    except Exception:
        raise FormatError("This is not a KinKeep vault file.") from None
    if not isinstance(e, dict) or e.get("app") != APP:
        raise FormatError("This is not a KinKeep vault file.")
    return e


def open_with_dek(env: dict, dek: bytes) -> dict:
    try:
        pt = AESGCM(dek).decrypt(unb64(env["iv"]), unb64(env["ct"]), _aad(int(env["seq"])))
    except (InvalidTag, KeyError, ValueError):
        raise FormatError("The vault is damaged or was changed outside KinKeep.") from None
    try:
        return json.loads(pt.decode("utf-8"))
    except Exception:
        raise FormatError("The vault is damaged.") from None


def find_slot(env: dict, slot_id: str) -> dict | None:
    return next((s for s in env.get("slots", []) if s.get("id") == slot_id), None)


# ---------------------------------------------------------------------------- legacy web vault
def open_legacy_web_vault(text: str, password: str) -> dict:
    """Open a backup made by the browser version (v1: PBKDF2-SHA256 + AES-GCM). Returns its data dict."""
    e = parse_envelope(text)
    if e.get("v") != 1 and not (e.get("ct") and e.get("salt")):
        raise FormatError("This is not a browser-version KinKeep backup.")
    it = int(e.get("iter") or 250000)
    if not (1000 <= it <= 2_000_000):
        raise FormatError("unsupported backup")
    key = PBKDF2HMAC(hashes.SHA256(), 32, unb64(e["salt"]), it).derive(password.encode("utf-8"))
    try:
        pt = AESGCM(key).decrypt(unb64(e["iv"]), unb64(e["ct"]), None)
    except InvalidTag:
        raise WrongPassword("That passphrase did not open this backup.") from None
    o = json.loads(pt.decode("utf-8"))
    if not isinstance(o, dict) or not isinstance(o.get("data"), dict):
        raise FormatError("This is not a KinKeep backup.")
    return o["data"]


def make_legacy_web_vault(data: dict, password: str, iters: int = 250000) -> str:
    """Write the browser-version format (used by tests and for moving data back to the web app)."""
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(hashes.SHA256(), 32, salt, iters).derive(password.encode("utf-8"))
    pt = json.dumps({"app": APP, "v": 1, "data": data}).encode()
    return json.dumps({"app": APP, "v": 1, "kdf": "PBKDF2-SHA256", "iter": iters, "salt": b64(salt), "iv": b64(iv),
                       "ct": b64(AESGCM(key).encrypt(iv, pt, None))})


# ---------------------------------------------------------------------------- security answers
def norm_answer(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^\w ]", "", s, flags=re.UNICODE).replace("_", "")
    return re.sub(r"\s+", " ", s).strip()


def hash_answer(answer: str, salt: bytes | None = None) -> dict:
    """Salted, memory-hard hash (scrypt). Answers are low-entropy, so they are never a key, only a check."""
    salt = salt or os.urandom(16)
    h = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(norm_answer(answer).encode())
    return {"salt": b64(salt), "h": b64(h)}


def check_answer(answer: str, rec: dict) -> bool:
    try:
        h = Scrypt(salt=unb64(rec["salt"]), length=32, n=2 ** 15, r=8, p=1).derive(norm_answer(answer).encode())
    except Exception:
        return False
    return secrets.compare_digest(h, unb64(rec["h"]))
