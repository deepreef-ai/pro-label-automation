"""LOCKED test 5: the demo story end to end, through HTTP only (SPEC 2 and 3).

1. A NEW job (not JC-1301) walks enquiry -> quote -> won -> job -> design -> GRN ->
   issue -> run -> QC -> dispatch -> invoice, each step done by its department's role,
   with the guards (issue needs a job card, dispatch <= QC approved) and the maths
   (metres, wastage, GST, profit via ``core.rules``) checked on the way, then Job 360
   shows every step in order.
2. Client lock: due + grace is not locked, due + grace + 1 is; only the owner can
   release, and the release is logged.

Each test runs on its own freshly built synthetic DB (``fresh_api``).
"""
from datetime import date, datetime, timedelta

import pytest

from core.rules.money import admin_share, invoice_amounts, job_profit
from core.rules.production import planned_metres, required_metres, ups, wastage

pytestmark = pytest.mark.integration

ORDER_QTY = 50_000
RATE = 0.60
UPS_ACROSS, UPS_ALONG = 4, 3
REPEAT_MM = 254.0
PAPER = "IT-0101"  # PP White 250 mm (rate 38.00 per sq m)
GALLUS = "M-01"  # Gallus EM 280, a press
UNITS = ["Cyan", "Magenta", "Yellow", "Black", "Gloss varnish"]
ISSUE_M = 1150.0
PRINTED = 52_000
RUN_HOURS = 3.5
CHECKED, APPROVED, REJECTED = 52_000, 50_900, 1_100
DISPATCH_QTY = 50_000
STORY_STAGES = ["enquiry", "quote", "po", "design", "store", "production", "qc", "dispatch", "invoice"]
COST_LINES = ["material", "plates", "ink", "salaries", "freight", "admin_share", "direct_overhead"]


def ok(response, *codes):
    codes = codes or (200, 201)
    assert response.status_code in codes, f"{response.request.method} {response.request.url}: " \
        f"{response.status_code} {response.text}"
    return response.json()


def iso(d: date) -> str:
    return d.isoformat()


