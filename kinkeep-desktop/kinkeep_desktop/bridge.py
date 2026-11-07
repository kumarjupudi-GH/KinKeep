"""The API between the user interface and everything that matters (encryption, files, sign-in, roles).

The interface never sees a key or a password it did not just type, and only receives the records its
signed-in person is allowed to see. Every method returns {"ok": True, ...} or {"ok": False, "error": text}.
"""
from __future__ import annotations
import base64
import datetime as dt
import functools
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

from . import access, crypto, officecrypt, otp as otpmod, schema, store as storemod, xlsx_io

log = logging.getLogger("kinkeep")
VERSION = "2.0.0"
LOCK_MINUTES = 10
QUESTIONS = ["What is your favorite food?", "What is your favorite color?", "What is your favorite movie or TV show?",
             "What is your favorite place to visit?", "Who is your favorite teacher?", "What is your favorite book?",
             "What is your favorite sport or team?", "What is your favorite song or singer?",
             "What is your favorite childhood game?", "What is your favorite festival or holiday?"]
EMAIL_RX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
LOGIN_RX = re.compile(r"^[A-Za-z0-9._-]{3,30}$")
GENERIC_LOGIN_ERR = "The login name or password is not correct."


def default_data_dir() -> Path:
    env = os.environ.get("KINKEEP_DATA")
    if env:
        return Path(env)
    return Path.home() / "Documents" / "KinKeep Data" if (Path.home() / "Documents").exists() else Path.home() / "KinKeep Data"


class Host:
    """What the operating system provides. The desktop launcher replaces these with real dialogs."""
    def __init__(self, export_dir: Path):
        self.export_dir = export_dir

    def save_file(self, suggested: str, data: bytes) -> str | None:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        p = self.export_dir / suggested
        storemod.atomic_write(p, data)
        return str(p)

    def open_folder(self, path: str) -> None:
        pass

    def open_url(self, url: str) -> None:
        pass

    def choose_folder(self) -> str | None:
        return None


def api(fn):
    @functools.wraps(fn)
    def wrap(self, *a, **k):
        try:
            r = fn(self, *a, **k)
            if isinstance(r, dict):
                return r if "ok" in r else {"ok": True, **r}
            return {"ok": True, "value": r}
        except access.Denied as e:
            return {"ok": False, "error": str(e), "denied": True}
        except otpmod.RateLimited:
            return {"ok": False, "error": "Please wait about 30 seconds before asking for another code (at most 6 per hour)."}
        except otpmod.SendFailed as e:
            why = str(e)
            return {"ok": False, "error": "The email could not be sent" + (" because email is not set up yet." if why == "not_configured" else
                    " (%s). Check your email settings and internet connection." % why)}
        except (crypto.VaultError, otpmod.OtpError, officecrypt.WrongPassword, officecrypt.FormatError) as e:
            return {"ok": False, "error": str(e) or e.__class__.__name__}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception:  # never leak internals or secrets to the screen
            log.exception("unexpected error in %s", fn.__name__)
            return {"ok": False, "error": "Something went wrong. Nothing was lost; your saved data is unchanged."}
    wrap.is_api = True
    return wrap


