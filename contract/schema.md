# Database schema (demo v0.1)

SQLAlchemy 2.x models in `apps/api/core`. SQLite now, Postgres later, so use portable types only:

| Type here | SQLAlchemy | Notes |
|---|---|---|
| `id` | `String` PK | Business IDs from SPEC section 1 (`JC-####`, `GRN-#####` ...). Permanent, never row-based. |
| `text` | `String` / `Text` | |
| `int` | `Integer` | Quantities in labels, minutes, days |
| `num` | `Numeric(14,2)` | Rupees. Serialise as JSON numbers with 2 decimals |
| `qty` | `Numeric(14,3)` | Metres, kg, sq m |
| `frac` | `Numeric(7,4)` | Fractions 0..1 (0.0866 = 8.66%) |
| `date` / `ts` | `Date` / `DateTime(timezone=True)` | ISO on the wire. ERP text dates are parsed **day first** |
| `bool` | `Boolean` | |
| `json` | `JSON` | Small nested lists only (evidence, payloads) |

Common columns (not repeated below):

- `is_demo bool not null default false` on every table marked **[demo]**. Generated rows are `true`; rows imported from client files are `false`. The API returns it and the UI shows a DEMO badge.
- `created_at ts`, `updated_at ts` on every table.

Derived numbers such as stock, required metres, wastage, QC approved, outstanding, lock status, ageing and profit are **computed by `core.rules`**. They are not stored, except where a column below says "snapshot".

---

## Masters

### clients [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `CL-###` | Client code |
| name | text | Company name (synthetic in fixtures) |
| gstin | text | GST number |
| city, state | text | |
| contact, phone, email | text | Accounts contact |
| credit_days | int | Default 30. Due date = invoice date + credit_days |
| credit_limit | num | |
| active | bool | |

Lock status is computed, not stored (see `audit_log` for releases). `lock_override_until date null` holds the date until which an owner release stays valid.

### vendors [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `VN-###` | |
| name, city | text | |
| msme | bool | If true, due = bill date + min(credit_days, `msme_days`) |
| credit_days | int | |
| supplies | text | Free text |

### items [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `IT-####` | ERP item |
| name | text | e.g. "PP White 250 mm" |
| group | text | Paper & Film, Ink, Varnish, Foil, Lamination |
| stock_head_id | FK stock_heads.id | Head used in the stock statement |
| width_mm | int null | Paper/film/foil width |
| uom | text | m, kg, sqm, nos |
| rate | num | Master rate, used for issue value and the GRN rate check |
| rate_unit | text | per_sqm, per_kg, per_m, per_nos |
| min_stock | qty | Below this = `low` |
| vendor_id | FK vendors.id null | Usual supplier |

### stock_heads [demo]
| Column | Type | Meaning |
|---|---|---|
| id | text | e.g. `PP-WHITE` |
| name | text | "PP White" |
| group | text | |
| ppic_paper | text null | Paper name as PPIC writes it, used for the material summary |

### opening_stock [demo]
| Column | Type | Meaning |
|---|---|---|
| id | int PK | |
| item_id | FK items.id | |
| as_of | date | = settings.stock_from |
| qty | qty | In the item UOM (metres for paper) |
| rate | num | Opening rate |
| physical_count | qty null | Last physical count |

Stock = opening (as of `stock_from`) + sum(grns.qty) - sum(issues.qty), counting only rows dated on or after `stock_from`.

### machines [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `M-##` | |
| name | text | Gallus EM 280, Hontec CI, Focus, Taiyo 10, Slitter SL-1, Inspection Rewinder RW-1 |
| type | text | `press` or `offline`. Only `press` runs count as printed |
| units | int | Print units |
| max_speed_mpm | int | Rated speed, used for OEE performance |
| web_width_mm | int | |

### machine_costs [demo]
| Column | Type | Meaning |
|---|---|---|
| machine_id | FK machines.id | |
| month | text `YYYY-MM` | |
| crew_salary | num | |
| other_cost | num | |

Hour rate = (crew_salary + other_cost) / press hours run in that month (from `runs`).

