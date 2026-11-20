"""Job 360: one job from enquiry to profit (SPEC 3, ``Job360`` in contract/openapi.yaml).

Every block reuses the owning service's serializer (jobs, marketing, design, store,
production, qc, dispatch, clients) so Job 360 shows exactly what each screen shows; the
cost block is ``services.profit``. Rule checks go through ``core.rules``.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import T
from app.services import design as design_svc
from app.services import dispatch as dispatch_svc
from app.services import jobs as jobs_svc
from app.services import marketing as mkt
from app.services import production as prod
from app.services import qc as qc_svc
from app.services import store as store_svc
from app.services.clients import invoice_dicts
from app.services.profit import jobs_profit
from core.rules import production as P
from core.rules.errors import ratio

STAGES = ("enquiry", "quote", "po", "design", "plates", "store", "production", "qc", "dispatch", "invoice",
          "receipt")
_RANK = {s: i for i, s in enumerate(STAGES)}


# ---------------------------------------------------------------- text helpers

def num(v: Any, places: int = 0) -> str:
    """Indian digit grouping (1,50,000; 1,058.33)."""
    v = float(v or 0)
    neg = v < 0
    s = f"{abs(v):.{places}f}"
    whole, _, frac = s.partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    out = ",".join([*groups, tail])
    frac = frac.rstrip("0")
    if frac:
        out += "." + frac
    return ("-" if neg else "") + out


def rs(v: Any) -> str:
    return f"Rs {num(v, 2)}"


def pct(v: Any) -> str:
    return f"{float(v or 0) * 100:.1f}%"


def day_label(iso: str | None) -> str:
    return date.fromisoformat(iso).strftime("%d-%b") if iso else ""


def _d(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (date, datetime)):
        return (v.date() if isinstance(v, datetime) else v).isoformat()
    return str(v)[:10]


# ---------------------------------------------------------------- blocks

def _quote(db: Session, job: dict) -> dict | None:
    q = T("quotes")
    stmt = None
    if job.get("quote_id"):
        stmt = select(q).where(q.c.id == job["quote_id"])
    elif job.get("enquiry_id"):
        stmt = select(q).where(q.c.enquiry_id == job["enquiry_id"]).order_by(q.c.date.desc(), q.c.id.desc())
    row = db.execute(stmt).first() if stmt is not None else None
    return mkt.quote_json(row) if row is not None else None


def _receipts(db: Session, invoice_ids: list[str]) -> list[dict]:
    if not invoice_ids:
        return []
    r = T("receipts")
    rows = db.execute(select(r.c.id, r.c.date, r.c.invoice_id, r.c.amount, r.c.mode)
                      .where(r.c.invoice_id.in_(invoice_ids)).order_by(r.c.date, r.c.id)).all()
    return [{"id": x.id, "date": _d(x.date), "invoice_id": x.invoice_id, "amount": float(x.amount or 0),
             "mode": x.mode or ""} for x in rows]


def checks(job: dict, runs: list[dict], qc: list[dict], tol: dict) -> list[dict]:
    """The SPEC 2 rule checks for one job (``RuleCheck``), each through ``core.rules``."""
    out = []
    press = [r for r in runs if r["machine_type"] == P.PRESS and r["used_m"] is not None]
    req = float(job["required_m"] or 0)
    used = sum(float(r["used_m"]) for r in press)
    wtol = float(tol["wastage_tol"])
    if press and req > 0:
        w = P.wastage(used, req)
        out.append({"rule": "wastage_tol", "label": f"Wastage % <= {wtol * 100:.0f}%", "value": w.pct,
                    "limit": wtol, "ok": not P.wastage_flag(used, req, wtol),
                    "detail": f"{num(w.metres, 2)} m over {num(req, 2)} m required"})
    else:
        out.append({"rule": "wastage_tol", "label": f"Wastage % <= {wtol * 100:.0f}%", "value": 0.0,
                    "limit": wtol, "ok": True, "detail": "No ended press run yet"})

    mtol = float(tol["material_tol"])
    planned, issued = float(job["planned_m"] or 0), float(job["issued_m"] or 0)
    var = float(ratio(issued - planned, planned)) if planned else 0.0
    mok = issued == 0 or not P.material_flag(issued, planned, mtol)
    out.append({"rule": "material_tol", "label": f"Issued vs planned within {mtol * 100:.0f}%",
                "value": round(var, 4), "limit": mtol, "ok": mok,
                "detail": f"Issued {num(issued, 2)} m vs planned {num(planned, 2)} m" if issued
                else "Nothing issued yet"})

    otol = float(tol["overprod_tol"])
    limit = float(job["order_qty"]) * (1 + otol)
    out.append({"rule": "overprod_tol", "label": f"Printed <= order + {otol * 100:.0f}%",
                "value": float(job["printed_qty"]), "limit": round(limit, 2),
                "ok": not P.overprod_flag(job["printed_qty"], job["order_qty"], otol),
                "detail": f"{num(job['printed_qty'])} printed for {num(job['order_qty'])} ordered"})

    chk = sum(q["checked"] for q in qc)
    apr = sum(q["approved"] for q in qc)
    rej = sum(q["rejected"] for q in qc)
    out.append({"rule": "qc_balance", "label": "Approved + rejected = checked", "value": float(apr + rej),
                "limit": float(chk), "ok": apr + rej == chk,
                "detail": f"{num(apr)} + {num(rej)} = {num(apr + rej)}" if qc else "No QC entry yet"})

    disp, appr = job["dispatched_qty"], job["qc_approved"]
    out.append({"rule": "dispatch_le_qc", "label": "Dispatched <= QC approved", "value": float(disp),
                "limit": float(appr), "ok": disp <= appr,
                "detail": f"{num(appr - disp)} approved labels left in stock" if disp <= appr
                else f"{num(disp - appr)} dispatched above QC approved"})
    return out


def timeline(job: dict, enquiry: dict | None, quote: dict | None, design: dict | None, plates: list[dict],
             issues: list[dict], runs: list[dict], qc: list[dict], dispatches: list[dict], invoices: list[dict],
             receipts: list[dict]) -> list[dict]:
    """Ordered ``TimelineEvent`` list: by date, then by stage order within a day."""
    ev: list[dict] = []

    def add(d: Any, stage: str, text: str, ref: str | None, link: str | None) -> None:
        iso = _d(d)
        if iso:
            ev.append({"date": iso, "stage": stage, "text": text, "ref": ref, "link": link})

    jc = job["job_card"]
    if enquiry:
        add(enquiry["date"], "enquiry", f"Enquiry on {enquiry['source']}: {num(enquiry['qty'])} "
            f"{enquiry['product'] or 'labels'}", enquiry["id"], "/marketing")
    if quote:
        add(quote["date"], "quote", f"Quote Rs {quote['rate']:.2f}/label = {rs(quote['value'])} "
            f"(est. margin {pct(quote['margin_pct'])})", quote["id"], "/marketing")
    if job.get("po_no") or job.get("po_date"):
        add(job["po_date"] or job["created_on"], "po", f"PO {job['po_no']} received", None, None)
    add(job["created_on"], "po", f"Job card {jc} created on {job['machine_name'] or job['machine_id']}", jc,
        f"/jobs/{jc}")
    if design:
        v = design.get("artwork_version") or 1
        if design.get("proof_sent_on"):
            add(design["proof_sent_on"], "design", f"Proof sent to client (v{v})", None, "/design")
        if design.get("approved_on"):
            who = f" by {design['approved_by']}" if design.get("approved_by") else ""
            add(design["approved_on"], "design", f"Proof approved{who} (v{v})", None, "/design")
    by_day: dict[str, list[dict]] = {}
    for p in plates:
        if p.get("made_on"):
            by_day.setdefault(p["made_on"], []).append(p)
    for d, ps in by_day.items():
        ids = sorted(p["id"] for p in ps)
        span = ids[0] if len(ids) == 1 else f"{ids[0]}..{ids[-1]}"
        add(d, "plates", f"{len(ps)} plate{'s' if len(ps) > 1 else ''} made {span} "
            f"({rs(sum(p['cost'] for p in ps))})", None, "/design?tab=plates")
    for i in issues:
        roll = f" from {i['roll_id']}" if i.get("roll_id") else ""
        add(i["date"], "store", f"Issued {num(i['qty'], 2)} {i['uom']} {i['item_name']}{roll}", i["id"], "/store")
    for r in sorted(runs, key=lambda x: (x["start"], x["id"])):
        if r["status"] == "running":
            text = f"Running on {r['machine_name']}: {num(r['printed_qty'])} so far"
        elif r["machine_type"] == P.PRESS:
            text = f"Printed {num(r['printed_qty'])} on {r['machine_name']} in {num(r['hours'], 2)} h"
            if r["wastage_m"] is not None:
                text += f"; wastage {num(r['wastage_m'], 2)} m ({pct(r['wastage_pct'])})"
        else:
            text = f"{r['machine_name']}: {num(r['printed_qty'])} in {num(r['hours'], 2)} h"
        add(r["start"], "production", text, r["id"], "/production")
    for q in qc:
        add(q["date"], "qc", f"QC ({q['decision']}): {num(q['checked'])} checked, {num(q['approved'])} approved, "
            f"{num(q['rejected'])} rejected", q["id"], "/qc")
    for d in dispatches:
        add(d["date"], "dispatch", f"Challan {d['id']}: {num(d['qty'])} labels, freight {rs(d['freight'])}",
            d["id"], "/dispatch")
    for i in invoices:
        kind = "Draft invoice" if i["status"] == "draft" else "Invoice"
        add(i["date"], "invoice", f"{kind} {i['id']} {rs(i['total'])} (taxable {num(i['taxable'], 2)} + GST "
            f"{num(i['gst'], 2)}), due {day_label(i['due_date'])}", i["id"], "/money?tab=invoices")
    for r in receipts:
        add(r["date"], "receipt", f"Received {rs(r['amount'])} against {r['invoice_id']}", r["id"],
            "/money?tab=debtors")
    ev.sort(key=lambda e: (e["date"], _RANK[e["stage"]]))
    return ev


def job_360(db: Session, job_card: str) -> dict | None:
    """The contract ``Job360`` for one job card, or None when it does not exist."""
    job = jobs_svc.get_job(db, job_card)
    if job is None:
        return None
    tol = jobs_svc.tolerances(db)
    enquiry = mkt.get_enquiry(db, job["enquiry_id"]) if job.get("enquiry_id") else None
    quote = _quote(db, job)
    design = design_svc.get_design(db, job_card)
    design_rows = T("design")
    has_design = db.execute(select(design_rows.c.job_card).where(design_rows.c.job_card == job_card)).first()
    plates = [p for p in design_svc.list_plates(db) if p["job_card"] == job_card]
    die = None
    if design.get("die_id"):
        die = next((d for d in design_svc.list_dies(db) if d["id"] == design["die_id"]), None)
    issues = store_svc.list_issues(db, job_card=job_card)
    roll_ids = {i["roll_id"] for i in issues if i.get("roll_id")}
    rolls = [r for r in store_svc.list_rolls(db) if r["id"] in roll_ids] if roll_ids else []
    runs = sorted(prod.list_runs(db, job_card=job_card), key=lambda r: (r["start"], r["id"]))
    qc = qc_svc.list_qc(db, job_card=job_card)
    dispatches = dispatch_svc.list_dispatches(db, job_card=job_card)
    invoices = [i for i in invoice_dicts(db, [job["client_id"]]) if i["job_card"] == job_card]
    receipts = _receipts(db, [i["id"] for i in invoices])
    cost = jobs_profit(db, [job_card], runs=runs).get(job_card)
    return {
        "job": job,
        "enquiry": enquiry,
        "quote": quote,
        "design": design,
        "plates": plates,
        "die": die,
        "issues": issues,
        "rolls": rolls,
        "runs": runs,
        "qc": qc,
        "dispatches": dispatches,
        "invoices": invoices,
        "cost": cost,
        "timeline": timeline(job, enquiry, quote, design if has_design else None, plates, issues, runs, qc,
                             dispatches, invoices, receipts),
        "checks": checks(job, runs, qc, tol),
    }
