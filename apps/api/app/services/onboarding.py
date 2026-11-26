"""Standard onboarding template import (SPEC 6.3, issue #54 B2; screen 18 step 4).

The template is one ``.xlsx`` with a sheet each for ``clients``, ``vendors``, ``items``, ``machines``,
``opening_stock`` and ``unpaid_invoices`` (row 1 = column names). Every sheet is checked; good rows are
saved for **this** company through a session scoped to it, bad rows are held back and listed in ``fixes``
(sheet, row, column, value, problem, fix) to correct and re-upload. Nothing is read from or copied to
another company. A re-upload skips rows that are already saved (same name / invoice number).
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit, next_id
from app.deps import T, bad_request
from app.serialize import jsonable, now

SHEETS = ("clients", "vendors", "items", "machines", "opening_stock", "unpaid_invoices")
COLUMNS = {
    "clients": ("name", "gstin", "city", "state", "contact", "phone", "email", "credit_days", "credit_limit"),
    "vendors": ("name", "city", "msme", "credit_days", "supplies", "gstin"),
    "items": ("name", "group", "uom", "width_mm", "rate", "rate_unit", "min_stock", "vendor"),
    "machines": ("name", "type", "units", "max_speed_mpm", "web_width_mm"),
    "opening_stock": ("item", "qty", "rate", "as_of"),
    "unpaid_invoices": ("invoice_no", "date", "client", "amount"),
}
REQUIRED = {
    "clients": ("name",),
    "vendors": ("name",),
    "items": ("name", "uom"),
    "machines": ("name", "type"),
    "opening_stock": ("item", "qty", "as_of"),
    "unpaid_invoices": ("invoice_no", "date", "client", "amount"),
}
UNITS = ("m", "kg", "sqm", "nos")
GSTIN = re.compile(r"^[0-9]{2}[A-Z0-9]{13}$")


@dataclass
class Rule:
    name: str
    severity: str  # warn | error
    ok_message: str
    count: int = 0
    note: str = ""


@dataclass
class SheetCheck:
    sheet: str
    rules: dict[str, Rule]
    rows: list[tuple[int, dict]] = field(default_factory=list)  # (row number, values)
    bad: set[int] = field(default_factory=set)
    missing_columns: list[str] = field(default_factory=list)
    present: bool = True


def _key(header: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(header or "").strip().lower()).strip("_")


def _text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _num(v: Any) -> Decimal | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return Decimal(str(v).replace(",", "").strip())
    except InvalidOperation:
        return None


def _day_first(v: Any) -> date | None:
    """A date cell, or text read day first (dd-mm-yyyy, dd/mm/yyyy, dd.mm.yyyy); ISO yyyy-mm-dd also works."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _text(v)
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    try:
        if m:
            d, mo, y = (int(x) for x in m.groups())
            return date(y + 2000 if y < 100 else y, mo, d)
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _shown(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (date, datetime)):
        return v.strftime("%d-%m-%Y")
    return str(v)


