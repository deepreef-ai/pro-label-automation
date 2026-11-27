// Generated from contract/openapi.yaml - keep in sync (change via a [contract] PR).
// Money = rupees (number, 2 dp). Dates = ISO 'YYYY-MM-DD'. Fractions are 0..1.

export type Role = "owner" | "ppic" | "design" | "store" | "production" | "qc" | "dispatch" | "accounts" | "marketing";

/** v0.2 (SPEC 6): a role inside one company. The company owner is also its company admin. */
export type CompanyRole = Role;
/** v0.2: company roles plus platform staff (belongs to no company, sees no company data). */
export type AnyRole = Role | "platform_admin";

/** Error body for 400/403/404/409 */
export interface ApiError {
  detail: string;
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  time: string;
  db: "ok" | "down";
  ai_mode: "cloud" | "local" | "off";
  /** demo data loaded */
  demo: boolean;
}

export interface SearchResult {
  type: "job" | "client" | "vendor" | "item" | "enquiry" | "invoice" | "dispatch" | "grn" | "roll" | "plate" | "die";
  id: string;
  title: string;
  subtitle: string;
  /** Frontend route */
  link: string;
}

export interface SearchResponse {
  q: string;
  results: SearchResult[];
}

export interface Settings {
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  wastage_tol: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  overprod_tol: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  material_tol: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  ink_tol: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  slit_tol: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  grn_rate_tol: number;
  grace_days: number;
  msme_days: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  gst_rate: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  planning_extra: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  admin_pct: number;
  ai_mode: "cloud" | "local" | "off";
  /** Opening stock date */
  stock_from: string;
  fy_start: string;
  company_name: string;
  updated_at: string | null;
  updated_by: string | null;
}

/** Any subset of Settings editable fields */
export interface SettingsUpdate {
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  wastage_tol?: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  overprod_tol?: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  material_tol?: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  ink_tol?: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  slit_tol?: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  grn_rate_tol?: number;
  grace_days?: number;
  msme_days?: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  gst_rate?: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  planning_extra?: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  admin_pct?: number;
  ai_mode?: "cloud" | "local" | "off";
  stock_from?: string;
  fy_start?: string;
  company_name?: string;
}

export interface FeedbackCreate {
  /** Route, e.g. /jobs */
  screen: string;
  message: string;
  rating?: number | null;
}

export interface Feedback {
  /** FB-#### */
  id: string;
  created_at: string;
  role: "owner" | "ppic" | "design" | "store" | "production" | "qc" | "dispatch" | "accounts" | "marketing";
  screen: string;
  message: string;
  rating: number | null;
  status: "new" | "seen" | "done";
}

export interface TrendPoint {
  label: string;
  /** Rupees, 2 decimals */
  revenue: number;
  /** Rupees, 2 decimals */
  profit: number;
}

export interface DashboardSummary {
  period: "today" | "month" | "year";
  from: string;
  to: string;
  /** Invoiced taxable value in period */
  revenue: number;
  invoices_count: number;
  /** PO value of jobs created in period */
  orders_booked_value: number;
  orders_booked_count: number;
  /** Press runs only */
  printed_qty: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  wastage_pct: number;
  /** Rupees, 2 decimals */
  gross_profit: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  margin_pct: number;
  /** Receipts */
  cash_in: number;
  /** Supplier payments + salaries */
  cash_out: number;
  /** All open invoices, as of today */
  receivables: number;
  /** Rupees, 2 decimals */
  overdue: number;
  /** Overdue of clients that will lock within grace */
  at_risk_value: number;
  at_risk_clients: number;
  locked_clients: number;
  /** Rupees, 2 decimals */
  payables_due_7d: number;
  /** Rupees, 2 decimals */
  stock_value: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  oee: number;
  /** Count of active jobs per job status */
  jobs_by_status: Record<string, number>;
  trend: TrendPoint[];
  top_clients: {
    client_id: string;
    client_name: string;
    /** Rupees, 2 decimals */
    revenue: number;
  }[];
}

export interface Alert {
  id: string;
  severity: "high" | "medium" | "low";
  area: "money" | "production" | "store" | "qc" | "dispatch" | "planning" | "design" | "agents";
  title: string;
  detail: string;
  link: string;
  created_at: string;
}

export interface AlertsResponse {
  as_of: string;
  alerts: Alert[];
}

export interface BriefItem {
  text: string;
  severity: "high" | "medium" | "low";
  link: string | null;
}

export interface AgentBrief {
  date: string;
  generated_at: string;
  headline: string;
  items: BriefItem[];
  source: "llm" | "template";
  finding_id: string | null;
}

