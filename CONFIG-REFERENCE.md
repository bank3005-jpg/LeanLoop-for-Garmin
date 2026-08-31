# 🧠 Config page reference

The **Config** page in Notion is the *brain* of your coach. Every current, personal, changes-over-time value lives here as plain text, and the coach reads it (via `get_config`) at the start of any food/training conversation. The split is deliberate:

- **Coaching *rules*** → [`playbook.md`](playbook.md), shared on GitHub (same for everyone, updates live).
- **Your *values*** → this Config page, private to you.

Your AI builds this during setup, but here's the full structure so you understand it and can hand-edit it. **Format:** one line per section, fields separated by `|`. **Values below are generic examples — replace with your own.**

```
CONFIG v1 (YYYY-MM-DD) — current personal values (coach reads via get_config); rules live in playbook.md
PROFILE|h=180|age=30|sex=M|w=85|bf=22%|ffm=66|smm=38|bmr=1800|inbody_score=75|visceral=10|updated=YYYY-MM-DD(InBody)|cuisine=Thai
PHASE|current=cut|goal=body_fat 22%->15%|deficit=moderate (protect muscle)|training=see PLAN below|next_inbody=~2 weeks
GOAL_ACTIVE|target=BODY FAT 15%|kcal_daily=2400 (ONE flat number every day incl rest — an avg training day's burn is baked in)|burn_baked_in=350 (avg exercise kcal already inside kcal_daily)|topup=if a day's real exercise_burn exceeds burn_baked_in, add back HALF of the excess|deficit_cap=500|kcal_floor=<your BMR>|p=160-180g (protein fixed high on a cut)|c=carb_cycle (heavy/medium/light set by tomorrow's training)|f=60-80g (the balancer that keeps kcal flat)|updated=YYYY-MM-DD
TDEE|baseline=<BMR x activity factor, e.g. 1.28> (used ONLY on no-watch days)|closeday=uses real Garmin totalKilocalories
CALIBRATION|bias_kcal_per_day=0 (updated by 'calibrate' every ~2 weeks)|last_calibrated=YYYY-MM-DD|note=prefer morning-fasted InBody fat-mass over the scale
COMMON|myshake=190/35p/9c/3f|<other foods you log often, as shorthand>
ATHLETE|<durable coaching notes about you — habits to watch, weaknesses, patterns the coach should remember>
PLAN|block=my_block|Mon=Legs A|Tue=Push+easy run|Wed=Tempo|Thu=Pull+easy run|Fri=Legs B|Sat=Long run|Sun=rest|rule=<scheduling notes>|pace=<your run paces>|cue=<form cues>
```

## What each line does
- **PROFILE** — body stats from your latest scan. Drives BMR, the calorie floor, and protein target.
- **PHASE** — what you're doing now (`cut` / `recomp` / `bulk` / `maintain`) + the goal. The coach respects this above daily whims.
- **GOAL_ACTIVE** — your calorie + macro targets. The example uses the **flat-daily-kcal** model: one number every day with an average workout baked in; on unusually big days you top up half the extra burn. *(A classic "deficit-off-TDEE" model works too — just document which one you use here so the coach follows it.)*
- **TDEE** — the fallback burn estimate for days with no watch data. Real days use Garmin's measured total.
- **CALIBRATION** — the bias number from your last `calibrate`; the coach adds it to future estimates so they self-correct.
- **COMMON** — shorthand for foods you eat a lot, so logging is instant.
- **ATHLETE** — durable notes the coach keeps about you (e.g. "skips breakfast", "easy runs too hard"). Coaching memory, not history.
- **PLAN** — your weekly training template (weekday -> session). The coach reads today's session from here and checks adherence. Update it when your goal shifts.

## How it stays current
On every new InBody scan, the coach updates PROFILE, recomputes the TDEE baseline (BMR x activity factor), resets the floor to your BMR, and re-checks protein — all in one edit. **You don't do the math; just send the scan photo.**

The **detailed exercise list** for each day (which lifts, sets, reps) lives on a separate **Training Plan** page, not in Config — Config's `PLAN` line only maps weekday -> session name.
