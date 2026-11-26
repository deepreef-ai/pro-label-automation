# core.etl: EXTRACT step

This step reads the client's real Excel system (`data/raw/`, git-ignored and confidential) into clean pandas frames. A separate loader maps the frames into the DB schema. This step creates no tables and writes no client data into committed files.

## How to run

```bash
# from the repo root
PYTHONPATH=apps/api .venv/Scripts/python -m core.etl.extract --raw data/raw --out data/extract
PYTHONPATH=apps/api .venv/Scripts/python -m core.etl.docs --raw data/raw      # document text summary
```

The extract writes `data/extract/<frame>.csv` (UTF-8, git-ignored) and prints a summary of rows per frame plus the quality report. It takes about 12 s on the demo laptop, and the docs step about 25 s.

In code:

```python
from core.etl.extract import extract_all        # -> dict[str, DataFrame]
from core.etl.docs import list_documents        # -> [{"source", "page", "text"}]
```

## How the workbooks are read

- Each workbook is opened once with `openpyxl.load_workbook(read_only=True, data_only=True)`. Only the needed sheets and columns are read, and each workbook is closed before the next one is opened. The one exception is the Accounts `P&L format` sheet, which is also opened with `data_only=False` to read its typed sum formulas.
- Headers are on row 4 and data starts on row 5. Rows are pre-filled with formulas, and the files were never recalculated, so formula cells are empty. **Only typed input columns are read.** Every computed column (outstanding, current stock, checks, ...) is left to the app.
- A sheet scan stops after 300 consecutive blank key rows.
- Files are found by prefix (`System/06 *.xlsx` and so on), so renamed copies still work.

## Cleaning rules (all frames)

- Text is stripped (including NBSP). Empty strings, and ERP blanks such as `' '`, become null.
- Numbers become floats. IDs and codes become text: integers lose the `.0`, so job card `22244503` stays `"22244503"`.
- **Blank rows are dropped**: a row is kept only when its key column(s) have a value.
- **DEMO rows are dropped**: any cell equal to `DEMO`, or containing `JC-DEMO` or `INV-2201`. Counts are reported as `demo_rows_dropped`.
- Item matching (issues/GRNs to Item Master) works like Excel's `TRIM` plus case-insensitive `MATCH`: whitespace is collapsed and the text is casefolded. The key is in `items.item_key`.
- `src_row` is the Excel row number, kept for traceability.
- Every row here is real, so the loader sets `is_demo = false`.

### ERP dates (parsed day-first, SPEC section 2)

- Text `dd-mm-yy` / `dd-mm-yyyy` is parsed day-first with `core.rules.dates.parse_erp_date` (`date_method = text`).
- When Excel already turned the text into a datetime, the original text is lost. Excel reads `dd-mm-yy` month-first, so only values with day <= 12 can be wrong:
  - day > 12: kept (`excel_unambiguous`);
  - day == month: nothing to fix (`same_day_month`);
  - otherwise there are two candidates, *keep* and *swap* (day and month exchanged). **Heuristic:** document numbers in one series (`PL/GR/27/0001...`, `PL/GI/27/...`) are issued in date order. For each document, take the nearest text-dated (anchor) document before and after it in number order; a document number that already has an anchor uses that anchor's date. The candidate that lies inside [previous anchor, next anchor], and for GRNs is not before the PO date in `P.O. Number` (`PO::dd-mm-yyyy`), wins. If both or neither fit, the one closer to the anchors wins. A tie keeps Excel's value. The methods are `swapped`, `kept_checked` and `kept_ambiguous`.
- `date_fixed` is true when a value was swapped. The counts are in `quality` (`date_*`, `date_fixes`). After the fix, GRN dates are monotonic in GRN number. Without the fix, 43 GRN lines would fall after `stock_from` and be counted as receipts.

## Frames and columns

