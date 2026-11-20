# Client demo script (v0.1)

A 20-minute walkthrough that follows one order, **Fresh Juice Co., 50,000 labels at Rs 0.60 (job JC-1301)**, through every screen. Rehearse it twice before the demo.

## Before the demo (15 min)

1. `git checkout dev && git pull`
2. Put the client files in `data/raw/` (local only, never committed).
3. Build a fresh demo database:
   ```bash
   set PYTHONPATH=apps/api
   python -m core.etl.build_demo_db --raw data/raw --db sqlite:///data/demo.db
   ```
4. Start the API (in its own terminal):
   ```bash
   set DATABASE_URL=sqlite:///data/demo.db
   set CORS_ORIGINS=http://localhost:5173,http://localhost:4173
   python -m uvicorn app.main:app --port 8000
   ```
5. Start the web app in live mode: `cd apps/web && npm run dev:live` → http://localhost:5173
6. AI: put a free Gemini key in `.env` (`GEMINI_API_KEY=...`, `AI_MODE=cloud`). Without a key the chatbot still answers the scripted questions through its built-in fallback.
7. Close other heavy apps. Open the app once and click every screen, so the first load is warm.
8. Keep the backup video ready in case the laptop or network fails.

## The story (scene → what to click → what to say)

| # | Screen | Click | Say |
|---|---|---|---|
| 0 | Role switcher | Owner → Store → Owner | "Each person only sees their own work." |
| 1 | Dashboard | Today / Month / Year, AI morning brief | "Your whole factory on one screen, live." |
| 2 | Marketing | New enquiry → quote (15-day validity) → Won | "Every enquiry, quote and win is tracked." |
| 3 | Jobs | New job from PO → drop the sample PO PDF → Confirm | "AI reads the PO; your team only checks and confirms." |
| 4 | Design | JC-1301: stages, Gallus, 4×3 ups, 5 colour units, route, die D-118 | "Design decides how it runs; planning instantly knows the paper needed (≈1,058 m)." |
| 5 | Store | Data quality tab → GRN → Issue without job card (refused) → with job card | "Your real ERP data: 28% of issues had no job card, and we fixed the date bug." |
| 6 | Production | Start run → live meter → End run | "Three taps; wastage, hours and crew cost are calculated." |
| 7 | QC | 52,000 checked / 50,900 approved / 1,100 rejected; show Hold warning | "Only approved labels can be dispatched." |
| 8 | Dispatch | Try 51,000 (refused) → 50,000 → open challan PDF | "The system enforces it." |
| 9 | Money | Invoice INV-2390, debtors ageing, locked client → owner release, cash plan, P&L vs Tally | "Bills make themselves; late payers lock automatically." |
| 10 | Job 360 | JC-1301 timeline + profit card (Rs 9,425, 31%) | "From the first call to profit, on one page." |
| 11 | Chatbot | The 7 questions below | "Ask anything in English or Hindi." |
| 12 | Agents Center | Approve collections reminders → Outbox; reject one with a reason | "AI works every morning; nothing happens without your approval." |
| 13 | Settings | Wastage limit 15% → 10% → back to Dashboard (new alerts) | "You set the rules." |
| 14 | Floor Board | Full screen | "Put this on the factory TV." |
| 15 | Close | "Suggest a change" button | "Tell us what to change, right here on each screen." |

### The 7 chatbot questions
1. Open JC-1301
2. Which clients get locked this week?
3. Why is JC-1240 flagged?
4. Profit from Fresh Juice this month?
5. How do I release a lock?
6. Fresh Juice ko Hindi mein reminder likho
7. Record: 10 rolls PP Silver received from Vendor X

## If something goes wrong

| Problem | Do this |
|---|---|
| A screen shows "Sample data" | That endpoint isn't live yet; say "sample data for this screen" and continue |
| The chatbot is slow | Free AI is rate-limited; use the scripted questions (they have fallbacks) |
| The API stops | Restart uvicorn; the web app keeps working in mock mode (`npm run dev`) |
| Data got messy during rehearsal | Rebuild the DB (step 3) |
| Laptop or network fails | Play the backup video |

## After the demo
Export the "Suggest a change" notes (`GET /api/feedback`) into GitHub issues for the full build.
