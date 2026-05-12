# Handover Checklist — Foodland Wudinna

## Before the visit

- [ ] Create a read-only GitHub token for the client machine
  - GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
  - Repository access: `foodland-wudinna` only
  - Permission: `Contents: Read-only`
  - Save the token — you'll need it on-site

- [ ] Install Tailscale on your laptop (tailscale.com), create account, log in

---

## On-site steps (run in order)

- [ ] **Python** — install Python 3.10+, tick "Add Python to PATH"

- [ ] **OneDrive** — share the `foodland_wudinna` folder with the client's Microsoft account (edit access). Wait for full sync before continuing — the DB and model must be present.

- [ ] **Setup** — double-click `setup.bat`, verify it completes without errors

- [ ] **Git authentication** — open a terminal in the project folder and run:
  ```
  git remote set-url origin https://<TOKEN>@github.com/<your-username>/foodland-wudinna.git
  git pull
  ```
  Windows Credential Manager stores the token — client never touches this again.

- [ ] **Test update.bat** — run once to confirm pull + install cycle works

- [ ] **Transfer `.api_key`** — copy manually to the project folder (gitignored, never travels via GitHub). Required for the Suggest PG Mappings feature.

- [ ] **Tailscale** — install on client machine, log in to your Tailscale account, verify the machine appears on your Tailscale dashboard

- [ ] **Test all launchers** — Order App, Performance Panel, one import. Confirm browser opens and app loads with real data.

- [ ] **Brief the client:**
  - Double-click to launch any panel
  - Run `update.bat` when consultant asks
  - Call consultant if anything looks wrong — do not reinstall anything

---

## Ongoing — remote maintenance

| Task | How |
|---|---|
| Push a code fix | Edit on your laptop → `git push` → ask client to run `update.bat` (or run it yourself via Tailscale) |
| Update the model | DB syncs to your laptop via OneDrive → retrain locally → drop new `.pkl` into the OneDrive folder → syncs to client silently |
| Fix an infra issue | Connect via Tailscale → open terminal → fix → disconnect |
| Add a Python package | Add to `requirements.txt` → push → client runs `update.bat` (pip install runs automatically) |