| frame | source | columns |
|---|---|---|
| `clients` | 06 Accounts > Client Register (B:O) | name, tally_name, gstin, billing_address, city, state, contact_person, phone, email, credit_days, grace_days, credit_limit, release_lock_until, remarks, src_row |
| `vendors` | 06 Accounts > Vendor Register (B:M) | name, gstin, gstin_state_code, state, contact_person, phone, email, credit_days, is_msme (true/false/null when not filled), udyam_no, bank_account, ifsc, remarks, src_row |
| `opening_debtors` | 06 Accounts > Opening Debtors (B:I), unpaid invoices at 30-Sep-2026 | client, debtor_list_name, invoice_no, invoice_date, due_date, amount_due, received_since, receipt_date, as_of, src_row |
| `fixed_assets` | 06 Accounts > Fixed Assets & Depreciation | kind (`block` / `misc_expenditure` / `addition`), asset_block, description, gross_block_opening, acc_dep_opening, net_block_opening, dep_fy2025_26, dep_rate, purchase_date, amount (write-off for misc, cost for additions), src_row |
| `tally_pnl` | 06 Accounts > P&L format, typed Tally figures (long format) | section, ledger, period (`opening` = 1-Apr-2026 or `YYYY-MM`), amount, is_memo (label-count memo line, not rupees), src_row |
| `pnl_ledgers` | 06 Accounts > Lists C:E | ledger, section, standard_per_month, src_row |
| `items` | 02 Store (System) > Item Master | item_name (ERP description, the match key), item_code (not unique), item_group, stock_head, ppic_paper, width_mm, uom, uom_factor, rate (null if missing or 0), has_rate, is_customer_material, rate_source, opening_running_m, opening_date, min_stock, stock_type, lying_since, item_key, src_row |
| `opening_stock` | 02 Store (System) > Stock Statement | item_group, stock_head, uom, opening_qty, opening_rate, value_only, opening_value (qty x rate, else value_only), min_stock, lying_since, as_of (= Lists `stock_from`, 2026-10-01), src_row |
| `jobs` | REVIEW > hidden `Ref PPIC Job Register` (B, I, AD) plus ERP issue facts | job_card (ERP number), job_name, ppic_status, src_row, erp_job_card_id, issue_lines, first_issue_date, last_issue_date, material_value_rs |
| `grns` | REVIEW > ERP GRN Paste A:X plus derived columns | grn_number, grn_date, date_method, date_fixed, grn_date_text, grn_date_excel, supplier_name, gstin, grn_type, po_number, po_date, hsn_code, item_description, item_code, item_known, item_group, qty, uom, uom_factor, qty_stock_uom, rate, rate_stock_uom, item_rate, rate_diff_pct, basic_amount, disc_rate, disc_amount, taxable_amount, sgst_rate, sgst_amount, cgst_rate, cgst_amount, igst_rate, igst_amount, gst_amount, total_amount, possible_duplicate, src_row |
| `issues` | REVIEW > ERP Issue Paste A:X plus derived columns | doc_number, doc_date, date_method, date_fixed, doc_date_text, job_card (null for `--`/`XX`/blank), has_job_card, job_card_in_ppic, job_card_number (raw), job_card_id, job_name, erp_group, item_code, item_description, item_known, item_group, uom, total_quantity, remarks, from_location, to_location, no_of_pack, qty_per_pack, quantity, roll_id, returned_no_of_pack, returned_qty_per_pack, returned_qty, return_roll_id, return_note_number, return_date, consumed_qty, net_qty (= quantity - returned_qty), uom_factor, net_qty_stock_uom, item_rate, value_rs, src_row |
| `machines` | 01 PPIC > Dropdown Lists C, plus 07 Design press list and 03 Production OEE rated speed | name, machine_type (`press` / `offline`), rated_speed_m_min, sort_order |
| `lists` | dropdown lists of 01/02/03/04/05/06/07 | list_name, value, sort_order (list names include paper_type, paper_width_mm, foil, foil_size_mm, lamination, transporter, defect_type, qc_decision, designer, design_status, downtime_reason, shift, operator, plate_status, die_type, uom, item_group, gst_rate, invoice_type, ...) |
| `settings` | admin cells | key, value, source (grace_days, fy_start, ink_tol, slit_tol, stock_from, ink_gsm_per_colour, anilox_transfer, ink_specific_gravity, design_approval_days) |
| `quality` | computed | area, metric, value, detail |

Derived rules follow the Store sheet. The UOM factor is 1 when the UOM equals the item UOM, width/1000 for Meter to Sq.Mtrs, 1000/width for Sq.Mtrs to Meter, and otherwise the Item Master factor. Issue `value_rs` = net qty in stock UOM x Item Master rate (0 when the rate or factor is unknown). `rate_diff_pct` = GRN rate per stock UOM / item rate - 1, flagged above 0.05 (`grn_rate_tol`).

## Quality report (`quality.csv`)

