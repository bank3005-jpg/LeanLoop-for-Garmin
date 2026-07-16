# Garmin Nutrition Coach

Turn Claude into your personal, data-driven health coach — self-hosted, private, ~$0/month.

Your own MCP server connects Claude to your **Garmin** wearable data (sleep, HRV, workouts, body composition — 32 tools) and your **Notion** workspace (food log, training log, body metrics). A nightly job writes your *real* daily calorie burn from Garmin into your food log automatically, so your deficit numbers are grounded in measurement, not formulas — and a built-in calibration routine checks them against your actual scale weight every two weeks.

## What you get

- 📸 **Photo food logging** — send a meal photo in Claude, get macros estimated with a documented protocol (reference-object scaling, hidden oil/sauce accounting), auto-saved to Notion
- 🌙 **Automatic day close** — at 00:15 your server pulls the finished day's true TDEE from Garmin and writes TDEE + deficit + workouts into your log. No manual steps, self-heals 3 days back
- 🏃 **Coaching on real data** — "Coach me today" (one-call readiness verdict), post-workout analysis (splits, HR zones, sleep context), weekly reviews, injury pattern tracking
- ⚖️ **Calibration loop** — every 2 weeks, logged deficit vs. actual weight change reveals your personal estimation bias, which then corrects future estimates
- 🔄 **Live-updating brain** — coaching rules ship in [`playbook.md`](playbook.md) and are fetched by your server at runtime; improvements land without you touching anything

## Architecture

```
Claude (any device) ──► your Cloud Run server (this repo, free tier)
                              ├─► Garmin Connect (your token, your data)
                              ├─► your Notion (food/training/body logs)
                              └─► playbook.md (rules, served live from GitHub)
        Cloud Scheduler ──► nightly close-day + keep-warm pings
```

Everything runs in **your** accounts. No third party sees your data. The Garmin login token is created on your own computer and stored only in your server's environment.

## Install

Open Claude, paste the link to [`SETUP.md`](SETUP.md), and say **"Set this up for me."** Claude will interview you, create the Notion structure, and walk you through the cloud steps (45–60 min, no coding knowledge needed).

Prerequisites: a Garmin watch, Notion account, Google account with billing enabled (stays in free tier), and a Claude plan with custom connectors.

## Updating

`git pull` + one deploy command (or a Cloud Build trigger on the `stable` branch for fully automatic updates). Coaching rules update live. See SETUP.md → Updates.

## Security notes

- Your server is protected by a long random secret in its URL — treat the connector URL like a password
- Garmin credentials never pass through chat; tokens live only in your Cloud Run env vars
- `stable` branch = tested releases; `main` = development

## License

MIT
