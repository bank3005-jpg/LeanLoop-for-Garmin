# 🔒 Security

LeanLoop is self-hosted — your data lives in **your** Google Cloud, **your** Notion, **your** Garmin. No shared backend, no third party (including this repo's author) ever sees it. A few rules keep it that way:

## Your connector URL is a password
It looks like `https://<your-run-url>/<MCP_SECRET>/mcp`. The random middle part is the **only** thing protecting your server — anyone with the full URL can read and write your data.
- Never post it publicly, screenshot it, or paste it into a shared doc/chat.
- If it leaks, **rotate** it (below) — that invalidates the old URL.

## Never commit secrets
Setup creates `token.txt`, `secret.txt`, and `env.yaml` in your working folder — these hold your Garmin token, MCP secret, and all keys. They're listed in [`.gitignore`](.gitignore) so git skips them. **Don't force-add them.** If you forked the repo, glance at `git status` and make sure none of them appear before you `git push`.

## Where secrets actually live
Every real secret (`MCP_SECRET`, `NOTION_TOKEN`, `GARMINTOKENS_B64`, Garmin email/password) lives **only** as an environment variable on your Cloud Run service — never in the code, never in the repo.

## Rotate a leaked MCP secret
```bash
python3 -c "import secrets;print(secrets.token_urlsafe(16))"   # 1) new secret
gcloud run services update garmin-mcp --region us-central1 --update-env-vars MCP_SECRET=<new-secret>
# 2) update the two Cloud Scheduler job URLs to the new /<secret>/... path
# 3) reconnect the connector in your AI app with the new URL
```

## Tokens
- **Garmin** token (~1 yr life): if leaked, change your Garmin password and regenerate the token (SETUP Phase 3).
- **Notion** integration secret (`ntn_…`): rotate at [notion.so/my-integrations](https://www.notion.so/my-integrations), then update the env var + redeploy.

## Reporting
Found a security issue in the code itself? Open a private note via GitHub Discussions rather than a public issue with details.