The quality report feeds the Store "data quality" screen. Per frame it gives rows_read, demo_rows_dropped and rows_kept, plus these metrics:

- issues without a job card: count, %, % by ERP group, and Rs value
- job cards not in PPIC
- unknown items (lines and distinct items) and UOM problems
- lines on items without a rate
- items without a rate or stock head
- date methods and fixes
- GRN rate differences above 5%, possible duplicates, and lines after `stock_from`
- clients without credit days, vendors without the MSME flag or credit days
- opening stock and debtors totals

## Known data facts / caveats

- The REVIEW GRNs actually date from **Apr-May 2026**, not Aug-Oct as the file name says. Issues run from 1-Aug to 6-Oct-2026. The opening stock is the 1-Oct-2026 statement.
- Items come from the live **System** Item Master, which already contains most of the items the older REVIEW master lacked. This is why there are almost no unknown items.
- The Vendor Register has only name and GSTIN filled, so MSME and credit days are unknown. The loader should apply defaults and leave the gap visible in the quality report.
- `jobs` has only job card, name and status: the REVIEW reference register holds nothing else. Client, quantities and similar fields are not available.
- Placeholder names (for example `Designer 2`, `QC Inspector 1`) are kept as they appear in the client's lists.
- Production, QC, Dispatch, Design, Marketing and C&D logs contain only DEMO rows, so they are not extracted.

## Documents (`docs.py`)

`list_documents(raw_dir)` reads `data/raw/docs/*.pdf|*.txt|*.md`. It takes PDF text per page with pypdf, falls back to pdfplumber for empty pages, and splits text files into blocks of about 3,000 characters. The result is `[{"source", "page", "text"}]` for the RAG index.

# core.etl: LOAD, GENERATE and BUILD steps (database)

```bash
# from the repo root; drops and recreates every table
PYTHONPATH=apps/api .venv/Scripts/python -m core.etl.build_demo_db --raw data/raw          # real + demo (~14 s, includes the extract)
PYTHONPATH=apps/api .venv/Scripts/python -m core.etl.build_demo_db --raw data/extract      # real from extract CSVs (~10 s)
PYTHONPATH=apps/api .venv/Scripts/python -m core.etl.build_demo_db --synthetic             # no client files (~1.5 s, CI)
#   --db sqlite:///data/demo.db  (default: env DATABASE_URL, else sqlite:///data/demo.db)   --json for a JSON summary
```

In code: `core.etl.build.build_database(db_url, raw_dir=None) -> dict` (summary: `mode`, `tables` row counts, `demo_rows`, `total_rows`, `seconds`). Without client files under `raw_dir` it builds a **synthetic-only** database. Models are in `core.models`, the engine/session in `core.db` (`get_engine`, `SessionLocal`, `get_session`, `init_db`; SQLite foreign keys are on).

| Module | Does |
|---|---|
| `load.py` | Maps the real frames into the tables with `is_demo = false` |
| `generate.py` | Deterministic demo rows (`random.Random(seed)`, `is_demo = true`); every number goes through `core.rules` |
| `build.py` | Drops/creates tables, runs load (if files) + generate, bulk-inserts in FK order |

## Real data (load.py)

- IDs never clash with the fixture stories: clients `CL-101+`, vendors `VN-101+`, items `IT-1001+`, GRNs `GRN-10001+`, issues `ISS-10001+`, opening invoices `INV-1001+`, receipts `RCP-5001+`. Real job cards keep the ERP number: `JC-22244503`. Machines: presses `M-01..M-04`, Slitter SL-1 `M-05`, Inspection `M-06` (as in the fixtures), the rest `M-07+`.
- GRN/issue qty and rate are in the item's stock UOM (`qty_stock_uom`, `net_qty_stock_uom`); the ERP document number goes to `ref`, the original date text to `raw_date`. Issues whose job card is blank stay `job_card = null` (`source = erp_import`).
- **opening_stock** is per stock head in the client's statement: `stock_head_id` is set and `item_id` is the first Item Master item of that head (null when the head has no item, e.g. finished labels).
- **Opening debtors** become invoices with `source = 'opening'`, `qty = 1`, `rate` = amount due incl. GST, `gst_rate = 0`, `ref` = original invoice number; due date follows the client's credit days.
- **tally_pnl**: the typed Tally ledgers (Apr-Sep 2026) are summed per month into `revenue` (sales minus returns), `material`, `plates`, `ink`, `salaries`, `freight` (freight outward), `admin` (admin + financial), `overheads` (direct expenses). Closing stock, cash-flow and carried-forward lines are not P&L keys and are skipped.
- `fixed_assets` and `lists` are extra tables (not in schema.md) for the Fixed Assets sheet and the dropdown lists. Real settings (`grace_days`, `ink_tol`, `slit_tol`, `stock_from`, `fy_start`) override the defaults; other admin cells go to `settings.extra`.

