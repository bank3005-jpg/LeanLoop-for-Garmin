# SETUP.md — Installation Playbook

> **If you are Claude (or another AI assistant): you are the installer.** The human has asked you to set this system up for them. Read this whole file, then guide them phase by phase. Run every step you can yourself (Notion database creation, verification calls); give the human short copy-paste blocks for the steps only they can do (cloud console, passwords). Never ask the human to type any password into the chat — passwords go into Cloud Shell or their own terminal only.

**What gets built:** the user's own private MCP server on Google Cloud Run (free tier) that connects Claude to their Garmin data (34 tools), plus Notion databases for food/training/body logs, plus a nightly job that writes their real daily calorie burn into Notion automatically. Total time: 45–60 min. Cost: ~$0/month.

---

## Phase 0 — Interview (do this first, in chat)

Collect and compute:

1. Name, height (cm), weight (kg), age, sex, timezone
2. Goal (fat loss / recomp / performance) and any event date
3. Garmin watch model (must sync to Garmin Connect) · does the account have 2FA/MFA? · **Garmin China accounts are not supported** (separate system)
4. Computer OS: Windows or macOS (needed in Phase 3)
5. Program start date (today is fine) → this becomes `D1_DATE`
6. Compute and confirm with the user: BMR (Mifflin-St Jeor), baseline TDEE (BMR × activity factor 1.2–1.4), targets: kcal range, protein 1.6–2.2 g/kg, fat ≥0.8 g/kg, carbs = remainder (3 tiers: heavy/medium/light for carb cycling), deficit target if cutting (300–600).
7. Optional but valuable: ask them to measure their hand (wrist→middle fingertip, palm width) — used to scale food photos.

## Phase 1 — Prerequisites (human checks)

