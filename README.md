# ops-dashboard

A status page, SLOs and an incident history for the two systems I run 24/7:
- **ai-trader:** a paper-trading agent, with a Vercel + Upstash dashboard and a Telegram bot
- **job-autopilot:** job hunting on GitHub Actions, with a Telegram bot

**Live page:** https://sayaksatpathi.github.io/ops-dashboard/

```
GitHub Actions cron (every 15 min, ops.py, stdlib only)
  ├─ probes:  ai-trader website · laptop data freshness (Upstash, read-only) · both Telegram bots · job search heartbeat
  ├─ GitHub API: 30-day success rate of every workflow
  ├─ Upstash API: today's command count → month projection vs the free limit
  ├─ downloads the last history.json from the live page → appends a sample → trims to 30 days
  ├─ burn-rate alerts → Telegram, each with a runbook link
  └─ publishes index.html + status.json + history.json to GitHub Pages ──▶ pings healthchecks.io
```

**No database, no server.** The published site is the store. A run that cannot read the previous history fails instead of overwriting it.

## Docs
- [SLO.md](SLO.md): the SLIs, the targets and why, burn-rate alerting, the error-budget policy
- [RUNBOOK.md](RUNBOOK.md): one section per alert
- [postmortems/](postmortems): blameless incident write-ups

## Privacy
The public page shows only up/down, latencies, ages and counts. It shows no URLs, P&L, positions, companies or emails. A test checks that the dashboard URL never appears in the page.

## Run it locally
```
python -m unittest test_ops
python ops.py --out site      # checks without secrets report "not configured"
```

## Setup
After creating the repo: `.\setup.ps1`. It copies the secrets from the ai-trader `.env`, asks for the rest (Upstash, the job bot, healthchecks.io), enables Pages and starts the first run.