### Generated values on real rows (marked `is_demo = true`)

- **jobs**: client, order qty, rate, ups, repeat, machine, due date are generated (the PPIC register has none of them), so **every job row is demo**. The paper item is the job's most-used paper from the real issues. For ~60 jobs with >= 300 m of paper issued, the order qty is derived from the metres really issued so the demo runs show realistic wastage.
- **vendors**: 3 vendors are marked MSME with 30/45/60 credit days (demo); the others get `msme = false`, 30 days.
- **machines**: presses whose name matches the fixtures get units / web width from the fixtures (demo).
- **receipts**: an opening-debtor invoice due more than 4 days before the demo date gets a DEMO receipt for its balance, so real clients are not all LOCKED on 2026-11-20.

## Demo data (generate.py)

- **Fixture stories** are read from `contract/fixtures/*.json` (stored columns only), so the DB matches the contract exactly: JC-1301 (ENQ-0045, Q-0045, design, plates PL-00871..875, rolls R-2026-0912/0913, issues 2 x 575 m, RUN-05531 52,000 printed / 1,150 m used, QC 52,000/50,900/1,100, DC-1388 50,000, INV-2390 Rs 35,400 unpaid, due 2026-12-12), JC-1240 (18% wastage, night shift), the 5 at-risk clients (Rs 42,60,272 overdue) and locked CL-011, MSME bill SB-0187 due 2026-11-23, PP Silver 200 mm stock 1,884.45 m (700 m short), all 11 agent findings with their agent runs. Jobs that fixtures only reference (JC-1205, JC-1262 ...) get a full run -> QC -> challan chain.
- Every guard is checked while generating: `qc_validate`, `check_dispatch` (dispatch <= approved), `invoice_amounts` (fixture totals), `fifo_allocate` (supplier payments), `stock_balance`, `slit_trim_pct`.
- **Background**: ~60 closed/invoiced jobs (real job cards in a real build, invented jobs JC-11xx/12xx in a synthetic build) with issue, press + inspection runs, QC, challan, invoice. Wastage is mostly 5-12% with a few above 15%; two jobs are over-produced. Invoices due more than 4 days ago are paid (some late, with a kept collection note); the rest stay open, so some are 1-4 days overdue without changing the lock story. Background runs end before 1-Nov so the November ink pool (Rs 18,240, JC-1301 share Rs 1,900) is as in the fixtures.
- **machine_costs** (Jul-Nov): the fixture monthly costs scaled to the hours actually run, so `machine_hour_rate` gives exactly the fixture rates (Gallus EM 280 = Rs 800/h, JC-1301 crew cost Rs 2,800).
- **opening_stock** of demo items is solved so that stock = opening + received - issued equals `store_stock.json`.
- `tally_pnl` 2026-10 (demo) is the Tally column of `pnl_2026-10.json`. Settings use the SPEC defaults. `outbox` and `feedback` start empty. Synthetic clients and vendors are invented names (`*.example` e-mails).

## Multi-tenant build (v0.2, SPEC 6)

- Everything above belongs to company `CO-001` (Pro Labels). `core.etl.tenants` stamps `company_id` on every row, adds the `companies` and `users` tables (from the contract fixtures), and builds two made-up companies, `CO-002` Sunrise Flexo Prints and `CO-003` Nilgiri Label Works, from separate **synthetic** runs: own ids (`JC-1301` -> `JC-6301` / `JC-8301`), own invented client and vendor names, all `is_demo = true`. Real client rows are never copied.
- Keys are per company: primary key `(company_id, id)` and composite foreign keys (`core.tenancy.apply_tenancy`).
- The app reads and writes through a session scoped to one company (`core.db.get_session` -> `core.tenancy.scoped`); until login (B1) that is `CO-001` (`DEMO_COMPANY_ID` overrides).
- An existing `data/demo.db` has the old schema: run `reset-demo` once after pulling.
