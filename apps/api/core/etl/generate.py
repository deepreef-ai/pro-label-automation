"""Deterministic DEMO data (all ``is_demo = true``) built on ``core.rules``.

Two layers:

1. **Fixture stories** (`add_story`): the rows behind `contract/fixtures/` are read from the
   fixture JSON files themselves (stored columns only), so the DB matches the contract exactly:
   JC-1301 for Fresh Juice Co. end to end, high-wastage JC-1240, the 5 at-risk clients and the
   locked Coastal Seafoods, the MSME bill due in 3 days, the PP Silver 200 mm shortage, the
   agent findings. Jobs that fixtures only reference (e.g. JC-1262 behind INV-2311) are
   generated with a full run -> QC -> dispatch chain. Every quantity is checked with
   ``core.rules`` (QC balance, dispatch <= approved, invoice maths) while generating.
2. **Background jobs** (`add_background`): ~60 closed/invoiced jobs with runs, QC, dispatch,
   invoices, receipts and collections, either on real job cards (real build) or on invented
   synthetic jobs (synthetic build). Their runs end before 1-Nov-2026 so the November ink pool
   and hour rates of the story stay exactly as in the fixtures.

Everything uses ``random.Random(seed)`` only, so a build is reproducible.
"""
from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.rules import money as M
from core.rules import production as P
from core.rules import quality as Q
from core.rules import store as S
from core.rules.errors import money
from core.rules.settings import DEFAULTS

TODAY = date(2026, 11, 20)
STOCK_FROM = date(2026, 10, 1)
FY_START = date(2026, 4, 1)
IST = timezone(timedelta(hours=5, minutes=30))
FIXTURES = Path(__file__).resolve().parents[4] / "contract" / "fixtures"
SEED = 1301

# hour rates of the fixture machines (machines.json); other machines use a default
FIXTURE_RATES = {"M-01": (120000, 56000, 800), "M-02": (110000, 70000, 900), "M-03": (90000, 40000, 650),
                 "M-04": (80000, 28000, 600), "M-05": (30000, 9000, 260), "M-06": (25000, 5000, 200)}
DEFAULT_RATE = (30000, 10000, 250)


# --------------------------------------------------------------------------- row container
class Rows:
    """Rows per table (dicts keyed by column name) plus an id allocator that never reuses an id."""

    def __init__(self) -> None:
        self.t: dict[str, list[dict]] = defaultdict(list)
        self.used: dict[str, set[str]] = defaultdict(set)
        self._next: dict[str, int] = {}
        from core.models import Base  # local import keeps this module importable early
        self._cols = {name: set(tbl.c.keys()) for name, tbl in Base.metadata.tables.items()}

    def add(self, table: str, row: dict, demo: bool | None = True) -> dict:
        cols = self._cols[table]
        unknown = set(row) - cols
        if unknown:
            raise KeyError(f"{table}: unknown columns {sorted(unknown)}")
        if "is_demo" in cols and "is_demo" not in row and demo is not None:
            row["is_demo"] = bool(demo)
        key = row.get("id") or (row.get("job_card") if table == "jobs" else None)
        if isinstance(key, str):
            prefix = key.rsplit("-", 1)[0]
            if key in self.used[prefix]:
                raise ValueError(f"duplicate id {key} in {table}")
            self.used[prefix].add(key)
        self.t[table].append(row)
        return row

    def new_id(self, prefix: str, width: int, start: int) -> str:
        n = max(self._next.get(prefix, start), start)
        while f"{prefix}-{n:0{width}d}" in self.used[prefix]:
            n += 1
        self._next[prefix] = n + 1
        return f"{prefix}-{n:0{width}d}"

    def find(self, table: str, **match: Any) -> list[dict]:
        return [r for r in self.t[table] if all(r.get(k) == v for k, v in match.items())]

    def one(self, table: str, **match: Any) -> dict:
        hits = self.find(table, **match)
        if len(hits) != 1:
            raise LookupError(f"{table} {match}: {len(hits)} rows")
        return hits[0]

    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in sorted(self.t.items())}


@dataclass
class Context:
    """What the generator needs to know about the masters already loaded."""

    real: bool = False
    machines: dict[str, dict] = field(default_factory=dict)          # id -> {type, max_speed_mpm, name}
    real_clients: list[str] = field(default_factory=list)            # CL ids of real clients
    real_jobs: list[dict] = field(default_factory=list)              # real job facts for background
    real_items: dict[str, dict] = field(default_factory=dict)        # IT id -> {width_mm, uom}


# --------------------------------------------------------------------------- helpers
def fx(name: str) -> Any:
    with open(FIXTURES / f"{name}.json", encoding="utf-8") as fh:
        return json.load(fh)


def d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def at(day: date, hh: int = 9, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=IST)


def pick(row: dict, *cols: str, **rename: str) -> dict:
    out = {c: row.get(c) for c in cols}
    out.update({new: row.get(old) for new, old in rename.items()})
    return out