def test_new_job_full_story(fresh_api):
    api = fresh_api

    # ---- Marketing: enquiry -> quote -> won ------------------------------------------------
    enquiry = ok(api.post("/api/enquiries", role="marketing", json={
        "client_id": "CL-001",
        "client_name": "Fresh Juice Co.",
        "product": "Guava juice 200 ml bottle label",
        "label_size": "60 x 80 mm",
        "qty": ORDER_QTY,
        "material": "PP White",
        "colours": 4,
        "finish": "Gloss varnish",
        "source": "whatsapp",
        "assigned_to": "Rohit Mehra",
    }), 201)
    enq_id = enquiry["id"]
    assert enq_id.startswith("ENQ-") and enq_id != "ENQ-0045"
    assert enquiry["status"] == "new"
    today = date.fromisoformat(enquiry["date"])

    quote = ok(api.post(f"/api/enquiries/{enq_id}/quote", role="marketing", json={
        "rate": RATE, "qty": ORDER_QTY, "valid_until": iso(today + timedelta(days=15)),
    }), 201)
    assert quote["enquiry_id"] == enq_id
    assert quote["value"] == pytest.approx(30_000.00)

    won = ok(api.post(f"/api/enquiries/{enq_id}/status", role="marketing",
                      json={"status": "won", "po_no": "FJ/2026/131"}), 200)
    assert won["status"] == "won"

    # ---- PPIC: job card --------------------------------------------------------------------------
    job = ok(api.post("/api/jobs", role="ppic", json={
        "client_id": "CL-001",
        "po_no": "FJ/2026/131",
        "po_date": iso(today),
        "product": "Guava juice 200 ml bottle label",
        "label_size": "60 x 80 mm",
        "order_qty": ORDER_QTY,
        "rate": RATE,
        "item_id": PAPER,
        "machine_id": GALLUS,
        "ups_across": UPS_ACROSS,
        "ups_along": UPS_ALONG,
        "repeat_mm": REPEAT_MM,
        "units": UNITS,
        "due_date": iso(today + timedelta(days=10)),
        "enquiry_id": enq_id,
        "priority": "normal",
    }), 201)
    jc = job["job_card"]
    assert jc.startswith("JC-") and jc != "JC-1301"
    total_ups = ups(UPS_ACROSS, UPS_ALONG)
    req_m = required_metres(ORDER_QTY, total_ups, REPEAT_MM)
    assert job["ups"] == total_ups == 12
    assert job["po_value"] == pytest.approx(30_000.00)
    assert job["required_m"] == pytest.approx(req_m, abs=0.01)
    assert job["required_m"] == pytest.approx(1058.33, abs=0.01)
    assert job["planned_m"] == pytest.approx(planned_metres(ORDER_QTY, total_ups, REPEAT_MM), abs=0.01)

    # ---- Design: Gallus route, 5 units -------------------------------------------------------
    design = ok(api.put(f"/api/design/{jc}", role="design", json={
        "stage": "approved",
        "designer": "Kavya Nair",
        "artwork_version": 1,
        "proof_sent_on": iso(today),
        "approved_on": iso(today),
        "approved_by": "Anil Deshmukh (client)",
        "units": [{"unit": i + 1, "colour": c, "anilox_lpi": 800, "plate_id": None} for i, c in enumerate(UNITS)],
        "route": ["Print Gallus EM 280", "Inspection RW-1", "Slitting / rewinding", "Pack"],
    }), 200)
    assert design["job_card"] == jc
    assert design["stage"] == "approved"
    assert len(design["units"]) == 5

    # ---- Store: GRN for the paper, then issue ----------------------------------------------------
    grn = ok(api.post("/api/store/grns", role="store", json={
        "date": iso(today), "vendor_id": "VN-001", "bill_no": "SGF/7781", "item_id": PAPER,
        "qty": 1200.0, "rate": 38.0, "roll_lengths_m": [1200.0],
    }), 201)
    assert grn["id"].startswith("GRN-")
    assert grn["rate_flag"] is False
    roll_id = grn["roll_ids"][0]

    issue_body = {"date": iso(today), "item_id": PAPER, "qty": ISSUE_M, "roll_id": roll_id,
                  "issued_to": "Gallus EM 280"}
    r = api.post("/api/store/issues", role="store", json=issue_body)  # no job card
    assert r.status_code == 400, r.text
    r = api.post("/api/store/issues", role="store", json={**issue_body, "job_card": "JC-9999"})
    assert r.status_code == 400, r.text
    issue = ok(api.post("/api/store/issues", role="store", json={**issue_body, "job_card": jc}))
    assert issue["job_card"] == jc
    assert issue["qty"] == pytest.approx(ISSUE_M)

    # ---- Production: run on the Gallus -------------------------------------------------------------
    run = ok(api.post("/api/production/runs/start", role="production", json={
        "job_card": jc, "machine_id": GALLUS, "operator": "Mahesh Shinde", "shift": "day",
    }), 201)
    assert run["status"] == "running"
    end = datetime.fromisoformat(run["start"]) + timedelta(hours=RUN_HOURS)
    run = ok(api.post(f"/api/production/runs/{run['id']}/end", role="production", json={
        "printed_qty": PRINTED, "used_m": ISSUE_M, "end": end.isoformat(),
    }), 200)
    w = wastage(ISSUE_M, req_m)
    assert run["status"] == "ended"
    assert run["machine_type"] == "press"
    assert run["hours"] == pytest.approx(RUN_HOURS)
    assert w.metres == pytest.approx(91.67, abs=0.01)
    assert run["wastage_m"] == pytest.approx(w.metres, abs=0.01)
    assert run["wastage_pct"] == pytest.approx(w.pct, abs=0.0001)
    assert run["wastage_flag"] is False
    assert run["overprod_flag"] is False
    assert run["crew_cost"] == pytest.approx(RUN_HOURS * run["hour_rate"], abs=0.01)

    # ---- QC -------------------------------------------------------------------------------------
    qc = ok(api.post("/api/qc", role="qc", json={
        "date": iso(today), "job_card": jc, "run_id": run["id"], "checked": CHECKED,
        "approved": APPROVED, "rejected": REJECTED, "decision": "Approved", "inspector": "Sneha Joshi",
    }), 201)
    assert (qc["checked"], qc["approved"], qc["rejected"]) == (CHECKED, APPROVED, REJECTED)
    assert qc["counts_as_approved"] is True

    # ---- Dispatch: above QC approved is refused, then the real challan -------------------------
    dispatch_body = {"date": iso(today), "job_card": jc, "boxes": 10, "vehicle_no": "MH12 AB 4521",
                     "transporter": "Metro Freight Carriers", "freight": 600.0, "lr_no": "MFC/55501"}
    r = api.post("/api/dispatch", role="dispatch", json={**dispatch_body, "qty": 51_000})
    assert r.status_code == 409, r.text
    dispatch = ok(api.post("/api/dispatch", role="dispatch", json={**dispatch_body, "qty": DISPATCH_QTY}), 201)
    assert dispatch["id"].startswith("DC-")
    assert dispatch["qty"] == DISPATCH_QTY

    # ---- Money: draft invoice from the challan -------------------------------------------------
    invoice = ok(api.post(f"/api/invoices/draft-from-dispatch/{dispatch['id']}", role="accounts"), 201)
    amounts = invoice_amounts(DISPATCH_QTY, RATE)
    assert invoice["job_card"] == jc
    assert invoice["dispatch_id"] == dispatch["id"]
    assert invoice["status"] == "draft"
    assert float(amounts.taxable) == pytest.approx(30_000.00)
    assert invoice["taxable"] == pytest.approx(float(amounts.taxable))
    assert float(amounts.gst) == pytest.approx(5_400.00)
    assert invoice["gst"] == pytest.approx(float(amounts.gst))
    assert float(amounts.total) == pytest.approx(35_400.00)
    assert invoice["total"] == pytest.approx(float(amounts.total))
    r = api.post(f"/api/invoices/draft-from-dispatch/{dispatch['id']}", role="accounts")
    assert r.status_code == 409, "a challan is invoiced only once"

    # ---- Job 360 -------------------------------------------------------------------------------
    j360 = ok(api.get(f"/api/jobs/{jc}/360", role="ppic"), 200)
    assert j360["job"]["job_card"] == jc
    assert j360["enquiry"]["id"] == enq_id
    assert j360["quote"]["id"] == quote["id"]
    assert j360["design"]["job_card"] == jc
    assert [i["id"] for i in j360["issues"]] == [issue["id"]]
    assert [x["id"] for x in j360["runs"]] == [run["id"]]
    assert [x["id"] for x in j360["qc"]] == [qc["id"]]
    assert [x["id"] for x in j360["dispatches"]] == [dispatch["id"]]  # the refused 51,000 left no row
    assert [x["id"] for x in j360["invoices"]] == [invoice["id"]]

    j = j360["job"]
    assert j["issued_m"] == pytest.approx(ISSUE_M)
    assert j["printed_qty"] == PRINTED
    assert j["qc_approved"] == APPROVED
    assert j["dispatched_qty"] == DISPATCH_QTY
    assert j["invoiced_qty"] == DISPATCH_QTY

    stages = [e["stage"] for e in j360["timeline"]]
    missing = [s for s in STORY_STAGES if s not in stages]
    assert not missing, f"timeline lacks {missing}: {stages}"
    first = [stages.index(s) for s in STORY_STAGES]
    assert first == sorted(first), f"timeline out of order: {stages}"
    dates = [e["date"] for e in j360["timeline"]]
    assert dates == sorted(dates)

    cost = j360["cost"]
    assert cost["revenue_basis"] == "invoiced"
    assert cost["revenue"] == pytest.approx(30_000.00)
    assert cost["material"] == pytest.approx(issue["value"], abs=0.01)
    assert cost["salaries"] == pytest.approx(run["crew_cost"], abs=0.01)
    assert cost["freight"] == pytest.approx(600.00)
    assert cost["admin_share"] == pytest.approx(float(admin_share(30_000)), abs=0.01)
    expected = job_profit(cost["revenue"], **{k: cost[k] for k in COST_LINES})
    assert cost["profit"] == pytest.approx(float(expected.profit), abs=0.01)
    assert cost["profit"] == pytest.approx(30_000.00 - sum(cost[k] for k in COST_LINES), abs=0.01)
    assert cost["margin_pct"] == pytest.approx(float(expected.margin), abs=0.0001)


