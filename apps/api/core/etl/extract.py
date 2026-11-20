"""EXTRACT step: read the client's real Excel workbooks into clean pandas frames.

``extract_all(raw_dir)`` opens each workbook once (read-only, cached values only),
reads only the TYPED input columns (the files were never recalculated, so formula
cells are empty), drops blank and DEMO rows, normalises text/dates/numbers and
returns ``{frame_name: DataFrame}`` plus a ``quality`` frame.

CLI::

    PYTHONPATH=apps/api python -m core.etl.extract --raw data/raw --out data/extract

See ``README.md`` in this folder for every frame, column and cleaning rule.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl
import pandas as pd

from core.rules.dates import parse_erp_date
from core.rules.errors import RuleError

FIRST_DATA_ROW = 5          # row 3 = entry hints, row 4 = headers
BLANK_RUN_STOP = 300        # stop scanning after this many consecutive blank rows
DEMO_TOKENS = ("JC-DEMO", "INV-2201")
NO_JOB_CARD = {"", "--", "XX", "-", "NA", "N/A"}
REVIEW_GLOB = "Review/*REVIEW*.xlsx"


# --------------------------------------------------------------------------- helpers
def _clean(v: Any) -> Any:
    """Strip text, turn empty strings into None; leave numbers/dates alone."""
    if isinstance(v, str):
        s = v.replace(" ", " ").strip()
        return s or None
    return v


def _key(v: Any) -> str | None:
    """Matching key like Excel TRIM + case-insensitive MATCH."""
    if v is None:
        return None
    s = " ".join(str(v).split())
    return s.casefold() or None


def _num(v: Any) -> float | None:
    v = _clean(v)
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _date(v: Any) -> date | None:
    v = _clean(v)
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return parse_erp_date(str(v))
    except RuleError:
        return None


def _text(v: Any) -> str | None:
    v = _clean(v)
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime):
        return v.date().isoformat()
    return str(v)


def _is_demo(values: Iterable[Any]) -> bool:
    for v in values:
        if isinstance(v, str):
            s = v.strip()
            if s.upper() == "DEMO" or any(t in s.upper() for t in DEMO_TOKENS):
                return True
    return False


def _find(raw_dir: Path, pattern: str) -> Path:
    hits = sorted(raw_dir.glob(pattern))
    if not hits:
        raise FileNotFoundError(f"no file matching {pattern!r} under {raw_dir}")
    return hits[0]


def _open(path: Path, data_only: bool = True):
    return openpyxl.load_workbook(path, read_only=True, data_only=data_only)


def _read_rows(ws, cols: dict[int, str], key_cols: Iterable[int], min_row: int = FIRST_DATA_ROW,
               max_row: int | None = None) -> tuple[list[dict], int]:
    """Read selected 0-based columns; keep rows where any key column has a value.

    Returns (records incl. ``src_row``, number of non-blank rows read).
    Demo rows are NOT removed here (caller counts them).
    """
    max_col = max(cols) + 1
    key_cols = list(key_cols)
    out, blank_run = [], 0
    for r_idx, row in enumerate(ws.iter_rows(min_row=min_row, max_row=max_row, max_col=max_col,
                                             values_only=True), start=min_row):
        row = tuple(row) + (None,) * (max_col - len(row))
        if all(_clean(row[c]) is None for c in key_cols):
            blank_run += 1
            if blank_run >= BLANK_RUN_STOP:
                break
            continue
        blank_run = 0
        rec = {name: _clean(row[c]) for c, name in cols.items()}
        rec["src_row"] = r_idx
        out.append(rec)
    return out, len(out)


class Quality:
    """Collects data-quality findings as rows (area, metric, value, detail)."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, area: str, metric: str, value: Any, detail: str = "") -> None:
        if isinstance(value, float):
            value = round(value, 4)
        self.rows.append({"area": area, "metric": metric, "value": value, "detail": detail})

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=["area", "metric", "value", "detail"])


def _keep_real(records: list[dict], area: str, q: Quality, rows_read: int,
               extra_check: Callable[[dict], bool] | None = None) -> list[dict]:
    kept = [r for r in records if not _is_demo(r.values()) and not (extra_check and extra_check(r))]
    q.add(area, "rows_read", rows_read)
    q.add(area, "demo_rows_dropped", rows_read - len(kept))
    q.add(area, "rows_kept", len(kept))
    return kept


