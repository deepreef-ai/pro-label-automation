# contract/

The shared contract between the frontend (`apps/web`) and the backend (`apps/api`). **LOCKED:** change it only through a separate PR titled `[contract] ...` that the other developer approves.

| File | What it is |
|---|---|
| `SPEC.md` | Source of truth: conventions, business rules, endpoint list, agent names |
| `openapi.yaml` | OpenAPI 3.1 with 87 operations (74 built + 13 v0.2 multi-tenant operations marked `x-status: planned`). Every operation has `x-roles`, the X-Role values allowed to call it (owner may call every company endpoint; `/api/platform/*` is `platform_admin` only). Errors use `{"detail": "..."}` with 400/401/403/404/409 |
| `schema.md` | Database tables, columns and foreign keys, plus the computed values |
| `types.ts` | TypeScript interfaces that mirror `components/schemas`, plus an `Endpoints` map from `"METHOD /path"` to the response type |
| `fixtures/*.json` | Synthetic example responses for every GET and every POST/PUT |
| `fixtures/index.json` | Maps `"METHOD /path[?query]"` to a fixture file name |

## Mock mode (`VITE_API_MODE=mock`)

`src/lib/api.ts` resolves a call without a backend, in this order:

1. **Exact key** with the query sorted by name, e.g. `GET /api/dashboard/summary?period=year`, `GET /api/jobs/JC-1240`.
2. **Template key** with the query, e.g. `GET /api/pnl?month=2026-10`.
3. **Template key** without the query, e.g. `GET /api/jobs/{job_card}`. This is the default for any id; it returns the JC-1301 story.

POST and PUT keys return the example response; mock mode does not persist anything. `GET /api/production/counter/stream` maps to an array of `CounterTick`, which mock mode replays one item every ~2 s. `GET /api/dispatch/{id}/challan.pdf` maps to a small PDF.

The live backend must return the same shapes. `tests/integration/test_api_contract.py` checks responses against `openapi.yaml`.

## The demo story (all synthetic)

Today is **2026-11-20**. The fixtures follow job **JC-1301** for Fresh Juice Co. from end to end:

- ENQ-0045 → Q-0045 → PO FJ/2026/118: 50,000 labels @ Rs 0.60.
- On the Gallus EM 280: 4x3 = 12 ups, repeat 254 mm, so 1,058.33 m are required. Store issued 1,150 m from rolls R-2026-0912 and R-2026-0913.
- Printed 52,000. Wastage 91.67 m (8.7%). The run took 3.5 h, so crew cost was Rs 2,800 at Rs 800/h.
- QC: 52,000 checked, 50,900 approved, 1,100 rejected.
- Dispatch DC-1388: 50,000 labels.
- Invoice INV-2390: Rs 35,400.
- Profit Rs 9,425 (`job_360_JC-1301.json`).

The other threads in the data:

- High-wastage job JC-1240 (18%, Gallus night shift, 2 plate-damage stops).
- 5 clients at risk of LOCK (Rs 42.6 lakh), with Coastal Seafoods Exports already LOCKED.
- An MSME bill due in 3 days.
- A PP Silver 200 mm shortage of 700 m.
- 8 open agent findings, one per agent.

Never put real client names, rates or files in fixtures. This repo is public.

### Multi-tenant story (v0.2, SPEC 6)

- **CO-001 Pro Labels** (parallel run, 8 active users) holds the whole JC-1301 story above. Its owner is Rajiv Malhotra (`U-0001`, synthetic).
- **CO-002 Sunrise Flexo Prints** (Pune, live) and **CO-003 Nilgiri Label Works** (Coimbatore, onboarding) are made up. Nilgiri's first template upload (`IMP-0007`) saved 454 rows and held back 9 with a fix list.
- **CO-004 Ganga Pack Labels** is the company created in the Add company wizard example.
- November cost: Rs 12,140.20 in total. The shared Rs 8,300 (server, database, storage, domain) is split by active users (8 / 9 / 3), and AI and OTP costs go to the company that used them. Sunrise has used 86% of its AI budget, so it shows the 80% warning.
- Login in mock and demo mode: company `prolabels`, any login, OTP `123456`.

`x-status: planned` operations are served from their fixtures in mock mode like any other operation. The locked contract test skips them until the backend task that builds them is merged; a `[contract]` PR then removes the marker.

## Changing the contract

1. Open an issue that explains the change and which screens or endpoints it affects.
2. On branch `contract/<topic>`, update `SPEC.md` if a decision changes, then `openapi.yaml`, `schema.md`, `types.ts` and the affected fixtures, all in the same PR.
3. Keep the fixtures consistent with the SPEC section 2 rules (stock, wastage, QC, dispatch ≤ approved, GST, lock, MSME, profit).
4. Check that every fixture is valid JSON, that every `index.json` entry points to an existing file, and that each fixture validates against its response schema (`jsonschema`, Draft 2020-12).
5. Title the PR `[contract] <summary>`. It needs approval from **both** developers. Frontend and backend then update in their own PRs.

Additive changes (a new optional field or a new endpoint) are safe. Renaming or removing a field, or changing a type, breaks the other side: list it under "Breaking" in the PR.
