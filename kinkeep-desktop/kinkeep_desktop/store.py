"""Encrypted vault on disk: atomic saves, JSON <-> spreadsheet consistency, crash recovery, backups.

Files in the data folder
  kinkeep.vault.json   authoritative encrypted vault (AES-256-GCM, key slots)
  kinkeep.data.xlsx    encrypted spreadsheet copy (Office password encryption) - for emergencies
  account.json         small unencrypted profile used by the sign-in screen (answers only as hashes)
  backups/             rolling copies of earlier vault / spreadsheet generations
  kinkeep.lock         advisory lock so two copies of the app do not write at once
"""
from __future__ import annotations
import datetime as dt
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import access, crypto, officecrypt, schema, xlsx_io

VAULT_NAME, XLSX_NAME, ACCOUNT_NAME, LOCK_NAME = "kinkeep.vault.json", "kinkeep.data.xlsx", "account.json", "kinkeep.lock"
KEEP_BACKUPS = 15
OWNER_SLOT = "owner"


class StoreError(crypto.VaultError):
    pass


class Locked(StoreError):
    pass


def atomic_write(path: Path, data: bytes) -> None:
    """Write to a temp file in the same folder, flush to disk, then rename over the target.
    A crash leaves either the old file or the new one, never half of each."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".kk-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if os.name == "posix":
        try:
            dfd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


@dataclass
class Session:
    store: "Store"
    role: str
    name: str
    login: str
    slot_id: str
    dek: bytes
    slots: list
    seq: int
    data: dict
    meta: dict
    profile: dict
    members: list
    master_pw: str | None = None  # only the Owner's session holds it (it encrypts the spreadsheet)
    sync: dict = field(default_factory=dict)
    recovered_from: str = ""

    # -- saving ---------------------------------------------------------------------------
    def commit(self) -> None:
        self.store._commit(self)

    def snapshot_hash(self) -> str:
        return xlsx_io.content_hash(self.data)


class Store:
    def __init__(self, folder: str | os.PathLike):
        self.dir = Path(folder)
        self.vault_path = self.dir / VAULT_NAME
        self.xlsx_path = self.dir / XLSX_NAME
        self.account_path = self.dir / ACCOUNT_NAME
        self.backup_dir = self.dir / "backups"
        self.lock_path = self.dir / LOCK_NAME
        self.xlsx_mode = "agile"

    # -- basics ---------------------------------------------------------------------------
    def exists(self) -> bool:
        if self.vault_path.exists():
            return True
        return self.backup_dir.exists() and any(self.backup_dir.glob("kinkeep.vault.*.json"))

    def account(self) -> dict | None:
        try:
            a = json.loads(self.account_path.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        return a if isinstance(a, dict) and a.get("login") and a.get("email") else None

    def _write_account(self, profile: dict, members: list) -> None:
        pub = {k: profile[k] for k in ("first", "last", "email", "dob", "login", "q") if k in profile}
        pub["v"] = 2
        pub["members"] = [{k: m[k] for k in ("login", "email", "name", "role", "access_id", "slot_id")} for m in members]
        atomic_write(self.account_path, json.dumps(pub, indent=1).encode())

    def acquire_lock(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, json.dumps({"pid": os.getpid(), "t": time.time()}).encode())
            os.close(fd)
            return
        except FileExistsError:
            pass
        try:
            info = json.loads(self.lock_path.read_text())
            pid = int(info.get("pid", 0))
            alive = False
            if pid and pid != os.getpid():
                try:
                    os.kill(pid, 0)
                    alive = True
                except OSError:
                    alive = False
            if alive and time.time() - float(info.get("t", 0)) < 86400:
                raise Locked("KinKeep is already open with this data folder.")
        except (ValueError, OSError):
            pass
        self.lock_path.unlink(missing_ok=True)
        self.acquire_lock()

    def release_lock(self) -> None:
        try:
            if json.loads(self.lock_path.read_text()).get("pid") == os.getpid():
                self.lock_path.unlink()
        except (OSError, ValueError):
            pass

    # -- create ---------------------------------------------------------------------------
    def create(self, profile: dict, password: str, data: dict | None = None, extra_meta: dict | None = None) -> tuple["Session", str]:
        """New vault. Returns (session, recovery_key). The recovery key is shown once and never stored."""
        if self.vault_path.exists():
            raise StoreError("A KinKeep vault already exists in this folder.")
        self.dir.mkdir(parents=True, exist_ok=True)
        dek = secrets.token_bytes(32)
        rk = crypto.new_recovery_key()
        slots = [crypto.make_password_slot(password, dek, OWNER_SLOT, "Owner password"), crypto.make_recovery_slot(rk, dek)]
        data = schema.normalize(data if data is not None else schema.empty_state())
        if not any(r["role"] == access.OWNER for r in data["access"]):
            data["access"].insert(0, {"id": schema.nid(), "name": f"{profile['first']} {profile['last']}".strip(), "role": access.OWNER,
                                      "scope": "Everything", "status": "Active"})
        meta = {"smtp": {}, "emergency_until": ""}
        meta.update(extra_meta or {})
        s = Session(self, access.OWNER, f"{profile['first']} {profile['last']}".strip(), profile["login"], OWNER_SLOT, dek, slots, 0,
                    data, meta, dict(profile), [], master_pw=password)
        self._commit(s)
        return s, rk

    # -- unlock ---------------------------------------------------------------------------
    def _read_envelope(self) -> tuple[dict, str]:
        """Return (envelope, source). Falls back to the last good copy if the main file is damaged."""
        candidates = [("main", self.vault_path), ("previous", self.vault_path.with_suffix(".json.bak"))]
        if self.backup_dir.exists():
            for p in sorted(self.backup_dir.glob("kinkeep.vault.*.json"), reverse=True):
                candidates.append((f"backup {p.name}", p))
        last = None
        for src, p in candidates:
            try:
                env = crypto.parse_envelope(p.read_text("utf-8"))
                if not env.get("slots"):
                    raise crypto.FormatError("bad")
                return env, src
            except (OSError, crypto.VaultError) as e:
                last = e
        raise StoreError("No readable KinKeep vault was found in this folder.") from last

    def _slot_for(self, env: dict, login: str, profile: dict | None) -> tuple[str, str, str]:
        """Which slot belongs to this login? -> (slot_id, role, member name)"""
        lg = login.strip().lower()
        prof = profile or self.account() or {}
        if lg and lg in (str(prof.get("login", "")).lower(), str(prof.get("email", "")).lower()):
            return OWNER_SLOT, access.OWNER, f"{prof.get('first', '')} {prof.get('last', '')}".strip()
        for m in (prof.get("members") or []):
            if lg and lg in (str(m.get("login", "")).lower(), str(m.get("email", "")).lower()):
                return m["slot_id"], m["role"], m.get("name", "")
        raise crypto.WrongPassword("The login name or password is not correct.")

    def unlock(self, login: str, password: str) -> Session:
        env, src = self._read_envelope()
        slot_id, _, _ = self._slot_for(env, login, None)
        slot = crypto.find_slot(env, slot_id)
        if slot is None:
            raise crypto.WrongPassword("The login name or password is not correct.")
        dek = crypto.open_password_slot(slot, password)
        return self._session_from(env, dek, slot_id, password if slot_id == OWNER_SLOT else None, src)

    def unlock_with_recovery(self, recovery_key: str) -> Session:
        env, src = self._read_envelope()
        slot = crypto.find_slot(env, "recovery")
        if slot is None:
            raise StoreError("This vault has no recovery key.")
        dek = crypto.open_recovery_slot(slot, recovery_key)
        return self._session_from(env, dek, "recovery", None, src)

    def _session_from(self, env, dek, slot_id, master_pw, src) -> Session:
        payload = crypto.open_with_dek(env, dek)
        data = schema.normalize(payload.get("data"))
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        meta.setdefault("smtp", {}); meta.setdefault("emergency_until", "")
        profile = payload.get("profile") or {}
        members = payload.get("members") or []
        role, name, login = access.OWNER, f"{profile.get('first', '')} {profile.get('last', '')}".strip(), profile.get("login", "")
        if slot_id not in (OWNER_SLOT, "recovery"):
            m = next((m for m in members if m["slot_id"] == slot_id), None)
            if not m:
                raise crypto.WrongPassword("The login name or password is not correct.")
            role, name, login = m["role"], m.get("name", ""), m["login"]
        s = Session(self, role, name, login, slot_id, dek, env["slots"], int(env["seq"]), data, meta, profile, members,
                    master_pw=master_pw, recovered_from="" if src == "main" else src)
        if src != "main":
            # the main file was damaged: write the recovered copy back so the next start is clean
            self._commit(s)
        if not self.account() and profile:
            self._write_account(profile, members)
        if master_pw:
            s.sync = self._sync_check(s)
        return s

    # -- committing -----------------------------------------------------------------------
    def _rotate(self, path: Path, tag: str) -> None:
        if not path.exists():
            return
        self.backup_dir.mkdir(exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, self.backup_dir / f"{path.stem}.{stamp}-{tag}{path.suffix}")
        olds = sorted(self.backup_dir.glob(f"{path.stem}.*{path.suffix}"))
        for p in olds[:-KEEP_BACKUPS]:
            p.unlink(missing_ok=True)

    def _payload(self, s: Session, seq: int) -> dict:
        return {"app": "KinKeep", "v": 2, "seq": seq, "savedAt": _now(), "data": s.data, "meta": s.meta,
                "profile": s.profile, "members": s.members}

    def _commit(self, s: Session) -> None:
        seq = s.seq + 1
        text = crypto.seal(self._payload(s, seq), s.dek, s.slots, seq)
        # verify before replacing anything: what we are about to write must open and match
        back = crypto.open_with_dek(crypto.parse_envelope(text), s.dek)
        if xlsx_io.content_hash(back["data"]) != xlsx_io.content_hash(s.data):
            raise StoreError("Internal check failed: the saved copy did not match. Nothing was changed.")
        self.dir.mkdir(parents=True, exist_ok=True)
        if self.vault_path.exists():
            shutil.copy2(self.vault_path, self.vault_path.with_suffix(".json.bak"))
        atomic_write(self.vault_path, text.encode("utf-8"))
        s.seq = seq
        self._write_account(s.profile, s.members)
        if s.master_pw:
            self._write_xlsx(s)
        self._mirror(s)

    def _mirror(self, s: Session) -> None:
        """Keep encrypted copies in extra folders (for example a Google Drive or OneDrive folder). Never fatal."""
        for m in (s.meta.get("mirrors") or []):
            try:
                d = Path(m)
                if not d.is_dir() or d.resolve() == self.dir.resolve():
                    continue
                for f in (self.vault_path, self.xlsx_path):
                    if f.exists():
                        atomic_write(d / f.name, f.read_bytes())
            except OSError:
                s.sync = {**(s.sync or {}), "mirror_error": str(m)}

    def _write_xlsx(self, s: Session) -> None:
        blob = xlsx_io.encrypt_workbook(s.data, s.seq, s.master_pw, self.xlsx_mode)
        plain = officecrypt.decrypt(blob, s.master_pw)  # verify in memory before it replaces the old file
        data, meta = xlsx_io.read_workbook(plain)
        if xlsx_io.content_hash(data) != xlsx_io.content_hash(s.data):
            raise StoreError("Internal check failed: the spreadsheet copy did not match. Nothing was changed.")
        if self.xlsx_path.exists():
            self._rotate(self.xlsx_path, "pre")
        atomic_write(self.xlsx_path, blob)
        s.sync = {"state": "in_sync", "seq": s.seq}

    def snapshot_vault(self, tag: str = "auto") -> None:
        if self.vault_path.exists():
            self._rotate(self.vault_path, tag)

    # -- consistency ----------------------------------------------------------------------
    def _sync_check(self, s: Session) -> dict:
        """Compare the spreadsheet with the vault. The vault is authoritative; the spreadsheet is never
        overwritten silently if it holds anything the vault does not."""
        if not self.xlsx_path.exists():
            self._write_xlsx(s)
            return {"state": "regenerated", "why": "The spreadsheet was missing and has been recreated."}
        try:
            plain = officecrypt.decrypt(self.xlsx_path.read_bytes(), s.master_pw)
            data, meta = xlsx_io.read_workbook(plain)
        except (officecrypt.WrongPassword, officecrypt.FormatError, ValueError, OSError) as e:
            self._rotate(self.xlsx_path, "unreadable")
            self._write_xlsx(s)
            return {"state": "regenerated", "why": "The spreadsheet could not be opened with your password (%s). The old file was kept in backups and a fresh one was written." % e.__class__.__name__}
        same = xlsx_io.content_hash(data) == xlsx_io.content_hash(s.data)
        xseq = int(meta.get("vault_seq") or 0)
        if same:
            if xseq != s.seq:
                self._write_xlsx(s)
            return {"state": "in_sync"}
        if xseq == s.seq:
            return {"state": "external_edits", "why": "The spreadsheet was edited outside KinKeep. Review and import the changes, or keep your KinKeep data.", "xlsx_data": data}
        if xseq > s.seq:
            return {"state": "xlsx_newer", "why": "The spreadsheet is newer than the vault (the vault may have been restored from an older copy).", "xlsx_data": data}
        self._rotate(self.xlsx_path, "stale")
        self._write_xlsx(s)
        return {"state": "regenerated", "why": "The spreadsheet was behind the vault (a family member saved, or KinKeep closed during a save). It was refreshed."}

    def resolve_sync(self, s: Session, choice: str) -> None:
        """choice: 'import' (take the spreadsheet) or 'keep' (keep the vault, rewrite the spreadsheet)."""
        if s.role != access.OWNER or not s.master_pw:
            raise access.Denied("Only the Owner can do that.")
        st = s.sync
        if choice == "import" and st.get("xlsx_data") is not None:
            self.snapshot_vault("before-xlsx-import")
            s.data = self._keep_access(s.data, st["xlsx_data"])
            self._commit(s)
        elif choice == "keep":
            self._rotate(self.xlsx_path, "replaced")
            self._write_xlsx(s)
        else:
            raise StoreError("Nothing to resolve.")

    @staticmethod
    def _keep_access(current: dict, incoming: dict) -> dict:
        """A spreadsheet can change records, but it cannot grant family access: the access sheet is
        merged so existing people keep their role and nobody new becomes active without approval."""
        out = schema.normalize(incoming)
        have = {r["id"]: r for r in current["access"]}
        merged = []
        for r in out["access"]:
            if r["id"] in have:
                merged.append({**r, "role": have[r["id"]]["role"], "status": have[r["id"]]["status"]})
            else:
                merged.append({**r, "status": "Needs re-approval"})
        for rid, r in have.items():
            if r["role"] == access.OWNER and not any(x["id"] == rid for x in merged):
                merged.insert(0, r)
        out["access"] = merged
        return out

    # -- passwords and members ------------------------------------------------------------
    def change_password(self, s: Session, current: str, new: str) -> None:
        slot = crypto.find_slot({"slots": s.slots}, s.slot_id)
        crypto.open_password_slot(slot, current)  # verifies the current password
        new_slot = crypto.make_password_slot(new, s.dek, s.slot_id, slot.get("label", ""))
        s.slots = [new_slot if x["id"] == s.slot_id else x for x in s.slots]
        if s.slot_id == OWNER_SLOT:
            s.master_pw = new
        self.snapshot_vault("before-password-change")
        self._commit(s)

    def reset_password_after_recovery(self, s: Session, new_password: str) -> None:
        """Used after the recovery key (plus questions and email code) proved who is asking."""
        s.slots = [x for x in s.slots if x["id"] != OWNER_SLOT] + [crypto.make_password_slot(new_password, s.dek, OWNER_SLOT, "Owner password")]
        s.slot_id, s.master_pw, s.role = OWNER_SLOT, new_password, access.OWNER
        self.snapshot_vault("before-reset")
        self._commit(s)

    def rotate_recovery_key(self, s: Session) -> str:
        if s.role != access.OWNER:
            raise access.Denied("Only the Owner can do that.")
        rk = crypto.new_recovery_key()
        s.slots = [x for x in s.slots if x["id"] != "recovery"] + [crypto.make_recovery_slot(rk, s.dek)]
        self._commit(s)
        return rk

    def add_member(self, s: Session, access_id: str, login: str, email: str, password: str) -> None:
        row = next((r for r in s.data["access"] if r["id"] == access_id), None)
        if row is None:
            raise StoreError("Add the person under Family access first.")
        if s.role not in (access.OWNER, access.COOWNER):
            raise access.Denied("Only the Owner or a Co-owner can give someone a login.")
        if row["role"] in (access.OWNER,) or (s.role == access.COOWNER and row["role"] in access.CO_OWNER_FORBIDDEN_ROLES):
            raise access.Denied("Only the Owner can do that for this role.")
        lg = login.strip().lower()
        taken = [m for m in s.members if m["login"].lower() == lg and m["access_id"] != access_id]
        if not re.fullmatch(r"[A-Za-z0-9._-]{3,30}", login) or taken or lg == str(s.profile.get("login", "")).lower():
            raise StoreError("Choose a different login name (3 to 30 letters, numbers, dots, dashes or underscores).")
        if len(password) < 10:
            raise StoreError("The password needs at least 10 characters.")
        slot_id = f"m-{access_id}"
        s.slots = [x for x in s.slots if x["id"] != slot_id] + [crypto.make_password_slot(password, s.dek, slot_id, row["name"], "member")]
        s.members = [m for m in s.members if m["access_id"] != access_id] + [
            {"login": login, "email": email, "name": row["name"], "role": row["role"], "access_id": access_id, "slot_id": slot_id}]
        row["status"] = "Active"
        self._commit(s)

    def remove_member(self, s: Session, access_id: str) -> None:
        if s.role not in (access.OWNER, access.COOWNER):
            raise access.Denied("Only the Owner or a Co-owner can remove a login.")
        m = next((m for m in s.members if m["access_id"] == access_id), None)
        if m and s.role == access.COOWNER and m["role"] in access.CO_OWNER_FORBIDDEN_ROLES:
            raise access.Denied("Only the Owner can do that.")
        s.slots = [x for x in s.slots if x["id"] != f"m-{access_id}"]
        s.members = [m for m in s.members if m["access_id"] != access_id]
        for r in s.data["access"]:
            if r["id"] == access_id and r["status"] == "Active":
                r["status"] = "Invited"
        self._commit(s)

    def sync_member_roles(self, s: Session) -> None:
        """Keep each login's role equal to the role in the Family access list; drop logins whose row was deleted."""
        by = {r["id"]: r for r in s.data["access"]}
        keep = []
        for m in s.members:
            r = by.get(m["access_id"])
            if r is None:
                s.slots = [x for x in s.slots if x["id"] != m["slot_id"]]
                continue
            m["role"], m["name"] = r["role"], r["name"]
            if r["role"] == access.OWNER:  # nobody becomes Owner through a member login
                s.slots = [x for x in s.slots if x["id"] != m["slot_id"]]
                continue
            keep.append(m)
        s.members = keep

    # -- backups and restore --------------------------------------------------------------
    def export_vault_backup(self, s: Session, dest: str | os.PathLike) -> Path:
        """Encrypted JSON backup: the Owner password and recovery key can open it; family logins are not included."""
        if s.role not in (access.OWNER, access.COOWNER):
            raise access.Denied("Only the Owner or a Co-owner can save a backup.")
        text = self.vault_path.read_text("utf-8")
        env = crypto.parse_envelope(text)
        env["slots"] = [x for x in env["slots"] if x["type"] in ("password", "recovery") and x["id"] in (OWNER_SLOT, "recovery")]
        # a backup must be self-contained and open with what the person remembers
        dest = Path(dest)
        atomic_write(dest, json.dumps(env, indent=1).encode())
        return dest

    def export_xlsx_backup(self, s: Session, dest: str | os.PathLike) -> Path:
        if s.role != access.OWNER or not s.master_pw:
            raise access.Denied("Only the Owner can save a spreadsheet backup.")
        dest = Path(dest)
        atomic_write(dest, xlsx_io.encrypt_workbook(s.data, s.seq, s.master_pw, self.xlsx_mode))
        return dest

    @staticmethod
    def _restored_data(old_access: list, data: dict) -> dict:
        """Relationships come back; access does not. Everyone except the Owner needs the Owner's approval again."""
        d = schema.normalize(data)
        for r in d["access"]:
            if r["role"] != access.OWNER:
                r["status"] = "Needs re-approval"
        return d

    def inspect_backup(self, text_or_bytes: bytes | str, password: str) -> dict:
        """Open a backup of any supported kind and describe it, without changing anything."""
        kind, data, saved = self._open_backup(text_or_bytes, password)
        return {"kind": kind, "savedAt": saved, "counts": {c: len(data[c]) for c in schema.COLLS}, "_data": data}

    def _open_backup(self, blob, password: str):
        if isinstance(blob, str):
            blob = blob.encode("utf-8")
        if officecrypt.is_encrypted(blob):
            try:
                data, meta = xlsx_io.read_workbook(officecrypt.decrypt(blob, password))
            except officecrypt.WrongPassword:
                raise crypto.WrongPassword("That password did not open this spreadsheet.") from None
            except (officecrypt.FormatError, ValueError) as e:
                raise crypto.FormatError(str(e)) from None
            return "spreadsheet", data, str(meta.get("saved_at", ""))
        env = crypto.parse_envelope(blob.decode("utf-8", "replace"))
        if env.get("v") == 1 or "slots" not in env:
            return "browser-version vault", schema.normalize(crypto.open_legacy_web_vault(blob.decode("utf-8"), password)), ""
        last = None
        for slot in env["slots"]:
            try:
                if slot["type"] == "recovery":
                    dek = crypto.open_recovery_slot(slot, password)
                else:
                    dek = crypto.open_password_slot(slot, password)
                p = crypto.open_with_dek(env, dek)
                return "vault", schema.normalize(p.get("data")), str(p.get("savedAt", ""))
            except crypto.WrongPassword as e:
                last = e
        raise last or crypto.FormatError("This is not a KinKeep backup.")

    def restore_into(self, s: Session, blob, password: str) -> dict:
        """Replace the data of the open vault with a backup (Owner only). Family logins are revoked."""
        if s.role != access.OWNER:
            raise access.Denied("Only the Owner can restore a backup.")
        kind, data, _ = self._open_backup(blob, password)
        self.snapshot_vault("before-restore")
        keep_owner = [r for r in s.data["access"] if r["role"] == access.OWNER]
        s.data = self._restored_data(s.data["access"], data)
        if not any(r["role"] == access.OWNER for r in s.data["access"]):
            s.data["access"] = keep_owner + s.data["access"]
        s.slots = [x for x in s.slots if x["id"] in (OWNER_SLOT, "recovery")]
        s.members = []
        s.meta["emergency_until"] = ""
        self._commit(s)
        return {"kind": kind}

    def restore_new(self, profile: dict, password: str, blob, backup_password: str | None = None) -> tuple[Session, str, str]:
        """First run on a new computer: build a new vault from a backup. Returns (session, recovery_key, kind)."""
        kind, data, _ = self._open_backup(blob, backup_password or password)
        data = self._restored_data([], data)
        s, rk = self.create(profile, password, data)
        return s, rk, kind