export interface Client {
  /** CL-### */
  id: string;
  name: string;
  gstin: string;
  city: string;
  state: string;
  contact: string;
  phone: string;
  email: string;
  credit_days: number;
  /** Rupees, 2 decimals */
  credit_limit: number;
  /** Rupees, 2 decimals */
  outstanding: number;
  /** Rupees, 2 decimals */
  overdue: number;
  lock_status: "ok" | "at_risk" | "locked";
  /** First day the client becomes LOCKED (due + grace + 1) */
  locks_on: string | null;
  locked_since: string | null;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface LockEvent {
  at: string;
  event: "locked" | "released";
  by: string;
  reason: string;
}

export interface ClientDetail {
  client: Client;
  /** Outstanding by days past due */
  buckets: {
    /** Rupees, 2 decimals */
    not_due: number;
    /** Rupees, 2 decimals */
    "1_30": number;
    /** Rupees, 2 decimals */
    "31_60": number;
    /** Rupees, 2 decimals */
    "61_90": number;
    /** Rupees, 2 decimals */
    "90_plus": number;
  };
  invoices: Invoice[];
  jobs: Job[];
  collections: Collection[];
  lock_log: LockEvent[];
}

export interface Vendor {
  /** VN-### */
  id: string;
  name: string;
  city: string;
  msme: boolean;
  credit_days: number;
  /** min(credit_days, msme_days) if MSME */
  effective_credit_days: number;
  supplies: string;
  /** Rupees, 2 decimals */
  outstanding: number;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface Item {
  /** IT-#### */
  id: string;
  name: string;
  group: "Paper & Film" | "Ink" | "Varnish" | "Foil" | "Lamination";
  stock_head: string;
  width_mm: number | null;
  uom: "m" | "kg" | "sqm" | "nos";
  /** Rupees, 2 decimals */
  rate: number;
  rate_unit: "per_sqm" | "per_kg" | "per_m" | "per_nos";
  min_stock: number;
  vendor_id: string | null;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface Machine {
  /** M-## */
  id: string;
  name: string;
  type: "press" | "offline";
  units: number;
  max_speed_mpm: number;
  web_width_mm: number;
  /** Rupees, 2 decimals */
  crew_salary_month: number;
  /** Rupees, 2 decimals */
  other_cost_month: number;
  hours_run_month: number;
  /** (crew salary + other) / hours run */
  hour_rate: number;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface Enquiry {
  /** ENQ-#### */
  id: string;
  date: string;
  client_id: string | null;
  client_name: string;
  product: string;
  label_size: string;
  qty: number;
  material: string;
  colours: number;
  finish: string;
  source: "phone" | "email" | "whatsapp" | "visit" | "repeat" | "website";
  assigned_to: string;
  status: "new" | "quoted" | "won" | "lost";
  quote_id: string | null;
  /** Rupees, 2 decimals */
  value: number | null;
  lost_reason: string | null;
  follow_up_on: string | null;
  job_card: string | null;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface EnquiryCreate {
  client_id?: string | null;
  client_name: string;
  product: string;
  label_size: string;
  qty: number;
  material: string;
  colours: number;
  finish?: string;
  source?: string;
  assigned_to?: string;
}

export interface Quote {
  /** Q-#### */
  id: string;
  enquiry_id: string;
  date: string;
  qty: number;
  /** Rupees, 2 decimals */
  rate: number;
  /** Rupees, 2 decimals */
  value: number;
  /** Rupees, 2 decimals */
  cost_estimate: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  margin_pct: number;
  valid_until: string;
  notes: string;
  status: "sent" | "accepted" | "rejected" | "expired";
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface QuoteCreate {
  /** Rupees, 2 decimals */
  rate: number;
  qty?: number;
  valid_until: string;
  notes?: string;
}

export interface EnquiryStatusUpdate {
  status: "new" | "quoted" | "won" | "lost";
  reason?: string;
  po_no?: string;
}

export interface MarketingSummary {
  /** YYYY-MM */
  month: string;
  /** Rupees, 2 decimals */
  target: number;
  /** Rupees, 2 decimals */
  achieved: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  achievement_pct: number;
  funnel: {
    new: number;
    quoted: number;
    won: number;
    lost: number;
  };
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  win_rate: number;
  /** Rupees, 2 decimals */
  pipeline_value: number;
  by_person: {
    name: string;
    /** Rupees, 2 decimals */
    target: number;
    /** Rupees, 2 decimals */
    achieved: number;
    enquiries: number;
    won: number;
  }[];
  lost_reasons: {
    reason: string;
    count: number;
  }[];
}

export interface Job {
  /** JC-#### */
  job_card: string;
  created_on: string;
  client_id: string;
  client_name: string;
  po_no: string;
  po_date: string;
  product: string;
  label_size: string;
  order_qty: number;
  /** Rupees, 2 decimals */
  rate: number;
  /** Rupees, 2 decimals */
  po_value: number;
  item_id: string;
  material: string;
  paper_width_mm: number;
  machine_id: string;
  machine_name: string;
  ups_across: number;
  ups_along: number;
  ups: number;
  repeat_mm: number;
  /** Colour per unit */
  units: string[];
  /** order_qty / ups * repeat_mm / 1000 */
  required_m: number;
  /** required_m * (1 + planning_extra) */
  planned_m: number;
  issued_m: number;
  /** Press runs only */
  printed_qty: number;
  qc_approved: number;
  dispatched_qty: number;
  invoiced_qty: number;
  /** planned = PO accepted, waiting for design/material; design = artwork/proof/plates; printing = on press; qc = printed, inspection open; dispatch = QC approved, dispatch open; invoiced; closed = paid; hold */
  status: "planned" | "design" | "printing" | "qc" | "dispatch" | "invoiced" | "closed" | "hold";
  priority: "high" | "normal" | "low";
  due_date: string;
  enquiry_id: string | null;
  quote_id: string | null;
  flags: ("wastage_high" | "material_variance" | "overprod" | "material_short" | "client_locked" | "qc_hold" | "late")[];
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface JobListResponse {
  total: number;
  items: Job[];
}

export interface JobCreate {
  client_id: string;
  po_no: string;
  po_date: string;
  product: string;
  label_size: string;
  order_qty: number;
  /** Rupees, 2 decimals */
  rate: number;
  item_id: string;
  machine_id?: string;
  ups_across: number;
  ups_along: number;
  repeat_mm: number;
  units?: string[];
  due_date: string;
  enquiry_id?: string | null;
  priority?: "high" | "normal" | "low";
}

export interface PoDraftField {
  value: string | number | number | null;
  /** 0..1 extraction confidence */
  confidence: number;
  source_text: string | null;
}

export interface PoDraft {
  /** Always false: a draft, never saved */
  saved: boolean;
  file_name: string;
  /** Keys are JobCreate field names */
  fields: Record<string, PoDraftField>;
  client_match: {
    client_id: string;
    client_name: string;
    /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
    score: number;
  } | null;
  warnings: string[];
  draft: JobCreate;
}

export interface MaterialNeed {
  item_id: string;
  material: string;
  width_mm: number;
  jobs: {
    job_card: string;
    client_name: string;
    need_m: number;
  }[];
  /** Sum of planned_m - issued_m for open jobs */
  need_m: number;
  stock_m: number;
  /** max(need - stock, 0) */
  shortage_m: number;
  status: "ok" | "short";
}

export interface MaterialSummary {
  as_of: string;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  planning_extra: number;
  items: MaterialNeed[];
  shortages: number;
}

export interface DesignUnit {
  unit: number;
  colour: string;
  anilox_lpi: number | null;
  plate_id: string | null;
}

export interface Design {
  job_card: string;
  client_name: string;
  product: string;
  stage: "artwork" | "proof_sent" | "approved" | "plates_ordered" | "plates_ready" | "done";
  designer: string;
  artwork_version: number;
  proof_sent_on: string | null;
  approved_on: string | null;
  approved_by: string | null;
  repeat_mm: number;
  ups_across: number;
  ups_along: number;
  die_id: string | null;
  plate_ids: string[];
  units: DesignUnit[];
  route: string[];
  notes: string;
  updated_at: string;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

/** Any subset of editable Design fields */
export interface DesignUpdate {
  stage?: "artwork" | "proof_sent" | "approved" | "plates_ordered" | "plates_ready" | "done";
  designer?: string;
  artwork_version?: number;
  proof_sent_on?: string | null;
  approved_on?: string | null;
  approved_by?: string | null;
  die_id?: string | null;
  units?: DesignUnit[];
  route?: string[];
  notes?: string;
}

export interface Plate {
  /** PL-##### */
  id: string;
  job_card: string;
  client_name: string;
  unit: number;
  colour: string;
  made_on: string;
  vendor_id: string;
  /** Rupees, 2 decimals */
  cost: number;
  impressions: number;
  status: "in_use" | "stored" | "damaged" | "scrapped";
  rack: string;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface Die {
  /** D-### */
  id: string;
  type: "rotary" | "flatbed";
  label_size: string;
  ups_across: number;
  ups_along: number;
  repeat_mm: number;
  vendor_id: string;
  /** Rupees, 2 decimals */
  cost: number;
  made_on: string;
  last_job_card: string | null;
  impressions: number;
  status: "ok" | "worn" | "damaged" | "scrapped";
  location: string;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface JobCost {
  /** Rupees, 2 decimals */
  revenue: number;
  revenue_basis: "invoiced" | "po_value";
  /** Rupees, 2 decimals */
  material: number;
  /** Rupees, 2 decimals */
  plates: number;
  /** Rupees, 2 decimals */
  ink: number;
  /** Rupees, 2 decimals */
  salaries: number;
  /** Rupees, 2 decimals */
  freight: number;
  /** Rupees, 2 decimals */
  admin_share: number;
  /** Rupees, 2 decimals */
  direct_overhead: number;
  /** revenue - all costs */
  profit: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  margin_pct: number;
}

export interface TimelineEvent {
  date: string;
  stage: "enquiry" | "quote" | "po" | "design" | "plates" | "store" | "production" | "qc" | "dispatch" | "invoice" | "receipt";
  text: string;
  ref: string | null;
  link: string | null;
}

export interface Job360 {
  job: Job;
  enquiry: Enquiry | null;
  quote: Quote | null;
  design: Design | null;
  plates: Plate[];
  die: Die | null;
  issues: Issue[];
  rolls: Roll[];
  runs: Run[];
  qc: QcRow[];
  dispatches: Dispatch[];
  invoices: Invoice[];
  cost: JobCost;
  timeline: TimelineEvent[];
  checks: RuleCheck[];
}

export interface RuleCheck {
  rule: string;
  label: string;
  value: number;
  limit: number;
  ok: boolean;
  detail: string;
}

export interface StoreGroupSummary {
  group: string;
  /** Rupees, 2 decimals */
  stock_value: number;
  /** Rupees, 2 decimals */
  received_value_month: number;
  /** Rupees, 2 decimals */
  issued_value_month: number;
  /** Rupees, 2 decimals */
  issued_without_jc_value_month: number;
}

export interface StoreSummary {
  as_of: string;
  stock_from: string;
  month: string;
  /** Rupees, 2 decimals */
  stock_value: number;
  groups: StoreGroupSummary[];
  grns_month: number;
  issues_month: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  issue_lines_without_jc_pct: number;
  below_min: number;
  shortages: MaterialNeed[];
  rate_flags: number;
  non_moving_items: number;
}

export interface StockRow {
  item_id: string;
  item_name: string;
  group: string;
  width_mm: number | null;
  uom: string;
  /** as of stock_from */
  opening: number;
  received: number;
  issued: number;
  /** opening + received - issued */
  stock: number;
  /** stock * width_mm / 1000 */
  stock_sqm: number | null;
  /** Rupees, 2 decimals */
  rate: number;
  /** Rupees, 2 decimals */
  value: number;
  min_stock: number;
  status: "ok" | "low" | "short" | "non_moving";
  last_movement: string;
}

export interface StockResponse {
  as_of: string;
  stock_from: string;
  /** Rupees, 2 decimals */
  total_value: number;
  items: StockRow[];
}

export interface GrnCreate {
  date: string;
  vendor_id: string;
  bill_no: string;
  item_id: string;
  qty: number;
  /** Rupees, 2 decimals */
  rate: number;
  /** One entry per numbered roll (paper/film) */
  roll_lengths_m?: number[];
}

export interface Grn {
  /** GRN-##### */
  id: string;
  date: string;
  vendor_id: string;
  vendor_name: string;
  bill_no: string;
  item_id: string;
  item_name: string;
  qty: number;
  uom: string;
  /** Rupees, 2 decimals */
  rate: number;
  /** Rupees, 2 decimals */
  item_rate: number;
  /** (rate - item_rate) / item_rate */
  rate_diff_pct: number;
  /** |diff| > grn_rate_tol */
  rate_flag: boolean;
  /** Rupees, 2 decimals */
  amount: number;
  roll_ids: string[];
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface IssueCreate {
  date: string;
  /** Required; 400 if missing/unknown */
  job_card: string;
  item_id: string;
  qty: number;
  roll_id?: string | null;
  issued_to?: string;
}

export interface Issue {
  /** ISS-##### */
  id: string;
  date: string;
  /** null only on imported ERP lines */
  job_card: string | null;
  item_id: string;
  item_name: string;
  qty: number;
  uom: string;
  sqm: number | null;
  roll_id: string | null;
  /** Rupees, 2 decimals */
  rate: number;
  /** Rupees, 2 decimals */
  value: number;
  issued_to: string;
  source: "app" | "erp_import";
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface Roll {
  /** R-YYYY-#### */
  id: string;
  item_id: string;
  item_name: string;
  width_mm: number;
  length_m: number;
  balance_m: number;
  source: "grn" | "slit" | "opening";
  source_ref: string;
  received_on: string;
  status: "in_stock" | "partly_issued" | "consumed";
  /** Job cards */
  issued_to: string[];
  location: string;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface SlitOutput {
  width_mm: number;
  count: number;
  roll_ids: string[];
}

export interface Slitting {
  /** SLT-#### */
  id: string;
  date: string;
  jumbo_roll_id: string;
  item_name: string;
  jumbo_width_mm: number;
  length_m: number;
  outputs: SlitOutput[];
  used_width_mm: number;
  trim_mm: number;
  /** trim_mm / jumbo_width_mm */
  trim_pct: number;
  /** > slit_tol */
  trim_flag: boolean;
  /** Rupees, 2 decimals */
  trim_value: number;
  operator: string;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface PartyLaminateRow {
  /** PLM-#### */
  id: string;
  date: string;
  client_id: string;
  client_name: string;
  movement: "in" | "out";
  laminate: string;
  width_mm: number;
  qty_m: number;
  job_card: string | null;
  /** Party balance after this row */
  balance_m: number;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface PartyLaminateResponse {
  as_of: string;
  balances: {
    client_id: string;
    client_name: string;
    laminate: string;
    balance_m: number;
  }[];
  rows: PartyLaminateRow[];
}

export interface InkAllocationRow {
  job_card: string;
  client_name: string;
  est_ink_kg: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  share_pct: number;
  /** Rupees, 2 decimals */
  allocated_value: number;
}

export interface InkAllocation {
  month: string;
  /** Ink/varnish issued without job card */
  pool_value: number;
  /** Rupees, 2 decimals */
  estimate_value: number;
  /** (pool - estimate) / estimate */
  variance_pct: number;
  /** |variance| > ink_tol */
  ink_flag: boolean;
  rows: InkAllocationRow[];
}

export interface DataQualityCheck {
  key: string;
  label: string;
  count: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  pct: number | null;
  /** Rupees, 2 decimals */
  value: number | null;
  severity: "high" | "medium" | "low";
  link: string;
}

export interface DateFix {
  source_row: number;
  doc_no: string;
  raw: string;
  excel_read_as: string | null;
  fixed_to: string;
}

export interface DataQuality {
  period_from: string;
  period_to: string;
  source: string;
  issue_lines: number;
  issue_lines_without_jc: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  pct_without_jc: number;
  /** Rupees, 2 decimals */
  value_without_jc: number;
  date_fixes: {
    count: number;
    examples: DateFix[];
  };
  checks: DataQualityCheck[];
}

export interface Stop {
  reason: string;
  minutes: number;
}

export interface Run {
  /** RUN-##### */
  id: string;
  job_card: string;
  client_name: string;
  machine_id: string;
  machine_name: string;
  machine_type: "press" | "offline";
  shift: "day" | "night";
  operator: string;
  start: string;
  end: string | null;
  hours: number | null;
  status: "running" | "ended";
  /** Live counter while running */
  printed_qty: number;
  required_m: number | null;
  used_m: number | null;
  /** used - required */
  wastage_m: number | null;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  wastage_pct: number | null;
  /** wastage_pct > wastage_tol */
  wastage_flag: boolean;
  overprod_flag: boolean;
  /** Rupees, 2 decimals */
  hour_rate: number;
  /** hours * hour_rate */
  crew_cost: number | null;
  stops: Stop[];
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface RunStart {
  job_card: string;
  machine_id: string;
  operator: string;
  shift: "day" | "night";
}

export interface RunEnd {
  printed_qty: number;
  used_m: number;
  stops?: Stop[];
  end?: string;
}

export interface PressUnit {
  unit: number;
  colour: string;
  anilox_lpi: number;
  anilox_bcm: number;
  plate_id: string | null;
  ink_item_id: string | null;
}

export interface PressSetup {
  job_card: string;
  machine_id: string;
  machine_name: string;
  web_width_mm: number;
  ups_across: number;
  ups_along: number;
  repeat_mm: number;
  die_id: string | null;
  units: PressUnit[];
  speed_target_mpm: number;
  est_ink_kg: number;
  notes: string;
  updated_at: string;
  updated_by: string;
}

export interface PressSetupInput {
  job_card: string;
  machine_id: string;
  web_width_mm: number;
  die_id?: string | null;
  units: PressUnit[];
  speed_target_mpm?: number;
  notes?: string;
}

export interface OeeMachine {
  machine_id: string;
  machine_name: string;
  planned_hours: number;
  run_hours: number;
  downtime_hours: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  availability: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  performance: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  quality: number;
  /** availability * performance * quality */
  oee: number;
  top_loss: string;
  /** Rupees, 2 decimals */
  hour_rate: number;
}

export interface Oee {
  month: string;
  from: string;
  to: string;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  plant_oee: number;
  machines: OeeMachine[];
}

export interface MorningMachine {
  machine_id: string;
  machine_name: string;
  jobs: string[];
  runs: number;
  printed_qty: number;
  required_m: number;
  used_m: number;
  wastage_m: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  wastage_pct: number;
  run_hours: number;
  downtime_min: number;
  mtd_printed_qty: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  mtd_wastage_pct: number;
}

export interface MorningReport {
  /** Report date */
  date: string;
  /** Production day covered (yesterday) */
  for_date: string;
  machines: MorningMachine[];
  totals: {
    printed_qty: number;
    used_m: number;
    wastage_m: number;
    /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
    wastage_pct: number;
    run_hours: number;
  };
  highlights: BriefItem[];
}

/** One SSE `data:` payload */
export interface CounterTick {
  run_id: string;
  ts: string;
  count: number;
  metres: number;
  speed_mpm: number;
  status: "running" | "stopped" | "ended";
}

export interface Defect {
  type: string;
  qty: number;
}

export interface QcRow {
  /** QC-##### */
  id: string;
  date: string;
  job_card: string;
  client_name: string;
  run_id: string | null;
  checked: number;
  approved: number;
  rejected: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  rejection_pct: number;
  decision: "Approved" | "Approved with Deviation" | "Hold" | "Rework" | "Rejected";
  /** false for Hold/Rework/Rejected */
  counts_as_approved: boolean;
  defects: Defect[];
  inspector: string;
  notes: string;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface QcCreate {
  date: string;
  job_card: string;
  run_id?: string | null;
  checked: number;
  approved: number;
  rejected: number;
  decision: "Approved" | "Approved with Deviation" | "Hold" | "Rework" | "Rejected";
  defects?: Defect[];
  inspector: string;
  notes?: string;
}

export interface Dispatch {
  /** DC-#### */
  id: string;
  date: string;
  job_card: string;
  client_id: string;
  client_name: string;
  qty: number;
  boxes: number;
  vehicle_no: string;
  transporter: string;
  /** Rupees, 2 decimals */
  freight: number;
  lr_no: string;
  qc_approved: number;
  dispatched_before: number;
  /** qc_approved - cumulative */
  balance_after: number;
  status: "dispatched" | "invoiced";
  invoice_id: string | null;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface DispatchCreate {
  date: string;
  job_card: string;
  qty: number;
  boxes?: number;
  vehicle_no: string;
  transporter: string;
  /** Rupees, 2 decimals */
  freight: number;
  lr_no?: string;
}

export interface Invoice {
  /** INV-#### */
  id: string;
  date: string;
  client_id: string;
  client_name: string;
  job_card: string;
  dispatch_id: string | null;
  qty: number;
  /** Rupees, 2 decimals */
  rate: number;
  /** qty * rate */
  taxable: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  gst_rate: number;
  /** Rupees, 2 decimals */
  gst: number;
  /** Rupees, 2 decimals */
  total: number;
  /** Rupees, 2 decimals */
  received: number;
  /** Rupees, 2 decimals */
  outstanding: number;
  /** date + client credit days */
  due_date: string;
  days_past_due: number;
  bucket: "not_due" | "1_30" | "31_60" | "61_90" | "90_plus";
  status: "draft" | "open" | "part_paid" | "paid";
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface InvoiceListResponse {
  /** Rupees, 2 decimals */
  total_outstanding: number;
  items: Invoice[];
}

export interface DebtorRow {
  client_id: string;
  client_name: string;
  credit_days: number;
  /** Rupees, 2 decimals */
  outstanding: number;
  /** Outstanding by days past due */
  buckets: {
    /** Rupees, 2 decimals */
    not_due: number;
    /** Rupees, 2 decimals */
    "1_30": number;
    /** Rupees, 2 decimals */
    "31_60": number;
    /** Rupees, 2 decimals */
    "61_90": number;
    /** Rupees, 2 decimals */
    "90_plus": number;
  };
  oldest_due_date: string | null;
  max_days_past_due: number;
  lock_status: "ok" | "at_risk" | "locked";
  locks_on: string | null;
  locked_since: string | null;
  last_receipt_date: string | null;
  promise: {
    date: string;
    /** Rupees, 2 decimals */
    amount: number;
  } | null;
}

export interface Debtors {
  as_of: string;
  grace_days: number;
  totals: {
    /** Rupees, 2 decimals */
    outstanding: number;
    /** Rupees, 2 decimals */
    overdue: number;
    /** Rupees, 2 decimals */
    at_risk: number;
    /** Rupees, 2 decimals */
    locked: number;
    /** Outstanding by days past due */
    buckets: {
      /** Rupees, 2 decimals */
      not_due: number;
      /** Rupees, 2 decimals */
      "1_30": number;
      /** Rupees, 2 decimals */
      "31_60": number;
      /** Rupees, 2 decimals */
      "61_90": number;
      /** Rupees, 2 decimals */
      "90_plus": number;
    };
  };
  clients: DebtorRow[];
}

export interface ReleaseLockRequest {
  reason: string;
}

export interface ReleaseLockResult {
  client_id: string;
  lock_status: "ok" | "at_risk" | "locked";
  released_by: "owner";
  released_at: string;
  reason: string;
  /** Lock re-applies after this date if still unpaid */
  valid_until: string;
  audit_id: string;
}

export interface Collection {
  /** COL-#### */
  id: string;
  date: string;
  client_id: string;
  client_name: string;
  invoice_ids: string[];
  mode: "call" | "whatsapp" | "email" | "visit";
  contact: string;
  note: string;
  promise_date: string | null;
  /** Rupees, 2 decimals */
  promise_amount: number | null;
  status: "open" | "kept" | "broken";
  next_follow_up: string | null;
  by: string;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface CollectionCreate {
  date: string;
  client_id: string;
  invoice_ids?: string[];
  mode: string;
  contact?: string;
  note: string;
  promise_date?: string | null;
  /** Rupees, 2 decimals */
  promise_amount?: number | null;
  next_follow_up?: string | null;
}

export interface SupplierBill {
  /** SB-#### */
  id: string;
  bill_no: string;
  date: string;
  /** Rupees, 2 decimals */
  amount: number;
  /** Rupees, 2 decimals */
  paid: number;
  /** Rupees, 2 decimals */
  balance: number;
  due_date: string;
  /** negative = overdue */
  days_to_due: number;
  status: "open" | "part_paid" | "paid" | "overdue";
  grn_ids: string[];
}

export interface CreditorRow {
  vendor_id: string;
  vendor_name: string;
  msme: boolean;
  credit_days: number;
  effective_credit_days: number;
  /** Rupees, 2 decimals */
  outstanding: number;
  next_due_date: string | null;
  bills: SupplierBill[];
}

export interface Creditors {
  as_of: string;
  totals: {
    /** Rupees, 2 decimals */
    outstanding: number;
    /** Rupees, 2 decimals */
    overdue: number;
    /** Rupees, 2 decimals */
    due_7d: number;
    /** Rupees, 2 decimals */
    msme_due_7d: number;
  };
  vendors: CreditorRow[];
}

export interface PaymentCreate {
  vendor_id: string;
  date: string;
  /** Rupees, 2 decimals */
  amount: number;
  mode: "neft" | "rtgs" | "cheque" | "upi";
  ref?: string;
}

export interface Payment {
  /** PAY-#### */
  id: string;
  vendor_id: string;
  vendor_name: string;
  date: string;
  /** Rupees, 2 decimals */
  amount: number;
  mode: string;
  ref: string;
  /** FIFO: oldest bill first */
  allocations: {
    bill_id: string;
    bill_no: string;
    /** Rupees, 2 decimals */
    applied: number;
    /** Rupees, 2 decimals */
    balance_after: number;
  }[];
  /** Rupees, 2 decimals */
  unallocated: number;
  /** true for generated demo rows; UI shows a DEMO badge */
  is_demo: boolean;
}

export interface CashMonth {
  month: string;
  /** Rupees, 2 decimals */
  opening: number;
  /** Rupees, 2 decimals */
  inflow_collections: number;
  /** Rupees, 2 decimals */
  outflow_suppliers: number;
  /** Rupees, 2 decimals */
  outflow_salaries: number;
  /** Rupees, 2 decimals */
  outflow_overheads: number;
  /** Rupees, 2 decimals */
  outflow_gst: number;
  /** Rupees, 2 decimals */
  outflow_other: number;
  /** opening + inflow - outflows */
  closing: number;
  low_cash: boolean;
}

export interface CashPlan {
  as_of: string;
  /** Rupees, 2 decimals */
  min_cash: number;
  months: CashMonth[];
}

export interface PnlLine {
  key: "revenue" | "material" | "plates" | "ink" | "salaries" | "freight" | "admin" | "overheads" | "profit";
  label: string;
  /** Rupees, 2 decimals */
  system: number;
  /** Rupees, 2 decimals */
  tally: number;
  /** system - tally */
  diff: number;
  note: string;
}

export interface Pnl {
  month: string;
  lines: PnlLine[];
  /** Rupees, 2 decimals */
  system_profit: number;
  /** Rupees, 2 decimals */
  tally_profit: number;
  /** Rupees, 2 decimals */
  difference: number;
  matched: boolean;
  tally_imported_at: string | null;
}

export interface Agent {
  name: "import_checker" | "store_watchdog" | "wastage_watchdog" | "planning" | "collections" | "payables" | "month_end" | "owner_brief";
  label: string;
  description: string;
  schedule: string;
  enabled: boolean;
  last_run_at: string | null;
  last_status: "ok" | "failed" | null;
  open_findings: number;
}

export interface AgentsResponse {
  agents: Agent[];
  recent_runs: AgentRun[];
}

export interface AgentRun {
  /** AR-#### */
  id: string;
  agent: string;
  started_at: string;
  finished_at: string | null;
  status: "running" | "ok" | "failed";
  findings_created: number;
  finding_ids: string[];
  /** 'rules' or LLM provider used for wording */
  model: string;
  note: string;
}

export interface AgentRunRequest {
  /** Agent name or 'all' */
  agent: string;
}

export interface AgentRunResponse {
  runs: AgentRun[];
}

export interface Evidence {
  label: string;
  link: string;
}

export interface SuggestedAction {
  type: "draft_messages" | "draft_purchase_request" | "schedule_payment" | "apply_fixes" | "create_task" | "draft_journal" | "notify" | "none";
  /** Action-specific; editable via /edit */
  payload: Record<string, unknown>;
}

export interface Finding {
  /** F-#### */
  id: string;
  agent: string;
  created_at: string;
  severity: "high" | "medium" | "low";
  title: string;
  detail: string;
  evidence: Evidence[];
  suggested_action: SuggestedAction;
  status: "open" | "done" | "rejected";
  decided_by: string | null;
  decided_at: string | null;
  reason: string | null;
}

export interface FindingsResponse {
  status: "open" | "done" | "rejected";
  items: Finding[];
}

export interface RejectRequest {
  reason: string;
}

export interface EditRequest {
  payload: Record<string, unknown>;
}

export interface ApproveResult {
  finding: Finding;
  outbox: OutboxItem[];
  effects: string[];
}

export interface OutboxItem {
  /** OB-#### */
  id: string;
  created_at: string;
  agent: string;
  finding_id: string | null;
  channel: "whatsapp" | "email" | "task";
  to: string;
  subject: string;
  body: string;
  status: "draft" | "approved" | "sent" | "failed";
  approved_by: string | null;
  sent_at: string | null;
  /** Demo: nothing leaves the laptop */
  simulated: boolean;
}

export interface OutboxResponse {
  items: OutboxItem[];
}

export interface FloorMachine {
  machine_id: string;
  machine_name: string;
  status: "running" | "setup" | "stopped" | "idle";
  stop_reason: string | null;
  run_id: string | null;
  job_card: string | null;
  client_name: string | null;
  product: string | null;
  counter: number;
  target: number;
  /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
  progress_pct: number;
  speed_mpm: number;
  metres_run: number;
  operator: string | null;
  shift: "day" | "night";
  started_at: string | null;
  eta: string | null;
  next_job_card: string | null;
  alert: string | null;
}

export interface FloorBoard {
  as_of: string;
  shift: "day" | "night";
  machines: FloorMachine[];
  today: {
    printed_qty: number;
    jobs_done: number;
    /** Fraction 0..1 (0.087 = 8.7%), 4 decimals */
    wastage_pct: number;
  };
  ticker: string[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  message: string;
  history?: ChatMessage[];
  role?: "owner" | "ppic" | "design" | "store" | "production" | "qc" | "dispatch" | "accounts" | "marketing";
}

export type ChatAction = {
  type: "navigate";
  /** Frontend route */
  to: string;
} | {
  type: "draft";
  /** e.g. collection, issue, enquiry */
  entity: string;
  endpoint: string;
  payload: Record<string, unknown>;
  summary: string;
};

export interface ChatSource {
  label: string;
  link: string | null;
}

export interface ChatResponse {
  reply: string;
  actions: ChatAction[];
  sources: ChatSource[];
}

export interface ChatSuggestions {
  role: "owner" | "ppic" | "design" | "store" | "production" | "qc" | "dispatch" | "accounts" | "marketing";
  suggestions: ({
    text: string;
    lang: "en" | "hi";
  })[];
}

// ---- v0.2 multi-tenant (SPEC 6). Endpoints below are `x-status: planned` until their backend task lands. ----

export type CompanyStatus = "onboarding" | "parallel_run" | "live" | "paused";

export interface CompanyRef {
  /** CO-### */
  id: string;
  name: string;
  /** Web address name, e.g. prolabels */
  slug: string;
}

export interface AuthOtpRequest {
  company_slug: string;
  /** Mobile number or e-mail */
  login: string;
}

export interface AuthOtpResult {
  sent: boolean;
  channel: "sms" | "email";
  masked_to: string;
  expires_in_s: number;
  /** Only in AUTH_MODE=demo; null in token mode */
  demo_otp: string | null;
}

export interface AuthLoginRequest {
  company_slug: string;
  login: string;
  /** 6 digits */
  otp: string;
}

export interface AuthUser {
  /** U-#### */
  id: string;
  name: string;
  login: string;
  role: AnyRole;
}

export interface AuthSession {
  /** Send as `Authorization: Bearer <token>`. Claims company_id, user_id, role, exp. */
  token: string;
  token_type: "Bearer";
  expires_at: string;
  user: AuthUser;
  /** null for platform_admin */
  company: CompanyRef | null;
}

export interface AuthMe {
  user: AuthUser;
  company: CompanyRef | null;
  /** demo = a call without a token acts as the Pro Labels owner */
  auth_mode: "demo" | "token";
  expires_at: string | null;
}

export interface LogoutResult {
  ok: boolean;
}

export interface Company {
  id: string;
  name: string;
  slug: string;
  city: string | null;
  state: string | null;
  status: CompanyStatus;
  /** Active users */
  users: number;
  /** Always true */
  isolation: boolean;
  last_import_at: string | null;
  ai_budget_month: number;
  ai_used_month: number;
  /** Fraction 0..1 */
  ai_used_pct: number;
  cost_month: number;
  created_on: string;
  is_demo: boolean;
}

export interface CompanyList {
  items: Company[];
  totals: {
    companies: number;
    live: number;
    parallel_run: number;
    onboarding: number;
    users: number;
    cost_month: number;
    ai_used_month: number;
  };
}

export interface CompanyCreate {
  name: string;
  /** ^[a-z0-9-]{3,30}$, unique */
  slug: string;
  city?: string;
  state?: string;
  gstin?: string | null;
  admin_name: string;
  admin_login: string;
  /** Default 1000 */
  ai_budget_month?: number;
}

export interface CompanyCreated {
  company: Company;
  admin: CompanyUser;
}

export interface ImportCheck {
  rule: string;
  status: "ok" | "warn" | "error";
  count: number;
  message: string;
}

export interface ImportSheet {
  sheet: "clients" | "vendors" | "items" | "machines" | "opening_stock" | "unpaid_invoices";
  rows: number;
  /** Saved for the company */
  good: number;
  /** Not saved; each has a line in `fixes` */
  held_back: number;
  status: "ok" | "warn" | "error";
  checks: ImportCheck[];
}

export interface ImportFix {
  sheet: string;
  row: number;
  column: string;
  value: string | null;
  problem: string;
  fix: string;
}

export interface ImportResult {
  /** IMP-#### */
  import_id: string;
  company_id: string;
  file_name: string;
  at: string;
  status: "ok" | "partial" | "failed";
  sheets: ImportSheet[];
  fixes: ImportFix[];
  totals: { rows: number; good: number; held_back: number };
}

export interface CostLine {
  key: string;
  label: string;
  /** shared = split by active users; per_use = charged to the company that used it */
  basis: "shared" | "per_use";
  monthly: number;
  note: string;
}

export interface CompanyUsage {
  company_id: string;
  name: string;
  users: number;
  saves: number;
  pos_read: number;
  chats: number;
  files: number;
  ai_calls: number;
  ai_cost: number;
  ai_budget_month: number;
  ai_used_pct: number;
  shared_cost: number;
  direct_cost: number;
  total_cost: number;
}

export interface Usage {
  /** YYYY-MM */
  month: string;
  currency: "INR";
  cost_lines: CostLine[];
  total_cost: number;
  companies: CompanyUsage[];
  /** Estimated cost per company as companies grow */
  growth: { companies: number; cost_per_company: number }[];
  is_estimate: boolean;
}

export interface CompanyProfile {
  id: string;
  name: string;
  slug: string;
  gstin: string | null;
  city: string | null;
  state: string | null;
  status: CompanyStatus;
  plan: string;
  users: number;
  created_on: string;
  ai_budget_month: number;
  ai_used_month: number;
  ai_used_pct: number;
  /** Warn at this fraction (0.8) */
  ai_alert_pct: number;
  /** true = AI answers fall back to deterministic text until next month */
  ai_over_budget: boolean;
}

export interface CompanyUser {
  id: string;
  name: string;
  login: string;
  role: CompanyRole;
  device: string | null;
  sign_in: "otp_phone" | "otp_email";
  last_active_at: string | null;
  status: "active" | "invited" | "disabled";
}

export interface CompanyUserList {
  items: CompanyUser[];
  totals: { active: number; invited: number; disabled: number };
}

export interface UserInvite {
  name: string;
  login: string;
  role: CompanyRole;
}

export interface UserUpdate {
  role?: CompanyRole;
  status?: "active" | "disabled";
}

export interface Connection {
  key: "erp" | "tally" | "po_inbox" | "whatsapp";
  label: string;
  status: "connected" | "demo" | "not_connected" | "error";
  detail: string;
  last_sync_at: string | null;
}

export interface ConnectionList {
  items: Connection[];
}

/** Response type per endpoint key (same keys as fixtures/index.json, without query). */
export interface Endpoints {
  "GET /api/health": Health;
  "GET /api/search": SearchResponse;
  "GET /api/settings": Settings;
  "PUT /api/settings": Settings;
  "POST /api/feedback": Feedback;
  "GET /api/feedback": Feedback[];
  "GET /api/dashboard/summary": DashboardSummary;
  "GET /api/alerts": AlertsResponse;
  "GET /api/agents/brief": AgentBrief;
  "GET /api/clients": Client[];
  "GET /api/clients/{id}": ClientDetail;
  "GET /api/vendors": Vendor[];
  "GET /api/items": Item[];
  "GET /api/machines": Machine[];
  "GET /api/enquiries": Enquiry[];
  "POST /api/enquiries": Enquiry;
  "POST /api/enquiries/{id}/quote": Quote;
  "POST /api/enquiries/{id}/status": Enquiry;
  "GET /api/marketing/summary": MarketingSummary;
  "GET /api/jobs": JobListResponse;
  "GET /api/jobs/{job_card}": Job;
  "POST /api/jobs": Job;
  "POST /api/jobs/from-po": PoDraft;
  "GET /api/planning/material-summary": MaterialSummary;
  "GET /api/design": Design[];
  "GET /api/design/{job_card}": Design;
  "PUT /api/design/{job_card}": Design;
  "GET /api/plates": Plate[];
  "GET /api/dies": Die[];
  "GET /api/jobs/{job_card}/360": Job360;
  "GET /api/store/summary": StoreSummary;
  "GET /api/store/stock": StockResponse;
  "GET /api/store/grns": Grn[];
  "POST /api/store/grns": Grn;
  "GET /api/store/issues": Issue[];
  "POST /api/store/issues": Issue;
  "GET /api/store/rolls": Roll[];
  "GET /api/store/slitting": Slitting[];
  "GET /api/store/party-laminate": PartyLaminateResponse;
  "GET /api/store/ink-allocation": InkAllocation;
  "GET /api/store/data-quality": DataQuality;
  "GET /api/production/runs": Run[];
  "POST /api/production/runs/start": Run;
  "POST /api/production/runs/{id}/end": Run;
  "GET /api/production/press-setup/{job_card}": PressSetup;
  "POST /api/production/press-setup": PressSetup;
  "GET /api/production/oee": Oee;
  "GET /api/production/morning-report": MorningReport;
  "GET /api/production/counter/stream": CounterTick;
  "GET /api/qc": QcRow[];
  "POST /api/qc": QcRow;
  "GET /api/dispatch": Dispatch[];
  "POST /api/dispatch": Dispatch;
  "GET /api/dispatch/{id}/challan.pdf": Blob;
  "GET /api/invoices": InvoiceListResponse;
  "POST /api/invoices/draft-from-dispatch/{dispatch_id}": Invoice;
  "POST /api/invoices/{id}/issue": Invoice;
  "GET /api/debtors": Debtors;
  "POST /api/clients/{id}/release-lock": ReleaseLockResult;
  "GET /api/collections": Collection[];
  "POST /api/collections": Collection;
  "GET /api/creditors": Creditors;
  "POST /api/payments": Payment;
  "GET /api/cashplan": CashPlan;
  "GET /api/pnl": Pnl;
  "GET /api/agents": AgentsResponse;
  "GET /api/agents/findings": FindingsResponse;
  "POST /api/agents/run": AgentRunResponse;
  "POST /api/agents/findings/{id}/approve": ApproveResult;
  "POST /api/agents/findings/{id}/reject": Finding;
  "POST /api/agents/findings/{id}/edit": Finding;
  "GET /api/outbox": OutboxResponse;
  "GET /api/floor/board": FloorBoard;
  "POST /api/chat": ChatResponse;
  "GET /api/chat/suggestions": ChatSuggestions;
  "POST /api/auth/otp": AuthOtpResult;
  "POST /api/auth/login": AuthSession;
  "POST /api/auth/logout": LogoutResult;
  "GET /api/auth/me": AuthMe;
  "GET /api/platform/companies": CompanyList;
  "POST /api/platform/companies": CompanyCreated;
  "POST /api/platform/companies/{id}/import": ImportResult;
  "GET /api/platform/usage": Usage;
  "GET /api/company/profile": CompanyProfile;
  "GET /api/company/users": CompanyUserList;
  "POST /api/company/users": CompanyUser;
  "PUT /api/company/users/{id}": CompanyUser;
  "GET /api/company/connections": ConnectionList;
}
