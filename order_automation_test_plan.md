# Order Automation — End-to-End Test Plan

Follow these steps in order. Each stage must pass before moving to the next.

---

## Stage 1 — GitHub secrets (5 min)

Before anything else, confirm all four secrets are set in the repo.

Go to **GitHub → foodland_wudinna repo → Settings → Secrets and variables → Actions**.

| Secret name        | What to put there                                              |
|--------------------|----------------------------------------------------------------|
| `ANTHROPIC_API_KEY`| Your Anthropic API key (already used by the local order app)  |
| `GMAIL_ADDRESS`    | The Gmail address that will *send* the order sheet email       |
| `GMAIL_APP_PASSWORD` | Gmail App Password for that address (not your login password) |
| `ORDER_RECIPIENTS` | Comma-separated list of who receives the order sheet          |

**Getting a Gmail App Password:**
Google Account → Security → 2-Step Verification → App passwords → create one named "FoodlandOrderBot".

---

## Stage 2 — Apps Script setup (15 min)

1. Open [script.google.com](https://script.google.com) in the Gmail account that receives the order emails.
2. Click **New project** → rename it `FoodlandOrderBot`.
3. Delete the placeholder code. Open `order_email_automation.gs` from your folder, copy all of it, paste into the editor. Save (Ctrl+S).
4. Select `testDateLogic` from the function dropdown → click **Run**.
   - A permissions popup appears → **Review permissions → Allow**.
   - Execution log should show: `SOH cycle date would be: 2026-05-XX` ✓
5. Go to **Project Settings (gear icon) → Script Properties → Edit script properties**. Add:

   | Key             | Value                          |
   |-----------------|--------------------------------|
   | `GITHUB_TOKEN`  | Your fine-grained PAT          |
   | `GITHUB_OWNER`  | Your GitHub username           |
   | `GITHUB_REPO`   | `foodland_wudinna`             |
   | `GITHUB_BRANCH` | `main`                         |

6. Select `testGitHubConnection` → **Run**.
   - Log should show: `GitHub connection test: HTTP 200` and a file listing ✓

---

## Stage 3 — Test specials date extraction (5 min)

This confirms the regex correctly reads the "Week Commencing" date out of the bulletin.

**Setup:** Make sure there is at least one unread specials email from `admin@wudinnafoodland.com.au` in the inbox. If the real one is already read, forward it to yourself from a different account — what matters is that it's unread and from that address.

1. Select `testSpecialsDateExtraction` → **Run**.
2. Check the log:
   ```
   Attachment     : Fruit & Veg No 20.doc
   Extracted cycle date : 2026-05-13
   Arrival-day fallback : 2026-05-XX
   ✓ Extraction succeeded — these differ ...
   ```
   - The extracted date should match the "Week Commencing" date in the bulletin, not the day the email arrived.
   - If the log shows "pattern not found", the script fell back to arrival-day logic — still works, just flag the bulletin format for investigation.

---

## Stage 4 — Test full Apps Script → GitHub commit (10 min)

This tests that the script correctly commits files and marks emails as read.

**Setup:** You need one unread email from each sender in the inbox:
- `admin@wudinnafoodland.com.au` (specials) — can be the real one or a forward
- `postmaster@mg.gapsolutions.com.au` (SOH) — can be the real one or a forward

1. Select `processOrderEmails` → **Run**.
2. Check the execution log — should show two `[OK]` lines, one per file.
3. Check Gmail:
   - Both emails should now be marked **read** and labelled **OrderBot/Processed** ✓
4. Check GitHub → `03_model/inputs/`:
   - `specials_2026-MM-DD.doc` (date from bulletin content) ✓
   - `stock_on_hand_2026-MM-DD.xlsx` (date from arrival Wednesday) ✓
5. Check GitHub → **Actions** tab:
   - A new workflow run named "Auto Order Sheet" should have started, triggered by the SOH push ✓

---

## Stage 5 — Watch the GitHub Actions run (5 min)

1. Click the running workflow in the Actions tab.
2. Watch each step:
   - **Locate input files** → confirms SOH path, lists all input files
   - **Generate order sheet** → LightGBM or EWMA forecast, specials matched, Excel built
   - **Send order sheet email** → `[email] Sent: FV Order Sheet — Foodland Wudinna — ...`
3. Check your inbox — the order sheet Excel should arrive within a minute of the workflow completing ✓

---

## Stage 6 — Set the live trigger (2 min)

Once Stages 1–5 all pass:

1. In the Apps Script editor, click **Triggers (clock icon) → + Add Trigger**.
2. Configure:
   - Function: `processOrderEmails`
   - Event source: Time-driven → Minutes timer → Every 5 minutes
3. Save. Google asks for permission again → Allow.

The pipeline is now live.

---

## What "live" looks like week-to-week

| When | What happens | You do nothing |
|------|-------------|----------------|
| Wed/Thu/Fri | Specials email arrives → Apps Script commits `specials_YYYY-MM-DD.doc` within 5 min | — |
| Wed ~1 PM | SOH email arrives → Apps Script commits `stock_on_hand_YYYY-MM-DD.xlsx` → GHA triggers → order sheet emailed by ~1:20 PM | — |
| Fri ~1 PM | Same as above — two specials files already in repo, FRI_TUE cycle auto-detected | — |

---

## Troubleshooting quick reference

| Symptom | Where to look | Likely cause |
|---------|--------------|--------------|
| Email not committed | Apps Script → Executions tab | Email is already read, or labelled OrderBot/Processed |
| Wrong date on specials file | Apps Script log | "Week Commencing" pattern not found — check bulletin format |
| GHA workflow not triggered | GitHub → Actions | Push trigger path mismatch, or commit was made by a bot (add `if: github.actor != 'github-actions[bot]'` if needed) |
| GHA fails at "Locate input files" | GHA step log | SOH file not yet committed, or wrong filename pattern |
| GHA fails at "Generate order sheet" | GHA step log | Missing specials file for cycle date, or model/snapshot issue |
| Order email not received | GHA step log | Wrong `ORDER_RECIPIENTS` secret, or Gmail App Password expired |
| Reprocess an email | Gmail | Remove `OrderBot/Processed` label, mark unread → next trigger picks it up |
