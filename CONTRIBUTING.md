# 🛠️ Fork & maintainer notes

Read this if you forked LeanLoop, plan to customize it, or will run it for other people. It explains **what's shared vs independent** so you can decide how to run yours. (You don't need this for a normal personal install — see [SETUP.md](SETUP.md).)

## What's shared vs independent

When you deploy, everything is **your own** — with **one** exception:

| Part | Whose it is | Do the original author's changes reach you? |
|---|---|---|
| Server code (`main.py`, the 20 tools) | your Cloud Run, from your clone | ❌ No — only when **you** `git pull` + redeploy |
| Your data — Notion (food / training / body / Config), Garmin, Cloud, secrets | 100% yours | ❌ Never |
| **`playbook.md` (the coaching rules)** | fetched **live at runtime** from whatever `PLAYBOOK_URL` points to | ✅ **Yes, within ~15 min — IF `PLAYBOOK_URL` points at the upstream repo** |

By default, `SETUP.md` sets:

```
PLAYBOOK_URL = https://raw.githubusercontent.com/bank3005-jpg/LeanLoop-for-Garmin/stable/playbook.md
```

So out of the box, **your coach's rules stream live from the upstream `stable` playbook.** You automatically get the maintainer's coaching improvements — but you also depend on their repo.

## Your decision: shared brain, or your own?

- **Keep the default** (`PLAYBOOK_URL` → upstream `stable`): easiest; you ride along with upstream's coaching updates, zero maintenance. Good if you trust the maintainer's rules.
- **Point it at your own fork** (`PLAYBOOK_URL` → `https://raw.githubusercontent.com/<your-username>/LeanLoop-for-Garmin/stable/playbook.md`): **full independence.** Upstream changes never touch you; you edit *your* playbook and it goes live to *your* server only. Recommended if you want to customize the coaching or run it for other people.

Change it any time: update the `PLAYBOOK_URL` env var on your Cloud Run service and redeploy — no code changes.

## If YOU maintain a playbook others depend on

If people point their `PLAYBOOK_URL` at **your** repo, your `stable` playbook becomes **their** live coaching brain. Keep it safe for them:

1. **`stable` = released & backward-compatible.** Push only tested, generic rules there. Do experiments on a `dev` / `main` branch first, then merge to `stable` deliberately — don't treat `stable` as your scratchpad.
2. **Ship code before the playbook needs it.** If a new rule calls a new tool or reads a new Notion field, that tool/field must already exist on downstream servers — otherwise their coach hits "tool not found." Deploy the `main.py` change first; keep the new playbook rule guarded (*"if the tool exists / else fallback"*) until people have redeployed. **Never let the shared playbook hard-depend on code or fields others don't have yet.**
3. **Keep the shared playbook universal.** Person-specific coaching (someone's habits, their weak points, their targets) belongs in that user's **Config `ATHLETE` / `GOAL_ACTIVE` lines** — not in the shared playbook. The shared brain must apply to everyone.
4. **No personal data in the playbook.** Names, exact numbers, specific foods/places — keep them out (they'd show to every user). Use placeholders in examples.

## Free to change with zero risk to others

Your **server code, Notion data, Config, Garmin, and Cloud** are entirely yours — add tools, change your targets, restructure Notion, experiment freely. None of it can affect anyone else's deployment. The **only** coupling point is the shared `playbook.md`, and only if you leave `PLAYBOOK_URL` pointing at someone else's repo.
