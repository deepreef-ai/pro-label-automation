"""Demo companies for the multi-tenant build (SPEC 6, issue #51 F1).

* ``CO-001`` Pro Labels: every row the build already makes (real client data when ``data/raw``
  exists, else the synthetic story). Nothing is copied out of it.
* ``CO-002`` Sunrise Flexo Prints and ``CO-003`` Nilgiri Label Works: made up. Each comes from a
  fresh run of the **synthetic** generator (never from real rows), with its own ids
  (``JC-1301`` -> ``JC-6301`` / ``JC-8301``), its own invented client and vendor names, and every
  text, link and JSON value rewritten to match. All their rows are ``is_demo = true``.

Companies and users follow the contract fixtures (``platform_companies.json``,
``company_users.json``) and the demo logins agreed on PR #67.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from core.etl.generate import Context, Rows, generate_demo
from core.tenancy import PLATFORM_TABLES

FIXTURES = Path(__file__).resolve().parents[4] / "contract" / "fixtures"
PRO_LABELS = "CO-001"
PLATFORM_ADMIN = {"id": "U-0900", "company_id": None, "name": "Platform Admin", "login": "admin@platform.example",
                  "role": "platform_admin", "sign_in": "otp_email", "device": None, "status": "active"}

# Made-up companies: id offset digit, seed, client and vendor name parts (all invented).
SYNTHETIC = {
    "CO-002": {
        "digit": 5, "seed": 2602,
        "places": ["Sahyadri", "Deccan", "Indrayani", "Pavana", "Bhima", "Koyna", "Shivneri", "Sinhagad",
                   "Rajgad", "Torna", "Purandar", "Lohgad", "Visapur", "Tikona", "Korigad", "Raigad",
                   "Pratapgad", "Panhala", "Vasota", "Jejuri", "Saswad", "Baramati", "Mulshi", "Velhe"],
        "owner": ("U-0201", "Meera Kulkarni", "+91 90000 00201"),
        "staff": [("U-0202", "Prakash Jadhav", "+91 90000 00202", "store"),
                  ("U-0203", "Swati Deshpande", "swati@sunriseflexo.example", "accounts"),
                  ("U-0204", "Ganesh Pawar", "+91 90000 00204", "production")],
    },
    "CO-003": {
        "digit": 7, "seed": 2603,
        "places": ["Velliangiri", "Marudhamalai", "Perur", "Kovai", "Pollachi", "Tiruppur", "Mettupalayam",
                   "Kotagiri", "Coonoor", "Sathy", "Annur", "Karamadai", "Sulur", "Avinashi", "Udumalai",
                   "Dharapuram", "Gobi", "Nambiyur", "Kangeyam", "Vellakoil", "Palladam", "Valparai",
                   "Anamalai", "Siruvani"],
        "owner": ("U-0301", "Karthik Subramaniam", "+91 90000 00301"),
        "staff": [("U-0302", "Lakshmi Narayanan", "lakshmi@nilgirilabels.example", "accounts")],
    },
}
CLIENT_KINDS = ["Foods", "Beverages", "Pharma", "Cosmetics", "Agro Products", "Dairy", "Chemicals", "Spices",
                "Wellness", "Organics", "Home Care", "Nutrition"]
VENDOR_KINDS = ["Films", "Papers", "Inks", "Adhesives", "Foils", "Laminates", "Coatings", "Cores"]

_ID = re.compile(r"^(?P<prefix>[A-Z]+(?:-\d{4})?-)(?P<num>\d+)$")


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def stamp(R: Rows, company_id: str) -> None:
    """Give every row of a company table its owner."""
    for table, rows in R.t.items():
        if table in PLATFORM_TABLES:
            continue
        for row in rows:
            row["company_id"] = company_id


def _id_map(R: Rows, digit: int) -> dict[str, str]:
    """Old id -> new id: the leading digit of the number becomes ``digit`` (JC-1301 -> JC-6301)."""
    out: dict[str, str] = {}
    for rows in R.t.values():
        for row in rows:
            for key in ("id", "job_card"):
                old = row.get(key)
                if not isinstance(old, str) or old in out:
                    continue
                m = _ID.match(old)
                if not m:
                    continue
                num = m["num"]
                width = len(num)
                new_num = int(num) + digit * 10 ** (width - 1)
                out[old] = f"{m['prefix']}{new_num:0{width}d}"
    return out


def _names(R: Rows, table: str, places: list[str], kinds: list[str], suffix: str, taken: set[str]) -> dict:
    out = {}
    pool = [f"{p} {k}{suffix}" for k in kinds for p in places]
    pool = [n for n in pool if n not in taken]
    for i, row in enumerate(sorted(R.t.get(table, []), key=lambda r: r["id"])):
        out[row["name"]] = pool[(i * 7) % len(pool)] if len(pool) > i else f"{places[0]} {i}"
    # make sure the mapping is one-to-one
    seen: dict[str, int] = {}
    for old, new in list(out.items()):
        if new in seen:
            seen[new] += 1
            out[old] = f"{new} {seen[new]}"
        else:
            seen[new] = 1
    return out


def _rewrite(value: Any, pattern: re.Pattern | None, repl: dict[str, str]) -> Any:
    if pattern is None:
        return value
    if isinstance(value, str):
        return pattern.sub(lambda m: repl[m.group(0)], value)
    if isinstance(value, list):
        return [_rewrite(v, pattern, repl) for v in value]
    if isinstance(value, dict):
        return {k: _rewrite(v, pattern, repl) for k, v in value.items()}
    return value


def _pattern(words: dict[str, str], ids: bool) -> re.Pattern | None:
    if not words:
        return None
    alts = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    if ids:
        return re.compile(rf"(?<![A-Za-z0-9-])(?:{alts})(?![0-9])")
    return re.compile(rf"(?:{alts})")


def synthetic_company(company_id: str, name: str, taken_names: set[str]) -> Rows:
    """A full synthetic data set for a made-up company (never derived from real rows)."""
    spec = SYNTHETIC[company_id]
    R = Rows()
    generate_demo(R, Context(), seed=spec["seed"], settings_overrides={"company_name": name})
    ids = _id_map(R, spec["digit"])
    names = _names(R, "clients", spec["places"], CLIENT_KINDS, "", taken_names)
    names |= _names(R, "vendors", spec["places"][::-1], VENDOR_KINDS, " Pvt Ltd", taken_names | set(names.values()))
    id_re, name_re = _pattern(ids, ids=True), _pattern(names, ids=False)
    for rows in R.t.values():
        for i, row in enumerate(rows):
            new = {}
            for k, v in row.items():
                v = _rewrite(v, id_re, ids)
                v = _rewrite(v, name_re, names)
                new[k] = v
            if "is_demo" in new:
                new["is_demo"] = True
            rows[i] = new
    stamp(R, company_id)
    return R


def add_platform(R: Rows) -> None:
    """Companies and users (SPEC 6): from the contract fixtures so mock and live agree."""
    companies = {c["id"]: c for c in _fixture("platform_companies")["items"]}
    profile = _fixture("company_profile")
    for cid in ("CO-001", "CO-002", "CO-003"):
        c = companies[cid]
        R.add("companies", {"id": cid, "name": c["name"], "slug": c["slug"], "city": c["city"], "state": c["state"],
                            "gstin": profile["gstin"] if cid == PRO_LABELS else None, "status": c["status"],
                            "plan": profile["plan"], "ai_budget_month": c["ai_budget_month"],
                            "ai_alert_pct": profile["ai_alert_pct"], "created_on": date.fromisoformat(c["created_on"])},
              demo=c["is_demo"])
    for u in _fixture("company_users")["items"]:
        R.add("users", {"id": u["id"], "company_id": PRO_LABELS, "name": u["name"], "login": u["login"],
                        "role": u["role"], "sign_in": u["sign_in"], "device": u["device"], "status": u["status"]})
    for cid, spec in SYNTHETIC.items():
        uid, uname, ulogin = spec["owner"]
        R.add("users", {"id": uid, "company_id": cid, "name": uname, "login": ulogin, "role": "owner",
                        "sign_in": "otp_phone", "device": "Laptop · Chrome", "status": "active"})
        for sid, sname, slogin, role in spec["staff"]:
            R.add("users", {"id": sid, "company_id": cid, "name": sname, "login": slogin, "role": role,
                            "sign_in": "otp_email" if "@" in slogin else "otp_phone", "device": None,
                            "status": "active"})
    R.add("users", dict(PLATFORM_ADMIN))


def add_tenants(R: Rows) -> list[Rows]:
    """Stamp CO-001 on ``R``, add the platform rows, and return the made-up companies' rows."""
    stamp(R, PRO_LABELS)
    add_platform(R)
    taken = {row["name"] for row in R.t.get("clients", [])} | {row["name"] for row in R.t.get("vendors", [])}
    out = []
    companies = {c["id"]: c["name"] for c in _fixture("platform_companies")["items"]}
    for cid in SYNTHETIC:
        rows = synthetic_company(cid, companies[cid], taken)
        taken |= {row["name"] for row in rows.t.get("clients", [])}
        out.append(rows)
    return out