def _df(records: list[dict], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame.from_records(records, columns=columns) if records else pd.DataFrame(columns=columns)


# --------------------------------------------------------------------------- date heuristic
_SEQ = re.compile(r"(\d+)\s*$")


def _seq_no(doc: Any) -> tuple[str, int] | None:
    """'PL/GR/27/0103' -> ('PL/GR/27/', 103)."""
    s = _text(doc)
    if not s:
        return None
    m = _SEQ.search(s)
    if not m:
        return None
    return s[: m.start()], int(m.group(1))


def fix_erp_dates(raw: list[Any], docs: list[Any], lower_bounds: list[date | None] | None = None
                  ) -> tuple[list[date | None], list[str]]:
    """Parse ERP dates day-first and repair Excel month-first misreads.

    * text ``dd-mm-yy``/``dd-mm-yyyy``: parsed day-first (method ``text``);
    * datetime with day > 12: Excel cannot have swapped it, kept (``excel_unambiguous``);
    * datetime with day <= 12 (original text unknown): candidates ``keep`` and ``swap``
      (day<->month). Anchors are the text/unambiguous dates of the same document
      series; for each document number we take the nearest anchor before and after
      in number order. The candidate that lies inside [prev anchor, next anchor]
      (and not before ``lower_bounds`` e.g. the PO date) wins; if both or neither fit,
      the one closer to the anchors wins; a tie keeps Excel's value. Methods:
      ``swapped`` / ``kept_checked`` / ``kept_ambiguous`` / ``same_day_month``.
    Returns (dates, methods).
    """
    n = len(raw)
    lower_bounds = lower_bounds or [None] * n
    dates: list[date | None] = [None] * n
    methods = [""] * n
    pending: list[int] = []
    anchors: dict[str, list[tuple[int, date]]] = {}
    seqs = [_seq_no(d) for d in docs]
    for i, v in enumerate(raw):
        if isinstance(v, datetime):
            v = v.date()
        if isinstance(v, date):
            if v.day > 12:
                dates[i], methods[i] = v, "excel_unambiguous"
            elif v.day == v.month:
                dates[i], methods[i] = v, "same_day_month"
            else:
                pending.append(i)
                continue
        else:
            d = _date(v)
            dates[i], methods[i] = d, ("text" if d else "unparsed")
        if dates[i] and seqs[i]:
            anchors.setdefault(seqs[i][0], []).append((seqs[i][1], dates[i]))
    index = {p: sorted(a) for p, a in anchors.items()}
    for i in pending:
        v = raw[i].date() if isinstance(raw[i], datetime) else raw[i]
        keep, swap = v, date(v.year, v.day, v.month)
        prev_d = next_d = None
        if seqs[i] and seqs[i][0] in index:
            arr = index[seqs[i][0]]
            nums = [a[0] for a in arr]
            lo = bisect_right(nums, seqs[i][1]) - 1
            hi = bisect_left(nums, seqs[i][1])
            # same document number already anchored -> use it exactly
            same = [a[1] for a in arr if a[0] == seqs[i][1]]
            if same:
                prev_d = next_d = same[0]
            else:
                prev_d = arr[lo][1] if lo >= 0 else None
                next_d = arr[hi][1] if hi < len(arr) else None
        lb = lower_bounds[i]

        def score(c: date) -> tuple[int, int]:
            dist = 0
            if prev_d and c < prev_d:
                dist += (prev_d - c).days
            if next_d and c > next_d:
                dist += (c - next_d).days
            if lb and c < lb:
                dist += (lb - c).days
            near = min([abs((c - x).days) for x in (prev_d, next_d) if x] or [0])
            return dist, near

        sk, ss = score(keep), score(swap)
        if ss < sk:
            dates[i], methods[i] = swap, "swapped"
        elif sk < ss:
            dates[i], methods[i] = keep, "kept_checked"
        else:
            dates[i], methods[i] = keep, "kept_ambiguous"
    return dates, methods


# --------------------------------------------------------------------------- workbook readers
def _read_accounts(path: Path, q: Quality) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    wb = _open(path)
    try:
        # Client Register
        cols = {1: "name", 2: "tally_name", 3: "gstin", 4: "billing_address", 5: "city", 6: "state",
                7: "contact_person", 8: "phone", 9: "email", 10: "credit_days", 11: "grace_days",
                12: "credit_limit", 13: "release_lock_until", 14: "remarks"}
        recs, n = _read_rows(wb["Client Register"], cols, [1])
        recs = _keep_real(recs, "clients", q, n)
        for r in recs:
            for k in ("credit_days", "grace_days", "credit_limit"):
                r[k] = _num(r[k])
            r["release_lock_until"] = _date(r["release_lock_until"])
            for k in ("name", "tally_name", "gstin", "phone", "remarks"):
                r[k] = _text(r[k])
        df = _df(recs, list(cols.values()) + ["src_row"])
        out["clients"] = df
        q.add("clients", "clients_without_credit_days", int(df["credit_days"].isna().sum()),
              "loader should apply the default (30 days)")
        q.add("clients", "duplicate_client_names", int(df["name"].map(_key).duplicated().sum()))

        # Vendor Register
        cols = {1: "name", 2: "gstin", 3: "state", 4: "contact_person", 5: "phone", 6: "email",
                7: "credit_days", 8: "msme_raw", 9: "udyam_no", 10: "bank_account", 11: "ifsc", 12: "remarks"}
        recs, n = _read_rows(wb["Vendor Register"], cols, [1])
        recs = _keep_real(recs, "vendors", q, n)
        for r in recs:
            r["credit_days"] = _num(r["credit_days"])
            m = (_text(r.pop("msme_raw")) or "").strip().lower()
            r["is_msme"] = True if m in ("yes", "y") else False if m in ("no", "n") else None
            r["gstin_state_code"] = (r["gstin"][:2] if r.get("gstin") and str(r["gstin"])[:2].isdigit()
                                     else None)
            for k in ("bank_account", "udyam_no", "phone"):
                r[k] = _text(r[k])
        vcols = ["name", "gstin", "gstin_state_code", "state", "contact_person", "phone", "email",
                 "credit_days", "is_msme", "udyam_no", "bank_account", "ifsc", "remarks", "src_row"]
        df = _df(recs, vcols)
        out["vendors"] = df
        q.add("vendors", "vendors_msme_flag_missing", int(df["is_msme"].isna().sum()),
              "MSME not filled in Vendor Register")
        q.add("vendors", "vendors_without_credit_days", int(df["credit_days"].isna().sum()))

        # Opening Debtors (unpaid invoices at 30-Sep-2026)
        cols = {1: "client", 2: "debtor_list_name", 3: "invoice_no", 4: "invoice_date", 5: "due_date",
                6: "amount_due", 7: "received_since", 8: "receipt_date"}
        recs, n = _read_rows(wb["Opening Debtors"], cols, [1, 3])
        recs = _keep_real(recs, "opening_debtors", q, n)
        for r in recs:
            r["invoice_no"] = _text(r["invoice_no"])
            for k in ("invoice_date", "due_date", "receipt_date"):
                r[k] = _date(r[k])
            for k in ("amount_due", "received_since"):
                r[k] = _num(r[k])
            r["as_of"] = date(2026, 9, 30)
        df = _df(recs, list(cols.values()) + ["as_of", "src_row"])
        out["opening_debtors"] = df
        ck = set(out["clients"]["name"].map(_key))
        q.add("opening_debtors", "debtor_rows_client_not_in_register",
              int((~df["client"].map(_key).isin(ck)).sum()))
        q.add("opening_debtors", "opening_debtors_total_rs", round(float(df["amount_due"].sum()), 2))

        out["fixed_assets"] = _read_fixed_assets(wb["Fixed Assets & Depreciation"], q)
        lists, ledgers, settings = _read_accounts_lists(wb["Lists"])
    finally:
        wb.close()
    out["_lists"] = lists
    out["pnl_ledgers"] = ledgers
    out["_settings"] = settings
    wbf = _open(path, data_only=False)
    try:
        out["tally_pnl"] = _read_tally_pnl(wbf["P&L format"], q)
    finally:
        wbf.close()
    return out


def _read_fixed_assets(ws, q: Quality) -> pd.DataFrame:
    rows = list(ws.iter_rows(min_row=1, max_row=60, max_col=6, values_only=True))
    recs = []
    for i, r in enumerate(rows, start=1):
        a = _clean(r[0])
        if 5 <= i <= 12 and a and a.upper() != "TOTAL" and _num(r[1]) is not None:
            g, d = _num(r[1]), _num(r[2]) or 0.0
            recs.append({"kind": "block", "asset_block": a, "description": None,
                         "gross_block_opening": g, "acc_dep_opening": d,
                         "net_block_opening": round(g - d, 2), "dep_fy2025_26": _num(r[4]),
                         "dep_rate": _num(r[5]), "purchase_date": None, "amount": None,
                         "src_row": i})
        elif i == 16 and _num(r[1]) is not None:
            recs.append({"kind": "misc_expenditure", "asset_block": a, "description": None,
                         "gross_block_opening": _num(r[1]), "acc_dep_opening": None,
                         "net_block_opening": _num(r[1]), "dep_fy2025_26": None,
                         "dep_rate": None, "purchase_date": None, "amount": _num(r[2]),
                         "src_row": i})
        elif i >= 31 and (a or _clean(r[1])) and _num(r[3]) is not None and not _is_demo(r):
            recs.append({"kind": "addition", "asset_block": _clean(r[1]), "description": a,
                         "gross_block_opening": None, "acc_dep_opening": None,
                         "net_block_opening": None, "dep_fy2025_26": None, "dep_rate": None,
                         "purchase_date": _date(r[2]), "amount": _num(r[3]), "src_row": i})
    df = _df(recs, ["kind", "asset_block", "description", "gross_block_opening", "acc_dep_opening",
                    "net_block_opening", "dep_fy2025_26", "dep_rate", "purchase_date", "amount", "src_row"])
    q.add("fixed_assets", "rows_kept", len(df))
    return df


def _read_accounts_lists(ws):
    lists, ledgers, settings = [], [], []
    for i, r in enumerate(ws.iter_rows(min_row=1, max_row=304, max_col=16, values_only=True), start=1):
        r = tuple(r) + (None,) * (16 - len(r))
        if i == 2:
            for j, v in enumerate(r):
                if isinstance(v, str) and "grace" in v.lower():
                    val = next((x for x in r[j + 1:] if isinstance(x, (int, float))), None)
                    if val is not None:
                        settings.append(("grace_days", val, "06 Accounts > Lists"))
        if i < FIRST_DATA_ROW:
            continue
        if _num(r[0]) is not None:
            lists.append(("gst_rate", _num(r[0])))
        if _clean(r[2]):
            ledgers.append({"ledger": _clean(r[2]), "section": _clean(r[3]),
                            "standard_per_month": _num(r[4]), "src_row": i})
        if _clean(r[6]):
            lists.append(("invoice_type", _clean(r[6])))
    return lists, _df(ledgers, ["ledger", "section", "standard_per_month", "src_row"]), settings


_REF = re.compile(r"\$?([A-Z]{1,3})\$?(\d+)")
_FUNC = re.compile(r"[A-Z]+\(")
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
                                       "oct", "nov", "dec"], start=1)}