### settings
One row (key/value table or a single wide row). Columns: `wastage_tol 0.15, overprod_tol 0.10, material_tol 0.03, ink_tol 0.20, slit_tol 0.05, grn_rate_tol 0.05, grace_days 15, msme_days 45, gst_rate 0.18, planning_extra 0.10, admin_pct 0.05, ai_mode 'cloud'`, plus `stock_from date`, `fy_start date`, `company_name text`, `updated_by text`. Only the owner can `PUT`.

### audit_log (users_audit)
| Column | Type | Meaning |
|---|---|---|
| id | id `AUD-#####` | |
| at | ts | |
| role | text | X-Role of the caller |
| action | text | e.g. `release_lock`, `settings_update`, `finding_approve`, `issue_create` |
| entity, entity_id | text | e.g. `client`, `CL-011` |
| before, after | json null | Changed fields |
| reason | text null | Required for `release_lock` and rejections |

Every write by a human or an approved agent action adds a row. Lock releases are listed here with time.

---

## Sales and planning

### enquiries [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `ENQ-####` | |
| date | date | |
| client_id | FK clients.id null | null for a new prospect (then `prospect_name`) |
| prospect_name | text null | |
| product, label_size, material, finish | text | |
| qty | int | |
| colours | int | |
| source | text | phone, email, whatsapp, visit, repeat, website |
| assigned_to | text | Salesperson |
| status | text | new, quoted, won, lost |
| lost_reason | text null | |
| follow_up_on | date null | |

### quotes [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `Q-####` | Same number as its enquiry |
| enquiry_id | FK enquiries.id | |
| date, valid_until | date | |
| qty | int | |
| rate | num | Per label |
| cost_estimate | num | From the costing rules |
| notes | text | |
| status | text | sent, accepted, rejected, expired |

Value = qty * rate. Margin = (value - cost_estimate) / value.

### jobs [demo]
| Column | Type | Meaning |
|---|---|---|
| job_card | id `JC-####` | |
| created_on | date | |
| client_id | FK clients.id | |
| po_no, po_date | text, date | Unique per client |
| enquiry_id | FK enquiries.id null | |
| quote_id | FK quotes.id null | |
| product, label_size | text | |
| order_qty | int | |
| rate | num | Per label. PO value = order_qty * rate |
| item_id | FK items.id | Paper/film |
| machine_id | FK machines.id | Planned press |
| ups_across, ups_along | int | ups = across * along |
| repeat_mm | qty | |
| units | json | Colour per unit, e.g. `["Cyan","Magenta","Yellow","Black","Gloss varnish"]` |
| due_date | date | |
| priority | text | high, normal, low |
| status | text | planned, design, printing, qc, dispatch, invoiced, closed, hold |

Computed: required_m = order_qty / ups * repeat_mm / 1000; planned_m = required_m * (1 + planning_extra); issued_m, printed_qty (press runs only), qc_approved, dispatched_qty, invoiced_qty, flags.

---

## Design

### design [demo]
| Column | Type | Meaning |
|---|---|---|
| job_card | PK, FK jobs.job_card | One record per job |
| stage | text | artwork, proof_sent, approved, plates_ordered, plates_ready, done |
| designer | text | |
| artwork_version | int | |
| proof_sent_on, approved_on | date null | |
| approved_by | text null | |
| die_id | FK dies.id null | |
| units | json | `[{unit, colour, anilox_lpi, plate_id}]` |
| route | json | Ordered process steps |
| notes | text | |

### plates [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `PL-#####` | |
| job_card | FK jobs.job_card | Job the plate was made for (repeats reuse it) |
| unit | int | |
| colour | text | |
| made_on | date | |
| vendor_id | FK vendors.id | |
| cost | num | Charged to the first job |
| impressions | int | |
| status | text | in_use, stored, damaged, scrapped |
| rack | text | Location |

