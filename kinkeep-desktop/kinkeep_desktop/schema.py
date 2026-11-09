"""Data model of KinKeep, ported 1:1 from the browser version (collections, fields, select lists).

tests/test_parity.py re-reads the original kinkeep.html and fails if this file drifts from it.
"""
from __future__ import annotations
import copy
import datetime as dt
import re
import uuid

T = {
    "assetType": ["Bank", "Investment", "Retirement", "Real estate", "Gold", "Vehicle", "Other"],
    "cur": ["USD", "INR"], "country": ["US", "IN", "Other"],
    "src": ["Statement", "Estimate", "Appraisal", "Self-reported"],
    "liab": ["Mortgage", "Loan", "Credit card", "Other"],
    "kind": ["Health", "Life", "Disability", "Auto", "Home", "Umbrella", "Travel", "Employer benefit"],
    "docCat": ["Insurance", "Identity", "Legal", "Tax", "Property", "Medical", "Other"],
    "docStatus": ["On file", "Missing"],
    "remType": ["Bill", "Renewal", "Tax", "Document", "Benefits", "Other"],
    "cRole": ["Emergency contact", "Doctor", "Attorney", "Insurance agent", "CPA", "Employer HR", "Other"],
    # Original roles were Owner, Adult, Teen, Viewer, Emergency only. Co-owner is new; the others are kept
    # (renamed to the desktop wording). LEGACY_ROLES maps old stored values onto the new names.
    "aRole": ["Owner", "Co-owner", "Adult Family Member", "Teen", "Viewer", "Emergency Contact"],
    "aStatus": ["Active", "Invited", "Needs re-approval", "Suspended"],
    "idType": ["Passport", "Driver license", "State ID", "Green card / permanent resident", "Visa", "Work permit (EAD)",
               "OCI card", "Aadhaar", "PAN card", "Voter ID", "Social Security card", "Birth certificate",
               "Health insurance card", "School or student ID", "Other"],
    "lead": ["180", "90", "60", "30"],
    "willType": ["Last will", "Revocable living trust", "Irrevocable trust", "Financial power of attorney",
                 "Guardianship for children", "Letter of instruction", "Other"],
    "stage": ["Signed and stored", "Draft with attorney", "Not started"],
    "cycle": ["36", "24", "12", "60"],
    "wishTopic": ["Healthcare directive (living will)", "Healthcare proxy (who decides)", "Do-not-resuscitate or POLST",
                  "Organ and tissue donation", "Medical conditions and allergies", "Medications",
                  "Preferred doctor or hospital", "Burial or cremation", "Celebration of life",
                  "Religious or cultural rites", "Memorial gifts or charity", "Obituary and message to family",
                  "Digital accounts and passwords plan", "Care for pets or dependents", "Other"],
}
LEGACY_ROLES = {"Adult": "Adult Family Member", "Emergency only": "Emergency Contact", "Emergency contact": "Emergency Contact"}


def F(k, label, t="text", o=None, wide=False):
    return {"k": k, "l": label, "t": t, "o": o or [], "wide": wide}


