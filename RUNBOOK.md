# Runbook

Every alert links to one section below. **Check first:** is the dashboard itself fresh? If not, start at [the monitor is down](#monitor).

## trader-web
**Means:** the Vercel dashboard is not serving `/login.html`.
1. Open the Vercel project. Is the latest production deployment `READY`?
2. If a deploy broke it, roll back to the last good deployment (Vercel → Deployments → Promote).
3. If Vercel itself is degraded, check vercel-status.com. Nothing to do but wait and record it.

## trader-data
**Means:** during market hours, the laptop's last push is more than 5 minutes old.
1. Is the laptop on and online? Is the autopilot running? Check the local dashboard.
2. Check the agent log for `cloud push failed`. A `401` means the `CLOUD_PUSH_TOKEN` in `agent/.env` no longer matches Vercel's `PUSH_TOKEN`. Re-run `cloud/setup.ps1`.
3. A storage error means Upstash may be over its free limit. Check the quota panel.

## trader-bot
**Means:** Telegram cannot deliver updates to the webhook.
1. Run `getWebhookInfo` with the bot token and read `last_error_message`.
2. If the URL is empty, set the webhook again with the secret token (see the ai-trader cloud README).
3. A `401` from our side means `TELEGRAM_WEBHOOK_SECRET` changed. Register the webhook again with the new secret.

## jobs-search
**Means:** the `search` workflow in job-autopilot-runner has not succeeded in 75 minutes.
1. Open the runner's Actions tab. If the runs are failing, open the latest log. The cause is printed without personal data.
2. If there are no runs at all, check whether the keeper chain broke. Run `keeper` manually (`workflow_dispatch`).
3. If GitHub disabled the scheduled workflow (this happens after 60 days with no repo activity), enable it again.

## jobs-bot
**Means:** `getMe` fails, so the job-autopilot bot token is invalid or revoked.
1. Get a new token from @BotFather and update `TELEGRAM_BOT_TOKEN` in the runner's secrets **and** `TG_JOBS_TOKEN` here.

## monitor
**Means:** the page shows the stale banner, or healthchecks.io reported a missed run.
1. Open ops-dashboard Actions → `probe`. If it errors with `refusing to overwrite`, the previous `history.json` could not be read. Check that GitHub Pages is up.
2. Run `probe` manually.

## Credentials that expire
| Credential | Where | Renew by |
|---|---|---|
| `STATE_TOKEN` (fine-grained PAT) | job-autopilot-runner secrets | check its expiry at github.com/settings/tokens |
| Gmail app password | job-autopilot secrets | it stops working if 2FA is reset or the Google password changes |
| Upstash API key | ops-dashboard secrets | it does not expire, but rotate it if leaked |
