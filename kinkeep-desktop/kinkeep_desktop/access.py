"""Family roles and what each may see or change. Enforced in Python (the user interface only ever
receives the filtered data, and writes are merged back through merge_back), never trusted from the UI.

Honest limit: all roles are protected by the same vault file. Roles stop people from using KinKeep
to see or change what they should not; they do not stop someone who has the master password and a
spreadsheet program from reading the spreadsheet. See docs/SECURITY.md.
"""
from __future__ import annotations
import copy
import datetime as dt

from . import schema

VIEW_OF = {"assets": "assets", "liabs": "liab", "policies": "cover", "docs": "docs", "ids": "ids", "wills": "will",
           "wishes": "wish", "reminders": "rem", "contacts": "plan", "access": "plan"}
VIEWS = ["home", "dash", "rem", "emerg", "assets", "liab", "cover", "docs", "ids", "will", "wish", "plan", "drive"]

OWNER, COOWNER, ADULT, TEEN, VIEWER, EMERGENCY = schema.T["aRole"]
_ALL_RW = {v: "rw" for v in VIEWS}
PERMS: dict[str, dict[str, str]] = {
    OWNER: dict(_ALL_RW),
    COOWNER: dict(_ALL_RW),
    # "drive" is the Storage and Security page. Every signed-in family member gets it read-only so they can
    # change their own password and lock the app; owner-only panels are hidden and refused by the engine.
    ADULT: {**_ALL_RW, "will": "r", "wish": "r", "drive": "r"},
    TEEN: {"home": "r", "rem": "r", "emerg": "r", "docs": "r", "ids": "r", "plan": "r", "drive": "r"},
    VIEWER: {"home": "r", "dash": "r", "rem": "r", "emerg": "r", "docs": "r", "ids": "r", "plan": "r", "drive": "r"},
    EMERGENCY: {"emerg": "r", "plan": "r"},
}
# collections inside "plan" that a role sees even though it cannot see the whole view
COLL_READ_OVERRIDES = {TEEN: {"access": ""}, VIEWER: {"access": ""}, EMERGENCY: {"access": ""}}
SEALED = {"wills", "wishes"}  # Adult Family Member sees these without the private notes
OWNER_ONLY_ACTIONS = {"clear", "reset", "delete_vault", "set_owner_password", "grant_emergency", "remove_owner"}
CO_OWNER_FORBIDDEN_ROLES = {OWNER, COOWNER}


class Denied(PermissionError):
    pass


def view_perm(role: str, view: str) -> str:
    return PERMS.get(role, {}).get(view, "")


def coll_perm(role: str, coll: str) -> str:
    ov = COLL_READ_OVERRIDES.get(role, {})
    if coll in ov:
        return ov[coll]
    return view_perm(role, VIEW_OF[coll])


def perms_for(role: str) -> dict:
    return {"role": role, "views": {v: view_perm(role, v) for v in VIEWS},
            "colls": {c: coll_perm(role, c) for c in schema.COLLS}}


def emergency_active(meta: dict, now: dt.datetime | None = None) -> bool:
    until = (meta or {}).get("emergency_until") or ""
    try:
        return dt.datetime.fromisoformat(until) > (now or dt.datetime.now(dt.timezone.utc))
    except ValueError:
        return False


def _first(name: str) -> str:
    return (name or "").strip().split(" ")[0].lower()


def _mine(row: dict, who: str, key: str) -> bool:
    v = (row.get(key) or "").lower()
    return bool(who) and (who in v.split() or v in ("both", "family", "everyone"))


def filter_state(full: dict, role: str, member_name: str = "") -> dict:
    """What the interface may see for this role."""
    d = copy.deepcopy(full)
    who = _first(member_name)
    for coll in schema.COLLS:
        p = coll_perm(role, coll)
        if not p:
            d[coll] = []
            continue
        if role == TEEN and coll == "docs":
            d[coll] = [r for r in d[coll] if _mine(r, who, "owner")]
        if role == TEEN and coll == "ids":
            d[coll] = [r for r in d[coll] if _mine(r, who, "person")]
        if role == EMERGENCY and coll == "policies":
            d[coll] = [r for r in d[coll] if r["kind"] == "Health"]
        if role == ADULT and coll in SEALED:
            for r in d[coll]:
                r["notes"] = ""
    if role == EMERGENCY:
        for coll in ("assets", "liabs", "docs", "ids", "wills", "wishes", "reminders"):
            d[coll] = []
        d["policies"] = [r for r in full["policies"] if r["kind"] == "Health"]
    if not view_perm(role, "plan"):
        d["plan"] = {"medical": "", "instructions": ""}
    if role in (VIEWER, TEEN):
        d["plan"] = {"medical": d["plan"]["medical"], "instructions": d["plan"]["instructions"]}
    if not view_perm(role, "drive"):
        d["settings"] = {"docStore": "", "targets": {"file": False, "drive": False}}
    return d


def merge_back(full: dict, incoming: dict, role: str, actor_name: str = "") -> dict:
    """Apply a save from a signed-in person. Anything the role may not change is kept from `full`."""
    out = copy.deepcopy(full)
    inc = schema.normalize(incoming)
    for coll in schema.COLLS:
        if coll_perm(role, coll) != "rw":
            continue
        if coll == "access":
            out[coll] = _merge_access(full[coll], inc[coll], role)
        else:
            out[coll] = inc[coll]
    if view_perm(role, "plan") == "rw":
        out["plan"] = inc["plan"]
    if view_perm(role, "assets") == "rw":
        out["rate"], out["rateDate"] = inc["rate"], inc["rateDate"]
    if view_perm(role, "drive") == "rw":
        out["settings"] = inc["settings"]
    if view_perm(role, "emerg"):
        out["check"] = inc["check"]  # ticking an emergency checklist is allowed for everyone who can see it
    return out


def _merge_access(old: list, new: list, role: str) -> list:
    if role == OWNER:
        if not any(r["role"] == OWNER for r in new):
            raise Denied("There must always be an Owner.")
        return new
    # Co-owner: may manage everyone except Owners and other Co-owners; cannot hand out those roles.
    old_by = {r["id"]: r for r in old}
    new_by = {r["id"]: r for r in new}
    for rid, r in old_by.items():
        if r["role"] in CO_OWNER_FORBIDDEN_ROLES and (rid not in new_by or new_by[rid] != r):
            raise Denied("Only the Owner can change an Owner or Co-owner.")
    for rid, r in new_by.items():
        if r["role"] in CO_OWNER_FORBIDDEN_ROLES and old_by.get(rid) != r:
            raise Denied("Only the Owner can give the Owner or Co-owner role.")
    return new


def check_action(role: str, action: str) -> None:
    if action in OWNER_ONLY_ACTIONS and role != OWNER:
        raise Denied("Only the Owner can do that.")