class Importer:
    def __init__(self) -> None:
        self.fixes: list[dict] = []
        self.checks: dict[str, SheetCheck] = {}

    # ---- helpers -----------------------------------------------------------------------------
    def problem(self, sc: SheetCheck, rule: str | None, row: int, column: str, value: Any, problem: str,
                fix: str) -> None:
        if rule:
            sc.rules[rule].count += 1
        sc.bad.add(row)
        self.fixes.append({"sheet": sc.sheet, "row": row, "column": column, "value": _shown(value),
                           "problem": problem, "fix": fix})

    def good(self, sheet: str) -> list[tuple[int, dict]]:
        sc = self.checks[sheet]
        return [(n, r) for n, r in sc.rows if n not in sc.bad]

    # ---- reading -----------------------------------------------------------------------------
    def read(self, data: bytes) -> None:
        try:
            from openpyxl import load_workbook

            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise bad_request("file must be the onboarding template (.xlsx)") from exc
        names = {_key(n): n for n in wb.sheetnames}
        for sheet in SHEETS:
            sc = SheetCheck(sheet, {})
            self.checks[sheet] = sc
            if sheet not in names:
                sc.present = False
                continue
            rows = wb[names[sheet]].iter_rows(values_only=True)
            header = [_key(h) for h in next(rows, ())]
            sc.missing_columns = [c for c in REQUIRED[sheet] if c not in header]
            for i, values in enumerate(rows, start=2):
                rec = {h: v for h, v in zip(header, values, strict=False) if h}
                if all(_text(v) is None for v in rec.values()):
                    continue
                sc.rows.append((i, rec))
        wb.close()

    # ---- checks per sheet ------------------------------------------------------------------------
    def check_all(self) -> None:
        rules = {
            "clients": [Rule("GSTIN format", "warn", "All GSTINs valid"),
                        Rule("Duplicate client names", "warn", "No duplicates"),
                        Rule("Credit days is a whole number", "error", "All valid")],
            "vendors": [Rule("MSME flag is Yes/No", "error", "All filled"),
                        Rule("Duplicate vendor names", "warn", "No duplicates")],
            "items": [Rule("Unit is m, kg, sqm or nos", "error", "All units valid"),
                      Rule("Width given for items sold per sq m", "error", "All widths given"),
                      Rule("Rate is a positive number", "error", "All rates valid")],
            "machines": [Rule("Machine type is press or offline", "error", "")],
            "opening_stock": [Rule("Item exists in items sheet", "error", "All items found"),
                              Rule("Quantity is a number", "error", "All quantities valid"),
                              Rule("Stock date is the go-live date", "error", "")],
            "unpaid_invoices": [Rule("Client exists in clients sheet", "error", "All clients found"),
                                Rule("Dates read day first (dd-mm-yyyy)", "error", "No ambiguous dates"),
                                Rule("Amount is a positive number", "error", "All amounts valid")],
        }
        for sheet, rs in rules.items():
            sc = self.checks[sheet]
            sc.rules = {r.name: r for r in rs}
            if not sc.present:
                self.fixes.append({"sheet": sheet, "row": 1, "column": "(sheet)", "value": None,
                                   "problem": f"Sheet {sheet} is missing",
                                   "fix": f"Add a sheet named {sheet} from the standard template"})
                continue
            if sc.missing_columns:
                for col in sc.missing_columns:
                    self.fixes.append({"sheet": sheet, "row": 1, "column": col, "value": None,
                                       "problem": f"Column {col} is missing",
                                       "fix": f"Add a column named {col} in row 1 (see the template)"})
                sc.bad = {n for n, _ in sc.rows}
                continue
            for n, r in sc.rows:
                for col in REQUIRED[sheet]:
                    if _text(r.get(col)) is None:
                        self.problem(sc, None, n, col, None, f"{col} is empty", f"Fill in {col}")
            getattr(self, f"_check_{sheet}")(sc)

    def _check_clients(self, sc: SheetCheck) -> None:
        seen: dict[str, int] = {}
        for n, r in sc.rows:
            g = _text(r.get("gstin"))
            if g and not GSTIN.match(g.upper()):
                self.problem(sc, "GSTIN format", n, "gstin", g, "GSTIN must be 15 characters"
                             if len(g) != 15 else "GSTIN must be 2 digits then 13 letters or digits",
                             "Type the full GSTIN from the client's invoice")
            name = (_text(r.get("name")) or "").lower()
            if name and name in seen:
                self.problem(sc, "Duplicate client names", n, "name", r.get("name"),
                             f"Same client as row {seen[name]}", "Keep one row per client")
            elif name:
                seen[name] = n
            cd = r.get("credit_days")
            if _text(cd) is not None and (_num(cd) is None or _num(cd) != int(_num(cd)) or _num(cd) < 0):
                self.problem(sc, "Credit days is a whole number", n, "credit_days", cd,
                             "Credit days must be a whole number", "Type the number of days, e.g. 30")

    def _check_vendors(self, sc: SheetCheck) -> None:
        seen: dict[str, int] = {}
        for n, r in sc.rows:
            m = _text(r.get("msme"))
            if m is not None and m.lower() not in ("yes", "no", "y", "n", "true", "false"):
                self.problem(sc, "MSME flag is Yes/No", n, "msme", m, "MSME must be Yes or No", "Type Yes or No")
            name = (_text(r.get("name")) or "").lower()
            if name and name in seen:
                self.problem(sc, "Duplicate vendor names", n, "name", r.get("name"),
                             f"Same vendor as row {seen[name]}", "Keep one row per vendor")
            elif name:
                seen[name] = n

    def _check_items(self, sc: SheetCheck) -> None:
        for n, r in sc.rows:
            uom = (_text(r.get("uom")) or "").lower()
            if uom and uom not in UNITS:
                self.problem(sc, "Unit is m, kg, sqm or nos", n, "uom", r.get("uom"), "Unit must be m, kg, sqm or nos",
                             "Use m (running metres) for paper and film rolls")
            per_sqm = uom == "sqm" or (_text(r.get("rate_unit")) or "").lower() == "per_sqm"
            if per_sqm and (_num(r.get("width_mm")) is None or _num(r.get("width_mm")) <= 0):
                self.problem(sc, "Width given for items sold per sq m", n, "width_mm", r.get("width_mm"),
                             "Paper sold per sq m needs a width", "Add the roll width in mm")
            rate = r.get("rate")
            if _text(rate) is not None and (_num(rate) is None or _num(rate) <= 0):
                self.problem(sc, "Rate is a positive number", n, "rate", rate, "Rate must be a positive number",
                             "Type the purchase rate in rupees")

    def _check_machines(self, sc: SheetCheck) -> None:
        rule = sc.rules["Machine type is press or offline"]
        for n, r in sc.rows:
            t = (_text(r.get("type")) or "").lower()
            if t and t not in ("press", "offline"):
                self.problem(sc, rule.name, n, "type", r.get("type"), "Type must be press or offline",
                             "Type press for printing machines, offline for slitting / rewinding")
        types = [(_text(r.get("type")) or "").lower() for n, r in sc.rows if n not in sc.bad]
        rule.ok_message = f"{types.count('press')} presses, {types.count('offline')} offline"

    def _check_opening_stock(self, sc: SheetCheck) -> None:
        items = {(_text(r.get("name")) or "").lower() for _, r in self.good("items")} | (self.existing_items or set())
        dates: dict[date, int] = {}
        for n, r in sc.rows:
            name = _text(r.get("item"))
            if name and name.lower() not in items:
                self.problem(sc, "Item exists in items sheet", n, "item", name, "Item not found in the items sheet",
                             "Use the exact item name from the items sheet, or add the item there")
            q = r.get("qty")
            if _text(q) is not None and _num(q) is None:
                self.problem(sc, "Quantity is a number", n, "qty", q, "Quantity must be a number",
                             "Type the quantity in the item's unit")
            raw = r.get("as_of")
            d = _day_first(raw)
            if _text(raw) is not None and d is None:
                self.problem(sc, "Stock date is the go-live date", n, "as_of", raw, "Date not read as dd-mm-yyyy",
                             "Type the go-live date as dd-mm-yyyy")
            elif d:
                dates[d] = dates.get(d, 0) + 1
        rule = sc.rules["Stock date is the go-live date"]
        if len(dates) == 1:
            rule.ok_message = f"All rows dated {next(iter(dates)).isoformat()}"
        elif dates:
            rule.ok_message = f"{len(dates)} different dates; usually all rows share the go-live date"
        else:
            rule.ok_message = "No rows"

    def _check_unpaid_invoices(self, sc: SheetCheck) -> None:
        clients = {(_text(r.get("name")) or "").lower() for _, r in self.good("clients")} | (self.existing_clients
                                                                                           or set())
        for n, r in sc.rows:
            name = _text(r.get("client"))
            if name and name.lower() not in clients:
                self.problem(sc, "Client exists in clients sheet", n, "client", name,
                             "Client not found in the clients sheet",
                             "Use the exact client name from the clients sheet, or add the client there")
            raw = r.get("date")
            if _text(raw) is not None and _day_first(raw) is None:
                self.problem(sc, "Dates read day first (dd-mm-yyyy)", n, "date", raw, "Date not read as dd-mm-yyyy",
                             "Type the invoice date as dd-mm-yyyy")
            amt = r.get("amount")
            if _text(amt) is not None and (_num(amt) is None or _num(amt) <= 0):
                self.problem(sc, "Amount is a positive number", n, "amount", amt, "Amount must be a positive number",
                             "Type the unpaid amount in rupees")

    existing_items: set[str] | None = None
    existing_clients: set[str] | None = None

    # ---- result --------------------------------------------------------------------------------
    def sheets(self) -> list[dict]:
        out = []
        for sheet in SHEETS:
            sc = self.checks[sheet]
            checks = []
            if not sc.present:
                checks.append({"rule": "Sheet present", "status": "error", "count": 1,
                               "message": f"Sheet {sheet} not found"})
            else:
                missing = len(sc.missing_columns)
                checks.append({"rule": "Required columns present", "status": "error" if missing else "ok",
                               "count": missing,
                               "message": f"Missing: {', '.join(sc.missing_columns)}" if missing
                               else f"All {len(REQUIRED[sheet])} required columns found"})
                if not missing:
                    for r in sc.rules.values():
                        checks.append({"rule": r.name, "status": r.severity if r.count else "ok", "count": r.count,
                                       "message": r.ok_message if not r.count
                                       else f"{r.count} row{'s' if r.count != 1 else ''} to fix"})
            held = len(sc.bad)
            if not sc.present or any(c["status"] == "error" for c in checks):
                status = "error"
            elif held or any(c["status"] == "warn" for c in checks):
                status = "warn"
            else:
                status = "ok"
            out.append({"sheet": sheet, "rows": len(sc.rows), "good": len(sc.rows) - held, "held_back": held,
                        "status": status, "checks": checks})
        return out


