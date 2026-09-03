# 📖 How to use LeanLoop — User Guide

You installed it — now what? LeanLoop lives **inside your AI chat** (Claude, or ChatGPT / Codex). You don't open an app or fill forms — **you just talk to it like a coach.** This guide shows exactly what to say, based on how it's used every day.

> 🌐 **Language:** the coach mirrors you — talk in English, Thai, or a mix. Examples below show both.

---

## 🔄 The daily loop (how it actually works)

1. **You log** what you eat (and optionally workouts) — just by chatting.
2. **Your watch measures** your real burn, sleep and recovery all day.
3. **Every night** your server pulls the finished day from Garmin and writes your true calorie burn + workouts into your log — your deficit recalculates itself.
4. **You ask the coach** anything — it reads your real numbers and answers.

You manage none of this plumbing. You only **log** and **ask**.

---

## 💬 Just talk — no commands needed

Say it how you'd say it to a person. The coach interprets natural (even voice-to-text) language.

### 🍽️ Logging food — the #1 daily habit
- **Photo:** 📸 send a picture of your meal → it itemizes, estimates calories + protein/carb/fat, saves it, and shows your whole day.
- **Text:** just name it — "chicken rice, one plate" / "ข้าวมันไก่ จานนึง" · "2 boiled eggs + a banana" / "ไข่ต้ม 2 ฟอง กล้วย 1" · "whey shake" / "เวย์แก้วนึง"
- **Add the time** if it wasn't just now: "8am oats" / "เมื่อเช้า 7 โมง ข้าวโอ๊ต"
- **Fix / remove:** "the rice was half" / "ข้าวกินครึ่งเดียว" · "remove the snack" / "ลบขนมออก" · "make lunch 600 not 800" / "มื้อเที่ยงแก้เป็น 600"

Every time, it shows your **whole day as a table** (meals + total + your target). A shown table = already saved.

### 📊 Checking your day
- "how much have I eaten? what's left?" / "วันนี้กินไปเท่าไหร่ เหลือเท่าไหร่"
- "am I over on carbs / protein?" / "คาร์บ/โปรตีนเกินยัง"

### 🏃 Running / cardio (auto-logged by your watch)
- "just finished a run" / "เพิ่งวิ่งเสร็จ" → it logs / enriches the session
- "how did my run go?" / "วิ่งเมื่อกี้เป็นไง" → real analysis: pace-vs-heart-rate, where you faded, fuel + sleep context
- "should I train today — hard or easy?" / "วันนี้ซ้อมได้ไหม หนักหรือเบา" → a verdict from your readiness + sleep

### 🏋️ Weight training (log + progressive overload)
- **Before you lift:** "what's today's Push? how much weight?" / "วันนี้ Push เล่นอะไร นน เท่าไร" → it reads your **last** Push session and gives each exercise + the weight to try this time (a bit more if you hit your reps last time).
- **Log it** (set-by-set or all at once): "bench 60 4x8, shoulder 40 3x10" / "เบนช์ 60 4เซ็ต8, ไหล่ 40 3เซ็ต10" · or lazy: "push day, chest+shoulders, felt strong" (no numbers needed)
- **Tell it your effort (RIR)** when it matters — "bench 60 4x8, last set RIR2" (~2 reps left in the tank; 0 = to failure). It stores RIR in the table and uses it to decide when to add weight (clean at RIR ≥2 → go up; near failure or form broke → hold).
- **Mid-session:** "done with squats — what's next?" / "สควอทเสร็จ ต่อท่าไหน"
- 💡 Log the **actual kg** on your main lifts — that's what lets progression work.

### 🧬 Body scans (InBody / DEXA)
- 📸 send a photo of your scan → it saves every number, updates your targets, and pushes it to Garmin.
- **Do scans morning + fasted** (before food/water/training). An evening scan reads ~2–3% higher — don't panic at it; only compare same-condition scans.

### 🎯 Calibration — every ~2 weeks (the magic)
- Say **"calibrate"** → it compares what you *logged* vs your *real* fat/weight change and finds your personal estimation bias. This is what makes the numbers get **more accurate over time** and forgives an imperfect formula.

### 📅 Reviews & plan changes
- "how was my week?" / "สรุปสัปดาห์นี้" → averages + the exact days that missed target
- "I want to focus on legs / running now" / "อยากเน้นขา/วิ่ง" → it reworks your weekly plan and nutrition targets

---

## 📆 A typical day (real usage)

- **Morning:** 📸 photo of breakfast → logged (or "skipped breakfast").
- **Before the gym:** "what's today's Leg A, how much weight?" → it lists squat / lunge / leg-press with your target loads.
- **After:** "logged: squat 60 3x8 …" + "how did my run feel?"
- **Meals through the day:** photo or text each → the running table keeps your remaining calories visible.
- **Dinner:** it may ask tomorrow's training to set your carb target.
- **Overnight:** you do nothing — the server closes the day, writes your real burn, updates your deficit.
- **Every 2 weeks:** "calibrate" + an InBody photo.

---

## ✅ Tips that make it work
- **Log the moment you eat** — a photo takes 2 seconds and beats guessing later.
- **Keep easy runs easy** — it'll tell you if your "easy" runs are secretly too hard.
- **Morning-fasted scans only** for comparisons.
- **Log real weights** on lifts so progression tracks.
- After a system update, if the tool list looks stale, **start a new chat**.

---

## 🤔 No Garmin watch — can I still use it?

**Yes — in a reduced mode. A watch unlocks most of the value, but the core loop still works.**

**Works fully without a watch:**
- ✅ Food logging + macros (photo or text)
- ✅ Weight-training log + progression
- ✅ InBody / body-scan tracking
- ✅ **Calibration** — logged intake vs real weight/fat change. This is the key: even with no watch, the 2-week calibration corrects your calorie formula against reality, so your deficit stays honest.
- ✅ Nutrition coaching + weekly food review

**What you lose without a watch:**
- ❌ **Real daily calorie burn** — the system falls back to a formula estimate (your BMR × an activity factor) + any workout you log by hand. Calibration then corrects that estimate over time, so it still works — just less precise day-to-day.
- ❌ Recovery coaching (sleep, HRV, body battery, "train or rest today?")
- ❌ Detailed run analysis (splits, pace-at-HR, aerobic decoupling)

To log a workout without a watch, just tell it — "ran 5k in 30 min", "1 hour of weights" — and it estimates the burn.

**Bottom line:** without a watch it's a **smart, self-calibrating calorie + training-log coach** — genuinely useful. With even a basic Garmin it becomes a full data-driven coach (real burn + recovery). If you're serious about results, a cheap Garmin pays for itself in accuracy.

> A non-Garmin wearable (Apple Watch, Fitbit, …) isn't supported directly — you'd log manually, same as the no-watch case.

---

## 🆘 Quick fixes
- **Coach forgot a tool / gives an odd error after an update** → open a **new chat** (the old one cached an old tool list).
- **A meal looks wrong** → just tell it the correction; it re-shows the corrected day.
- **Numbers feel off after 2 weeks** → say "calibrate" and (ideally) add a fresh morning-fasted InBody.

For deeper issues see [SETUP.md](SETUP.md) → Troubleshooting.