def slug(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", str(text).upper()).strip("-") or "MISC"


def q3(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.001")))


# --------------------------------------------------------------------------- demo masters
CLIENT_COLS = ("id", "name", "gstin", "city", "state", "contact", "phone", "email", "credit_days", "credit_limit")
EXTRA_ITEMS = [  # jumbo and slit widths referenced by store_slitting.json
    {"id": "IT-0109", "name": "PP White 1020 mm jumbo", "head": "PP White", "width_mm": 1020, "rate": 38.0,
     "vendor_id": "VN-001"},
    {"id": "IT-0110", "name": "Chromo Paper 1020 mm jumbo", "head": "Chromo", "width_mm": 1020, "rate": 22.0,
     "vendor_id": "VN-001"},
    {"id": "IT-0111", "name": "PP Silver 1020 mm jumbo", "head": "PP Silver", "width_mm": 1020, "rate": 44.0,
     "vendor_id": "VN-002"},
    {"id": "IT-0112", "name": "PP Silver 240 mm", "head": "PP Silver", "width_mm": 240, "rate": 44.0,
     "vendor_id": "VN-002"},
]
SYNTH_CLIENTS = [  # invented names only
    ("Amrit Ayurveda Labs", "Haridwar", "Uttarakhand", 30), ("Blue Lagoon Beverages", "Goa", "Goa", 30),
    ("Crystal Clear Chemicals", "Ankleshwar", "Gujarat", 45), ("Deccan Pickles & Preserves", "Hyderabad",
                                                                "Telangana", 30),
    ("Everfresh Bakery Foods", "Nagpur", "Maharashtra", 30), ("Golden Harvest Oils", "Rajkot", "Gujarat", 45),
    ("Himalaya Herbal Teas", "Dehradun", "Uttarakhand", 30), ("Indus Agro Exports", "Ludhiana", "Punjab", 60),
    ("Jasmine Personal Care", "Chennai", "Tamil Nadu", 30), ("Konkan Cashew Co.", "Ratnagiri",
                                                             "Maharashtra", 30),
    ("Malabar Coffee Roasters", "Kozhikode", "Kerala", 45), ("Narmada Dairy Products", "Bharuch", "Gujarat", 30),
    ("Pearl Pharma Formulations", "Baddi", "Himachal Pradesh", 60),
]
SYNTH_VENDORS = [("VN-007", "Apex Adhesive Tapes", "Faridabad", False, 30, "Tapes, cores"),
                 ("VN-008", "Sunshine Packaging", "Pune", True, 30, "Boxes, cartons")]
PRODUCTS = [  # (product, label size, colours)
    ("Lemon squash 750 ml label", "80 x 100 mm", 5), ("Hair oil 200 ml bottle label", "60 x 90 mm", 4),
    ("Chyawanprash 500 g jar label", "90 x 70 mm", 5), ("Hand wash 250 ml label", "55 x 85 mm", 4),
    ("Mango pickle 400 g jar label", "80 x 60 mm", 4), ("Cold pressed oil 1 L label", "70 x 110 mm", 4),
    ("Green tea 100 g pouch label", "75 x 70 mm", 3), ("Basmati rice 5 kg bag label", "120 x 80 mm", 4),
    ("Face cream 50 g carton label", "45 x 60 mm", 5), ("Phenyl 1 L bottle label", "90 x 100 mm", 3),
    ("Cashew 250 g pouch label", "70 x 60 mm", 4), ("Filter coffee 200 g label", "65 x 85 mm", 4),
    ("Ghee 500 ml jar label", "85 x 65 mm", 5), ("Vitamin C tablets bottle label", "50 x 70 mm", 5),
]
COLOURS = ["Cyan", "Magenta", "Yellow", "Black", "Gloss varnish"]
OPERATORS = {"M-01": ["Suresh Patil", "Ajay Kamble"], "M-02": ["Imran Shaikh", "Nitin Gaikwad"],
             "M-03": ["Ramesh Yadav", "Santosh Pawar"], "M-04": ["Mahesh Shinde", "Deepak Jadhav"]}
STOPS = ["Make-ready", "Ink top-up", "Web break", "Colour matching", "Plate cleaning", "Splice"]
DEFECTS = ["Colour variation", "Die-cut miss", "Ink smudge", "Registration", "Web splice"]
TRANSPORTERS = [("Metro Freight Carriers", "MFC"), ("Southern Roadways", "SR")]


def add_demo_masters(R: Rows, ctx: Context) -> None:
    """Fixture clients, vendors, stock heads, items, dies (and machines in a synthetic build)."""
    for c in fx("clients"):
        R.add("clients", pick(c, *CLIENT_COLS) | {"active": True})
    for v in fx("vendors"):
        R.add("vendors", pick(v, "id", "name", "city", "msme", "credit_days", "supplies"))
    items = fx("items")
    heads: dict[str, dict] = {}
    for it in items:
        heads.setdefault(it["stock_head"], {"group": it["group"]})
    for x in EXTRA_ITEMS:
        heads.setdefault(x["head"], {"group": "Paper & Film"})
    for name, h in heads.items():
        R.add("stock_heads", {"id": slug(name), "name": name, "group": h["group"],
                              "ppic_paper": name if h["group"] == "Paper & Film" else None})
    for it in items:
        R.add("items", pick(it, "id", "name", "group", "width_mm", "uom", "rate", "rate_unit", "min_stock",
                            "vendor_id") | {"stock_head_id": slug(it["stock_head"])})
    for x in EXTRA_ITEMS:
        R.add("items", {"id": x["id"], "name": x["name"], "group": "Paper & Film", "stock_head_id": slug(x["head"]),
                        "width_mm": x["width_mm"], "uom": "m", "rate": x["rate"], "rate_unit": "per_sqm",
                        "min_stock": 0, "vendor_id": x["vendor_id"]})
    if not ctx.real:
        for m in fx("machines"):
            R.add("machines", pick(m, "id", "name", "type", "units", "max_speed_mpm", "web_width_mm"))
            ctx.machines[m["id"]] = {"type": m["type"], "max_speed_mpm": m["max_speed_mpm"], "name": m["name"]}
        for i, (name, city, state, cr) in enumerate(SYNTH_CLIENTS, start=12):
            R.add("clients", {"id": f"CL-{i:03d}", "name": name, "gstin": f"27AABC{i:03d}S1Z{i % 10}",
                              "city": city, "state": state, "contact": "Accounts desk",
                              "phone": f"+91 98000 2{i:04d}", "email": f"accounts{i}@client.example",
                              "credit_days": cr, "credit_limit": 600000.0, "active": True})
        for vid, name, city, msme, cr, sup in SYNTH_VENDORS:
            R.add("vendors", {"id": vid, "name": name, "city": city, "msme": msme, "credit_days": cr,
                              "supplies": sup})


# --------------------------------------------------------------------------- fixture story
JOB_COLS = ("job_card", "client_id", "po_no", "product", "label_size", "order_qty", "rate", "item_id",
            "machine_id", "ups_across", "ups_along", "repeat_mm", "units", "priority", "status",
            "enquiry_id", "quote_id")

# Jobs that fixtures reference (invoices, dies, laminate) but do not list in jobs.json.
# (job, client, created, product, size, qty, rate, item, machine, across, along, repeat, colours, die)
IMPLIED_JOBS = [
    ("JC-1205", "CL-011", "2026-07-28", "Frozen prawns 500 g pack label", "100 x 80 mm", 200000, 0.75, "IT-0107",
     "M-03", 2, 3, 254.0, ["Cyan", "Black", "White"], "D-088"),
    ("JC-1222", "CL-001", "2026-09-08", "Orange juice 200 ml bottle label", "60 x 80 mm", 48000, 0.60, "IT-0101",
     "M-01", 4, 3, 254.0, COLOURS, "D-114"),
    ("JC-1231", "CL-011", "2026-09-05", "Frozen squid rings 400 g label", "100 x 70 mm", 140000, 0.70, "IT-0107",
     "M-03", 2, 3, 254.0, ["Cyan", "Black", "White"], None),
    ("JC-1251", "CL-003", "2026-09-12", "Rose water 200 ml label", "60 x 90 mm", 60000, 0.85, "IT-0107", "M-03",
     3, 3, 279.4, ["Cyan", "Magenta", "Yellow", "Black", "Opaque white"], None),
    ("JC-1262", "CL-002", "2026-09-20", "Cough syrup 100 ml label (annual order)", "70 x 50 mm", 2658500, 0.50,
     "IT-0102", "M-02", 4, 4, 254.0, ["Blue", "Red", "Black"], None),
    ("JC-1265", "CL-006", "2026-09-22", "Turmeric powder 200 g pouch label", "75 x 70 mm", 1670000, 0.50,
     "IT-0106", "M-03", 4, 4, 304.8, ["Cyan", "Magenta", "Yellow", "Black"], None),
    ("JC-1270", "CL-004", "2026-09-24", "Toned milk 500 ml pouch label", "95 x 60 mm", 1650000, 0.38, "IT-0108",
     "M-02", 2, 5, 304.8, ["Blue", "Red", "Black"], None),
    ("JC-1272", "CL-005", "2026-09-26", "Packaged water 500 ml wrap-around", "200 x 50 mm", 1668750, 0.32,
     "IT-0108", "M-02", 2, 4, 254.0, ["Blue", "Cyan", "White"], None),
    ("JC-1276", "CL-008", "2026-09-30", "Toilet cleaner 500 ml label", "80 x 100 mm", 685000, 0.60, "IT-0102",
     "M-03", 3, 2, 254.0, ["Cyan", "Magenta", "Yellow", "Black"], None),
    ("JC-1279", "CL-004", "2026-10-20", "Buttermilk 200 ml cup sleeve", "95 x 60 mm", 125000, 0.38, "IT-0108",
     "M-02", 2, 5, 304.8, ["Blue", "Red", "Black"], None),
    ("JC-1283", "CL-007", "2026-10-22", "Groundnut oil 1 L label", "60 x 70 mm", 80000, 0.65, "IT-0104", "M-04",
     3, 4, 228.6, ["Green", "Gold", "Black"], "D-123"),
    ("JC-1290", "CL-002", "2026-10-24", "Antacid syrup 170 ml label", "70 x 50 mm", 240000, 0.40, "IT-0101",
     "M-01", 4, 3, 254.0, COLOURS, "D-121"),
    ("JC-1293", "CL-009", "2026-10-25", "Herbal shampoo 200 ml label", "50 x 75 mm", 55000, 0.80, "IT-0102",
     "M-01", 3, 4, 254.0, COLOURS, None),
    ("JC-1297", "CL-010", "2026-10-27", "Soan papdi 250 g box label", "90 x 60 mm", 30000, 1.20, "IT-0105",
     "M-04", 2, 3, 203.2, ["Magenta", "Yellow", "Black", "Gold foil"], "D-130"),
]

FINDING_KEYS = {
    "F-0231": "import_checker:date_day_first:ERP-2026-08-10", "F-0232": "store_watchdog:grn_rate:GRN-00436",
    "F-0233": "wastage_watchdog:RUN-05570", "F-0234": "planning:short:IT-0103",
    "F-0235": "collections:lock_risk:2026-11-20", "F-0236": "payables:msme_due:SB-0187",
    "F-0237": "month_end:2026-10", "F-0238": "owner_brief:2026-11-20",
    "F-0219": "import_checker:job_card_match:2026-11-18", "F-0224": "collections:promise_broken:COL-0141",
    "F-0227": "store_watchdog:grn_rate:GRN-00418",
}
OLD_RUNS = {"F-0219": ("AR-0398", "2026-11-18T06:30:00+05:30"),
            "F-0224": ("AR-0371", "2026-11-11T07:00:00+05:30"),
            "F-0227": ("AR-0360", "2026-11-07T07:00:00+05:30")}


def _job_row(j: dict) -> dict:
    row = pick(j, *JOB_COLS)
    row.update(created_on=d(j["created_on"]), po_date=d(j["po_date"]), due_date=d(j["due_date"]))
    return row


def add_story(R: Rows, ctx: Context, rng: random.Random) -> None:
    """All rows behind contract/fixtures (exact numbers) plus the jobs they imply."""
    # sales
    for e in fx("enquiries"):
        R.add("enquiries", pick(e, "id", "client_id", "product", "label_size", "material", "finish", "qty",
                                "colours", "source", "assigned_to", "status", "lost_reason")
              | {"date": d(e["date"]), "follow_up_on": d(e["follow_up_on"]),
                 "prospect_name": None if e["client_id"] else e["client_name"]})
    q45 = fx("job_360_JC-1301")["quote"]
    for e in fx("enquiries"):
        if not e["quote_id"]:
            continue
        if e["quote_id"] == "Q-0045":
            R.add("quotes", pick(q45, "id", "enquiry_id", "qty", "rate", "cost_estimate", "notes", "status")
                  | {"date": d(q45["date"]), "valid_until": d(q45["valid_until"])})
            continue
        qd = d(e["date"]) + timedelta(days=1)
        rate = float(money(Decimal(str(e["value"])) / e["qty"]))
        status = {"won": "accepted", "lost": "rejected", "quoted": "sent"}.get(e["status"], "sent")
        R.add("quotes", {"id": e["quote_id"], "enquiry_id": e["id"], "date": qd, "valid_until": qd + timedelta(15),
                         "qty": e["qty"], "rate": rate, "status": status,
                         "cost_estimate": float(money(e["value"] * rng.uniform(0.66, 0.74))),
                         "notes": "Ex-works; GST 18% extra; 30 days credit"})
    # jobs listed in fixtures
    listed = {j["job_card"]: j for j in fx("jobs")["items"]}
    for j in listed.values():
        R.add("jobs", _job_row(j))
    for (jc, cl, created, product, size, qty, rate, item, mach, ua, ul, rep, units, _die) in IMPLIED_JOBS:
        cd = d(created)
        R.add("jobs", {"job_card": jc, "client_id": cl, "created_on": cd, "po_no": f"PO/{jc[3:]}/26",
                       "po_date": cd - timedelta(days=1), "product": product, "label_size": size, "order_qty": qty,
                       "rate": rate, "item_id": item, "machine_id": mach, "ups_across": ua, "ups_along": ul,
                       "repeat_mm": rep, "units": units, "due_date": cd + timedelta(days=14),
                       "priority": "normal", "status": "invoiced"})
    for die in fx("dies"):
        R.add("dies", pick(die, "id", "type", "label_size", "ups_across", "ups_along", "repeat_mm", "vendor_id",
                           "cost", "last_job_card", "impressions", "status", "location") | {"made_on": d(die["made_on"])})
    # design, plates, press setup
    for ds in fx("design"):
        R.add("design", pick(ds, "job_card", "stage", "designer", "artwork_version", "approved_by", "die_id",
                             "units", "route", "notes")
              | {"proof_sent_on": d(ds["proof_sent_on"]), "approved_on": d(ds["approved_on"])})
    for pl in fx("plates"):
        R.add("plates", pick(pl, "id", "job_card", "unit", "colour", "vendor_id", "cost", "impressions", "status",
                             "rack") | {"made_on": d(pl["made_on"])})
    ps = fx("press_setup_JC-1301")
    R.add("press_setup", pick(ps, "job_card", "machine_id", "web_width_mm", "die_id", "units", "speed_target_mpm",
                              "est_ink_kg", "notes", "updated_by"))
    for row in fx("store_ink_allocation")["rows"]:
        if row["job_card"] != "JC-1301":
            _press_setup(R, R.one("jobs", job_card=row["job_card"]), est=row["est_ink_kg"])
    # store
    for g in fx("store_grns"):
        R.add("grns", pick(g, "id", "vendor_id", "bill_no", "item_id", "qty", "rate") | {"date": d(g["date"]),
                                                                                        "source": "app"})
    rolls = {r["id"]: r for r in fx("store_rolls")}
    for r in rolls.values():
        R.add("rolls", pick(r, "id", "item_id", "width_mm", "length_m", "source", "source_ref", "location")
              | {"received_on": d(r["received_on"])})
    for g in fx("store_grns"):  # rolls of a GRN that store_rolls.json does not list
        missing = [rid for rid in g["roll_ids"] if rid not in rolls]
        for rid in missing:
            item = R.one("items", id=g["item_id"])
            R.add("rolls", {"id": rid, "item_id": g["item_id"], "width_mm": item["width_mm"],
                            "length_m": g["qty"] / len(g["roll_ids"]), "source": "grn", "source_ref": g["id"],
                            "received_on": d(g["date"]), "location": "Bay 2 / Rack 7"})
    jumbo_items = {"PP White 1020 mm jumbo": "IT-0109", "Chromo 1020 mm jumbo": "IT-0110",
                   "PP Silver 1020 mm jumbo": "IT-0111"}
    slit_item = {250: "IT-0101", 330: "IT-0106", 240: "IT-0112"}
    for s in fx("store_slitting"):
        sd = d(s["date"])
        if not R.find("rolls", id=s["jumbo_roll_id"]):
            R.add("rolls", {"id": s["jumbo_roll_id"], "item_id": jumbo_items[s["item_name"]],
                            "width_mm": s["jumbo_width_mm"], "length_m": s["length_m"], "source": "opening",
                            "source_ref": "Opening 2026-10-01", "received_on": STOCK_FROM,
                            "location": "Jumbo bay"})
        S.slit_trim_pct(s["jumbo_width_mm"], [o["width_mm"] for o in s["outputs"] for _ in range(o["count"])])
        R.add("slitting", pick(s, "id", "jumbo_roll_id", "jumbo_width_mm", "length_m", "outputs", "operator")
              | {"date": sd})
        for o in s["outputs"]:
            for rid in o["roll_ids"]:
                if not R.find("rolls", id=rid):
                    R.add("rolls", {"id": rid, "item_id": slit_item[o["width_mm"]], "width_mm": o["width_mm"],
                                    "length_m": s["length_m"], "source": "slit", "source_ref": s["id"],
                                    "received_on": sd, "location": "Bay 2 / Rack 6"})
    for i in fx("store_issues"):
        R.add("issues", pick(i, "id", "job_card", "item_id", "qty", "roll_id", "issued_to", "source")
              | {"date": d(i["date"])})
    # November ink pool: fixture pool is Rs 18,240; the listed no-job-card lines make Rs 11,800
    for iid, day, item, qty in (("ISS-02209", "2026-11-07", "IT-0203", 2.0), ("ISS-02244", "2026-11-16",
                                                                               "IT-0204", 1.68)):
        R.add("issues", {"id": iid, "date": d(day), "job_card": None, "item_id": item, "qty": qty,
                         "issued_to": "Ink room", "source": "erp_import", "raw_date": d(day).strftime("%d-%m-%y")})
    for p in fx("store_party_laminate")["rows"]:
        R.add("party_laminate", pick(p, "id", "client_id", "movement", "laminate", "width_mm", "qty_m", "job_card")
              | {"date": d(p["date"])})
    # production, QC, dispatch, money
    for r in fx("production_runs"):
        R.add("runs", pick(r, "id", "job_card", "machine_id", "shift", "operator", "hours", "printed_qty",
                           "used_m", "stops") | {"start": ts(r["start"]), "end": ts(r["end"])})
    for qc in fx("qc"):
        printed = sum(x["printed_qty"] for x in R.find("runs", job_card=qc["job_card"])
                      if ctx.machines.get(x["machine_id"], {}).get("type") == "press")
        Q.qc_validate(printed, qc["checked"], qc["approved"], qc["rejected"])
        R.add("qc", pick(qc, "id", "job_card", "run_id", "checked", "approved", "rejected", "decision", "defects",
                         "inspector", "notes") | {"date": d(qc["date"])})
    _implied_production(R, ctx, rng)
    for dc in fx("dispatch"):
        _guard_dispatch(R, dc["job_card"], dc["qty"])
        R.add("dispatches", pick(dc, "id", "job_card", "qty", "boxes", "vehicle_no", "transporter", "lr_no",
                                 "freight") | {"date": d(dc["date"])})
    for inv in fx("invoices")["items"]:
        amounts = M.invoice_amounts(inv["qty"], inv["rate"], inv["gst_rate"])
        assert float(amounts.total) == inv["total"], inv["id"]
        R.add("invoices", pick(inv, "id", "client_id", "job_card", "dispatch_id", "qty", "rate", "gst_rate")
              | {"date": d(inv["date"]), "status": "open", "source": "app"})
    for rid, inv_id, day, amount, mode in (("RCP-0201", "INV-2201", "2026-09-30", 50000.0, "neft"),
                                           ("RCP-0214", "INV-2290", "2026-10-22", 33984.0, "neft"),
                                           ("RCP-0233", "INV-2302", "2026-11-14", 60180.0, "cheque")):
        inv = R.one("invoices", id=inv_id)
        R.add("receipts", {"id": rid, "date": d(day), "client_id": inv["client_id"], "invoice_id": inv_id,
                           "amount": amount, "mode": mode, "ref": f"UTR{rid[4:]}88"})
    for c in fx("collections"):
        R.add("collections", pick(c, "id", "client_id", "invoice_ids", "mode", "contact", "note", "promise_amount",
                                  "status", "by")
              | {"date": d(c["date"]), "promise_date": d(c["promise_date"]),
                 "next_follow_up": d(c["next_follow_up"])})
    _implied_dispatch(R, rng)
    _payables(R)
    _agents(R)


def _press_setup(R: Rows, job: dict, est: float, die_id: str | None = None) -> None:
    units = [{"unit": n, "colour": c, "anilox_lpi": 800 if n < 4 else 400, "anilox_bcm": 3.5 if n < 4 else 8.0,
              "plate_id": None, "ink_item_id": None} for n, c in enumerate(job["units"] or [], start=1)]
    item = R.find("items", id=job["item_id"])
    R.add("press_setup", {"job_card": job["job_card"], "machine_id": job["machine_id"],
                          "web_width_mm": item[0]["width_mm"] if item else None, "die_id": die_id, "units": units,
                          "speed_target_mpm": 60, "est_ink_kg": est, "notes": "", "updated_by": "Production"})


def _approved(R: Rows, job_card: str) -> int:
    rows = [{"approved_qty": q["approved"], "decision": q["decision"]} for q in R.find("qc", job_card=job_card)]
    return Q.approved_total(rows)


def _guard_dispatch(R: Rows, job_card: str, qty: int) -> None:
    before = sum(x["qty"] for x in R.find("dispatches", job_card=job_card))
    Q.check_dispatch(_approved(R, job_card), before, qty)


def produce(R: Rows, ctx: Context, rng: random.Random, job: dict, run_day: date, wastage: float, *,
            used_m: float | None = None, issue: bool = True, approved: int | None = None,
            overprod: bool = False, shift: str = "day") -> dict:
    """Press run (+ material issue, inspection run, QC) for a job, using the rules engine."""
    total_ups = P.ups(job["ups_across"], job["ups_along"])
    required = P.required_metres(job["order_qty"], total_ups, job["repeat_mm"])
    if used_m is None:
        used_m = round(required * (1 + wastage), 1)
    machine = ctx.machines[job["machine_id"]]
    item = R.find("items", id=job["item_id"])
    width = (item[0]["width_mm"] if item else None) or ctx.real_items.get(job["item_id"], {}).get("width_mm")
    if issue:
        qty_m = float(-(-Decimal(str(used_m)) // 5) * 5)  # round up to 5 m
        R.add("issues", {"id": R.new_id("ISS", 5, 2001), "date": run_day, "job_card": job["job_card"],
                         "item_id": job["item_id"], "qty": qty_m, "issued_to": machine["name"], "source": "app"})
    if approved is not None:
        printed = int(round(approved / (1 - rng.uniform(0.012, 0.028)), -2))
    else:
        printed = int(round(job["order_qty"] * (1 + (rng.uniform(0.11, 0.14) if overprod else rng.uniform(0.01, 0.05))),
                            -2))
    speed = (machine.get("max_speed_mpm") or 60) * rng.uniform(0.45, 0.6)
    hours = max(1.0, round(used_m / speed / 60 * 4) / 4)
    start = at(run_day, 21 if shift == "night" else 9)
    run_id = R.new_id("RUN", 5, 5001)
    n_stops = rng.randint(0, 2)
    R.add("runs", {"id": run_id, "job_card": job["job_card"], "machine_id": job["machine_id"], "shift": shift,
                   "operator": rng.choice(OPERATORS.get(job["machine_id"], ["Operator 1"])), "start": start,
                   "end": start + timedelta(hours=hours), "hours": hours, "printed_qty": printed,
                   "used_m": used_m,
                   "stops": [{"reason": rng.choice(STOPS), "minutes": rng.choice([10, 15, 20, 25])}
                             for _ in range(n_stops)]})
    insp = "M-06" if "M-06" in ctx.machines else None
    if insp:
        ih = max(1.0, round(printed / 40000 * 2) / 2)
        istart = at(run_day + timedelta(days=1), 9)
        R.add("runs", {"id": R.new_id("RUN", 5, 5001), "job_card": job["job_card"], "machine_id": insp,
                       "shift": "day", "operator": "Vikas More", "start": istart,
                       "end": istart + timedelta(hours=ih), "hours": ih, "printed_qty": printed, "used_m": None,
                       "stops": []})
    rejected = printed - approved if approved is not None else int(round(printed * rng.uniform(0.012, 0.03), -1))
    ok = printed - rejected
    Q.qc_validate(printed, printed, ok, rejected)
    split = rng.randint(1, rejected - 1) if rejected >= 2 else rejected
    R.add("qc", {"id": R.new_id("QC", 5, 3001), "date": run_day + timedelta(days=1), "job_card": job["job_card"],
                 "run_id": run_id, "checked": printed, "approved": ok, "rejected": rejected, "decision": "Approved",
                 "defects": [{"type": t, "qty": q} for t, q in zip(rng.sample(DEFECTS, 2),
                                                                     (split, rejected - split), strict=True) if q > 0],
                 "inspector": rng.choice(["QC Inspector A", "QC Inspector B"]), "notes": ""})
    return {"printed": printed, "approved": ok, "required": required, "used_m": used_m, "width": width,
            "hours": hours}


def dispatch(R: Rows, rng: random.Random, job: dict, day: date, qty: int) -> str:
    _guard_dispatch(R, job["job_card"], qty)
    name, code = rng.choice(TRANSPORTERS)
    dc = R.new_id("DC", 4, 1300)
    R.add("dispatches", {"id": dc, "date": day, "job_card": job["job_card"], "qty": qty,
                         "boxes": max(1, qty // 5000), "vehicle_no": f"MH12 {rng.choice('ABCDKLPQ')}"
                         f"{rng.choice('ABDGJKMQ')} {rng.randint(1000, 9999)}", "transporter": name,
                         "lr_no": f"{code}/{rng.randint(50000, 59999)}",
                         "freight": float(rng.choice([600, 800, 900, 1100, 1200, 1500]))})
    return dc


def _implied_production(R: Rows, ctx: Context, rng: random.Random) -> None:
    """Run -> QC (+ issue, press setup, design) for jobs that fixtures only reference."""
    fixture_dc = {dc["job_card"]: dc for dc in fx("dispatch")}
    inv_by_job: dict[str, list[dict]] = defaultdict(list)
    for inv in fx("invoices")["items"]:
        inv_by_job[inv["job_card"]].append(inv)
    for (jc, *_rest) in IMPLIED_JOBS:
        job = R.one("jobs", job_card=jc)
        die = _rest[-1]
        invs = sorted(inv_by_job.get(jc, []), key=lambda r: r["date"])
        first = d(invs[0]["date"]) if invs else d(fixture_dc[jc]["date"])
        run_day = min(job["created_on"] + timedelta(days=4), first - timedelta(days=3), date(2026, 10, 30))
        if jc in fixture_dc:
            need = fixture_dc[jc]["qc_approved"]
        else:  # approve a little more than was invoiced so every challan passes the guard
            need = int(-(-sum(i["qty"] for i in invs) * 1.004 // 100) * 100)
        produce(R, ctx, rng, job, run_day, rng.uniform(0.06, 0.11), approved=need)
        _press_setup(R, job, est=round(len(job["units"]) * 0.3, 1), die_id=die)
        R.add("design", _design_done(ctx, job, die, "Kavya Nair"))
    story = {j["job_card"] for j in fx("jobs")["items"]}
    for job in R.t["jobs"]:
        if job["job_card"] in story and not R.find("design", job_card=job["job_card"]):
            row = _design_done(ctx, job, None, "Arjun Desai")
            if job["status"] == "hold":
                row["stage"] = "approved"
            R.add("design", row)


def _design_done(ctx: Context, job: dict, die: str | None, designer: str) -> dict:
    return {"job_card": job["job_card"], "stage": "done", "designer": designer, "artwork_version": 1,
            "proof_sent_on": job["created_on"] + timedelta(days=1),
            "approved_on": job["created_on"] + timedelta(days=2), "approved_by": "Client", "die_id": die,
            "units": [{"unit": n, "colour": c, "anilox_lpi": 800, "plate_id": None}
                      for n, c in enumerate(job["units"] or [], 1)],
            "route": [f"Print {ctx.machines[job['machine_id']]['name']}", "Inspection RW-1", "Pack"], "notes": ""}


def _implied_dispatch(R: Rows, rng: random.Random) -> None:
    """Challans for the older fixture invoices (their fixture dispatch_id is null); link them."""
    fixture_dc = {dc["job_card"] for dc in fx("dispatch")}
    for (jc, *_rest) in IMPLIED_JOBS:
        if jc in fixture_dc:
            continue
        job = R.one("jobs", job_card=jc)
        for inv in sorted(R.find("invoices", job_card=jc), key=lambda r: r["date"]):
            inv["dispatch_id"] = dispatch(R, rng, job, inv["date"], inv["qty"])


def _payables(R: Rows) -> None:
    """Open bills from creditors.json plus older bills cleared by FIFO payments."""
    open_bills = []
    for v in fx("creditors")["vendors"]:
        for b in v["bills"]:
            open_bills.append(b["id"])
            R.add("supplier_bills", {"id": b["id"], "vendor_id": v["vendor_id"], "bill_no": b["bill_no"],
                                     "date": d(b["date"]), "amount": b["amount"], "grn_ids": b["grn_ids"]})
    history = {  # vendor -> [(bill date, amount incl. GST)], all paid before the open bills
        "VN-001": [("2026-07-18", 154200.0), ("2026-08-12", 98300.0), ("2026-09-03", 176500.0)],
        "VN-002": [("2026-07-25", 212400.0), ("2026-08-21", 188800.0)],
        "VN-003": [("2026-08-05", 59000.0), ("2026-09-08", 70800.0)],
        "VN-004": [("2026-08-14", 23600.0), ("2026-09-19", 35400.0)],
        "VN-005": [("2026-09-11", 7600.0), ("2026-10-09", 9100.0)],
        "VN-006": [("2026-08-02", 96000.0)],
    }
    n_bill, n_pay = 101, 1
    for vid, bills in history.items():
        vendor = R.one("vendors", id=vid)
        objs = []
        for bd, amt in bills:
            sb = f"SB-{n_bill:04d}"
            n_bill += 1
            R.add("supplier_bills", {"id": sb, "vendor_id": vid, "bill_no": f"{slug(vendor['name'])[:3]}/{n_bill}",
                                     "date": d(bd), "amount": amt, "grn_ids": []})
            objs.append(M.Bill(sb, d(bd), Decimal(str(amt))))
        # two payments per vendor: first covers ~60% of the history, second the rest (FIFO allocation)
        total = sum(b.amount for b in objs)
        first = money(total * Decimal("0.6"))
        remaining = {b.id: b.amount for b in objs}
        last_due = max(M.supplier_due_date(b.bill_date, vendor["credit_days"], vendor["msme"]) for b in objs)
        for k, amount in enumerate((first, total - first)):
            pid = f"PAY-{n_pay:04d}"
            n_pay += 1
            pay_day = min(last_due - timedelta(days=5 * (1 - k)), TODAY - timedelta(days=3))
            R.add("payments", {"id": pid, "vendor_id": vid, "date": pay_day, "amount": float(amount), "mode": "neft",
                               "ref": f"NEFT{pid[4:]}26"})
            open_objs = [M.Bill(b.id, b.bill_date, remaining[b.id]) for b in objs if remaining[b.id] > 0]
            for bid, applied in M.fifo_allocate(amount, open_objs).items():
                if applied > 0:
                    remaining[bid] -= applied
                    R.add("payment_allocations", {"payment_id": pid, "bill_id": bid, "applied": float(applied)})


def _agents(R: Rows) -> None:
    runs = fx("agents")["recent_runs"]
    for r in runs:
        R.add("agent_runs", pick(r, "id", "agent", "status", "findings_created", "model", "note")
              | {"started_at": ts(r["started_at"]), "finished_at": ts(r["finished_at"])})
    run_of = {fid: r["id"] for r in runs for fid in r["finding_ids"]}
    findings = []
    for name in ("agents_findings_open", "agents_findings_done", "agents_findings_rejected"):
        findings += fx(name)["items"]
    for f in findings:
        if f["id"] not in run_of:
            rid, started = OLD_RUNS[f["id"]]
            R.add("agent_runs", {"id": rid, "agent": f["agent"], "started_at": ts(started),
                                 "finished_at": ts(started) + timedelta(seconds=9), "status": "ok",
                                 "findings_created": 1, "model": "rules", "note": ""})
            run_of[f["id"]] = rid
        R.add("agent_findings", pick(f, "id", "agent", "severity", "title", "detail", "evidence",
                                     "suggested_action", "status", "decided_by", "reason")
              | {"run_id": run_of[f["id"]], "decided_at": ts(f["decided_at"]), "dedupe_key": FINDING_KEYS[f["id"]],
                 "created_at": ts(f["created_at"]), "updated_at": ts(f["decided_at"] or f["created_at"])})
        if f["decided_at"]:
            action = "finding_reject" if f["status"] == "rejected" else "finding_approve"
            R.add("audit_log", {"id": R.new_id("AUD", 5, 1), "at": ts(f["decided_at"]), "role": f["decided_by"],
                                "action": action, "entity": "finding", "entity_id": f["id"],
                                "before": {"status": "open"}, "after": {"status": f["status"]},
                                "reason": f["reason"]})


# --------------------------------------------------------------------------- background jobs
def add_background(R: Rows, ctx: Context, rng: random.Random, n: int = 60) -> None:
    """~60 closed/invoiced jobs with runs, QC, dispatch, invoices, receipts (all before 1-Nov runs)."""
    presses = [m for m, v in ctx.machines.items() if v["type"] == "press"][:4]
    specs: list[dict] = []
    if ctx.real:
        for rj in ctx.real_jobs[:n]:
            specs.append(rj)
    else:
        clients = [c["id"] for c in R.t["clients"] if int(c["id"][3:]) >= 12]
        papers = ["IT-0101", "IT-0102", "IT-0104", "IT-0105", "IT-0106", "IT-0107", "IT-0108"]
        free = [k for k in range(1150, 1300) if f"JC-{k}" not in R.used["JC"]]
        step = len(free) / n
        numbers = [free[int(i * step)] for i in range(n)]
        span = (date(2026, 10, 22) - date(2026, 7, 20)).days
        for i, num in enumerate(numbers):
            created = date(2026, 7, 20) + timedelta(days=int(i * span / n))
            product, size, ncol = PRODUCTS[i % len(PRODUCTS)]
            item = papers[i % len(papers)]
            specs.append({"job_card": f"JC-{num}", "created_on": created, "client_id": clients[i % len(clients)],
                          "product": product, "label_size": size, "item_id": item, "colours": ncol,
                          "machine_id": presses[i % len(presses)], "run_day": created + timedelta(days=5)})
    high = set(rng.sample(range(len(specs)), 4))           # a few jobs above the 15% wastage tolerance
    over = set(rng.sample(sorted(set(range(len(specs))) - high), 2))   # and two over-produced jobs
    enq_no = 1
    for i, sp in enumerate(specs):
        w = rng.uniform(0.155, 0.2) if i in high else rng.uniform(0.05, 0.12)
        ua, ul = rng.choice([(2, 3), (3, 3), (3, 4), (4, 3), (2, 5)])
        rep = rng.choice([203.2, 228.6, 254.0, 279.4, 304.8])
        total_ups = P.ups(ua, ul)
        if sp.get("used_m"):           # real job: derive the order from the metres actually issued
            req_guess = sp["used_m"] / (1 + w)
            qty = max(1000, int(round(req_guess * total_ups * 1000 / rep, -2)))
        else:
            qty = rng.choice([20000, 30000, 40000, 50000, 60000, 75000, 100000, 120000, 150000, 200000])
        rate = round(rng.uniform(0.32, 1.1), 2)
        units = COLOURS[: sp.get("colours", 4)] if sp.get("colours", 4) <= 5 else COLOURS
        job = {"job_card": sp["job_card"], "created_on": sp["created_on"], "client_id": sp["client_id"],
               "po_no": f"PO/{sp['job_card'][3:]}", "po_date": sp["created_on"] - timedelta(days=1),
               "product": sp["product"], "label_size": sp.get("label_size"), "order_qty": qty, "rate": rate,
               "item_id": sp["item_id"], "machine_id": sp.get("machine_id") or presses[i % len(presses)],
               "ups_across": ua, "ups_along": ul, "repeat_mm": rep, "units": units,
               "due_date": sp["created_on"] + timedelta(days=14), "priority": "normal", "status": "closed"}
        if sp.get("existing"):
            sp["existing"].update({k: v for k, v in job.items() if k not in ("job_card", "created_on", "product")})
            job = sp["existing"]
        else:
            R.add("jobs", job)
        if enq_no <= 24 and i % 2 == 0:
            _won_enquiry(R, rng, job, enq_no)
            enq_no += 1
        run_day = min(sp["run_day"], date(2026, 10, 30))
        res = produce(R, ctx, rng, job, run_day, w, used_m=sp.get("used_m"), issue=not sp.get("used_m"),
                      overprod=i in over, shift="night" if i in high else "day")
        _press_setup(R, job, est=round(len(units) * rng.uniform(0.2, 0.35), 2))
        R.add("design", _design_done(ctx, job, None, rng.choice(["Kavya Nair", "Arjun Desai"])))
        ship = min(qty, res["approved"])
        dday = run_day + timedelta(days=rng.randint(2, 4))
        dc = dispatch(R, rng, job, dday, ship)
        _invoice_and_receipt(R, rng, job, dc, dday, ship)
    for _ in range(enq_no, 39):        # older enquiries that did not convert
        _lost_enquiry(R, rng, enq_no)
        enq_no += 1


def _won_enquiry(R: Rows, rng: random.Random, job: dict, n: int) -> None:
    eid, qid = f"ENQ-{n:04d}", f"Q-{n:04d}"
    ed = job["created_on"] - timedelta(days=rng.randint(5, 9))
    R.add("enquiries", {"id": eid, "date": ed, "client_id": job["client_id"], "product": job["product"],
                        "label_size": job["label_size"], "material": "Label stock", "finish": "None",
                        "qty": job["order_qty"], "colours": len(job["units"]), "source": rng.choice(
                            ["phone", "email", "whatsapp", "repeat"]), "assigned_to": rng.choice(
                            ["Rohit Mehra", "Pooja Iyer"]), "status": "won"})
    value = M.po_value(job["order_qty"], job["rate"])
    R.add("quotes", {"id": qid, "enquiry_id": eid, "date": ed + timedelta(days=1), "valid_until": ed + timedelta(16),
                     "qty": job["order_qty"], "rate": job["rate"],
                     "cost_estimate": float(money(value * Decimal(str(round(rng.uniform(0.66, 0.76), 2))))),
                     "notes": "Ex-works; GST 18% extra", "status": "accepted"})
    job["enquiry_id"], job["quote_id"] = eid, qid


def _lost_enquiry(R: Rows, rng: random.Random, n: int) -> None:
    clients = [c["id"] for c in R.t["clients"]]
    product, size, ncol = PRODUCTS[n % len(PRODUCTS)]
    ed = date(2026, 7, 15) + timedelta(days=n * 2)
    qty = rng.choice([25000, 50000, 80000, 100000])
    R.add("enquiries", {"id": f"ENQ-{n:04d}", "date": ed, "client_id": rng.choice(clients), "product": product,
                        "label_size": size, "material": "PP White", "finish": "None", "qty": qty, "colours": ncol,
                        "source": rng.choice(["phone", "email", "website"]), "assigned_to": "Pooja Iyer",
                        "status": "lost", "lost_reason": rng.choice(["Price", "Lead time", "No reply"])})
    R.add("quotes", {"id": f"Q-{n:04d}", "enquiry_id": f"ENQ-{n:04d}", "date": ed + timedelta(days=1),
                     "valid_until": ed + timedelta(days=16), "qty": qty, "rate": 0.55,
                     "cost_estimate": float(money(qty * 0.55 * 0.72)), "notes": "", "status": "expired"})


def _invoice_and_receipt(R: Rows, rng: random.Random, job: dict, dc: str, day: date, qty: int) -> None:
    """Invoice the challan. Paid unless the due date is within the last 4 days or still ahead.

    Unpaid overdue invoices are therefore 1-4 days past due: overdue, but they never lock a client
    and stay outside the 10-day lock-risk window of the fixture story.
    """
    client = R.one("clients", id=job["client_id"])
    inv_id = R.new_id("INV", 4, 2101)
    R.add("invoices", {"id": inv_id, "date": day, "client_id": client["id"], "job_card": job["job_card"],
                       "dispatch_id": dc, "qty": qty, "rate": job["rate"], "gst_rate": DEFAULTS.gst_rate,
                       "status": "open", "source": "app"})
    total = M.invoice_amounts(qty, job["rate"], DEFAULTS.gst_rate).total
    due = M.due_date(day, client["credit_days"])
    if due >= TODAY - timedelta(days=4):
        job["status"] = "invoiced"
        return
    pay_day = min(max(day + timedelta(days=7), due + timedelta(days=rng.randint(-10, 12))), TODAY - timedelta(1))
    rid = R.new_id("RCP", 4, 1)
    R.add("receipts", {"id": rid, "date": pay_day, "client_id": client["id"], "invoice_id": inv_id,
                       "amount": float(total), "mode": rng.choice(["neft", "rtgs", "cheque"]),
                       "ref": f"UTR{rid[4:]}{rng.randint(100, 999)}"})
    if pay_day > due:
        R.add("collections", {"id": R.new_id("COL", 4, 101), "date": due + timedelta(days=1),
                              "client_id": client["id"], "invoice_ids": [inv_id], "mode": "call",
                              "contact": client.get("contact"), "note": "Reminder after due date",
                              "promise_date": pay_day, "promise_amount": float(total), "status": "kept",
                              "next_follow_up": None, "by": "Accounts"})


# --------------------------------------------------------------------------- finishing rows
def add_machine_costs(R: Rows, ctx: Context) -> None:
    """Monthly crew + other cost per machine so that hour rate = cost / hours run is the fixture rate.

    Costs are the fixture's monthly figures scaled to the hours actually run in the demo data
    (``machine_hour_rate`` then returns exactly 800, 900, ...). Months without a run keep the
    fixture figures. Covers Jul-Nov 2026.
    """
    hours: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for r in R.t["runs"]:
        if r["hours"] is not None and r["end"] is not None:
            hours[(r["machine_id"], r["start"].strftime("%Y-%m"))] += Decimal(str(r["hours"]))
    for mid in ctx.machines:
        crew0, other0, rate = FIXTURE_RATES.get(mid, DEFAULT_RATE)
        for month in ("2026-07", "2026-08", "2026-09", "2026-10", "2026-11"):
            h = hours.get((mid, month))
            if not h:
                if mid not in FIXTURE_RATES:
                    continue
                crew, other = Decimal(crew0), Decimal(other0)
            else:
                total = money(Decimal(rate) * h)
                crew = money(total * Decimal(crew0) / Decimal(crew0 + other0))
                other = total - crew
                assert P.machine_hour_rate(crew, other, h) == Decimal(rate)
            R.add("machine_costs", {"machine_id": mid, "month": month, "crew_salary": float(crew),
                                    "other_cost": float(other)})


def add_opening_stock(R: Rows) -> None:
    """Opening stock (1-Oct-2026) of demo items, solved so stock = opening + received - issued
    equals ``store_stock.json`` (e.g. PP Silver 200 mm = 1,884.45 m, the planning shortage)."""
    target = {r["item_id"]: r["stock"] for r in fx("store_stock")["items"]}
    demo_items = [it for it in R.t["items"] if it.get("is_demo")]
    received: dict[str, Decimal] = defaultdict(Decimal)
    issued: dict[str, list] = defaultdict(list)
    for g in R.t["grns"]:
        if g["date"] >= STOCK_FROM:
            received[g["item_id"]] += Decimal(str(g["qty"]))
    for i in R.t["issues"]:
        if i["date"] >= STOCK_FROM:
            issued[i["item_id"]].append(i["qty"])
    for it in demo_items:
        iid = it["id"]
        base = Decimal(str(target.get(iid, 1500)))
        opening = base - received[iid] + sum((Decimal(str(q)) for q in issued[iid]), Decimal(0))
        assert S.stock_balance(opening, received[iid], issued[iid]) == base
        R.add("opening_stock", {"item_id": iid, "stock_head_id": it["stock_head_id"], "as_of": STOCK_FROM,
                                "qty": float(opening), "rate": it["rate"], "uom": it["uom"],
                                "physical_count": None})


def add_settings(R: Rows, extra: dict | None = None, overrides: dict | None = None) -> None:
    s = fx("settings")
    row = pick(s, "wastage_tol", "overprod_tol", "material_tol", "ink_tol", "slit_tol", "grn_rate_tol",
               "grace_days", "msme_days", "gst_rate", "planning_extra", "admin_pct", "ai_mode", "company_name",
               "updated_by") | {"id": 1, "stock_from": d(s["stock_from"]), "fy_start": d(s["fy_start"]),
                                "extra": extra or {}}
    row.update(overrides or {})
    R.add("settings", row)
    R.add("audit_log", {"id": R.new_id("AUD", 5, 1), "at": ts(s["updated_at"]), "role": "owner",
                        "action": "settings_update", "entity": "settings", "entity_id": "1", "before": None,
                        "after": {"ai_mode": s["ai_mode"]}, "reason": None})


def add_demo_tally(R: Rows) -> None:
    """Tally P&L for Oct-2026 (demo; month_end compares it with the system P&L)."""
    pnl = fx("pnl_2026-10")
    for line in pnl["lines"]:
        if line["key"] == "profit":
            continue
        R.add("tally_pnl", {"month": pnl["month"], "key": line["key"], "amount": line["tally"],
                            "imported_at": ts(pnl["tally_imported_at"]), "note": line["note"] or None})


DEMO_LISTS = {"shift": ["day", "night"], "qc_decision": ["Approved", "Approved with Deviation", "Hold", "Rework",
                                                         "Rejected"],
              "defect_type": DEFECTS + ["Plate damage marks"], "transporter": [t for t, _ in TRANSPORTERS],
              "designer": ["Kavya Nair", "Arjun Desai"], "downtime_reason": STOPS + ["Plate damage"]}


def add_demo_lists(R: Rows) -> None:
    for name, values in DEMO_LISTS.items():
        for k, v in enumerate(values, 1):
            R.add("lists", {"list_name": name, "value": v, "sort_order": k})


def generate_demo(R: Rows, ctx: Context, seed: int = SEED, settings_extra: dict | None = None,
                  settings_overrides: dict | None = None) -> Rows:
    """Add every demo row to ``R`` (masters must already contain real machines in a real build)."""
    rng = random.Random(seed)
    add_demo_masters(R, ctx)
    add_story(R, ctx, rng)
    add_background(R, ctx, rng)
    add_machine_costs(R, ctx)
    add_opening_stock(R)
    add_settings(R, settings_extra, settings_overrides)
    add_demo_tally(R)
    if not ctx.real:
        add_demo_lists(R)
    return R


def iter_rows(R: Rows) -> Iterable[tuple[str, list[dict]]]:
    return R.t.items()