def _col_idx(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _read_tally_pnl(ws, q: Quality) -> pd.DataFrame:
    """Tally P&L typed by Accounts (Apr-Sep 2026). Literal sums like ``=1+2`` and simple
    same-sheet references like ``=8352740-D25`` are evaluated; computed total rows
    (IF/SUM/INDEX formulas) are skipped (the loader can recompute totals)."""
    grid = [list(r) for r in ws.iter_rows(min_row=1, max_row=160, max_col=14, values_only=True)]
    grid = [r + [None] * (14 - len(r)) for r in grid]
    header = grid[3]
    periods: dict[int, str] = {}
    for j in range(1, 14):
        h = _clean(header[j])
        if isinstance(h, datetime):
            periods[j] = h.strftime("%Y-%m")
        elif isinstance(h, str):
            if h.lower().startswith("opening"):
                periods[j] = "opening"
            else:
                m = re.match(r"([A-Za-z]{3})[- ](\d{2})", h)
                if m and m.group(1).lower() in _MONTHS:
                    periods[j] = f"20{m.group(2)}-{_MONTHS[m.group(1).lower()]:02d}"

    def is_input(v: Any) -> bool:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return True
        if isinstance(v, str) and v.startswith("="):
            body = v[1:]
            if _FUNC.search(body.upper()):
                return False
            return bool(re.search(r"\d", _REF.sub("", body)))
        return False

    def value(r: int, c: int, depth: int = 0) -> float | None:
        v = grid[r][c] if r < len(grid) else None
        if v is None or depth > 10:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.startswith("=") and not _FUNC.search(v[1:].upper()):
            expr = _REF.sub(lambda m: repr(value(int(m.group(2)) - 1, _col_idx(m.group(1)), depth + 1) or 0.0),
                            v[1:])
            if re.fullmatch(r"[0-9eE\.\+\-\*/\(\) ]+", expr):
                try:
                    return float(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 (digits/operators only)
                except Exception:
                    return None
        return None

    recs, section = [], None
    for r in range(4, len(grid)):
        label = _clean(grid[r][0])
        if not label:
            continue
        cells = [grid[r][j] for j in periods]
        if all(c is None for c in cells):
            # heading = UPPER-CASE label ("SALES & INCOME", "CLOSING STOCK (month-end) ...") or a
            # "Less: ..." sub-heading followed by plain ledgers; other empty rows are unused ledgers
            head = re.split(r"[(—–]", label)[0]
            nxt = _clean(grid[r + 1][0]) if r + 1 < len(grid) else None
            if (head.strip() and head == head.upper()) or (
                    label.startswith("Less:") and nxt and not re.match(r"(Less|Add):", str(nxt))):
                section = label
            continue
        if not any(is_input(c) for c in cells):
            continue
        for j, p in periods.items():
            if is_input(grid[r][j]):
                amt = value(r, j)
                if amt is not None:
                    recs.append({"section": section, "ledger": label, "period": p,
                                 "amount": round(amt, 2), "is_memo": "memo" in label.lower(),
                                 "src_row": r + 1})
    df = _df(recs, ["section", "ledger", "period", "amount", "is_memo", "src_row"])
    q.add("tally_pnl", "ledgers", int(df["ledger"].nunique()) if len(df) else 0)
    q.add("tally_pnl", "rows_kept", len(df), "long format: one row per ledger x period")
    q.add("tally_pnl", "months_filled", ",".join(sorted(p for p in df["period"].unique() if p != "opening")))
    return df


def _read_store_system(path: Path, q: Quality) -> dict[str, Any]:
    out: dict[str, Any] = {}
    wb = _open(path)
    try:
        ws = wb["Lists"]
        settings, lists = [], []
        for i, r in enumerate(ws.iter_rows(min_row=1, max_row=704, max_col=18, values_only=True), start=1):
            r = tuple(r) + (None,) * (18 - len(r))
            lab, val = _clean(r[8]), r[12]
            if lab and val is not None and i <= 6:
                low = lab.lower()
                key = ("fy_start" if "financial year" in low else "ink_tol" if "ink tolerance" in low
                       else "slit_tol" if "slitting" in low else "stock_from" if "stock counted" in low
                       else None)
                if key:
                    settings.append((key, val.date() if isinstance(val, datetime) else val, "02 Store > Lists"))
            if i >= FIRST_DATA_ROW:
                for c, name in ((3, "item_group"), (4, "uom"), (5, "stock_type"),
                                (6, "stock_statement_group"), (17, "party_laminate_movement")):
                    if _clean(r[c]):
                        lists.append((name, _clean(r[c])))
        out["_settings"], out["_lists"] = settings, lists
        stock_from = next((v for k, v, _ in settings if k == "stock_from"), date(2026, 10, 1))

        # Item Master
        cols = {1: "item_name", 2: "item_code", 3: "item_group", 4: "stock_head", 5: "ppic_paper",
                6: "width_mm", 7: "uom", 8: "uom_factor", 9: "rate", 10: "rate_source",
                11: "opening_running_m", 12: "opening_date", 13: "min_stock", 30: "stock_type",
                31: "lying_since"}
        recs, n = _read_rows(wb["Item Master"], cols, [1])
        recs = _keep_real(recs, "items", q, n)
        for r in recs:
            r["item_code"] = _text(r["item_code"])
            for k in ("width_mm", "uom_factor", "rate", "opening_running_m", "min_stock"):
                r[k] = _num(r[k])
            if r["rate"] is not None and r["rate"] <= 0:
                r["rate"] = None
            rs = _text(r["rate_source"])
            r["rate_source"] = rs.replace("⚠", "").strip() if rs else None
            r["opening_date"], r["lying_since"] = _date(r["opening_date"]), _date(r["lying_since"])
            r["has_rate"] = r["rate"] is not None
            r["is_customer_material"] = bool(rs and "customer material" in rs.lower())
            r["item_key"] = _key(r["item_name"])
        icols = ["item_name", "item_code", "item_group", "stock_head", "ppic_paper", "width_mm", "uom",
                 "uom_factor", "rate", "has_rate", "is_customer_material", "rate_source", "opening_running_m", "opening_date",
                 "min_stock", "stock_type", "lying_since", "item_key", "src_row"]
        df = _df(recs, icols)
        out["items"] = df
        q.add("items", "items_without_rate", int((~df["has_rate"] & ~df["is_customer_material"]).sum()),
              "rate still to be entered (excludes customer-owned material)")
        q.add("items", "items_customer_material_no_cost", int(df["is_customer_material"].sum()))
        q.add("items", "items_without_stock_head", int(df["stock_head"].isna().sum()))
        q.add("items", "duplicate_item_names", int(df["item_key"].duplicated().sum()))

        # Stock Statement (opening)
        cols = {1: "item_group", 2: "stock_head", 3: "uom", 4: "opening_qty", 5: "opening_rate",
                6: "value_only", 20: "min_stock", 24: "lying_since"}
        recs, n = _read_rows(wb["Stock Statement"], cols, [2])
        recs = _keep_real(recs, "opening_stock", q, n)
        for r in recs:
            for k in ("opening_qty", "opening_rate", "value_only", "min_stock"):
                r[k] = _num(r[k])
            r["lying_since"] = _date(r["lying_since"])
            qv = (r["opening_qty"] or 0) * (r["opening_rate"] or 0)
            r["opening_value"] = round(qv if qv else (r["value_only"] or 0.0), 2)
            r["as_of"] = stock_from
        df = _df(recs, ["item_group", "stock_head", "uom", "opening_qty", "opening_rate", "value_only",
                        "opening_value", "min_stock", "lying_since", "as_of", "src_row"])
        out["opening_stock"] = df
        q.add("opening_stock", "opening_value_total_rs", round(float(df["opening_value"].sum()), 2))
        q.add("opening_stock", "heads_value_only", int(df["value_only"].notna().sum()),
              "heads with value but no quantity (e.g. mixed ink)")
        heads = set(df["stock_head"].map(_key))
        im = out["items"]
        q.add("items", "items_stock_head_not_in_statement",
              int((im["stock_head"].notna() & ~im["stock_head"].map(_key).isin(heads)).sum()))
    finally:
        wb.close()
    return out


def _read_review(path: Path, items: pd.DataFrame, q: Quality) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    imap = {k: row for k, row in zip(items["item_key"], items.to_dict("records"), strict=False)}
    wb = _open(path)
    try:
        # ---- jobs (hidden 'Ref PPIC Job Register': B job card, I job name, AD PPIC status)
        cols = {1: "job_card", 8: "job_name", 29: "ppic_status"}
        recs, n = _read_rows(wb["Ref PPIC Job Register"], cols, [1])
        recs = _keep_real(recs, "jobs", q, n)
        for r in recs:
            r["job_card"] = _text(r["job_card"])
        jobs = _df(recs, ["job_card", "job_name", "ppic_status", "src_row"])

        # ---- GRNs (A:X)
        gcols = ["supplier_name", "gstin", "grn_number", "grn_date_raw", "grn_type", "po_ref", "hsn_code",
                 "item_description", "item_code", "qty", "uom", "rate", "basic_amount", "disc_rate",
                 "disc_amount", "taxable_amount", "sgst_rate", "sgst_amount", "cgst_rate", "cgst_amount",
                 "igst_rate", "igst_amount", "gst_amount", "total_amount"]
        recs, n = _read_rows(wb["ERP GRN Paste"], dict(enumerate(gcols)), [2, 7])
        recs = [r for r in recs if not str(r["grn_number"] or "").upper().startswith("GRN")]
        recs = _keep_real(recs, "grns", q, n)
        out["grns"] = _build_grns(recs, imap, q)

        # ---- Issues (A:X)
        icols = ["doc_number", "doc_date_raw", "job_card_number", "job_card_id", "job_name", "erp_group",
                 "item_code", "item_description", "uom", "total_quantity", "remarks", "from_location",
                 "to_location", "no_of_pack", "qty_per_pack", "quantity", "roll_id", "returned_no_of_pack",
                 "returned_qty_per_pack", "returned_qty", "return_roll_id", "return_note_number",
                 "return_date_raw", "consumed_qty"]
        recs, n = _read_rows(wb["ERP Issue Paste"], dict(enumerate(icols)), [0, 7])
        recs = [r for r in recs if not str(r["doc_number"] or "").upper().startswith(("DOC", "REPORT"))]
        recs = _keep_real(recs, "issues", q, n)
        out["issues"] = _build_issues(recs, imap, jobs, q)
    finally:
        wb.close()

    # enrich jobs with ERP issue facts
    iss = out["issues"]
    withjc = iss[iss["job_card"].notna()]
    agg = withjc.groupby("job_card").agg(erp_job_card_id=("job_card_id", "first"),
                                          issue_lines=("doc_number", "size"),
                                          first_issue_date=("doc_date", "min"),
                                          last_issue_date=("doc_date", "max"),
                                          material_value_rs=("value_rs", "sum")).reset_index()
    jobs = jobs.merge(agg, on="job_card", how="left")
    jobs["issue_lines"] = jobs["issue_lines"].fillna(0).astype(int)
    jobs["material_value_rs"] = jobs["material_value_rs"].fillna(0.0).round(2)
    out["jobs"] = jobs
    q.add("jobs", "jobs_without_issue_lines", int((jobs["issue_lines"] == 0).sum()))
    return out


def _uom_factor(uom: str | None, item: dict | None) -> float | None:
    """Same rule as the Store sheet: issue/GRN UOM -> item stock UOM."""
    if not item:
        return None
    iu, w = item.get("uom"), item.get("width_mm") or 0
    if uom == iu:
        return 1.0
    if uom == "Meter" and iu == "Sq.Mtrs" and w > 0:
        return w / 1000
    if uom == "Sq.Mtrs" and iu == "Meter" and w > 0:
        return 1000 / w
    f = item.get("uom_factor")
    return f if f and f > 0 else None


def _date_quality(area: str, methods: list[str], q: Quality) -> None:
    s = pd.Series(methods, dtype="object")
    for m in ("text", "excel_unambiguous", "same_day_month", "swapped", "kept_checked", "kept_ambiguous",
              "unparsed"):
        q.add(area, f"date_{m}", int((s == m).sum()))
    q.add(area, "date_fixes", int((s == "swapped").sum()),
          "Excel month-first misreads swapped back (GRN/doc number sequence heuristic)")


def _build_grns(recs: list[dict], imap: dict, q: Quality) -> pd.DataFrame:
    num_cols = ["qty", "rate", "basic_amount", "disc_rate", "disc_amount", "taxable_amount", "sgst_rate",
                "sgst_amount", "cgst_rate", "cgst_amount", "igst_rate", "igst_amount", "gst_amount",
                "total_amount"]
    for r in recs:
        for k in num_cols:
            r[k] = _num(r[k])
        for k in ("gstin", "grn_number", "item_code", "hsn_code", "po_ref", "grn_type", "uom"):
            r[k] = _text(r[k])
        po = r["po_ref"] or ""
        num, _, pdt = po.partition("::")
        r["po_number"] = num.strip() or None
        r["po_date"] = _date(pdt) if pdt else None
        r["grn_date_text"] = r["grn_date_raw"] if isinstance(r["grn_date_raw"], str) else None
    dates, methods = fix_erp_dates([r["grn_date_raw"] for r in recs], [r["grn_number"] for r in recs],
                                   [r["po_date"] for r in recs])
    rate_diff = dup = unknown = uom_bad = 0
    seen: dict[tuple, int] = {}
    unknown_items = set()
    for r, d, m in zip(recs, dates, methods, strict=False):
        r["grn_date"], r["date_method"] = d, m
        r["date_fixed"] = m == "swapped"
        excel = r["grn_date_raw"]
        r["grn_date_excel"] = excel.date() if isinstance(excel, datetime) else None
        item = imap.get(_key(r["item_description"]))
        r["item_known"] = item is not None
        r["item_group"] = item["item_group"] if item else None
        f = _uom_factor(r["uom"], item)
        r["uom_factor"] = f
        r["qty_stock_uom"] = round(r["qty"] * f, 4) if (f and r["qty"] is not None) else None
        r["rate_stock_uom"] = round(r["rate"] / f, 4) if (f and r["rate"] is not None) else None
        ir = item["rate"] if item else None
        r["item_rate"] = ir
        r["rate_diff_pct"] = (round(r["rate_stock_uom"] / ir - 1, 4)
                              if (ir and r["rate_stock_uom"] is not None) else None)
        if not item:
            unknown += 1
            unknown_items.add(_key(r["item_description"]))
        elif f is None:
            uom_bad += 1
        if r["rate_diff_pct"] is not None and abs(r["rate_diff_pct"]) > 0.05:
            rate_diff += 1
        k = (_key(r["grn_number"]), _key(r["item_description"]), r["qty"])
        seen[k] = seen.get(k, 0) + 1
        del r["grn_date_raw"], r["po_ref"]
    for r in recs:
        r["possible_duplicate"] = seen[(_key(r["grn_number"]), _key(r["item_description"]), r["qty"])] > 1
        dup += r["possible_duplicate"]
    cols = ["grn_number", "grn_date", "date_method", "date_fixed", "grn_date_text", "grn_date_excel",
            "supplier_name", "gstin", "grn_type", "po_number", "po_date", "hsn_code", "item_description",
            "item_code", "item_known", "item_group", "qty", "uom", "uom_factor", "qty_stock_uom", "rate",
            "rate_stock_uom", "item_rate", "rate_diff_pct", "basic_amount", "disc_rate", "disc_amount",
            "taxable_amount", "sgst_rate", "sgst_amount", "cgst_rate", "cgst_amount", "igst_rate",
            "igst_amount", "gst_amount", "total_amount", "possible_duplicate", "src_row"]
    df = _df(recs, cols)
    _date_quality("grns", methods, q)
    q.add("grns", "grn_numbers", int(df["grn_number"].nunique()))
    q.add("grns", "suppliers", int(df["supplier_name"].map(_key).nunique()))
    if len(df):
        q.add("grns", "grn_date_min", str(df["grn_date"].min()))
        q.add("grns", "grn_date_max", str(df["grn_date"].max()))
        q.add("grns", "taxable_total_rs", round(float(df["taxable_amount"].sum()), 2))
    q.add("grns", "unknown_item_lines", unknown)
    q.add("grns", "unknown_items_distinct", len(unknown_items))
    q.add("grns", "uom_problem_lines", uom_bad)
    q.add("grns", "rate_diff_gt_5pct_lines", rate_diff, "GRN rate vs Item Master rate (grn_rate_tol 0.05)")
    q.add("grns", "possible_duplicate_lines", int(dup))
    return df


def _build_issues(recs: list[dict], imap: dict, jobs: pd.DataFrame, q: Quality) -> pd.DataFrame:
    num_cols = ["total_quantity", "no_of_pack", "qty_per_pack", "quantity", "returned_no_of_pack",
                "returned_qty_per_pack", "returned_qty", "consumed_qty"]
    for r in recs:
        for k in num_cols:
            r[k] = _num(r[k])
        for k in ("doc_number", "job_card_number", "job_card_id", "item_code", "roll_id", "return_roll_id",
                  "return_note_number", "uom", "erp_group"):
            r[k] = _text(r[k])
        jc = (r["job_card_number"] or "").strip()
        r["job_card"] = None if jc.upper() in NO_JOB_CARD else jc
        if r["job_name"] in ("--", "-"):
            r["job_name"] = None
        r["return_date"] = _date(r.pop("return_date_raw"))
        r["doc_date_text"] = r["doc_date_raw"] if isinstance(r["doc_date_raw"], str) else None
    dates, methods = fix_erp_dates([r["doc_date_raw"] for r in recs], [r["doc_number"] for r in recs])
    known_jobs = set(jobs["job_card"])
    unknown_items, unknown_lines, uom_bad, no_rate = set(), 0, 0, 0
    for r, d, m in zip(recs, dates, methods, strict=False):
        r["doc_date"], r["date_method"], r["date_fixed"] = d, m, m == "swapped"
        del r["doc_date_raw"]
        r["has_job_card"] = r["job_card"] is not None
        r["job_card_in_ppic"] = (r["job_card"] in known_jobs) if r["job_card"] else None
        r["net_qty"] = (r["quantity"] or 0.0) - (r["returned_qty"] or 0.0)
        item = imap.get(_key(r["item_description"]))
        r["item_known"] = item is not None
        r["item_group"] = item["item_group"] if item else None
        f = _uom_factor(r["uom"], item)
        r["uom_factor"] = f
        r["net_qty_stock_uom"] = round(r["net_qty"] * f, 4) if f else None
        rate = item["rate"] if item else None
        r["item_rate"] = rate
        r["value_rs"] = round(r["net_qty_stock_uom"] * rate, 2) if (rate and f) else 0.0
        if not item:
            unknown_lines += 1
            unknown_items.add(_key(r["item_description"]))
        elif f is None:
            uom_bad += 1
        elif rate is None:
            no_rate += 1
    cols = ["doc_number", "doc_date", "date_method", "date_fixed", "doc_date_text", "job_card",
            "has_job_card", "job_card_in_ppic", "job_card_number", "job_card_id", "job_name", "erp_group",
            "item_code", "item_description", "item_known", "item_group", "uom", "total_quantity", "remarks",
            "from_location", "to_location", "no_of_pack", "qty_per_pack", "quantity", "roll_id",
            "returned_no_of_pack", "returned_qty_per_pack", "returned_qty", "return_roll_id",
            "return_note_number", "return_date", "consumed_qty", "net_qty", "uom_factor",
            "net_qty_stock_uom", "item_rate", "value_rs", "src_row"]
    df = _df(recs, cols)
    _date_quality("issues", methods, q)
    total = len(df)
    nojc = int((~df["has_job_card"]).sum()) if total else 0
    q.add("issues", "issue_lines_total", total)
    q.add("issues", "issue_lines_without_job_card", nojc)
    q.add("issues", "issue_lines_without_job_card_pct", round(100 * nojc / total, 1) if total else 0.0)
    if total:
        g = df.groupby("erp_group")["has_job_card"].agg(lambda s: round(100 * (1 - s.mean()), 1))
        q.add("issues", "pct_without_job_card_by_erp_group", "",
              "; ".join(f"{k}={v}%" for k, v in g.sort_index().items()))
        q.add("issues", "value_without_job_card_rs", round(float(df.loc[~df["has_job_card"], "value_rs"].sum()), 2))
        q.add("issues", "value_total_rs", round(float(df["value_rs"].sum()), 2))
        q.add("issues", "doc_date_min", str(df["doc_date"].min()))
        q.add("issues", "doc_date_max", str(df["doc_date"].max()))
        q.add("issues", "lines_with_returns", int((df["returned_qty"].fillna(0) != 0).sum()))
    q.add("issues", "job_cards_not_in_ppic", int((df["job_card_in_ppic"] == False).sum()))  # noqa: E712
    q.add("issues", "unknown_item_lines", unknown_lines)
    q.add("issues", "unknown_items_distinct", len(unknown_items))
    q.add("issues", "uom_problem_lines", uom_bad)
    q.add("issues", "lines_item_without_rate", no_rate)
    return df


def _read_simple_lists(path: Path, sheet: str, spec: dict[int, str], max_row: int = 304) -> list[tuple]:
    wb = _open(path)
    try:
        ws = wb[sheet]
        out = []
        for r in ws.iter_rows(min_row=FIRST_DATA_ROW, max_row=max_row, max_col=max(spec) + 1, values_only=True):
            r = tuple(r) + (None,) * (max(spec) + 1 - len(r))
            for c, name in spec.items():
                v = _clean(r[c])
                if v is not None and not _is_demo([v]):
                    out.append((name, v))
        return out
    finally:
        wb.close()


def _read_machines(ppic: Path, production: Path, design: Path) -> tuple[pd.DataFrame, list, list]:
    wb = _open(ppic)
    try:
        names = []
        for r in wb["Dropdown Lists"].iter_rows(min_row=FIRST_DATA_ROW, max_row=304, max_col=3, values_only=True):
            if len(r) > 2 and _clean(r[2]):
                names.append(_clean(r[2]))
    finally:
        wb.close()
    presses = {_key(v) for k, v in _read_simple_lists(design, "Lists", {4: "press"})}
    speeds, settings = {}, []
    wb = _open(production)
    try:
        for r in wb["OEE"].iter_rows(min_row=6, max_row=30, max_col=3, values_only=True):
            if len(r) > 2 and _clean(r[1]) and _num(r[2]) is not None:
                speeds[_key(r[1])] = _num(r[2])
        for i, r in enumerate(wb["Lists"].iter_rows(min_row=1, max_row=3, max_col=11, values_only=True), 1):
            if i == 2 and len(r) > 10 and _num(r[10]) is not None:
                settings.append(("ink_gsm_per_colour", _num(r[10]), "03 Production > Lists"))
        for i, r in enumerate(wb["Anilox List"].iter_rows(min_row=1, max_row=3, max_col=17, values_only=True), 1):
            if len(r) > 16 and _num(r[16]) is not None:
                settings.append(("anilox_transfer" if i == 2 else "ink_specific_gravity", _num(r[16]),
                                 "03 Production > Anilox List"))
    finally:
        wb.close()
    recs = []
    for i, n in enumerate(names, 1):
        is_press = _key(n) in presses
        recs.append({"name": n, "machine_type": "press" if is_press else "offline",
                     "rated_speed_m_min": speeds.get(_key(n)), "sort_order": i})
    return pd.DataFrame(recs, columns=["name", "machine_type", "rated_speed_m_min", "sort_order"]), settings, \
        [("machine", n) for n in names]


def _lists_frame(items: list[tuple]) -> pd.DataFrame:
    seen, recs, order = set(), [], {}
    for name, v in items:
        val = v.date().isoformat() if isinstance(v, datetime) else v
        k = (name, _key(val))
        if k in seen:
            continue
        seen.add(k)
        order[name] = order.get(name, 0) + 1
        recs.append({"list_name": name, "value": val, "sort_order": order[name]})
    return pd.DataFrame(recs, columns=["list_name", "value", "sort_order"])


# --------------------------------------------------------------------------- main entry
def extract_all(raw_dir: str | Path) -> dict[str, Any]:
    """Extract every real frame from ``raw_dir`` (expects ``System/``, ``Review/``)."""
    raw = Path(raw_dir)
    sysd = raw / "System"
    q = Quality()
    frames: dict[str, Any] = {}
    lists: list[tuple] = []
    settings: list[tuple] = []

    acc = _read_accounts(_find(sysd, "06 *.xlsx"), q)
    lists += acc.pop("_lists")
    settings += acc.pop("_settings")
    frames.update(acc)

    st = _read_store_system(_find(sysd, "02 *.xlsx"), q)
    lists += st.pop("_lists")
    settings += st.pop("_settings")
    frames.update(st)

    frames.update(_read_review(_find(raw, REVIEW_GLOB), frames["items"], q))

    machines, msettings, _ = _read_machines(_find(sysd, "01 *.xlsx"), _find(sysd, "03 *.xlsx"),
                                            _find(sysd, "07 *.xlsx"))
    frames["machines"] = machines
    settings += msettings
    q.add("machines", "machines", len(machines), f"presses={int((machines['machine_type'] == 'press').sum())}")

    lists += _read_simple_lists(_find(sysd, "01 *.xlsx"), "Dropdown Lists", {
        1: "division", 3: "job_status", 4: "paper_type", 5: "paper_width_mm", 6: "foil_type", 7: "foil",
        8: "foil_size_mm", 9: "lamination", 10: "screen", 11: "ppic_status", 12: "design_remark",
        13: "qc_remark", 14: "plate_vendor", 16: "job_type"})
    lists += _read_simple_lists(_find(sysd, "03 *.xlsx"), "Lists", {3: "shift", 4: "operator", 6: "downtime_reason"})
    lists += _read_simple_lists(_find(sysd, "04 *.xlsx"), "Lists", {0: "defect_type", 1: "qc_decision",
                                                                    2: "qc_inspector"})
    lists += _read_simple_lists(_find(sysd, "05 *.xlsx"), "Lists", {0: "transporter"})
    lists += _read_simple_lists(_find(sysd, "07 *.xlsx"), "Lists", {
        0: "design_status", 1: "designer", 2: "barcode_verified", 3: "die_option", 4: "press", 5: "colour",
        8: "plate_status", 11: "die_type", 12: "die_condition"})
    wb = _open(_find(sysd, "07 *.xlsx"))
    try:
        r2 = next(wb["Lists"].iter_rows(min_row=2, max_row=2, max_col=10, values_only=True))
        if len(r2) > 9 and _num(r2[9]) is not None:
            settings.append(("design_approval_days", _num(r2[9]), "07 Design > Lists"))
    finally:
        wb.close()
    frames["lists"] = _lists_frame(lists)
    frames["settings"] = pd.DataFrame(
        [{"key": k, "value": (v.isoformat() if isinstance(v, (date, datetime)) else v), "source": s}
         for k, v, s in settings], columns=["key", "value", "source"])
    q.add("lists", "list_names", int(frames["lists"]["list_name"].nunique()))

    # cross-file checks
    vk = set(frames["vendors"]["name"].map(_key))
    g = frames["grns"]
    q.add("grns", "suppliers_not_in_vendor_register", int(len(set(g["supplier_name"].map(_key)) - vk)))
    sf = next((v for k, v, _ in settings if k == "stock_from"), None)
    if sf is not None and len(g):
        q.add("grns", "grn_lines_after_stock_from", int((pd.to_datetime(g["grn_date"]) >= pd.Timestamp(sf)).sum()),
              f"stock_from={sf}")
        q.add("grns", "grn_lines_excel_value_after_stock_from_before_fix",
              int((pd.to_datetime(g["grn_date_excel"]) >= pd.Timestamp(sf)).sum()),
              "would wrongly count as receipts without the date fix")
    frames["quality"] = q.frame()
    return frames


def _summary(frames: dict[str, Any]) -> str:
    lines = [f"{'frame':<18}{'rows':>8}  cols"]
    for k, v in frames.items():
        if k == "quality":
            continue
        lines.append(f"{k:<18}{len(v):>8}  {len(v.columns)}")
    lines.append("")
    lines.append("quality:")
    for r in frames["quality"].itertuples():
        det = f"  ({r.detail})" if r.detail else ""
        lines.append(f"  {r.area:<16}{r.metric:<52}{r.value!s:>14}{det}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract the client's Excel data into CSV frames")
    ap.add_argument("--raw", default="data/raw", help="folder with System/, Review/, docs/")
    ap.add_argument("--out", default="data/extract", help="output folder for <frame>.csv (git-ignored)")
    a = ap.parse_args(argv)
    t0 = time.time()
    frames = extract_all(a.raw)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in frames.items():
        df.to_csv(out / f"{name}.csv", index=False, encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    print(_summary(frames))
    print(f"\nwrote {len(frames)} files to {out} in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
