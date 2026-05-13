# Order Email Automation — Setup Checklist

One-time setup. Takes about 15 minutes end-to-end.

---

## 1. Create a GitHub fine-grained PAT

1. Go to **GitHub → Settings → Developer Settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Set a name like `FoodlandOrderBot`.
3. **Resource owner:** your account (or the org that owns the repo).
4. **Repository access:** Only select repositories → `foodland_wudinna`.
5. **Permissions → Contents:** Read and write.
6. All other permissions: leave as No access.
7. Click **Generate token** and copy the value — you'll paste it in step 4.

---

## 2. Create the Apps Script project

1. Open [script.google.com](https://script.google.com) in the **same Google account that owns the Gmail inbox** you want to watch.
2. Click **New project**.
3. Rename it to something recognisable (e.g. `FoodlandOrderBot`).
4. Delete the placeholder `function myFunction() {}` in the editor.
5. Open `order_email_automation.gs` from this folder, copy the entire contents, and paste it into the editor.
6. Click **Save** (Ctrl+S).

---

## 3. Grant Google permissions (first-run consent)

> Apps Script won't connect to Gmail or the internet until you approve the scopes at least once.

1. In the editor, select the function `testDateLogic` from the function dropdown (top toolbar).
2. Click **Run**.
3. A popup will ask you to review permissions — click **Review permissions**.
4. Choose your Gmail account.
5. You'll see a warning ("Google hasn't verified this app") — click **Advanced → Go to FoodlandOrderBot (unsafe)**.
6. Click **Allow**.
7. Check the **Execution log** at the bottom — you should see something like:
   ```
   Cycle date would be: 2026-05-14
   ```

---

## 4. Set Script Properties (credentials)

1. In the editor, go to **Project Settings** (gear icon, left sidebar).
2. Scroll down to **Script Properties** and click **Edit script properties**.
3. Add the following four properties (click **Add property** for each):

| Property key    | Value                                        |
|-----------------|----------------------------------------------|
| `GITHUB_TOKEN`  | The PAT you generated in step 1              |
| `GITHUB_OWNER`  | Your GitHub username (e.g. `fabio-tavares`)  |
| `GITHUB_REPO`   | `foodland_wudinna`                           |
| `GITHUB_BRANCH` | `main`                                       |

4. Click **Save script properties**.

---

## 5. Test the GitHub connection

1. Select the function `testGitHubConnection` from the dropdown.
2. Click **Run**.
3. Check the execution log — expected output:
   ```
   GitHub connection test: HTTP 200
   Files in 03_model/inputs: specials_..., stock_on_hand_...
   ```
   If you see HTTP 401, the token is wrong. If you see HTTP 404, check `GITHUB_OWNER` and `GITHUB_REPO`.

---

## 6. Set the time-driven trigger

1. In the left sidebar, click the **clock icon** (Triggers).
2. Click **+ Add Trigger** (bottom right).
3. Configure:
   - **Function to run:** `processOrderEmails`
   - **Deployment:** Head
   - **Event source:** Time-driven
   - **Type:** Minutes timer
   - **Interval:** Every 5 minutes
4. Click **Save**.

Google will ask for permission again — approve it.

---

## 7. End-to-end test

1. In your Gmail inbox, forward one of the historical specials or SOH emails from the correct sender address **to yourself** — or simply find a real one if it exists and make sure it's **unread**.
2. Wait up to 5 minutes (or manually run `processOrderEmails` from the editor).
3. Check:
   - **Gmail:** the test email should now be marked as read and labelled `OrderBot/Processed`.
   - **GitHub repo → `03_model/inputs/`:** the file should appear with a commit message like `auto: stock_on_hand_2026-05-14.xlsx (...)`.
   - **GitHub Actions:** the `auto_order.yml` workflow should have triggered and produced the order sheet.
4. Check the **Executions** tab in Apps Script to see the log from that run.

---

## Normal weekly operation (no action needed)

| Day       | What happens                                                          |
|-----------|-----------------------------------------------------------------------|
| Wednesday | SOH email arrives ~13:00 → script picks it up within 5 min → GH Actions runs → order sheet committed by ~13:30 |
| Wednesday | Specials email arrives (timing varies) → same flow                   |
| Friday    | SOH email arrives ~13:00 (if SOH is also sent Fridays) → same flow   |

---

## Troubleshooting

**Email not being picked up**
- Confirm the sender address exactly matches `SPECIALS_SENDER` or `SOH_SENDER` in the script.
- Check that the email is **unread** and does **not** have the `OrderBot/Processed` label.
- Run `processOrderEmails` manually from the editor and read the execution log.

**GitHub PUT fails with 409 Conflict**
- Rare — means two runs overlapped. The next 5-minute run will succeed because it will fetch the correct SHA.

**GitHub PUT fails with 422**
- Usually means `sha` was stale. Same resolution — next run corrects itself.

**Attachment committed with wrong name**
- The script uses the current Wednesday date. If an email arrives very late (e.g. late Thursday after a holiday), the date will advance to next Wednesday. This is intentional — the file belongs to the next cycle.

**Want to reprocess a message**
- Remove the `OrderBot/Processed` label from it in Gmail and mark it unread. The next trigger run will pick it up again.

---

## Script Properties reference

| Key             | Description                                    | Example                    |
|-----------------|------------------------------------------------|----------------------------|
| `GITHUB_TOKEN`  | Fine-grained PAT (Contents: read + write)      | `github_pat_...`           |
| `GITHUB_OWNER`  | GitHub username or org owning the repo         | `fabio-tavares`            |
| `GITHUB_REPO`   | Repository name (exact, case-sensitive)        | `foodland_wudinna`         |
| `GITHUB_BRANCH` | Branch to commit to (optional, default: main)  | `main`                     |
