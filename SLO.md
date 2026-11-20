# Service Level Objectives

I run two personal production systems 24/7:

- **ai-trader:** a paper-trading NSE agent. It runs on my laptop and pushes a snapshot to a Vercel dashboard (Upstash Redis) every minute. It also has a Telegram bot (a webhook on Vercel).
- **job-autopilot:** job discovery and application on GitHub Actions. A keeper/watchdog chain keeps it running, and a Telegram bot controls it.

All SLOs use a **rolling 30-day window**. A probe runs every 15 minutes ([probe.yml](.github/workflows/probe.yml)).

| SLI | What counts as good | Target | Budget (30 d) |
|---|---|---|---|
| `trader-web` | `GET /login.html` returns 200 within 10 s | 99.5% | ~3.6 h |
| `trader-data` | the laptop's last push is at most 5 min old. **Counted only Mon–Fri 09:15–15:30 IST** | 99.0% | ~1.3 h of market time |
| `trader-bot` | the webhook is set, no delivery error in the last hour, fewer than 20 updates waiting | 99.5% | ~3.6 h |
| `jobs-search` | the `search` workflow succeeded within the last 75 min | 99.0% | ~7.2 h |
| `jobs-bot` | the bot token is valid (`getMe`) | 99.5% | ~3.6 h |

## Why these targets
- **`trader-data` excludes hours outside the market.** The laptop sleeps at night, and that is by design, not an outage. Counting those hours would make the SLO measure my sleep schedule.
- **`jobs-search` is 99%, not 99.9%.** GitHub's scheduled runs are best effort and can be delayed by an hour or more. My keeper workflow restarts missed runs, but I cannot promise a higher target on a scheduler I don't control.
- **No 99.9% targets anywhere.** At one probe every 15 minutes, 99.9% over 30 days allows only about 3 bad samples. One failed probe would spend most of the month's budget, which is noise, not signal.

## Alerting: multi-window burn rate
Burn rate means how many times faster than allowed the error budget is being spent. 1.0x means the budget runs out exactly at the end of the window.

| Level | Condition | Action |
|---|---|---|
| page | 1 h burn > 14.4x **and** the latest probe failed | Telegram now. Open the runbook. |
| ticket | 6 h burn > 6x **and** 1 h burn > 6x | Telegram. Fix the same day. |

Alerts fire only when the level changes (a new alert or a resolution), so a long outage sends 2 messages, not 96.

**A known limit:** with only 4 samples per hour, a single failed probe pushes the 1 h burn over 14.4x. In practice, any failure whose latest probe is still bad pages me. More frequent probes would fix this. GitHub's 5-minute cron minimum and its delays make 15 minutes the honest resolution.

## Error budget policy
- **More than 50% of the budget left:** ship features freely.
- **25–50% left:** every change needs a test that would have caught the last incident.
- **Budget gone:** feature work on that service stops. Fix reliability first, and write a postmortem for anything that used more than 25% of the budget.

## Watching the watcher
- **The probe workflow's own reliability** is on the dashboard (the `ops-dashboard/probe.yml` row).
- **A missed or failed run** pings [healthchecks.io](https://healthchecks.io) (`HC_PING_URL`), which alerts from outside GitHub.
- **A stale page** (no update in over 45 minutes) shows a red banner, computed in the browser.

## What is not measured (yet)
- **Vercel usage:** Hobby has no usage API, so I check it by hand.
- **Gmail app password and GitHub PAT expiry:** neither has an API to read expiry, so I track them in the runbook.
- **NSE holidays:** they still count as market days.
