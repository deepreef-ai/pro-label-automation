"""LOAD step: map the real extract frames (``core.etl.extract``) into the DB tables.

Rows taken from the client's files get ``is_demo = false``. Where the files lack a value the
schema needs, a generated value is filled in and the row is marked ``is_demo = true``:

* **jobs**: the PPIC register holds only job card, name and status, so client, order qty, rate,
  ups, repeat, machine and due date are generated (deterministic) -> every job row is demo.
  The paper item comes from the job's real issues, and for the ~60 jobs that get demo runs the
  order qty is derived from the metres really issued, so wastage stays realistic.
* **vendors**: MSME flag and credit days are blank in the register. Three vendors are marked
  MSME with 30-60 credit days (demo rows); the others get msme = false and the default 30 days.
* **machines**: the four presses get units / web width from the fixtures (demo rows).
* **opening debtors** become invoices (``source = 'opening'``, qty 1, rate = amount due incl. GST,
  gst_rate 0, ``ref`` = original invoice number). Real receipts are kept; the balance of every
  invoice whose due date is more than 4 days back is cleared with a DEMO receipt so that real
  clients are not all LOCKED on the demo date (2026-11-20).

IDs never clash with the fixture stories: clients CL-101+, vendors VN-101+, items IT-1001+,
GRNs GRN-10001+, issues ISS-10001+, invoices INV-1001+, receipts RCP-5001+; real job cards keep
their ERP number as ``JC-<number>``.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from core.etl.extract import _key
from core.etl.generate import COLOURS, FIXTURE_RATES, IST, TODAY, Context, Rows, fx, slug
from core.rules import money as M
from core.rules.dates import parse_erp_date
from core.rules.errors import RuleError, money

SEED = 2026
FRAMES = ["clients", "vendors", "items", "opening_stock", "opening_debtors", "fixed_assets", "tally_pnl",
          "machines", "jobs", "grns", "issues", "lists", "settings"]
UOM = {"sq.mtrs": ("sqm", "per_sqm"), "kg": ("kg", "per_kg"), "meter": ("m", "per_m"), "can": ("nos", "per_nos"),
       "no.": ("nos", "per_nos"), "nos": ("nos", "per_nos")}


# --------------------------------------------------------------------------- value helpers
def _nil(v: Any) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip()) \
        or v is pd.NaT


def s_(v: Any) -> str | None:
    if _nil(v):
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def f_(v: Any) -> float | None:
    if _nil(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def i_(v: Any) -> int | None:
    x = f_(v)
    return None if x is None else int(round(x))


def d_(v: Any) -> date | None:
    if _nil(v):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, pd.Timestamp):
        return v.date()
    try:
        return parse_erp_date(str(v).strip())
    except RuleError:
        return None


def b_(v: Any) -> bool | None:
    if _nil(v):
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


def read_frames(raw_dir: str) -> dict[str, pd.DataFrame]:
    """Extract CSVs if ``raw_dir`` holds them, else run the extract on the workbooks."""
    p = Path(raw_dir)
    if (p / "clients.csv").is_file():
        return {n: pd.read_csv(p / f"{n}.csv", dtype=str, keep_default_na=True) for n in FRAMES
                if (p / f"{n}.csv").is_file()}
    from core.etl.extract import extract_all

    return extract_all(p)


def recs(df: pd.DataFrame | None) -> list[dict]:
    if df is None or not len(df):
        return []
    return df.to_dict("records")


# --------------------------------------------------------------------------- loader
def load_real(R: Rows, ctx: Context, raw_dir: str) -> tuple[dict, dict]:
    """Add every real row to ``R``; fill ``ctx``. Returns (settings extra, settings overrides)."""
    rng = random.Random(SEED)
    fr = read_frames(raw_dir)
    ctx.real = True

    # clients
    client_by_name: dict[str, str] = {}
    for n, c in enumerate(recs(fr.get("clients")), start=101):
        cid = f"CL-{n:03d}"
        R.add("clients", {"id": cid, "name": s_(c["name"]), "gstin": s_(c.get("gstin")), "city": s_(c.get("city")),
                          "state": s_(c.get("state")), "contact": s_(c.get("contact_person")),
                          "phone": s_(c.get("phone")), "email": s_(c.get("email")),
                          "credit_days": i_(c.get("credit_days")) or 30, "credit_limit": f_(c.get("credit_limit")),
                          "active": True, "lock_override_until": d_(c.get("release_lock_until"))}, demo=False)
        client_by_name[_key(c["name"])] = cid
        if s_(c.get("tally_name")):
            client_by_name.setdefault(_key(c["tally_name"]), cid)
        ctx.real_clients.append(cid)

    # vendors (3 demo MSME vendors)
    vendors = recs(fr.get("vendors"))
    msme_idx = dict(zip(sorted(rng.sample(range(len(vendors)), min(3, len(vendors)))), (30, 45, 60), strict=False))
    vendor_by_key: dict[str, str] = {}
    for n, v in enumerate(vendors):
        vid = f"VN-{101 + n:03d}"
        real_msme = b_(v.get("is_msme"))
        credit = i_(v.get("credit_days"))
        demo = n in msme_idx and real_msme is None
        R.add("vendors", {"id": vid, "name": s_(v["name"]), "city": s_(v.get("state")), "gstin": s_(v.get("gstin")),
                          "msme": True if demo else bool(real_msme),
                          "credit_days": msme_idx[n] if demo else (credit or 30), "supplies": s_(v.get("remarks"))},
              demo=demo)
        vendor_by_key[_key(v["name"])] = vid

    # stock heads (ids must not clash with the demo heads added later)
    reserved = {slug(i["stock_head"]) for i in fx("items")} | {"PP-WHITE", "PP-SILVER", "CHROMO"}
    head_id: dict[str, str] = {}

    def head(name: str | None, group: str | None, ppic: str | None = None) -> str | None:
        if not name:
            return None
        k = _key(name)
        if k not in head_id:
            hid = slug(name)
            while hid in reserved or hid in head_id.values():
                hid += "-ERP"
            head_id[k] = hid
            R.add("stock_heads", {"id": hid, "name": name, "group": group, "ppic_paper": ppic}, demo=False)
        return head_id[k]

    # items
    item_by_key: dict[str, str] = {}
    first_item_of_head: dict[str, str] = {}
    for n, it in enumerate(recs(fr.get("items")), start=1001):
        iid = f"IT-{n:04d}"
        uom, unit = UOM.get((s_(it.get("uom")) or "").lower(), ("nos", "per_nos"))
        hid = head(s_(it.get("stock_head")), s_(it.get("item_group")), s_(it.get("ppic_paper")))
        width = i_(it.get("width_mm"))
        R.add("items", {"id": iid, "name": s_(it["item_name"]), "group": s_(it.get("item_group")),
                        "stock_head_id": hid, "width_mm": width, "uom": uom, "rate": f_(it.get("rate")),
                        "rate_unit": unit, "min_stock": f_(it.get("min_stock")), "vendor_id": None,
                        "code": s_(it.get("item_code"))}, demo=False)
        item_by_key[s_(it.get("item_key")) or _key(it["item_name"])] = iid
        ctx.real_items[iid] = {"width_mm": width, "uom": uom, "group": s_(it.get("item_group"))}
        if hid:
            first_item_of_head.setdefault(hid, iid)

    # opening stock (per stock head; item = first item of that head when there is one)
    for o in recs(fr.get("opening_stock")):
        hid = head(s_(o.get("stock_head")), s_(o.get("item_group")))
        R.add("opening_stock", {"item_id": first_item_of_head.get(hid), "stock_head_id": hid,
                                "as_of": d_(o.get("as_of")), "qty": f_(o.get("opening_qty")) or 0.0,
                                "rate": f_(o.get("opening_rate")), "uom": s_(o.get("uom")),
                                "value": f_(o.get("opening_value")), "physical_count": None}, demo=False)

    # machines: presses M-01..M-04 (as in the fixtures), Slitter SL-1 M-05, inspection M-06, rest M-07+
    fixture_m = {m["name"]: m for m in fx("machines")}
    ms = sorted(recs(fr.get("machines")), key=lambda m: i_(m.get("sort_order")) or 0)
    presses = [m for m in ms if s_(m.get("machine_type")) == "press"]
    slitter = [m for m in ms if "slitter" in (s_(m["name"]) or "").lower()][:1]
    insp = [m for m in ms if "inspection" in (s_(m["name"]) or "").lower()][:1]
    ordered = presses[:4] + slitter + insp
    ordered += [m for m in ms if m not in ordered]
    for n, m in enumerate(ordered, start=1):
        mid = f"M-{n:02d}"
        name = s_(m["name"])
        fm = fixture_m.get(name)
        mtype = s_(m.get("machine_type")) or "offline"
        R.add("machines", {"id": mid, "name": name, "type": mtype, "units": fm["units"] if fm else None,
                           "max_speed_mpm": i_(m.get("rated_speed_m_min")) or (fm or {}).get("max_speed_mpm"),
                           "web_width_mm": fm["web_width_mm"] if fm else None}, demo=bool(fm))
        ctx.machines[mid] = {"type": mtype, "name": name,
                             "max_speed_mpm": i_(m.get("rated_speed_m_min")) or 60}
    assert all(k in ctx.machines for k in FIXTURE_RATES), "real machine list lacks the six fixture machines"

    # issues -> metres per job / main paper item
    issues = recs(fr.get("issues"))
    metres: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    value: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for i in issues:
        jc = s_(i.get("job_card"))
        iid = item_by_key.get(_key(i.get("item_description")) or "")
        if not jc or not iid:
            continue
        info = ctx.real_items[iid]
        value[jc][iid] += f_(i.get("value_rs")) or 0.0
        if info["group"] != "Paper & Film":
            continue
        q = f_(i.get("net_qty")) or 0.0
        u = (s_(i.get("uom")) or "").lower()
        if u == "meter":
            metres[jc][iid] += q
        elif u == "sq.mtrs" and info["width_mm"]:
            metres[jc][iid] += q * 1000 / info["width_mm"]

    # jobs (generated fields -> demo rows)
    jobs = recs(fr.get("jobs"))
    press_ids = [k for k, v in ctx.machines.items() if v["type"] == "press"][:4]
    candidates = sorted(s_(j["job_card"]) for j in jobs
                        if sum(metres[s_(j["job_card"])].values()) >= 300 and d_(j.get("last_issue_date")))
    chosen = set(rng.sample(candidates, min(60, len(candidates))))
    for j in jobs:
        num = s_(j["job_card"])
        jc = f"JC-{num}"
        first = d_(j.get("first_issue_date")) or date(2026, 8, 1)
        paper = max(metres[num].items(), key=lambda kv: kv[1]) if metres[num] else None
        item = paper[0] if paper else (max(value[num].items(), key=lambda kv: kv[1])[0] if value[num] else None)
        if item is None:
            continue
        ua, ul = rng.choice([(2, 3), (3, 3), (3, 4), (4, 3)])
        rep = rng.choice([203.2, 228.6, 254.0, 279.4])
        used = round(paper[1], 1) if paper else 0.0
        qty = max(1000, int(round(used / 1.08 * ua * ul * 1000 / rep, -2))) if used else rng.choice(
            [10000, 20000, 30000, 50000])
        row = R.add("jobs", {"job_card": jc, "created_on": first - timedelta(days=2),
                             "client_id": rng.choice(ctx.real_clients), "po_no": None,
                             "po_date": first - timedelta(days=3), "product": s_(j.get("job_name")),
                             "label_size": None, "order_qty": qty, "rate": round(rng.uniform(0.3, 1.1), 2),
                             "item_id": item, "machine_id": rng.choice(press_ids), "ups_across": ua,
                             "ups_along": ul, "repeat_mm": rep, "units": COLOURS[:4],
                             "due_date": first + timedelta(days=12), "priority": "normal",
                             "status": "closed" if (s_(j.get("ppic_status")) or "").lower() == "closed" else "planned"})
        if num in chosen:
            ctx.real_jobs.append({"job_card": jc, "created_on": row["created_on"], "client_id": row["client_id"],
                                  "product": row["product"], "item_id": item, "colours": 4,
                                  "machine_id": row["machine_id"], "run_day": d_(j.get("last_issue_date")),
                                  "used_m": used, "existing": row})
    ctx.real_jobs.sort(key=lambda r: r["job_card"])
    job_ids = {r["job_card"] for r in R.t["jobs"]}

    # GRNs
    for n, g in enumerate(recs(fr.get("grns")), start=10001):
        iid = item_by_key.get(_key(g.get("item_description")) or "")
        if not iid:
            continue
        R.add("grns", {"id": f"GRN-{n:05d}", "date": d_(g["grn_date"]),
                       "vendor_id": vendor_by_key.get(_key(g.get("supplier_name")) or ""), "bill_no": None,
                       "item_id": iid, "qty": f_(g.get("qty_stock_uom")) or f_(g.get("qty")) or 0.0,
                       "rate": f_(g.get("rate_stock_uom")) or f_(g.get("rate")), "source": "erp_import",
                       "ref": s_(g.get("grn_number")), "raw_date": s_(g.get("grn_date_text"))}, demo=False)

    # issues
    for n, i in enumerate(issues, start=10001):
        iid = item_by_key.get(_key(i.get("item_description")) or "")
        if not iid:
            continue
        jc = f"JC-{s_(i['job_card'])}" if s_(i.get("job_card")) else None
        qty = f_(i.get("net_qty_stock_uom"))
        R.add("issues", {"id": f"ISS-{n:05d}", "date": d_(i["doc_date"]), "job_card": jc if jc in job_ids else None,
                         "item_id": iid, "qty": qty if qty is not None else (f_(i.get("net_qty")) or 0.0),
                         "roll_id": None, "issued_to": s_(i.get("to_location")), "source": "erp_import",
                         "raw_date": s_(i.get("doc_date_text")), "ref": s_(i.get("doc_number"))}, demo=False)

    _opening_debtors(R, rng, fr.get("opening_debtors"), client_by_name)

    for a in recs(fr.get("fixed_assets")):
        R.add("fixed_assets", {"kind": s_(a["kind"]), "asset_block": s_(a.get("asset_block")),
                               "description": s_(a.get("description")),
                               "gross_block_opening": f_(a.get("gross_block_opening")),
                               "acc_dep_opening": f_(a.get("acc_dep_opening")),
                               "net_block_opening": f_(a.get("net_block_opening")),
                               "dep_fy2025_26": f_(a.get("dep_fy2025_26")), "dep_rate": f_(a.get("dep_rate")),
                               "purchase_date": d_(a.get("purchase_date")), "amount": f_(a.get("amount"))},
              demo=False)
    _tally(R, fr.get("tally_pnl"))
    for li in recs(fr.get("lists")):
        if s_(li.get("value")):
            R.add("lists", {"list_name": s_(li["list_name"]), "value": s_(li["value"]),
                            "sort_order": i_(li.get("sort_order"))}, demo=False)

    extra, overrides = {}, {}
    for st in recs(fr.get("settings")):
        k, v = s_(st["key"]), s_(st["value"])
        if k in ("grace_days",):
            overrides[k] = int(float(v))
        elif k in ("ink_tol", "slit_tol"):
            overrides[k] = float(v)
        elif k in ("stock_from", "fy_start"):
            overrides[k] = d_(v)
        else:
            extra[k] = f_(v) if f_(v) is not None else v
    return extra, overrides


def _opening_debtors(R: Rows, rng: random.Random, df: pd.DataFrame | None, client_by_name: dict) -> None:
    n_rcp = 5001
    for n, o in enumerate(recs(df), start=1001):
        cid = client_by_name.get(_key(o.get("client")) or "") or client_by_name.get(_key(o.get("debtor_list_name"))
                                                                                    or "")
        amount = f_(o.get("amount_due"))
        inv_date = d_(o.get("invoice_date"))
        if not cid or not amount or not inv_date:
            continue
        inv_id = f"INV-{n:04d}"
        R.add("invoices", {"id": inv_id, "date": inv_date, "client_id": cid, "job_card": None, "dispatch_id": None,
                           "qty": 1, "rate": amount, "gst_rate": 0.0, "status": "open", "source": "opening",
                           "ref": s_(o.get("invoice_no"))}, demo=False)
        received = f_(o.get("received_since")) or 0.0
        if received > 0:
            R.add("receipts", {"id": f"RCP-{n_rcp:04d}", "date": d_(o.get("receipt_date")) or d_(o.get("as_of")),
                               "client_id": cid, "invoice_id": inv_id, "amount": received, "mode": "bank",
                               "ref": "Opening Debtors sheet"}, demo=False)
            n_rcp += 1
        balance = float(money(Decimal(str(amount)) - Decimal(str(received))))
        client = R.one("clients", id=cid)
        due = M.due_date(inv_date, client["credit_days"])
        if balance > 0 and due < TODAY - timedelta(days=4):
            start = max(date(2026, 10, 1), inv_date + timedelta(days=1))
            pay = min(max(start, due + timedelta(days=rng.randint(-5, 12))), TODAY - timedelta(days=1))
            R.add("receipts", {"id": f"RCP-{n_rcp:04d}", "date": pay, "client_id": cid, "invoice_id": inv_id,
                               "amount": balance, "mode": "neft", "ref": "DEMO settlement"}, demo=True)
            n_rcp += 1


TALLY_KEYS = {  # section -> key; a few ledgers override the section
    "SALES & INCOME": "revenue", "Less: Sales Return / Rejection": "revenue", "PURCHASES": "material",
    "EMPLOYEE BENEFIT EXPENSES": "salaries", "ADMINISTRATIVE & OTHER EXPENSES": "admin",
    "FINANCIAL EXPENSES": "admin", "DIRECT EXPENSES": "overheads",
}


def _tally(R: Rows, df: pd.DataFrame | None) -> None:
    """Typed Tally P&L (Apr-Sep 2026) summed into the schema keys per month."""
    sums: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    lines: dict[tuple[str, str], int] = defaultdict(int)
    for t in recs(df):
        period, section, ledger = s_(t.get("period")), s_(t.get("section")) or "", s_(t.get("ledger")) or ""
        if not period or period == "opening" or b_(t.get("is_memo")) or f_(t.get("amount")) is None:
            continue
        key = TALLY_KEYS.get(section)
        if key is None:
            continue
        low = ledger.lower()
        if section == "PURCHASES" and "plates" in low:
            key = "plates"
        elif section == "PURCHASES" and "ink" in low:
            key = "ink"
        elif "freight outward" in low:
            key = "freight"
        amt = Decimal(str(f_(t["amount"])))
        if section.startswith("Less:"):
            amt = -amt
        sums[(period, key)] += amt
        lines[(period, key)] += 1
    now = datetime(2026, 11, 5, 18, 20, tzinfo=IST)
    for (month, key), amt in sorted(sums.items()):
        R.add("tally_pnl", {"month": month, "key": key, "amount": float(money(amt)), "imported_at": now,
                            "note": f"Tally import: {lines[(month, key)]} ledger lines"}, demo=False)
