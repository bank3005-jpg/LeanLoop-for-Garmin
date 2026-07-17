<p align="center">
  <img src="assets/leanloop-cover.jpg" alt="LeanLoop for Garmin — private AI nutrition & fitness coach (Garmin + Claude + Notion + Google Cloud)" width="100%">
</p>

**Turn Claude into your personal, data-driven health coach — self-hosted, private, ~$0/month.**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/Protocol-MCP-blue)](https://modelcontextprotocol.io)
[![Cloud Run](https://img.shields.io/badge/Runs%20on-Google%20Cloud%20Run-4285F4?logo=googlecloud&logoColor=white)](https://cloud.google.com/run)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](requirements.txt)

### Why LeanLoop?

Losing weight is a calorie deficit — but a deficit run **blind** burns muscle, not just fat. Lose muscle and your daily burn (TDEE) drops, so you have to eat *even less* to keep losing. That's the slow-starvation spiral that makes most diets miserable and short-lived.

LeanLoop keeps you on the healthy side of that line by giving Claude three things at once:

- 🍽️ **What you eat** — snap a photo or just type it; calories **and macros** land in Notion, and every meal is kept with its time so you can see your real eating habits, not just a daily number.
- 🔥 **What you *actually* burn** — your Garmin measures it live, every day (workouts, steps, all-day movement), so your deficit is based on your real body — not a one-size-fits-all formula that's wrong for you.
- 🌙 **How you're recovering** — sleep, HRV, stress and body battery feed the coaching, so "train hard or rest today?" fits the day you're actually having.

Because all of it already flows to Claude, there's **no more screenshotting dashboards into chat**. Just ask.

> *"Coach me today" · "How did I sleep?" · "Why did my run feel bad?" · "What are my eating patterns this week?" ·* 📸 *[photo of lunch]*

## ✨ Features

| | Feature | What it does |
|---|---|---|
| 📸 | **Photo (or text) food logging** | Snap a meal or type it → calories & macros estimated and auto-saved to Notion, with the full per-meal history (time + item) kept on the day's page for habit analysis |
| 🌙 | **Automatic day close** | Every night your server pulls the finished day's true TDEE from Garmin and writes TDEE + workouts into your log (your deficit column recalculates itself instantly — it's a Notion formula) — self-heals 3 days back, colored sync tags show status at a glance |
| 🔥 | **Progress you can see** | Cumulative deficit (≈ kg of fat) updated nightly right on your Notion food log |
| 🏃 | **Coaching on real data** | One-call readiness verdicts, post-workout analysis (splits, HR zones, sleep context), weekly reviews, injury pattern tracking |
| 📈 | **Second-by-second analysis** | FIT-file parsing: HR/pace/cadence streams + **aerobic decoupling** — the endurance metric real coaches use |
| ⚖️ | **Calibration loop** | Every 2 weeks: logged deficit vs. actual weight change reveals your personal estimation bias, which corrects all future estimates |
| 🔄 | **Live-updating brain** | Coaching rules live in [`playbook.md`](playbook.md), fetched by your server at runtime — improvements reach every user instantly, no reinstall |

## 🚀 Install (no coding needed)

1. In Claude, create a **Project** and name it **LeanLoop** (this is where your coach will live).
2. In that Project, enable the **Notion** connector (Claude needs it to build your databases).
3. Open a chat inside the Project — set the model to **Sonnet at Medium** effort for setup (lots of IDs to track; switch to Low for everyday use afterward) — and paste:

```
Read https://github.com/bank3005-jpg/LeanLoop-for-Garmin/blob/stable/SETUP.md and set this up for me
```

Claude interviews you (goals, body stats), creates your Notion databases, walks you through the cloud steps, then adds your server as a second connector and loads the coaching rules into the Project. **45–60 minutes, one time.** After setup, everyday food logging runs fine on **Sonnet Low**.

**Prerequisites:** a Garmin watch · Notion account (free) · Google account with billing enabled (stays within free tier) · **Claude Pro** (or Max/Team — needs two custom connectors at once; Free allows only one) · Windows or macOS computer for one step.

## 🏗️ Architecture

```
Claude (any device, incl. phone)
   └── your Cloud Run server  ← this repo, deployed to YOUR Google account
         ├── Garmin Connect   ← your token, created on your own computer
         ├── your Notion      ← food / training / body logs
         └── playbook.md      ← coaching rules, served live from GitHub
   Cloud Scheduler → nightly close-day job + keep-warm pings
```

**Privacy by design:** everything runs in *your* accounts. No third party — including this repo's author — ever sees your data. The server is protected by a long random secret; Garmin credentials never pass through chat.

## 🧰 What's inside (16 lean MCP tools)

**Health** `get_wellness(metric)` — sleep, HRV, stress, body battery, heart rate, SpO2, respiration, intensity minutes, hydration, blood pressure, body composition, training readiness/status · `get_daily_summary`
**Training** `get_activities` (recent or date range) · `get_activity(id, view)` — summary, splits, HR zones, FIT streams, aerobic decoupling · `get_fitness(metric)` — VO2max, race predictions, endurance/hill scores, lactate threshold, PRs, fitness age · `get_coach_snapshot` (one-call verdict data) · `analyze_activity` (one-call post-workout bundle) · `weekly_report` / `calibrate_report` (pre-computed reviews)
**Body** `get_weight_history` · `add_body_composition` (**write** InBody/DEXA scans into Garmin)
**System** `foodlog_read` / `foodlog_upsert` (direct Notion food log, meal-by-meal history) · `get_config` / `foodlib_find` (fast server-side Notion reads) · `get_playbook` (live coaching rules)

Few tools by design: a lean tool list keeps every chat's context small — grouped tools with a `metric`/`view` parameter carry the same 35 capabilities at ~half the token overhead.

## 🔄 Updating

- **Coaching rules** — update automatically (served live from this repo)
- **Server code** — `git pull` + one deploy command, or enable a Cloud Build trigger on `stable` for fully automatic deploys
- Want to customize the code? **Fork** the repo and point your deployment at your fork

## ❓ FAQ

**Is it really free?** Yes — Cloud Run free tier covers personal use many times over. The setup guide includes guardrails so you stay in it.
**Does my data go anywhere?** No. Your server, your Garmin token, your Notion. Self-hosted means self-owned.
**What if Garmin changes their API?** The community library this builds on ([python-garminconnect](https://github.com/cyberjunky/python-garminconnect)) gets patched quickly; update with one `git pull` + deploy.
**Garmin China accounts?** Not supported (separate system).
**No watch some days?** The nightly job falls back to your formula baseline and tags the day `estimated`.

## 💬 Why this exists

I'm not a programmer. I built LeanLoop together with Claude because I wanted to lose weight, get my confidence back, and just *feel better* — and I couldn't find a tracker that coached me on my **real** data instead of generic formulas. It worked for me, so I'm sharing it.

I use LeanLoop every single day and keep refining it as I go. If you hit a problem or want a feature, **[open a thread in Discussions](https://github.com/bank3005-jpg/LeanLoop-for-Garmin/discussions)** — I read everything.

## 🙏 Credits

Built on [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) by cyberjunky · [fitdecode](https://github.com/polyvertex/fitdecode) · [MCP](https://modelcontextprotocol.io) by Anthropic.

## ⚠️ Disclaimer

This is a personal tracking and coaching tool, **not medical advice or a medical device**. Calorie and macro estimates are approximations. Consult a healthcare professional for medical decisions, and stop training and seek care for any concerning symptoms.

## 📄 License

[MIT](LICENSE) — use it, fork it, share it.