class Bridge:
    def __init__(self, data_dir: str | os.PathLike | None = None, host: Host | None = None,
                 otp_service: otpmod.OtpService | None = None, sender=None, clock=time.time):
        self.dir = Path(data_dir) if data_dir else default_data_dir()
        self.store = storemod.Store(self.dir)
        self.host = host or Host(self.dir / "exports")
        self.otp = otp_service or otpmod.OtpService(clock)
        self.sender_override = sender  # tests inject a fake mailbox
        self.clock = clock
        self.s: storemod.Session | None = None
        self.pending: dict | None = None
        self.quick_login: str | None = None  # who may unlock with the password alone after an idle lock
        self.fails: dict[str, tuple[int, float]] = {}
        self.restore_pending: dict | None = None
        self.last_error = ""

    # ------------------------------------------------------------------ helpers
    def _locked_out(self, key: str) -> int:
        n, until = self.fails.get(key, (0, 0))
        return max(0, int(until - self.clock()))

    def _fail(self, key: str) -> None:
        n, _ = self.fails.get(key, (0, 0))
        n += 1
        delay = 0 if n < 5 else min(900, 15 * 2 ** (n - 5))
        self.fails[key] = (n, self.clock() + delay)

    def _ok(self, key: str) -> None:
        self.fails.pop(key, None)

    def _need(self) -> storemod.Session:
        if self.s is None:
            raise access.Denied("Please sign in first.")
        return self.s

    def _sender(self, smtp: dict | None):
        if self.sender_override:
            return self.sender_override
        return otpmod.smtp_sender(smtp) if otpmod.smtp_ready(smtp) else None

    def _issue(self, email: str, purpose: str, smtp: dict | None, demo: bool) -> dict:
        eff_demo = demo or (self.sender_override is None and not otpmod.smtp_ready(smtp))
        r = self.otp.issue(email, purpose, self._sender(smtp), demo=eff_demo)
        out = {"id": r["id"], "masked": otpmod.mask_email(email), "demo": eff_demo}
        if eff_demo:
            out["demo_code"] = r["demo_code"]
        return out

    def _state_payload(self) -> dict:
        s = self._need()
        if s.role == access.EMERGENCY and not access.emergency_active(s.meta):
            raise access.Denied("The Owner has not approved emergency access right now.")
        view = access.filter_state(s.data, s.role, s.name)
        sync = {k: v for k, v in (s.sync or {}).items() if k != "xlsx_data"}
        return {"state": view, "perms": access.perms_for(s.role), "user": {"name": s.name, "role": s.role, "login": s.login},
                "seq": s.seq, "sync": sync, "vaultLine": self._vault_line(), "lockMinutes": LOCK_MINUTES}

    def _vault_line(self) -> str:
        s = self.s
        return "Encrypted vault, unlocked. Saved %s." % dt.datetime.now().strftime("%H:%M") if s else "Locked."

    # ------------------------------------------------------------------ startup
    @api
    def status(self):
        acct = self.store.account()
        return {"hasVault": self.store.exists(), "signedIn": self.s is not None, "quickUser": self.quick_login,
                "account": None if not acct else {"first": acct.get("first", ""), "login": acct["login"],
                                                  "emailMasked": otpmod.mask_email(acct["email"]), "questions": [q["q"] for q in acct.get("q", [])]},
                "questions": QUESTIONS, "presets": otpmod.PRESETS, "dataDir": str(self.dir), "version": VERSION,
                "platform": sys.platform, "lockMinutes": LOCK_MINUTES}

    # ------------------------------------------------------------------ registration
    @api
    def register_start(self, p: dict):
        if self.store.vault_path.exists():
            raise ValueError("A KinKeep account already exists on this computer. Sign in instead.")
        v = lambda k: str(p.get(k) or "").strip()
        d = {"first": v("first")[:60], "last": v("last")[:60], "email": v("email")[:120], "dob": v("dob"), "login": v("login")}
        pw, pw2 = str(p.get("password") or ""), str(p.get("password2") or "")
        qs = p.get("questions") or []
        if not d["first"] or not d["last"]:
            raise ValueError("Please enter your first and last name.")
        if not EMAIL_RX.match(d["email"]):
            raise ValueError("Please enter a valid email address. Your codes are sent there.")
        try:
            dob = dt.date.fromisoformat(d["dob"])
            if dob > dt.date.today() or dob.year < 1900:
                raise ValueError
        except ValueError:
            raise ValueError("Please enter your date of birth.") from None
        if not LOGIN_RX.match(d["login"]):
            raise ValueError("Your login name needs 3 to 30 letters, numbers, dots, dashes or underscores.")
        if len(qs) != 3 or len({int(q.get("qi", -1)) for q in qs}) != 3 or any(not 0 <= int(q.get("qi", -1)) < len(QUESTIONS) for q in qs):
            raise ValueError("Pick three different questions.")
        answers = [str(q.get("answer") or "") for q in qs]
        if any(len(crypto.norm_answer(a)) < 2 for a in answers):
            raise ValueError("Please answer all three questions (at least 2 letters or numbers each).")
        if len({crypto.norm_answer(a) for a in answers}) < 3:
            raise ValueError("Use a different answer for each question.")
        if len(pw) < 10:
            raise ValueError("Your password needs at least 10 characters. Three or four random words work well.")
        if pw != pw2:
            raise ValueError("The two passwords do not match.")
        if d["login"].lower() in pw.lower() or pw.lower() == d["email"].lower():
            raise ValueError("Your password should not contain your login name or email.")
        d["q"] = [{"q": QUESTIONS[int(q["qi"])], **crypto.hash_answer(a)} for q, a in zip(qs, answers)]
        smtp = p.get("smtp") or {}
        demo = bool(p.get("demo")) or (self.sender_override is None and not otpmod.smtp_ready(smtp))
        self.pending = {"kind": "reg", "profile": d, "password": pw, "smtp": smtp, "demo": demo, "verified": False}
        info = self._issue(d["email"], "reg", smtp, demo)
        self.pending["otp"] = info["id"]
        return {"otp": info}

    @api
    def otp_resend(self):
        pd = self.pending or {}
        if pd.get("kind") == "reg":
            info = self._issue(pd["profile"]["email"], "reg", pd["smtp"], pd["demo"])
        elif pd.get("kind") in ("login", "reset"):
            info = self._issue(pd["email"], pd["kind"], pd.get("smtp"), pd.get("demo", False))
        else:
            raise ValueError("There is nothing to send a code for.")
        pd["otp"] = info["id"]
        return {"otp": info}

    @api
    def otp_verify(self, code: str):
        pd = self.pending
        if not pd or not pd.get("otp"):
            raise ValueError("No code has been sent yet. Press Resend code.")
        r = self.otp.verify(pd["otp"], code, pd["kind"])
        if not r["ok"]:
            msg = {"expired": "That code has expired. Press Resend code.", "locked": "Too many wrong tries. Press Resend code for a new one."}.get(
                r["error"], "That code is not right." + (" %d tries left." % r["left"] if r.get("left") is not None else ""))
            return {"ok": False, "error": msg}
        pd["verified"] = True
        if pd["kind"] == "login":
            return self._finish_login()
        return {"next": pd["kind"]}

    @api
    def register_finish(self, opts: dict):
        pd = self.pending
        if not pd or pd.get("kind") != "reg" or not pd.get("verified"):
            raise access.Denied("Confirm your email first.")
        smtp = dict(pd["smtp"]) if otpmod.smtp_ready(pd["smtp"]) else {}
        meta = {"smtp": smtp, "demo_otp": bool(pd["demo"]), "emergency_until": "", "mirrors": []}
        start = opts.get("start", "empty")
        kind = ""
        if start == "backup":
            blob = base64.b64decode(opts["backup_b64"])
            s, rk, kind = self.store.restore_new(pd["profile"], pd["password"], blob, opts.get("backup_password") or pd["password"])
            s.meta.update(meta)
        else:
            data = schema.normalize(opts.get("sample") if start == "sample" else None)
            data["settings"]["docStore"] = opts.get("docStore") if opts.get("docStore") in ("drive", "computer", "other") else ""
            s, rk = self.store.create(pd["profile"], pd["password"], data, meta)
        s.commit()
        self.s, self.pending, self.quick_login = s, None, s.login
        out = self._state_payload()
        out.update({"recoveryKey": rk, "restoredFrom": kind})
        return out

    # ------------------------------------------------------------------ sign in
    @api
    def login(self, login: str, password: str):
        key = login.strip().lower()
        wait = self._locked_out(key)
        if wait:
            raise ValueError("Too many wrong tries. Please wait %d seconds." % wait)
        try:
            s = self.store.unlock(login, password)
        except crypto.WrongPassword:
            self._fail(key)
            raise crypto.WrongPassword(GENERIC_LOGIN_ERR) from None
        self._ok(key)
        if s.role == access.EMERGENCY and not access.emergency_active(s.meta):
            raise access.Denied("The Owner has not approved emergency access right now.")
        acct = self.store.account() or {}
        email = acct.get("email") if s.slot_id == storemod.OWNER_SLOT else next((m["email"] for m in s.members if m["slot_id"] == s.slot_id), "")
        self.pending = {"kind": "login", "session": s, "email": email, "smtp": s.meta.get("smtp"), "demo": bool(s.meta.get("demo_otp")), "verified": False}
        info = self._issue(email, "login", s.meta.get("smtp"), self.pending["demo"])
        self.pending["otp"] = info["id"]
        return {"otp": info}

    def _finish_login(self):
        pd = self.pending
        self.s, self.pending, self.quick_login = pd["session"], None, pd["session"].login
        return self._state_payload()

    @api
    def login_with_recovery_key(self, login: str, recovery_key: str):
        """Offline second factor for the Owner: the recovery key proves possession of the secret printed at setup."""
        pd = self.pending
        if not pd or pd.get("kind") != "login":
            raise access.Denied("Enter your password first.")
        if pd["session"].slot_id != storemod.OWNER_SLOT:
            raise access.Denied("Only the Owner can use the recovery key here.")
        key = "rk:" + login.strip().lower()
        if self._locked_out(key):
            raise ValueError("Too many wrong tries. Please wait.")
        try:
            crypto.open_recovery_slot(crypto.find_slot({"slots": pd["session"].slots}, "recovery"), recovery_key)
        except crypto.WrongPassword:
            self._fail(key)
            raise
        self._ok(key)
        return self._finish_login()

    @api
    def unlock(self, password: str):
        """After the idle lock: the password alone, as in the web version."""
        if not self.quick_login:
            raise access.Denied("Please sign in.")
        key = self.quick_login.lower()
        if self._locked_out(key):
            raise ValueError("Too many wrong tries. Please wait.")
        try:
            s = self.store.unlock(self.quick_login, password)
        except crypto.WrongPassword:
            self._fail(key)
            raise crypto.WrongPassword("That password is not correct.") from None
        self._ok(key)
        self.s = s
        return self._state_payload()

    @api
    def lock(self):
        if self.s:
            self.s = None  # keys and records leave memory; quick_login stays so the password alone unlocks
        return {}

    @api
    def signout(self):
        self.s, self.quick_login, self.pending = None, None, None
        return {}

    # ------------------------------------------------------------------ data
    @api
    def load_state(self):
        return self._state_payload()

    @api
    def save_state(self, state: dict, base_seq: int | None = None):
        """base_seq is the vault generation the screen was built from. If the vault has moved on (another
        window or a restore changed it) the save is refused so a stale screen can never overwrite newer data."""
        s = self._need()
        if base_seq is not None and int(base_seq) != s.seq:
            return {"ok": False, "stale": True, "error": "The records changed somewhere else. Your screen was refreshed; please repeat your change."}
        if s.role == access.EMERGENCY:
            raise access.Denied("This sign-in can only read.")
        new = access.merge_back(s.data, state, s.role, s.name)
        if xlsx_io.content_hash(new) == xlsx_io.content_hash(s.data):
            return {"seq": s.seq, "changed": False}
        s.data = new
        if s.role in (access.OWNER, access.COOWNER):
            self.store.sync_member_roles(s)
        s.commit()
        return {"seq": s.seq, "changed": True, "vaultLine": self._vault_line()}

    # ------------------------------------------------------------------ forgot password
    @api
    def forgot_start(self):
        acct = self.store.account()
        if not acct:
            raise ValueError("There is no account on this computer yet.")
        return {"questions": [q["q"] for q in acct["q"]], "emailMasked": otpmod.mask_email(acct["email"])}

    @api
    def forgot_answers(self, answers: list):
        acct = self.store.account()
        if not acct or len(answers) != 3:
            raise ValueError("Answer all three questions.")
        if self._locked_out("forgot"):
            raise ValueError("Too many wrong tries. Please wait %d minutes." % (self._locked_out("forgot") // 60 + 1))
        if not all(crypto.check_answer(a, q) for a, q in zip(answers, acct["q"])):
            self._fail("forgot")
            raise ValueError("Those answers did not match.")
        self._ok("forgot")
        smtp = self._saved_smtp()
        self.pending = {"kind": "reset", "email": acct["email"], "smtp": smtp, "demo": not otpmod.smtp_ready(smtp) and self.sender_override is None, "verified": False}
        info = self._issue(acct["email"], "reset", smtp, self.pending["demo"])
        self.pending["otp"] = info["id"]
        return {"otp": info}

    def _saved_smtp(self):
        try:
            from . import secret_store
            return secret_store.load_smtp()
        except Exception:
            return None

    @api
    def reset_password(self, new_password: str, recovery_key: str = ""):
        """Needs the 3 answers AND the emailed code (both already passed). With the recovery key the records are kept;
        without it the old vault is set aside as an encrypted backup and a new empty vault is started."""
        pd = self.pending
        if not pd or pd.get("kind") != "reset" or not pd.get("verified"):
            raise access.Denied("Verify your answers and the emailed code first.")
        acct = self.store.account()
        if len(new_password) < 10:
            raise ValueError("Your password needs at least 10 characters.")
        if acct["login"].lower() in new_password.lower():
            raise ValueError("Your password should not contain your login name.")
        if recovery_key.strip():
            s = self.store.unlock_with_recovery(recovery_key)
            self.store.reset_password_after_recovery(s, new_password)
            s.meta.pop("emergency_until", None); s.meta["emergency_until"] = ""
            s.commit()
            self.s, self.pending, self.quick_login = s, None, s.login
            out = self._state_payload()
            out["kept"] = True
            return out
        archive = self.dir / "backups" / ("old-vault-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
        archive.mkdir(parents=True, exist_ok=True)
        for f in (storemod.VAULT_NAME, storemod.XLSX_NAME):
            if (self.dir / f).exists():
                os.replace(self.dir / f, archive / f)
        profile = {k: acct[k] for k in ("first", "last", "email", "dob", "login", "q")}
        s, rk = self.store.create(profile, new_password, None, {"smtp": {}, "demo_otp": True, "emergency_until": "", "mirrors": []})
        self.s, self.pending, self.quick_login = s, None, s.login
        out = self._state_payload()
        out.update({"kept": False, "recoveryKey": rk, "archivedTo": str(archive)})
        return out

    # ------------------------------------------------------------------ account, security
    @api
    def change_password(self, current: str, new: str):
        s = self._need()
        if len(new) < 10:
            raise ValueError("The new password needs at least 10 characters.")
        if s.login.lower() in new.lower():
            raise ValueError("Your password should not contain your login name.")
        self.store.change_password(s, current, new)
        return {"message": "Password changed. Older backups still need the password they were saved with."}

    @api
    def rotate_recovery_key(self, password: str):
        s = self._need()
        crypto.open_password_slot(crypto.find_slot({"slots": s.slots}, s.slot_id), password)
        return {"recoveryKey": self.store.rotate_recovery_key(s)}

    @api
    def member_add(self, access_id: str, login: str, email: str, password: str):
        s = self._need()
        if not EMAIL_RX.match(email or ""):
            raise ValueError("Enter the person's email address. Their sign-in codes go there.")
        self.store.add_member(s, access_id, login, email, password)
        return self._state_payload()

    @api
    def member_remove(self, access_id: str):
        self.store.remove_member(self._need(), access_id)
        return self._state_payload()

    @api
    def members(self):
        s = self._need()
        if s.role not in (access.OWNER, access.COOWNER):
            raise access.Denied("Only the Owner or a Co-owner can see logins.")
        return {"members": [{k: m[k] for k in ("access_id", "login", "email", "name", "role")} for m in s.members]}

    @api
    def emergency_grant(self, hours: int):
        s = self._need()
        access.check_action(s.role, "grant_emergency")
        hours = max(1, min(int(hours), 24 * 14))
        s.meta["emergency_until"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)).isoformat(timespec="seconds")
        s.commit()
        return {"until": s.meta["emergency_until"]}

    @api
    def emergency_revoke(self):
        s = self._need()
        access.check_action(s.role, "grant_emergency")
        s.meta["emergency_until"] = ""
        s.commit()
        return {}

    @api
    def smtp_save(self, cfg: dict, demo: bool = False):
        s = self._need()
        if s.role != access.OWNER:
            raise access.Denied("Only the Owner can change email settings.")
        clean = {k: str(cfg.get(k) or "")[:200] for k in ("host", "user", "password", "from", "security")}
        clean["port"] = int(cfg.get("port") or 465)
        if cfg.get("password") == "" and s.meta.get("smtp", {}).get("password"):
            clean["password"] = s.meta["smtp"]["password"]  # blank = keep the saved one
        s.meta["smtp"] = clean if otpmod.smtp_ready(clean) else {}
        s.meta["demo_otp"] = bool(demo) or not otpmod.smtp_ready(clean)
        s.commit()
        try:
            from . import secret_store
            secret_store.save_smtp(s.meta["smtp"])
        except Exception:
            pass
        return {"configured": otpmod.smtp_ready(s.meta["smtp"]), "demo": s.meta["demo_otp"]}

    @api
    def smtp_test(self):
        s = self._need()
        acct = self.store.account()
        if not otpmod.smtp_ready(s.meta.get("smtp")):
            raise ValueError("Email is not set up yet.")
        otpmod.smtp_sender(s.meta["smtp"])(acct["email"], "KinKeep test message", "This is a test from KinKeep. Your email settings work.")
        return {"message": "A test message was sent to " + otpmod.mask_email(acct["email"]) + "."}

    @api
    def security_status(self):
        s = self._need()
        smtp = s.meta.get("smtp")
        return {"secondFactor": "email" if otpmod.smtp_ready(smtp) and not s.meta.get("demo_otp") else "demo",
                "kdf": "Argon2id (%d MiB, %d passes)" % (crypto.KDF_COST["m"] // 1024, crypto.KDF_COST["t"]), "cipher": "AES-256-GCM",
                "xlsx": "Office AES-256 (agile)" if self.store.xlsx_mode == "agile" else "Office AES-128 (compatibility)",
                "emergencyUntil": s.meta.get("emergency_until", ""), "xlsxStale": (s.sync or {}).get("state") not in (None, "in_sync", "regenerated"),
                "hasMembers": bool(s.members), "dataDir": str(self.dir), "mirrors": s.meta.get("mirrors", [])}

    # ------------------------------------------------------------------ spreadsheet, backups
    @api
    def spreadsheet_info(self):
        s = self._need()
        return {"path": str(self.store.xlsx_path), "exists": self.store.xlsx_path.exists(), "seq": s.seq, "mode": self.store.xlsx_mode,
                "sync": (s.sync or {}).get("state", ""), "ownerOnly": s.role != access.OWNER}

    @api
    def set_xlsx_mode(self, mode: str):
        s = self._need()
        if s.role != access.OWNER or mode not in ("agile", "standard"):
            raise access.Denied("Only the Owner can do that.")
        self.store.xlsx_mode = mode
        s.commit()
        return {"mode": mode}

    @api
    def sync_resolve(self, choice: str):
        s = self._need()
        self.store.resolve_sync(s, choice)
        s.sync = {"state": "in_sync"}
        return self._state_payload()

    @api
    def export_backup(self, kind: str):
        s = self._need()
        stamp = dt.datetime.now().strftime("%Y-%m-%d")
        tmp = self.dir / ".export.tmp"
        if kind == "vault":
            self.store.export_vault_backup(s, tmp)
            name = f"KinKeep vault {stamp}.kinkeep.json"
        elif kind == "xlsx":
            self.store.export_xlsx_backup(s, tmp)
            name = f"KinKeep data {stamp}.xlsx"
        else:
            raise ValueError("Unknown backup type.")
        try:
            where = self.host.save_file(name, tmp.read_bytes())
        finally:
            tmp.unlink(missing_ok=True)
        return {"path": where, "name": name}

    @api
    def backup_inspect(self, b64: str, password: str, name: str = ""):
        s = self._need()
        if s.role != access.OWNER:
            raise access.Denied("Only the Owner can restore a backup.")
        blob = base64.b64decode(b64)
        info = self.store.inspect_backup(blob, password)
        self.restore_pending = {"blob": blob, "password": password}
        info.pop("_data")
        return info

    @api
    def backup_apply(self):
        s = self._need()
        rp = self.restore_pending
        if not rp:
            raise ValueError("Open a backup first.")
        r = self.store.restore_into(s, rp["blob"], rp["password"])
        self.restore_pending = None
        out = self._state_payload()
        out["restoredKind"] = r["kind"]
        return out

    @api
    def backup_cancel(self):
        self.restore_pending = None
        return {}

    @api
    def open_data_folder(self):
        self.host.open_folder(str(self.dir))
        return {"path": str(self.dir)}

    @api
    def open_url(self, url: str):
        if not re.match(r"^https://([a-z0-9-]+\.)*(google\.com|healthcare\.gov|ready\.gov|careeronestop\.org|identitytheft\.gov|weather\.gov|disasterassistance\.gov|travel\.state\.gov)(/|$)", url):
            raise access.Denied("That address is not on the list of sites KinKeep opens.")
        self.host.open_url(url)
        return {}

    @api
    def add_mirror(self, folder: str):
        s = self._need()
        if s.role != access.OWNER:
            raise access.Denied("Only the Owner can do that.")
        p = Path(folder)
        if not p.is_dir():
            raise ValueError("That folder does not exist.")
        mirrors = [m for m in s.meta.get("mirrors", []) if m != str(p)] + [str(p)]
        s.meta["mirrors"] = mirrors
        s.commit()
        return {"mirrors": mirrors}

    @api
    def remove_mirror(self, folder: str):
        s = self._need()
        if s.role != access.OWNER:
            raise access.Denied("Only the Owner can do that.")
        s.meta["mirrors"] = [m for m in s.meta.get("mirrors", []) if m != folder]
        s.commit()
        return {"mirrors": s.meta["mirrors"]}

    @api
    def pick_folder(self):
        s = self._need()
        if s.role != access.OWNER:
            raise access.Denied("Only the Owner can do that.")
        return {"folder": self.host.choose_folder()}

    @api
    def save_recovery_sheet(self, recovery_key: str):
        """A printable text sheet: the recovery key plus the steps to reach the data without KinKeep."""
        s = self._need()
        if s.role != access.OWNER:
            raise access.Denied("Only the Owner can do that.")
        crypto.open_recovery_slot(crypto.find_slot({"slots": s.slots}, "recovery"), recovery_key)  # must be the real key
        text = RECOVERY_SHEET.format(key=recovery_key, name=s.name, date=dt.date.today().isoformat(), folder=self.dir,
                                     vault=storemod.VAULT_NAME, xlsx=storemod.XLSX_NAME)
        where = self.host.save_file("KinKeep recovery sheet.txt", text.encode("utf-8"))
        return {"path": where}


RECOVERY_SHEET = """KINKEEP RECOVERY SHEET  -  keep this on paper, in a safe place, away from the computer
Prepared for: {name}      Date: {date}

RECOVERY KEY
    {key}

Anyone who has this key AND your data files can open your records. Treat it like a house key.
KinKeep does not store it and cannot show it again.

IF YOU FORGET YOUR PASSWORD
    Open KinKeep, choose "Forgot your password", answer your three questions, enter the emailed code,
    then type this recovery key. Your records are kept and you choose a new password.

IF KINKEEP WILL NOT START (no KinKeep needed)
    1. Find the file {xlsx} in {folder}  (or in any extra folder you added, or in a backup).
    2. Open it with Microsoft Excel, LibreOffice Calc, or any program that opens password-protected .xlsx files.
    3. Enter your KinKeep master password when asked. Every module is a separate sheet.
    4. If you do not know the password, KinKeep cannot recover the spreadsheet: only the password opens it.
       (This recovery key opens {vault} inside KinKeep, not the spreadsheet.)
"""
