# Client demo script (v0.2)

A 25-minute walkthrough in three parts. Rehearse it twice before the demo.

- **Part A · One order, start to finish (15 min):** sign in as Pro Labels and follow one order, **Fresh Juice Co., 50,000 labels at Rs 0.60 (job JC-1301)**, through every screen.
- **Part B · Many companies, one app (5 min):** a second label company signs in to the same app and sees only its own data.
- **Part C · Platform and cost (5 min):** our own admin view: all companies, adding a new one, and what it costs to run.

All companies except Pro Labels are **made up** for the demo (synthetic data, no real people).

**Live or mock?** Each Part B / C scene is marked:
- **Works today** = works now in mock mode (`npm run dev`) and in live mode.
- **Needs B1 #53** = the API login and company guard must be live to show it for real.
- **Needs B2 #54** = the platform and company-admin API must be live to show real numbers.

Until those tasks are merged, the screens use the contract sample data. That is fine: say "sample data for this screen" and continue.

## Demo logins

The OTP is always **123456**. On the login screen, open **Demo logins (OTP 123456)** and click a name to fill the form.

| Who | Company web address | Login |
|---|---|---|
| Pro Labels owner (company #1, `CO-001`) | `prolabels` | `+91 90000 00001` |
| Sunrise Flexo Prints owner (`CO-002`, made up) | `sunriseflexo` | `+91 90000 00201` |
| Nilgiri Label Works owner (`CO-003`, made up) | `nilgirilabels` | `+91 90000 00301` |
| Platform admin (us, no company) | `platform` (the screen sends no company) | `admin@platform.example` |

These are the real demo users in the backend (made-up people), so they work in mock and live mode; `run-demo` / `reset-demo` print the full list. Pro Labels store is `+91 90000 00005`, Sunrise store `+91 90000 00202`. (Mock mode also accepts the old short form `<role>@<company>.demo`.)

## Before the demo (15 min)

1. Get the latest code: `git checkout dev && git pull`
2. Put the client files in `data/raw/` (local only, never committed).
3. Rebuild the demo database: `.\reset-demo.cmd`
   The database now has a `company_id` on every row and three companies, so an old `data/demo.db` will not work. Always reset after pulling.
4. Start everything: `.\run-demo.cmd` (it prints the web and API addresses; stop with `.\stop-demo.cmd`).
5. AI: put a free Gemini key in `.env` (`GEMINI_API_KEY=...`, `AI_MODE=cloud`). Without a key the chatbot still answers the scripted questions through its built-in fallback.
6. Sign in once with each login in the table above, and click every screen, so the first load is warm. Then sign out.
7. Close other heavy apps. Keep the backup video ready in case the laptop or network fails.

## Part A · One order, start to finish (scene → what to click → what to say)

| # | Screen | Click | Say |
|---|---|---|---|
| A0 | Login | Company `prolabels` → `+91 90000 00001` → Send OTP → `123456` → Sign in | "Each company signs in at its own web address with a one-time password." |
| A0b | Header | Point at the **Pro Labels** badge; open it ("You see only Pro Labels data") | "Your company name is always on screen. Your role decides which screens you get." |
| A1 | Dashboard | Today / Month / Year, AI morning brief | "Your whole factory on one screen, live." |
| A2 | Marketing | New enquiry → quote (15-day validity) → Won | "Every enquiry, quote and win is tracked." |
| A3 | Jobs | New job from PO → drop the sample PO PDF → Confirm | "AI reads the PO; your team only checks and confirms." |
| A4 | Design | JC-1301: stages, Gallus, 4×3 ups, 5 colour units, route, die D-118 | "Design decides how it runs; planning instantly knows the paper needed (≈1,058 m)." |
| A5 | Store | Data quality tab → GRN → Issue without job card (refused) → with job card | "Your real ERP data: 28% of issues had no job card, and we fixed the date bug." |
| A6 | Production | Start run → live meter → End run | "Three taps; wastage, hours and crew cost are calculated." |
| A7 | QC | 52,000 checked / 50,900 approved / 1,100 rejected; show Hold warning | "Only approved labels can be dispatched." |
| A8 | Dispatch | Try 51,000 (refused) → 50,000 → open challan PDF | "The system enforces it." |
| A9 | Money | Invoice INV-2390, debtors ageing, locked client → owner release, cash plan, P&L vs Tally | "Bills make themselves; late payers lock automatically." |
| A10 | Job 360 | JC-1301 timeline + profit card (live: Rs 9,375, 31%) | "From the first call to profit, on one page." |
| A11 | Chatbot | The 7 questions below | "Ask anything in English or Hindi." |
| A12 | Agents Center | Approve collections reminders → Outbox; reject one with a reason | "AI works every morning; nothing happens without your approval." |
| A13 | Settings | Wastage limit 15% → 10% → back to Dashboard (new alerts) | "You set the rules." |
| A14 | Floor Board | Full screen | "Put this on the factory TV." |

### The 7 chatbot questions
1. Open JC-1301
2. Which clients get locked this week?
3. Why is JC-1240 flagged?
4. Profit from Fresh Juice this month?
5. How do I release a lock?
6. Fresh Juice ko Hindi mein reminder likho
7. Record: 10 rolls PP Silver received from Polyfilm Industries

## Part B · Many companies, one app

The point: **one app, many label companies, and each one sees only its own data** (multi-tenant from day 1).

| # | Screen | Click | Say | Status |
|---|---|---|---|---|
| B1 | Header | Company badge → **Sign out** | "Now let's be a different label company using the same app." | Works today |
| B2 | Login | Company `sunriseflexo` → `+91 90000 00201` → OTP `123456` → Sign in | "Sunrise Flexo Prints in Pune. Same app, its own web address." | Works today |
| B3 | Header + Dashboard | Point at the **Sunrise Flexo Prints** badge; open the Dashboard and Jobs | "Its own name, its own jobs, its own numbers. Nothing from Pro Labels." | Badge works today. Own data **needs B1 #53** (in mock mode every company shows the same sample numbers: show only the badge and skip the numbers) |
| B4 | Jobs / Job 360 | Search or open **JC-1301** | "This is a Pro Labels job. For Sunrise it simply does not exist: not found, not even 'no access'." | **Needs B1 #53**. In mock mode the sample job still opens, so do not show it: say "the server answers *not found* for another company's job; our locked tests check this on every change" |
| B5 | Users & connections | **Invite a user** (name, mobile, role Store) → Invite; change one user's role in the table | "The company's own owner adds people and sets roles. No call to us needed." | Works today (mock mode shows the change at once). Saved for real **needs B2 #54** |
| B6 | Users & connections | Point at Company profile, AI budget, Connections | "Its own profile, its own AI budget, its own ERP and Tally links." | Works today (sample data until **B2 #54**) |
| B7 | Settings | Read the line "These apply to Sunrise Flexo Prints only"; change the wastage limit | "Each company sets its own rules. Pro Labels' settings do not change." | Works today on screen. Kept per company **needs B1 #53** |

## Part C · Platform and cost

The point: **we run one small shared system, so the cost per company is low and falls as more companies join** (minimum cost).

| # | Screen | Click | Say | Status |
|---|---|---|---|---|
| C1 | Login | Sign out → company `platform` → `admin@platform.example` → OTP `123456` | "This is us, the platform team. We have no company of our own." | Works today |
| C2 | Companies | Read the 4 cards: 3 companies, 20 users, cost this month, **Company isolation ON** | "Three companies on one system. Isolation is always on: the database itself blocks one company from reading another's rows." | Works today (sample data until **B2 #54**) |
| C3 | Companies | Table: status (Live / Parallel run / Onboarding), AI budget bars; point at **Sunrise at 86%** (amber) | "Each company has an AI budget. At 80% the owner and we get an alarm; at 100% the AI switches to its non-AI fallback, so nothing breaks and the bill never runs away." | Works today |
| C4 | Companies | Click **Open** on a company | "We see the list and the cost, never a company's jobs, stock or money. Support access needs the company's approval." | Works today |
| C5 | Add company | Walk the **6 steps**: Company details → Rules & limits → Users & roles → Import data → Connect ERP / Tally → Parallel run → live | "A new company takes six steps. No new server, no new code." | Works today (mock); real saving **needs B2 #54** |
| C6 | Add company · Import | Upload the filled template (`.xlsx`) → show the sheet table and the **Fix list** → Download fix list | "Every row is checked. Good rows are saved for this company only. Bad rows (a short GSTIN, a unit 'roll' instead of metres) are held back with a fix list. Nothing is ever copied from another company." | Works today. Sample result: 463 rows checked, 454 saved, 9 held back. Real checks **need B2 #54** |
| C7 | Cost & usage | Point at the **Estimate** badge, then "Where the money goes" | "Server, database, storage and domain are **shared** and split by active users. AI and OTP messages are **per use**: each company pays for what it used." | Works today (sample data until **B2 #54**) |
| C8 | Cost & usage | "Usage by company" table, then the chart "Cost per company as we grow" | "The more companies join, the cheaper it gets for each one." | Works today |

**Numbers on screen (sample estimates, say "about"):**
- Total this month: about **Rs 12,140** for 3 companies, so about **Rs 4,050 per company**.
- Shared: server Rs 4,800, database Rs 2,900, storage Rs 450, domain Rs 150. Per use: AI Rs 3,680, OTP Rs 160.
- Per company: Pro Labels about Rs 5,250, Sunrise Flexo Prints about Rs 5,510, Nilgiri Label Works about Rs 1,380.
- Cost per company as we grow: 1 company about Rs 9,580 → 3 about Rs 4,050 → 10 about Rs 2,110 → 25 about Rs 1,810 → 50 about Rs 1,680 per month.
- Always say: **"These are estimates, not a bill."**

### Close

| # | Screen | Click | Say |
|---|---|---|---|
| Z | Any screen | "Suggest a change" button | "Tell us what to change, right here on each screen." |

## If something goes wrong

| Problem | Do this |
|---|---|
| Sign-in does not work | Use **Demo logins** on the login screen (OTP `123456`). If it still fails, click **Continue without signing in (demo)**: you are Pro Labels owner as in v0.1 |
| A screen shows "Sample data" | That endpoint isn't live yet (often B1 #53 / B2 #54); say "sample data for this screen" and continue |
| A Part B / C scene is not live yet | Use the mock-mode line in its Status column |
| "Your session ended" | Sign in again; the company is remembered |
| The chatbot is slow | Free AI is rate-limited; use the scripted questions (they have fallbacks) |
| The API stops | `.\stop-demo.cmd` then `.\run-demo.cmd`; or run the web app alone in mock mode (`cd apps/web && npm run dev`) |
| Data got messy during rehearsal, or errors about `company_id` | `.\reset-demo.cmd` then `.\run-demo.cmd` |
| Laptop or network fails | Play the backup video |

## After the demo
Export the "Suggest a change" notes (`GET /api/feedback`) into GitHub issues for the full build.
