# Pro Label Automation

An AI-powered operations system for a label-printing plant. It replaces a set of 11 linked Excel workbooks (PPIC, Store, Production, QC, Dispatch, Accounts, Design, Marketing, Creditors & Debtors, an owner MASTER dashboard and factory display boards) with **one web app**, an **owner dashboard**, a **chatbot** and **AI agents**.

> **Current goal: Demo v0.1.** A clickable, good-looking demo for the client, built only with **free tools and free API tiers**, running on a laptop and ready to move to AWS after approval.
>
> 📌 **Task board:** [Issue #20 – Demo v0.1 Task Board](../../issues/20)

---

## ⚠️ Read this first: this repository is PUBLIC

- **Never commit client data**: Excel files, PDFs, exports, databases or anything with real names, rates or amounts.
- **Never commit secrets**: API keys belong in a local `.env` file only.
- Client files and the local database live in `data/`, which is **git-ignored** and stays on your machine.
- Tests and sample fixtures use **synthetic data only** (for example the fictional *Fresh Juice Co.*).

---

## What the demo shows

| # | Screen | Purpose |
|---|---|---|
| 1 | Owner Dashboard | Today / month / year KPIs, profit, cash, alerts, AI morning brief |
| 2 | Marketing | Enquiry → quote → won/lost, sales targets |
| 3 | Jobs (PPIC) | Job register, required paper, shortage check, **AI "New job from PO"** |
| 4 | Design | Artwork → proof → approval → plates, press setup, route, plate & die store |
| 5 | Store | Receipts (GRN), issues, live stock, rolls, slitting, ink allocation |
| 6 | Production | Tablet view: runs, live counter, wastage, hours, cost, OEE |
| 7 | QC | Checked / approved / rejected, decisions, camera-defect demo |
| 8 | Dispatch | Challans, quantity limited to QC-approved |
| 9 | Money | Invoices, debtors ageing, client lock, collections, creditors (MSME), cash plan, P&L vs Tally |
| 10 | Job 360° | One job's full journey from enquiry to profit |
| 11 | Agents Center | AI findings with **Approve / Reject / Edit** |
| 12 | Floor Board | Full-screen TV view per press |
| ⭐ | Chatbot | Navigate, ask, explain, draft entries (English / Hindi), on every screen |

**Core principles**
1. **Code does the maths, AI does the rest.** Stock, cost, profit, the client lock and tolerances run in a deterministic rules engine. The LLM never calculates money.
2. **AI drafts, humans approve.** Any AI action that changes data needs a confirm click, and it's logged.
3. **The original Excel system is the rulebook.** Every formula becomes a coded rule with a test.

---

## Tech stack (all free)

| Layer | Tools |
|---|---|
| Frontend | React, Vite, Tailwind CSS, shadcn/ui, Recharts, Lucide, Framer Motion |
| Backend | Python, FastAPI, SQLAlchemy, SQLite (Postgres-ready) |
| Data | pandas, openpyxl |
| AI orchestration | LangGraph, LangChain tools |
| LLM gateway | LiteLLM with fallback: Gemini (free) → Groq (free) → OpenRouter `:free` → Hugging Face → local Ollama (Qwen 2.5 3B) |
| RAG | sentence-transformers (bge-small, CPU) + ChromaDB |
| ML | scikit-learn (anomaly detection) |
| Documents | pdfplumber + LLM structured extraction |
| Testing | pytest, hypothesis, Playwright |
| CI/CD | GitHub Actions |
| Later (after approval) | AWS (ECS, RDS Postgres, S3/CloudFront), Claude API, WhatsApp Business API |

---

## Repository layout and ownership

```
pro-label-automation/
├── contract/          🔒 Shared API spec, DB schema, sample JSON (changes need both reviewers)
├── tests/             🔒 Locked unit + integration tests
├── .github/           🔒 CI workflow, CODEOWNERS, PR template
├── apps/
│   ├── web/           Frontend: all screens (owner: Vinay)
│   │   └── e2e/       🔒 Locked smoke test
│   └── api/
│       ├── core/      Foundation: models, rules engine, ETL, LLM gateway (Task 0)
│       ├── app/       Backend API endpoints and services (owner: Yash)
│       ├── agents/    PO reader + AI agents + outbox (owner: Yash)
│       └── chat/      LangGraph chatbot + RAG (owner: Vinay)
├── infra/             Dockerfiles and compose (owner: Yash)
├── docs/              Demo script, guides, synthetic sample POs
└── data/              ⛔ Git-ignored: client files, SQLite DB, vector index
```

**Each person edits only their own folders.** The web app talks to the backend only through `contract/`, so frontend and backend can be built at the same time without waiting on each other.

> The folders above are created by **Task 0** (issues #1–#6). Until Task 0 is merged, `main` contains only this README.

---

## Getting started

### Prerequisites
- Git, **Python 3.11+**, **Node.js 20+**
- Optional for local AI mode: [Ollama](https://ollama.com) with `qwen2.5:3b`
- Free API keys (at least Gemini): Google AI Studio, Groq, OpenRouter, Hugging Face

### Clone

```bash
git clone https://github.com/deepreef-ai/pro-label-automation.git
cd pro-label-automation
```

### After Task 0 is merged

```bash
# 1. Environment
cp .env.example .env            # add your free API keys; never commit .env

# 2. Backend
cd apps/api
python -m venv .venv
.venv\Scripts\activate           # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

# 3. Client data (local only)
#    Put the client files in data/raw/ (git-ignored), then build the demo DB:
python -m core.etl.build_demo_db

# 4. Frontend
cd ../web
npm install
npm run dev                      # runs on mock data until the API is connected
```

A single `run-demo` command will start everything once issue #19 (G2) is merged.

### Run the 3-company demo (v0.2)

```powershell
.\run-demo.cmd              # SQLite: builds data/demo.db with 3 companies, starts API :8000 + web :5173
.\run-demo.cmd -Postgres    # same, but API + agent scheduler on PostgreSQL with row-level security (Docker)
.\reset-demo.cmd            # rebuild the 3-company DB between rehearsals (run once after pulling v0.2)
.\stop-demo.cmd             # stop (with -Postgres also: docker compose -f infra/docker-compose.postgres.yml down)
```
macOS/Linux: `./run-demo.sh [--postgres]`, `./reset-demo.sh`, `./stop-demo.sh`.

Demo logins (OTP is always `123456`; the scripts print this table):

| Who | Company (web address) | Login |
|---|---|---|
| Pro Labels owner | `prolabels` | `+91 90000 00001` |
| Pro Labels store | `prolabels` | `+91 90000 00005` |
| Sunrise Flexo Prints owner (made up) | `sunriseflexo` | `+91 90000 00201` |
| Nilgiri Label Works owner (made up) | `nilgirilabels` | `+91 90000 00301` |
| Platform admin | none | `admin@platform.example` |

`AUTH_MODE=demo` (default) also lets screens work without signing in (Pro Labels owner, role switcher); `AUTH_MODE=token` requires login.

### LLM providers and keys (`.env`)

All AI calls go through one gateway (`apps/api/core/llm/`, details in its README). Every provider is
optional and used only when its key is set in `.env` (copy `.env.example`; **never commit `.env` or keys**).

| Provider | Key env | Cost |
|---|---|---|
| Claude (Anthropic SDK, `claude-opus-5-5`) | `ANTHROPIC_API_KEY` | paid: ~$4 / $20 per million input / output tokens |
| Groq, Cerebras, Gemini, SambaNova, Mistral, NVIDIA, GitHub Models, OpenRouter, Hugging Face | `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `GEMINI_API_KEY`, `SAMBANOVA_API_KEY`, `MISTRAL_API_KEY`, `NVIDIA_API_KEY`, `GITHUB_MODELS_TOKEN`, `OPENROUTER_API_KEY`, `HF_TOKEN` | free tiers |
| Ollama (local) | none (`OLLAMA_URL`) | free |

- **Order:** `LLM_ORDER` (default `anthropic,groq,cerebras,gemini,sambanova,mistral,nvidia,github,openrouter,huggingface,ollama`). Claude goes first when its key is set; put the free ones first to save money.
- **More keys:** add `<KEY>_2` .. `<KEY>_9` (e.g. `GEMINI_API_KEY_2`). Calls rotate across keys; a key that hits 429/quota/5xx rests for `LLM_COOLDOWN_SECONDS` (60).
- **Speed:** `LLM_PARALLEL=2` races two providers and keeps the first answer (`1` = one at a time).
- **Models:** each provider has a `<NAME>_MODEL` override; `ANTHROPIC_EFFORT` (`low` default) trades Claude speed/cost for depth.
- **Privacy:** in cloud mode client and vendor names are replaced by aliases before any request leaves the machine (Claude included); `AI_MODE=local` uses only Ollama.

---

## How we work

### Branches and pull requests

```
main   ← stable, demo-ready; updated only by "[release] …" PRs from dev at milestones
 └── dev   ← integration branch; every feature PR targets dev
      ├── feat/web-*   ── PR ──► dev, reviewed by Yash
      └── feat/api-*   ── PR ──► dev, reviewed by Vinay
```

1. `git checkout dev && git pull`
2. `git checkout -b feat/<task>` (the branch name is given in each issue)
3. Work **only in your folders**; keep one task per PR.
4. `git pull --rebase origin dev`, run the tests locally, push, then open a PR **into `dev`** that links the issue (`Closes #<n>`).
5. CI must be green → the other person reviews and approves → squash-merge → delete the branch.
6. **Merge reviewed PRs quickly** and always branch from the latest `dev`, so nothing drifts and conflicts stay rare.

Both developers' Claude sessions follow [`CLAUDE.md`](CLAUDE.md) (folder ownership, branch flow, hard rules).

**Merge order:** Task 0 → A1 → W1–W5 (any time, mock mode) → A2 → A3 → C1 → G1 → G2 → W6 → release PR dev → main → tag `v0.1-demo`

### Task assignments

| Owner | Issues |
|---|---|
| **Vinay** (frontend + chat) | #1–#7 Foundation & CI setup · #8 W1 · #9 W2 · #10 W3 · #11 W4 · #12 W5 · #13 C1 · #14 W6 |
| **Ravi** (backend + agents, v0.1) | #15 A1 · #16 A2 · #17 A3 · #18 G1 · #19 G2 |

**Demo v0.2 (multi-tenant), Task Board #64:**

| Owner | Issues |
|---|---|
| **Vinay** (frontend + chat) | #48 H2 · #56 W1 · #57 W2 · #58 W3 · #59 C1 · #60 W4 · #62 D1 · #63 R1 |
| **Yash** (backend + agents + infra) | #47 H1 · #49 K1 · #50 K2 · #51 F1 · #52 F2 · #53 B1 · #54 B2 · #55 B3 · #61 G1 · #63 R1 |

---

## Testing and CI

A small set of **locked**, high-value tests guards everything that must never break:

| # | Test | Protects |
|---|---|---|
| 1 | `tests/unit/test_rules_golden.py` | Production maths against known answers |
| 2 | `tests/unit/test_money_rules.py` | Lock boundary, MSME due dates, FIFO payments, ageing, GST |
| 3 | `tests/unit/test_guards.py` | Dispatch ≤ QC approved, no issue without a job card, ERP date parsing, tolerance edges |
| 4 | `tests/integration/test_api_contract.py` | Every endpoint matches `contract/`; role permissions |
| 5 | `tests/integration/test_demo_flow.py` | Full enquiry-to-profit flow through the API |
| 6 | `tests/integration/test_ai_safety.py` | Read-only chat by default, drafts only, anonymisation, provider fallback, no network |
| 7 | `apps/web/e2e/smoke.spec.ts` | All screens load without errors |

**CI on every PR:** `integrity` → `backend` (lint + unit + coverage) → `integration` → `web` (typecheck, lint, build, smoke). Target: under 5 minutes.

**Tests are locked:**
- `tests/`, `apps/web/e2e/`, `.github/` and `contract/` are protected by CODEOWNERS and need the **other** person's approval.
- A PR that changes tests **together with** app code fails the `integrity` check. Test changes go in a separate `[tests] …` PR with a clear reason.
- Adding `skip`, `xfail` or `.only`, or lowering coverage, fails CI.

---

## Roadmap

| Milestone | Scope |
|---|---|
| **M0 – Foundation** | Contract, rules engine, ETL + demo data, LLM gateway, locked tests, CI, branch protection |
| **M1 – Demo build** | All screens, API, chatbot, agents |
| **M2 – Demo release v0.1** | Live end-to-end demo, rehearsal, tag `v0.1-demo` |
| **After approval** | Move to AWS, Claude API, real logins, WhatsApp, live ERP / Tally / machine data |