### dies [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `D-###` | |
| type | text | rotary, flatbed |
| label_size | text | |
| ups_across, ups_along | int | |
| repeat_mm | qty | |
| vendor_id | FK vendors.id | |
| cost | num | |
| made_on | date | |
| last_job_card | FK jobs.job_card null | |
| impressions | int | |
| status | text | ok, worn, damaged, scrapped |
| location | text | |

---

## Store

### grns [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `GRN-#####` | |
| date | date | |
| vendor_id | FK vendors.id | |
| bill_no | text | Vendor bill number. Links to supplier_bills |
| item_id | FK items.id | |
| qty | qty | In the item UOM |
| rate | num | Billed rate (same unit as items.rate_unit) |
| source | text | `app` or `erp_import` |

Computed: amount (sq m * rate for per_sqm items), rate_diff_pct = (rate - items.rate) / items.rate, rate_flag if |diff| > grn_rate_tol.

### issues [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `ISS-#####` | |
| date | date | |
| job_card | FK jobs.job_card **null only for `erp_import` rows** | The API rejects a new issue without a valid job card (400) |
| item_id | FK items.id | |
| qty | qty | |
| roll_id | FK rolls.id null | |
| issued_to | text | Machine or department |
| source | text | `app` or `erp_import` |
| raw_date | text null | Original ERP text when imported, kept for the date-fix report |

Value = qty (or sq m) * items.rate. Ink and varnish issued without a job card go into the monthly ink pool.

### rolls [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `R-YYYY-####` | Numbered roll |
| item_id | FK items.id | |
| width_mm | int | |
| length_m | qty | |
| source | text | grn, slit, opening |
| source_ref | text | GRN id, slitting id or "Opening" |
| received_on | date | |
| location | text | |

Balance = length_m - sum(issues.qty where roll_id = id) - slit-out metres.

### slitting [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `SLT-####` | |
| date | date | |
| jumbo_roll_id | FK rolls.id | |
| jumbo_width_mm | int | |
| length_m | qty | |
| outputs | json | `[{width_mm, count, roll_ids[]}]`. New rolls are created in `rolls` with source `slit` |
| operator | text | |

Trim = jumbo width - sum(output widths). trim_pct = trim / jumbo width. Flag if > slit_tol.

### party_laminate [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `PLM-####` | |
| date | date | |
| client_id | FK clients.id | Owner of the laminate (ABL/PBL) |
| movement | text | in, out |
| laminate | text | |
| width_mm | int | |
| qty_m | qty | |
| job_card | FK jobs.job_card null | Required for `out` |

---

## Production

### press_setup [demo]
| Column | Type | Meaning |
|---|---|---|
| job_card | FK jobs.job_card | PK together with machine_id |
| machine_id | FK machines.id | |
| web_width_mm | int | |
| die_id | FK dies.id null | |
| units | json | `[{unit, colour, anilox_lpi, anilox_bcm, plate_id, ink_item_id}]` |
| speed_target_mpm | int | |
| est_ink_kg | qty | Estimated ink, used to share the ink pool |
| notes | text | |
| updated_by | text | |

### runs [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `RUN-#####` | |
| job_card | FK jobs.job_card | |
| machine_id | FK machines.id | Its type decides press or offline |
| shift | text | day, night |
| operator | text | |
| start, end | ts, ts null | end null = running |
| hours | qty null | Run hours |
| printed_qty | int | Counter at end (or live) |
| used_m | qty null | Metres used (press only) |
| stops | json | `[{reason, minutes}]` |

Computed: wastage_m = used - required, wastage_pct = wastage_m / required (flag if > wastage_tol; exactly equal passes), crew_cost = hours * hour rate, over-production flag.

### qc [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `QC-#####` | |
| date | date | |
| job_card | FK jobs.job_card | |
| run_id | FK runs.id null | |
| checked, approved, rejected | int | approved + rejected must equal checked. Cumulative checked must be <= printed |
| decision | text | Approved, Approved with Deviation, Hold, Rework, Rejected. Only the first two count as approved |
| defects | json | `[{type, qty}]` |
| inspector | text | |
| notes | text | |

---

## Dispatch and money