# name -> (sheet title, noun, fields). Order = order of sheets in the spreadsheet.
C = {
    "assets": ("Assets", "asset", [F("name", "Name"), F("type", "Type", "select", T["assetType"]), F("owner", "Owner"),
        F("country", "Country", "select", T["country"]), F("currency", "Currency", "select", T["cur"]),
        F("value", "Value", "number"), F("date", "Valued on", "date"), F("source", "Source", "select", T["src"])]),
    "liabs": ("Liabilities", "liability", [F("name", "Name"), F("type", "Type", "select", T["liab"]), F("owner", "Owner"),
        F("currency", "Currency", "select", T["cur"]), F("balance", "Balance", "number"), F("rate", "Interest %", "number"),
        F("payment", "Monthly payment", "number"), F("due", "Next due", "date")]),
    "policies": ("Insurance", "policy or benefit", [F("kind", "Type", "select", T["kind"]), F("name", "Insurer / plan"),
        F("holder", "Covered person"), F("limit", "Limit"), F("deductible", "Deductible"), F("renewal", "Renews", "date"),
        F("beneficiary", "Beneficiary"), F("claims", "Claims phone"), F("notes", "Notes (exclusions, reminders)", wide=True)]),
    "docs": ("Documents", "document", [F("title", "Title"), F("category", "Category", "select", T["docCat"]),
        F("owner", "Belongs to"), F("expires", "Expires", "date"), F("file", "File name"), F("status", "Status", "select", T["docStatus"])]),
    "ids": ("Identity", "identity record", [F("person", "Person"), F("idType", "ID type", "select", T["idType"]),
        F("number", "Last 4 of ID number only"), F("issuer", "Issued by (country or state)"), F("issued", "Issued on", "date"),
        F("expires", "Expires on", "date"), F("lead", "Remind me (days before expiry)", "select", T["lead"]),
        F("notes", "Notes (renewal steps, where the original is kept)", wide=True)]),
    "wills": ("WillAndTrust", "will or trust record", [F("title", "Document name"), F("docType", "Type", "select", T["willType"]),
        F("person", "Whose document"), F("executor", "Executor or trustee"), F("backup", "Backup executor or trustee"),
        F("heirs", "Main beneficiaries"), F("guardian", "Guardian named for minor children"), F("attorney", "Attorney or firm"),
        F("jurisdiction", "State or country"), F("signed", "Date signed", "date"), F("reviewed", "Last reviewed on", "date"),
        F("cycle", "Review every (months)", "select", T["cycle"]), F("location", "Where the original is kept"),
        F("online", "Online will service or website (if any)"), F("softcopy", "Soft copy: Google Drive link or file ID"),
        F("progress", "Stage", "select", T["stage"]), F("notes", "Notes", wide=True)]),
    "wishes": ("MedicalAndWishes", "wish note", [F("person", "Whose wish"), F("topic", "Topic", "select", T["wishTopic"]),
        F("summary", "The wish, in a sentence"), F("contact", "Who knows or will carry it out"),
        F("location", "Where the details are kept"), F("reviewed", "Last reviewed on", "date"), F("notes", "Notes", wide=True)]),
    "reminders": ("Reminders", "reminder", [F("title", "Reminder"), F("due", "Due", "date"), F("type", "Type", "select", T["remType"])]),
    "contacts": ("Contacts", "contact", [F("name", "Name"), F("relation", "Relationship"),
        F("role", "Role", "select", T["cRole"]), F("phone", "Phone")]),
    "access": ("FamilyAccess", "family member", [F("name", "Name"), F("role", "Role", "select", T["aRole"]),
        F("scope", "Can see"), F("status", "Status", "select", T["aStatus"])]),
}
COLLS = list(C)
FIELDS = {k: v[2] for k, v in C.items()}
SHEET = {k: v[0] for k, v in C.items()}
MAX_ROWS = 500


def iso(offset: int = 0) -> str:
    return (dt.date.today() + dt.timedelta(days=offset)).isoformat()


def nid() -> str:
    return "r" + uuid.uuid4().hex[:12]


def empty_state() -> dict:
    d = {"rate": 85, "rateDate": iso(0), "plan": {"medical": "", "instructions": ""}, "check": {},
         "settings": {"docStore": "", "targets": {"file": False, "drive": False}}}
    for k in COLLS:
        d[k] = []
    return d


def _num(v) -> float:
    try:
        n = float(v)
        return n if n == n and abs(n) != float("inf") else 0
    except (TypeError, ValueError):
        return 0


def normalize(d) -> dict:
    """Data read back from storage is untrusted: rebuild it field by field (same limits as the web app)."""
    d = d if isinstance(d, dict) else {}
    out = empty_state()
    r = _num(d.get("rate"))
    out["rate"] = r if r > 0 else 85
    out["rateDate"] = str(d.get("rateDate") or iso(0))[:10]
    for coll in COLLS:
        rows = d.get(coll) if isinstance(d.get(coll), list) else []
        for r in rows[:MAX_ROWS]:
            if not isinstance(r, dict):
                continue
            rid = r.get("id")
            o = {"id": rid[:40] if isinstance(rid, str) and rid else nid()}
            for f in FIELDS[coll]:
                v = r.get(f["k"])
                if f["t"] == "number":
                    o[f["k"]] = _num(v)
                else:
                    o[f["k"]] = ("" if v is None else str(v))[:500]
            if coll == "access":
                o["role"] = LEGACY_ROLES.get(o["role"], o["role"])
                if o["role"] not in T["aRole"]:
                    o["role"] = "Viewer"
                if o["status"] not in T["aStatus"]:
                    o["status"] = "Invited"
            if coll == "reminders":
                o["done"] = bool(r.get("done"))
            out[coll].append(o)
    p = d.get("plan")
    if isinstance(p, dict):
        out["plan"] = {"medical": str(p.get("medical") or "")[:2000], "instructions": str(p.get("instructions") or "")[:2000]}
    ck = d.get("check")
    if isinstance(ck, dict):
        for k in list(ck)[:30]:
            c = ck[k]
            if isinstance(c, dict):
                out["check"][str(k)[:20]] = {str(i)[:4]: bool(v) for i, v in list(c.items())[:30]}
    st = d.get("settings") if isinstance(d.get("settings"), dict) else {}
    tg = st.get("targets") if isinstance(st.get("targets"), dict) else {}
    out["settings"] = {"docStore": st.get("docStore") if st.get("docStore") in ("drive", "computer", "other") else "",
                       "targets": {"file": bool(tg.get("file")), "drive": bool(tg.get("drive"))}}
    return out


def blank_like(d: dict) -> dict:
    return copy.deepcopy(d)