class _Ids:
    """Permanent ids for new rows of one company: one above the highest existing number."""

    def __init__(self, db: Session, table: str, prefix: str, width: int, column: str = "id") -> None:
        first = next_id(db, table, prefix, width, column)
        self.prefix, self.width, self.n = prefix, width, int(first.rsplit("-", 1)[1])

    def __call__(self) -> str:
        out = f"{self.prefix}-{self.n:0{self.width}d}"
        self.n += 1
        return out


def _by_name(db: Session, table: str) -> dict[str, str]:
    tbl = T(table)
    return {(name or "").strip().lower(): rid for rid, name in db.execute(select(tbl.c.id, tbl.c.name))}


def _yes(v: Any) -> bool:
    return (_text(v) or "").lower() in ("yes", "y", "true")


def _int(v: Any) -> int | None:
    n = _num(v)
    return int(n) if n is not None else None


def _save(db: Session, imp: Importer) -> None:
    """Insert the good rows; ``db`` is scoped to the company, so ``company_id`` is filled in for each row."""
    vendors = _by_name(db, "vendors")
    new_id = _Ids(db, "vendors", "VN", 3)
    for _, r in imp.good("vendors"):
        key = _text(r["name"]).lower()
        if key in vendors:
            continue
        vendors[key] = vid = new_id()
        db.execute(T("vendors").insert().values(
            id=vid, name=_text(r["name"]), city=_text(r.get("city")), msme=_yes(r.get("msme")),
            credit_days=_int(r.get("credit_days")) or 30, supplies=_text(r.get("supplies")),
            gstin=_text(r.get("gstin"))))

    clients = _by_name(db, "clients")
    new_id = _Ids(db, "clients", "CL", 3)
    for _, r in imp.good("clients"):
        key = _text(r["name"]).lower()
        if key in clients:
            continue
        clients[key] = cid = new_id()
        db.execute(T("clients").insert().values(
            id=cid, name=_text(r["name"]), gstin=(_text(r.get("gstin")) or "").upper() or None,
            city=_text(r.get("city")), state=_text(r.get("state")), contact=_text(r.get("contact")),
            phone=_text(r.get("phone")), email=_text(r.get("email")),
            credit_days=_int(r.get("credit_days")) or 30, credit_limit=_num(r.get("credit_limit")), active=True))

    items = _by_name(db, "items")
    new_id = _Ids(db, "items", "IT", 4)
    for _, r in imp.good("items"):
        key = _text(r["name"]).lower()
        if key in items:
            continue
        items[key] = iid = new_id()
        uom = _text(r["uom"]).lower()
        db.execute(T("items").insert().values(
            id=iid, name=_text(r["name"]), group=_text(r.get("group")), uom=uom, width_mm=_int(r.get("width_mm")),
            rate=_num(r.get("rate")), rate_unit=_text(r.get("rate_unit")) or f"per_{uom}",
            min_stock=_num(r.get("min_stock")), vendor_id=vendors.get((_text(r.get("vendor")) or "").lower())))

    machines = _by_name(db, "machines")
    new_id = _Ids(db, "machines", "M", 2)
    for _, r in imp.good("machines"):
        key = _text(r["name"]).lower()
        if key in machines:
            continue
        machines[key] = new_id()
        db.execute(T("machines").insert().values(
            id=machines[key], name=_text(r["name"]), type=_text(r["type"]).lower(), units=_int(r.get("units")),
            max_speed_mpm=_int(r.get("max_speed_mpm")), web_width_mm=_int(r.get("web_width_mm"))))

    stock = T("opening_stock")
    have = {(iid, d) for iid, d in db.execute(select(stock.c.item_id, stock.c.as_of))}
    for _, r in imp.good("opening_stock"):
        iid, as_of = items[_text(r["item"]).lower()], _day_first(r["as_of"])
        if (iid, as_of) in have:
            continue
        have.add((iid, as_of))
        qty, rate = _num(r["qty"]), _num(r.get("rate"))
        db.execute(stock.insert().values(item_id=iid, as_of=as_of, qty=qty, rate=rate,
                                         value=qty * rate if rate is not None else None))

    inv = T("invoices")
    refs = {ref for (ref,) in db.execute(select(inv.c.ref).where(inv.c.source == "opening"))}
    new_id = _Ids(db, "invoices", "INV", 4)
    for _, r in imp.good("unpaid_invoices"):
        ref = _text(r["invoice_no"])
        if ref in refs:
            continue
        refs.add(ref)
        db.execute(inv.insert().values(
            id=new_id(), date=_day_first(r["date"]), client_id=clients[_text(r["client"]).lower()], job_card=None,
            qty=1, rate=_num(r["amount"]), gst_rate=0, status="open", source="opening", ref=ref))


def run_import(db: Session, company_id: str, file_name: str, data: bytes, role: str) -> dict:
    """Check the template, save the good rows for ``company_id`` (``db`` is scoped to it) and log the import."""
    imp = Importer()
    imp.read(data)
    imp.existing_items = set(_by_name(db, "items"))
    imp.existing_clients = set(_by_name(db, "clients"))
    imp.check_all()
    sheets = imp.sheets()
    _save(db, imp)
    totals = {k: sum(s[k] for s in sheets) for k in ("rows", "good", "held_back")}
    status = "ok" if not imp.fixes else ("partial" if totals["good"] else "failed")
    imp_id = next_id(db, "imports", "IMP", 4)
    result = {"import_id": imp_id, "company_id": company_id, "file_name": file_name, "at": jsonable(now()),
              "status": status, "sheets": sheets, "fixes": imp.fixes, "totals": totals}
    db.execute(T("imports").insert().values(id=imp_id, file_name=file_name, at=now(), status=status, result=result,
                                            by_user=db.info.get("user_id")))
    audit(db, role=role, action="import", entity="imports", entity_id=imp_id, after={"status": status, **totals})
    db.commit()
    return result