- Claude plan with custom connectors support
- Notion account (free is fine) + Notion connector enabled in Claude
- Google account **with billing enabled** (console.cloud.google.com → Billing; card required, won't be charged within free tier)
- Their computer available for one step (Garmin login)

## Phase 2 — Notion structure (Claude does this via the Notion connector)

Create a parent page `HealthTracker`, then these databases under it. Record every data-source ID you get — they're needed later.

- **FoodLog** — day (title) · date (date) · kcal, p, c, f, exercise_burn, tdee_est (number) · deficit_actual (**formula**: `prop("tdee_est") - prop("kcal")` — computes itself, the server never writes it) · exercise_type (text) · sync (select with options: pending=yellow, synced=green, estimated=blue, error=red)
  > Installer note: add `deficit_actual` **after** `tdee_est` and `kcal` exist (the formula references them). If formula creation fails for any reason, create it as a plain **number** instead — the system still works fully (the server computes and writes it on number columns); it can be converted to a formula later.
- **TrainingLog** — session (title) · type (text) · date (date) · distance_km, avg_hr, max_hr, zone4_5_pct, kcal_burn_app, kcal_burn_adjusted (number) · duration, pace, training_effect, body_signals, coach_notes (text)
- **BodyMetrics** — day (title) · date (date) · w, h, bf, BMI, fatMass, leanMass, smm, bmr, score, visceral, whr (number) · source (select)
- **FoodLib** — name (title) · serving (text) · kcal, p, c, f (number) · notes (text)
- **LessonsArchive** — plain page (estimation corrections get appended here)
> ⚠️ **Never rename these database property names later** (e.g. `kcal` → `calories`). The server reads them by exact name; renaming silently breaks logging.

- **Config** — plain page, fill from the Phase 0 interview:

```
PROFILE|h={{H}}|w={{W}}|age={{AGE}}|sex={{SEX}}|bmr={{BMR}}|updated={{DATE}}
HAND|{{hand measurements or "not measured"}}
GOAL|kcal={{RANGE}}|p={{P}}g|c=carb_cycle_FUEL_FOR_TOMORROW(heavy={{CH}},medium={{CM}},light={{CL}})|f={{F}}g|deficit_target={{DEF}}
TDEE|baseline={{TDEE}}(bmr×{{FACTOR}})|training_day=baseline+adjusted_burn
CALIBRATION|bias_kcal_per_day=not_measured|last_calibrated=—
COMMON|(labeled products the user eats often — add over time)
```

Then the human creates a Notion integration: [notion.so/my-integrations](https://www.notion.so/my-integrations) → New integration → copy the **Internal Integration Secret** (starts `ntn_`, ~50 chars — NOT any shorter ID) → open the `HealthTracker` page → ⋯ menu → **Connections** → add the integration.

## Phase 3 — Garmin token (on the human's computer, NOT in the cloud)

> Why: Garmin blocks logins from cloud IPs (HTTP 429). The login must run from their home network. The resulting token works from the cloud afterwards.

**macOS (Terminal):**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
curl -LsSO https://raw.githubusercontent.com/bank3005-jpg/LeanLoop-for-Garmin/stable/gen_token.py
uv run --python 3.12 --with garminconnect gen_token.py
```

**Windows (PowerShell):**
```powershell
irm https://astral.sh/uv/install.ps1 | iex
irm https://raw.githubusercontent.com/bank3005-jpg/LeanLoop-for-Garmin/stable/gen_token.py -OutFile gen_token.py
uv run --python 3.12 --with garminconnect gen_token.py
```

They type their Garmin email/password (and MFA code if asked) **in the terminal**. Output: `token.txt` in the current folder. If 429 appears and it still fails: wait 60 minutes, try again (rate limit from repeated attempts).

## Phase 4 — Deploy the server (Google Cloud Shell)

Human opens [console.cloud.google.com](https://console.cloud.google.com) → `>_` icon (Cloud Shell) → uploads `token.txt` (⋮ → Upload) → pastes, **one block at a time**:

```bash
git clone https://github.com/bank3005-jpg/LeanLoop-for-Garmin.git ~/garmin-mcp
cd ~/garmin-mcp && git checkout stable
mv ~/token.txt .
PROJECT=$(gcloud config get-value project)
PN=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${PN}-compute@developer.gserviceaccount.com" --role="roles/cloudbuild.builds.builder" --condition=None
```

Then build the env file — **fill the three {{values}} first** (Claude: prepare this block for them with real values from Phase 2):

```bash
cd ~/garmin-mcp
python3 - <<'PY'
import json, secrets
secret = secrets.token_urlsafe(16)
open('secret.txt','w').write(secret)
vals = {
  "MCP_SECRET": secret,
  "GARMINTOKENS_B64": open('token.txt').read().strip(),
  "NOTION_TOKEN": "{{NOTION_SECRET}}",
  "NOTION_FOODLOG_DS": "{{FOODLOG_DATA_SOURCE_ID}}",
  "D1_DATE": "{{D1_DATE}}",
  "PLAYBOOK_URL": "https://raw.githubusercontent.com/bank3005-jpg/LeanLoop-for-Garmin/stable/playbook.md",
  "TDEE_BASELINE": "{{BASELINE_TDEE_FROM_PHASE_0}}",
  "PROGRESS_PAGE_ID": "{{HEALTHTRACKER_PAGE_ID}}",
  "TZ_NAME": "{{TIMEZONE}}",
}
open('env.yaml','w').write("".join(f"{k}: {json.dumps(v)}\n" for k,v in vals.items()))
print('env.yaml OK')
PY
gcloud run deploy garmin-mcp --source . --region us-central1 --allow-unauthenticated --env-vars-file env.yaml --memory 512Mi --min-instances 0
```

(Answer `y` to any prompts. First build ≈ 5 min. Ignore any "Regional Access Boundary … Gaia id not found" noise — harmless.)

Then schedulers + the final URL:

```bash
gcloud services enable cloudscheduler.googleapis.com
URL=$(gcloud run services describe garmin-mcp --region us-central1 --format 'value(status.url)')
gcloud scheduler jobs create http garmin-warm --schedule="*/5 * * * *" --uri="$URL/" --http-method=GET --location=us-central1
gcloud scheduler jobs create http garmin-closeday --schedule="15 0 * * *" --time-zone="{{TIMEZONE}}" --uri="$URL/$(cat secret.txt)/closeday" --http-method=GET --location=us-central1
echo "CONNECTOR URL (keep secret): $URL/$(cat secret.txt)/mcp"
```

**Never set `--min-instances` above 0** (that leaves the free tier, ~$8–10/month).

## Phase 5 — Connect to Claude

1. claude.ai → Settings → Connectors → **Add custom connector** → name `Garmin`, paste the connector URL. No OAuth fields.
2. Create a Claude Project (e.g. "Health Coach"). Enable the Garmin + Notion connectors in it.
3. Set the project instructions (Project page → Settings/⚙ → "Set project instructions"). **Claude: print the block below with every {{value}} already filled in from Phase 2/0 — the human should only have to copy-paste it, never edit it:**

```
At the start of any conversation about food, training, health data, or coaching,
call the `get_playbook` tool from the Garmin connector and follow the rules it
returns. My personal targets live in the Config page in Notion.
My Notion database IDs:
FoodLog={{ID}} TrainingLog={{ID}} BodyMetrics={{ID}} FoodLib={{ID}}
LessonsArchive={{ID}} Config={{ID}}
D1 (program day 1) = {{D1_DATE}}. Timezone: {{TIMEZONE}}.
```

## Phase 6 — Verify (Claude runs these in a NEW chat inside the Claude Project from Phase 5 — old chats have a stale tool list)

1. "How did I sleep last night?" → real sleep data appears
2. Send a food photo → estimate + table + auto-saved to Notion FoodLog
3. "Coach me today" → one-call snapshot verdict
4. Cloud Shell: `curl -s "$URL/$(cat secret.txt)/closeday"` → per-day statuses (`no-foodlog-row` is normal before any logging)
5. After the first nightly run: FoodLog rows get a colored `sync` tag (green=real Garmin TDEE · blue=formula estimate, no-watch day · yellow=awaiting sync · red=sync failed) and the 🔥 cumulative-deficit progress line appears both under the FoodLog database title and as a callout on the HealthTracker page. Tip: users may HIDE the `date` column in views (the title shows the date) — but never delete it; the server finds rows by it

## Updates

- Server code: maintainer pushes to `stable` → user (or their Claude) runs in Cloud Shell: `cd ~/garmin-mcp && git pull && gcloud run deploy garmin-mcp --source . --region us-central1 --allow-unauthenticated --memory 512Mi --min-instances 0` (env vars persist). Optional: set up a Cloud Build trigger on `stable` for fully automatic deploys.
- Coaching rules (playbook.md): update automatically — served live from GitHub, no user action.
- New tools appear in new chats automatically; old chats keep stale tool lists — just start a new chat.
- **Want to customize the server code?** Don't edit your local clone — automatic deploys build from GitHub and will overwrite local changes. Fork this repo, point your deployment at your fork, and merge upstream releases manually when you want them.

## Troubleshooting

| Symptom | Cause → fix |
|---|---|
| Deploy fails mentioning billing | Billing not actually enabled on the project → console.cloud.google.com → Billing → link a billing account, then redeploy |
| Windows: `irm \| iex` blocked / "running scripts is disabled" | PowerShell execution policy → run `Set-ExecutionPolicy -Scope Process Bypass` first, then retry |
| Garmin login 429 | Cloud IP or too many attempts → run token step on home computer; wait 60 min between attempts |
| `Invalid token` / all Garmin tools fail | Token expired (~1 yr) → redo Phase 3, then update `GARMINTOKENS_B64` in env.yaml and redeploy |
| Notion 401 in closeday | Wrong/rotated Notion secret → recheck it's the ~50-char `ntn_` secret; update env and redeploy |
| `no-foodlog-row` every day | Integration not connected to the HealthTracker page (⋯ → Connections) |
| 403 storage.objects.get on deploy | IAM step skipped → run the add-iam-policy-binding block, wait 1 min, redeploy |
| Claude says connector "couldn't connect" | URL must end in `/mcp` with the exact secret; watch for lookalike characters — always copy, never retype |
| Commands eaten when pasting a block containing `read` | Paste blocks exactly as given here (they avoid interactive reads); enter values only when a prompt is visible |