### dispatches [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `DC-####` | Delivery challan |
| date | date | |
| job_card | FK jobs.job_card | Cumulative qty must be <= QC approved (409) |
| qty | int | |
| boxes | int | |
| vehicle_no, transporter, lr_no | text | |
| freight | num | Charged to the job |

### invoices [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `INV-####` | |
| date | date | |
| client_id | FK clients.id | |
| job_card | FK jobs.job_card | |
| dispatch_id | FK dispatches.id null | unique; one invoice per challan |
| qty | int | |
| rate | num | |
| gst_rate | frac | Snapshot of settings.gst_rate |
| status | text | draft, open (paid/part_paid are computed) |

Computed: taxable = qty * rate, gst = taxable * gst_rate, total, due_date = date + client credit days, received (from receipts), outstanding, days past due, bucket.

### receipts [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `RCP-####` | |
| date | date | |
| client_id | FK clients.id | |
| invoice_id | FK invoices.id | One receipt line per invoice |
| amount | num | |
| mode, ref | text | |

### collections [demo]
Follow-ups and payment promises.

| Column | Type | Meaning |
|---|---|---|
| id | id `COL-####` | |
| date | date | |
| client_id | FK clients.id | |
| invoice_ids | json | |
| mode | text | call, whatsapp, email, visit |
| contact, note | text | |
| promise_date | date null | |
| promise_amount | num null | |
| status | text | open, kept, broken. Computed nightly from receipts |
| next_follow_up | date null | |
| by | text | |

### supplier_bills [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `SB-####` | |
| vendor_id | FK vendors.id | |
| bill_no | text | |
| date | date | |
| amount | num | Including GST |
| grn_ids | json | |

Computed: due_date (MSME rule), paid (from payment allocations), balance, days_to_due.

### payments [demo]
| Column | Type | Meaning |
|---|---|---|
| id | id `PAY-####` | |
| vendor_id | FK vendors.id | |
| date | date | |
| amount | num | |
| mode, ref | text | |

### payment_allocations [demo]
| Column | Type | Meaning |
|---|---|---|
| payment_id | FK payments.id | |
| bill_id | FK supplier_bills.id | |
| applied | num | FIFO: oldest bill first |

### tally_pnl
Imported monthly P&L from Tally, compared with the system P&L.

| Column | Type | Meaning |
|---|---|---|
| month | text `YYYY-MM` | PK with key |
| key | text | revenue, material, plates, ink, salaries, freight, admin, overheads |
| amount | num | |
| imported_at | ts | |
| note | text | Reconciliation note |

---

## Agents, outbox, feedback

### agent_runs
| Column | Type | Meaning |
|---|---|---|
| id | id `AR-####` | |
| agent | text | One of the 8 names in SPEC section 4 |
| started_at, finished_at | ts | |
| status | text | running, ok, failed |
| findings_created | int | |
| model | text | `rules` or the LLM provider used for wording |
| note | text | |

### agent_findings
| Column | Type | Meaning |
|---|---|---|
| id | id `F-####` | |
| run_id | FK agent_runs.id | |
| agent | text | |
| severity | text | high, medium, low |
| title, detail | text | Wording may come from the LLM. Numbers always come from the rules engine |
| evidence | json | `[{label, link}]` |
| suggested_action | json | `{type, payload}` |
| status | text | open, done, rejected |
| decided_by | text null | Role |
| decided_at | ts null | |
| reason | text null | Required on reject |
| dedupe_key | text | Stops an agent re-raising the same open finding |

### outbox
| Column | Type | Meaning |
|---|---|---|
| id | id `OB-####` | |
| agent | text | |
| finding_id | FK agent_findings.id null | |
| channel | text | whatsapp, email, task |
| to, subject, body | text | |
| status | text | draft, approved, sent, failed |
| approved_by | text null | |
| sent_at | ts null | |
| simulated | bool | Always true in the demo: nothing leaves the laptop |

### feedback
| Column | Type | Meaning |
|---|---|---|
| id | id `FB-####` | |
| role | text | |
| screen | text | Route |
| message | text | |
| rating | int null | 1-5 |
| status | text | new, seen, done |
