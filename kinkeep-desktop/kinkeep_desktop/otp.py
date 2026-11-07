"""Six-digit email codes, generated and checked locally. Same limits as the web version's email service:
10 minute life, 5 tries per code, one code per 25 seconds, 6 per hour per address.
Codes are kept only as salted hashes in memory and are never logged or written to disk."""
from __future__ import annotations
import hashlib
import hmac
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Callable

TTL, MAX_TRIES, COOLDOWN, PER_HOUR = 600, 5, 25, 6
SUBJECT = {"reg": "Confirm your email for KinKeep", "login": "Your KinKeep sign-in code", "reset": "Your KinKeep password reset code"}
PRESETS = {
    "gmail": {"host": "smtp.gmail.com", "port": 465, "security": "ssl", "note": "Use an app password (Google Account > Security > App passwords)."},
    "outlook": {"host": "smtp-mail.outlook.com", "port": 587, "security": "starttls", "note": "Needs SMTP AUTH enabled for the mailbox and an app password."},
    "yahoo": {"host": "smtp.mail.yahoo.com", "port": 465, "security": "ssl", "note": "Use an app password from Yahoo Account Security."},
    "icloud": {"host": "smtp.mail.me.com", "port": 587, "security": "starttls", "note": "Use an app-specific password from appleid.apple.com."},
    "custom": {"host": "", "port": 465, "security": "ssl", "note": "Ask your email provider for the SMTP server, port and security type."},
}


class OtpError(Exception):
    pass


class RateLimited(OtpError):
    pass


class SendFailed(OtpError):
    pass


def smtp_ready(cfg: dict | None) -> bool:
    c = cfg or {}
    return bool(c.get("host") and c.get("user") and c.get("password") and c.get("from"))


def smtp_sender(cfg: dict) -> Callable[[str, str, str], None]:
    def send(to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = cfg["from"], to, subject
        msg.set_content(body)
        ctx = ssl.create_default_context()  # certificates are always verified
        try:
            if cfg.get("security", "ssl") == "ssl":
                with smtplib.SMTP_SSL(cfg["host"], int(cfg.get("port", 465)), context=ctx, timeout=15) as s:
                    s.login(cfg["user"], cfg["password"]); s.send_message(msg)
            else:
                with smtplib.SMTP(cfg["host"], int(cfg.get("port", 587)), timeout=15) as s:
                    s.starttls(context=ctx); s.login(cfg["user"], cfg["password"]); s.send_message(msg)
        except (smtplib.SMTPException, OSError) as e:
            raise SendFailed(e.__class__.__name__) from None
    return send


def mask_email(e: str) -> str:
    p = str(e).split("@")
    return "***" if len(p) < 2 else p[0][:1] + "***@" + p[1]


class OtpService:
    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.codes: dict[str, dict] = {}
        self.sends: dict[str, list[float]] = {}

    def issue(self, email: str, purpose: str, sender: Callable[[str, str, str], None] | None, demo: bool = False) -> dict:
        email = email.strip().lower()
        now = self.clock()
        hist = [t for t in self.sends.get(email, []) if now - t < 3600]
        if len(hist) >= PER_HOUR or (hist and now - hist[-1] < COOLDOWN):
            raise RateLimited("rate_limited")
        code = str(100000 + secrets.randbelow(900000))
        if demo:
            shown = code
        else:
            if sender is None:
                raise SendFailed("not_configured")
            sender(email, SUBJECT.get(purpose, SUBJECT["login"]),
                   f"Your KinKeep code is {code}. It expires in 10 minutes.\nIf you did not ask for it, ignore this email and consider changing your password.")
            shown = None
        hist.append(now)
        self.sends[email] = hist
        cid, salt = secrets.token_hex(16), secrets.token_bytes(8)
        self.codes = {k: v for k, v in self.codes.items() if v["exp"] > now}
        self.codes[cid] = {"email": email, "salt": salt, "h": self._h(code, salt), "exp": now + TTL, "tries": 0, "purpose": purpose}
        out = {"id": cid, "expiresIn": TTL}
        if demo:
            out["demo_code"] = shown
        return out

    @staticmethod
    def _h(code: str, salt: bytes) -> bytes:
        return hashlib.sha256(salt + b":" + code.encode()).digest()

    def verify(self, cid: str, code: str, purpose: str | None = None) -> dict:
        c = self.codes.get(cid)
        if not c or c["exp"] < self.clock():
            return {"ok": False, "error": "expired"}
        if purpose and c["purpose"] != purpose:
            return {"ok": False, "error": "wrong"}
        if c["tries"] >= MAX_TRIES:
            return {"ok": False, "error": "locked"}
        c["tries"] += 1
        if hmac.compare_digest(self._h("".join(str(code).split()), c["salt"]), c["h"]):
            del self.codes[cid]  # single use
            return {"ok": True}
        return {"ok": False, "error": "wrong", "left": MAX_TRIES - c["tries"]}