def test_client_lock_boundary_and_owner_release(fresh_api):
    api = fresh_api
    debtors = ok(api.get("/api/debtors", role="accounts"), 200)
    as_of = date.fromisoformat(debtors["as_of"])
    assert debtors["grace_days"] == 15

    # Story client CL-011 is LOCKED: an unpaid invoice is more than 15 days past due.
    cl011 = ok(api.get("/api/clients/CL-011"), 200)
    assert cl011["client"]["lock_status"] == "locked"
    assert max(i["days_past_due"] for i in cl011["invoices"] if i["outstanding"] > 0) >= 16

    # Boundary on a real unpaid invoice: an at-risk client whose oldest invoice is d days past due.
    # With grace = d the invoice sits on day due+grace (not locked); with grace = d-1 on
    # day due+grace+1 (locked). Under the default grace 15 this is day 15 vs day 16.
    at_risk = [c for c in debtors["clients"] if c["lock_status"] == "at_risk" and c["max_days_past_due"] >= 1]
    assert at_risk, "the synthetic story has clients at risk of lock"
    client = max(at_risk, key=lambda c: c["max_days_past_due"])
    cid, d = client["client_id"], client["max_days_past_due"]
    assert d <= 15

    def lock_of(client_id):
        return ok(api.get(f"/api/clients/{client_id}", role="accounts"), 200)["client"]

    try:
        ok(api.put("/api/settings", json={"grace_days": d}), 200)
        c = lock_of(cid)
        assert c["lock_status"] != "locked", f"day due+{d} with grace {d} must not lock"
        assert c["locks_on"] == iso(as_of + timedelta(days=1))

        ok(api.put("/api/settings", json={"grace_days": d - 1}), 200)
        c = lock_of(cid)
        assert c["lock_status"] == "locked", f"day due+{d} with grace {d - 1} must lock"
        assert c["locked_since"] == iso(as_of)
    finally:
        ok(api.put("/api/settings", json={"grace_days": 15}), 200)
    assert lock_of(cid)["lock_status"] == "at_risk"

    # Only the owner may release a lock.
    reason = "Rs 1,00,000 RTGS confirmed by bank; balance by 30-Nov"
    r = api.post("/api/clients/CL-011/release-lock", role="store", json={"reason": reason})
    assert r.status_code == 403, r.text
    assert lock_of("CL-011")["lock_status"] == "locked"

    released = ok(api.post("/api/clients/CL-011/release-lock", role="owner", json={"reason": reason}), 200)
    assert released["client_id"] == "CL-011"
    assert released["lock_status"] == "ok"
    assert released["released_by"] == "owner"
    assert released["reason"] == reason
    assert released["audit_id"]
    datetime.fromisoformat(released["released_at"])

    detail = ok(api.get("/api/clients/CL-011"), 200)
    assert detail["client"]["lock_status"] == "ok"
    last = detail["lock_log"][-1]
    assert (last["event"], last["by"], last["reason"]) == ("released", "owner", reason)

    r = api.post("/api/clients/CL-011/release-lock", role="owner", json={"reason": reason})
    assert r.status_code == 409, "releasing a client that is not locked"
