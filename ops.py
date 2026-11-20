"""Ops dashboard: probe my services, keep 30 days of samples, compute SLOs, alert, render a static page.

No database. The history lives in history.json on the published GitHub Pages site: each run downloads it,
appends one sample per check, trims to 30 days and publishes it again. Stdlib only.

Run:  python ops.py --out site
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

WINDOW = 30 * 86400          # SLO window
PROBE_EVERY = 15 * 60        # matches the cron in .github/workflows/probe.yml
IST = timezone(timedelta(hours=5, minutes=30))
OWNER = "sayaksatpathi"
REPO_URL = f"https://github.com/{OWNER}/ops-dashboard"
UPSTASH_MONTHLY_LIMIT = int(os.getenv("UPSTASH_MONTHLY_LIMIT", "500000"))  # check Upstash's pricing page

# Workflows whose run history is the "Actions failures" panel: (repo, workflow file, max minutes between successes)
WORKFLOWS = [
    ("job-autopilot-runner", "search.yml", 75),     # every 30 min by day, hourly overnight
    ("job-autopilot-runner", "watchdog.yml", 240),
    # keeper.yml is left out: each run lives ~6 h and ends "cancelled" by design; jobs-search proves it works
    ("ops-dashboard", "probe.yml", 45),
]


def env(name):
    return os.getenv(name, "").strip()


def http(url, method="GET", headers=None, body=None, timeout=15):
    """Return (status, parsed JSON or text, seconds). Network errors become status 0."""
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except Exception as e:  # DNS, TLS, timeout, reset
        return 0, str(e)[:120], time.time() - t
    try:
        return status, json.loads(raw), time.time() - t
    except ValueError:
        return status, raw.decode("utf-8", "replace"), time.time() - t


def gh(path):
    h = {"Accept": "application/vnd.github+json", "User-Agent": "ops-dashboard"}
    if env("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {env('GITHUB_TOKEN')}"
    return http(f"https://api.github.com{path}", headers=h)


# ---------- checks: each returns (ok: True/False/None, public detail). None = not counted (skipped). ----------

def market_open(now):
    t = now.astimezone(IST)
    # shortcut: NSE holidays are not excluded; add a holiday list if they start costing error budget
    return t.weekday() < 5 and (9, 15) <= (t.hour, t.minute) <= (15, 30)


def check_trader_web(now):
    url = env("AITRADER_URL")
    if not url:
        return None, "not configured"
    status, _, secs = http(url.rstrip("/") + "/login.html", timeout=10)
    return status == 200, f"HTTP {status or 'error'} in {secs:.1f}s"


def check_trader_data(now):
    url, tok = env("UPSTASH_URL"), env("UPSTASH_READ_TOKEN")
    if not (url and tok):
        return None, "not configured"
    if not market_open(now):
        return None, "market closed (not counted)"
    # The laptop's snapshot starts with {"synced_at": ...}; read 80 bytes instead of the whole page data.
    status, body, _ = http(url.rstrip("/") + "/getrange/snapshot/0/80", headers={"Authorization": f"Bearer {tok}"})
    m = re.search(r'"synced_at":\s*"([^"]+)"', str(body.get("result") if isinstance(body, dict) else ""))
    if status != 200 or not m:
        return False, f"cannot read snapshot (HTTP {status})"
    age = (now - datetime.fromisoformat(m.group(1))).total_seconds() / 60
    return age <= 5, f"laptop data {age:.0f} min old"


def check_bot(token_env, webhook):
    def run(now):
        tok = env(token_env)
        if not tok:
            return None, "not configured"
        status, body, _ = http(f"https://api.telegram.org/bot{tok}/" + ("getWebhookInfo" if webhook else "getMe"))
        if status != 200 or not isinstance(body, dict) or not body.get("ok"):
            return False, f"Telegram API HTTP {status}"
        if not webhook:
            return True, "bot token valid"
        r = body["result"]
        recent_err = r.get("last_error_date") and now.timestamp() - r["last_error_date"] < 3600
        if not r.get("url"):
            return False, "webhook not set"
        if recent_err or r.get("pending_update_count", 0) > 20:
            return False, f"webhook failing ({r.get('pending_update_count', 0)} updates waiting)"
        return True, "webhook delivering"
    return run


def workflow_runs(repo, wf, since):
    """Completed runs of one workflow since `since`, newest first. None if the API call failed."""
    runs, page = [], 1
    while page <= 20:
        status, body, _ = gh(f"/repos/{OWNER}/{repo}/actions/workflows/{wf}/runs"
                             f"?status=completed&per_page=100&page={page}&created=>={since:%Y-%m-%d}")
        if status != 200:
            return None if page == 1 else runs
        batch = body.get("workflow_runs", [])
        runs += [{"at": r["created_at"], "c": r["conclusion"]} for r in batch]
        if len(batch) < 100:
            return runs
        page += 1
    return runs


def check_heartbeat(wf_stats, repo, wf):
    def run(now):
        s = wf_stats.get((repo, wf))
        if s is None:
            return False, "GitHub API unreachable"
        if s["last_ok_min"] is None:
            return False, "no successful run in 30 days"
        return s["last_ok_min"] <= s["max_gap"], f"last success {s['last_ok_min']:.0f} min ago"
    return run


# ---------- SLO maths (pure functions, tested in test_ops.py) ----------

def sli(samples, now, window):
    """Share of good samples in the last `window` seconds. None if nothing was counted."""
    xs = [ok for t, ok in samples if now - t < window]
    return (sum(xs) / len(xs), len(xs)) if xs else (None, 0)


def burn(samples, now, window, target):
    """How many times faster than allowed the error budget is being spent (1.0 = exactly on budget)."""
    good, n = sli(samples, now, window)
    return None if good is None else (1 - good) / (1 - target)


def alert_level(samples, now, target):
    """Google SRE workbook multi-window burn-rate alert, sized for a 15-minute probe."""
    b1, b6 = burn(samples, now, 3600, target), burn(samples, now, 6 * 3600, target)
    latest_bad = bool(samples) and samples[-1][1] == 0
    if b1 is not None and b1 > 14.4 and latest_bad:
        return "page"
    if b6 is not None and b6 > 6 and b1 is not None and b1 > 6:
        return "ticket"
    return None


def merge(history, results, now):
    """Append one sample per counted check and drop samples older than the window. Returns a new dict."""
    out = {k: [s for s in v if now - s[0] < WINDOW] for k, v in history.items()}
    for name, (ok, _) in results.items():
        if ok is not None:
            out.setdefault(name, []).append([int(now), int(ok)])
    return out


def project_month(today_count, now):
    """Linear projection of a monthly quota from today's count. Returns (projected, day the limit is hit)."""
    per_day = today_count / max((now.hour * 60 + now.minute) / 1440, 1 / 24)
    projected = per_day * 30
    days_left = (UPSTASH_MONTHLY_LIMIT - projected) / per_day if per_day else None
    return projected, days_left


# ---------- the run ----------

CHECKS = [  # name, title, SLO target, function factory
    ("trader-web", "ai-trader website", 0.995),
    ("trader-data", "ai-trader data freshness (market hours)", 0.99),
    ("trader-bot", "ai-trader Telegram bot", 0.995),
    ("jobs-search", "job-autopilot search heartbeat", 0.99),
    ("jobs-bot", "job-autopilot Telegram bot", 0.995),
]


def load_history():
    base = env("PAGES_URL")
    if not base:
        return {}
    status, body, _ = http(base.rstrip("/") + "/history.json")
    if status == 404:
        return {}  # first run
    if status != 200 or not isinstance(body, dict):
        # Never publish over a history we could not read: fail the run, healthchecks.io notices.
        sys.exit(f"cannot read previous history.json (HTTP {status}); refusing to overwrite it")
    return body.get("checks", {})


def telegram_alert(text):
    tok, chat = env("TG_ALERT_TOKEN"), env("TG_ALERT_CHAT")
    if tok and chat:
        http(f"https://api.telegram.org/bot{tok}/sendMessage", method="POST",
             headers={"Content-Type": "application/json"},
             body=json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode())
    print("ALERT:", text)


def upstash_today():
    db, email, key = env("UPSTASH_DB_ID"), env("UPSTASH_EMAIL"), env("UPSTASH_API_KEY")
    if not (db and email and key):
        return None
    import base64
    auth = base64.b64encode(f"{email}:{key}".encode()).decode()
    status, body, _ = http(f"https://api.upstash.com/v2/redis/stats/{db}", headers={"Authorization": f"Basic {auth}"})
    v = body.get("daily_net_commands") if status == 200 and isinstance(body, dict) else None
    return v if isinstance(v, (int, float)) else None


def main(out):
    now_dt = datetime.now(timezone.utc)
    now = now_dt.timestamp()
    history = load_history()

    since = now_dt - timedelta(days=30)
    wf_stats = {}
    for repo, wf, max_gap in WORKFLOWS:
        runs = workflow_runs(repo, wf, since)
        if runs is None:
            continue
        done = [r for r in runs if r["c"] in ("success", "failure", "timed_out", "startup_failure")]
        ok = [r for r in done if r["c"] == "success"]
        last = (now_dt - datetime.fromisoformat(ok[0]["at"].replace("Z", "+00:00"))).total_seconds() / 60 if ok else None
        wf_stats[(repo, wf)] = {"runs": len(done), "fails": len(done) - len(ok),
                                "rate": len(ok) / len(done) if done else None, "last_ok_min": last, "max_gap": max_gap}

    fns = {"trader-web": check_trader_web, "trader-data": check_trader_data,
           "trader-bot": check_bot("TG_AITRADER_TOKEN", webhook=True),
           "jobs-search": check_heartbeat(wf_stats, "job-autopilot-runner", "search.yml"),
           "jobs-bot": check_bot("TG_JOBS_TOKEN", webhook=False)}
    results = {}
    for name, _, _ in CHECKS:
        try:
            results[name] = fns[name](now_dt)
        except Exception as e:  # a broken check is a failed check, never a crashed monitor
            results[name] = (False, f"check crashed: {type(e).__name__}")

    new = merge(history, results, now)
    for name, title, target in CHECKS:
        before, after = alert_level(history.get(name, []), now - PROBE_EVERY, target), alert_level(new.get(name, []), now, target)
        if after != before:
            state = f"🔴 {after.upper()}" if after else "✅ RESOLVED"
            telegram_alert(f"{state}: {title}\n{results[name][1]}\nRunbook: {REPO_URL}/blob/main/RUNBOOK.md#{name}")

    quota = None
    today = upstash_today()
    if today is not None:
        projected, days_left = project_month(today, now_dt)
        quota = {"today": today, "projected": projected, "limit": UPSTASH_MONTHLY_LIMIT, "days_left": days_left}
        if projected > 0.8 * UPSTASH_MONTHLY_LIMIT:
            telegram_alert(f"⚠️ Upstash on course for {projected:,.0f}/{UPSTASH_MONTHLY_LIMIT:,} commands this month")

    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "history.json"), "w") as f:
        json.dump({"generated_at": int(now), "checks": new}, f, separators=(",", ":"))
    status = {name: {"ok": results[name][0], "detail": results[name][1]} for name, _, _ in CHECKS}
    with open(os.path.join(out, "status.json"), "w") as f:
        json.dump({"generated_at": int(now), "checks": status}, f, indent=1)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(render(now, new, results, wf_stats, quota))
    print(json.dumps(status, indent=1))


# ---------- page ----------

def pct(x, digits=2):
    return "–" if x is None else f"{x * 100:.{digits}f}%"


def day_bars(samples, now):
    cells = []
    for d in range(29, -1, -1):
        lo, hi = now - (d + 1) * 86400, now - d * 86400
        xs = [ok for t, ok in samples if lo <= t < hi]
        cls = "none" if not xs else "ok" if all(xs) else "bad" if sum(xs) / len(xs) < 0.95 else "warn"
        label = "no data" if not xs else f"{sum(xs)}/{len(xs)} good"
        cells.append(f'<i class="{cls}" title="{d} days ago: {label}"></i>')
    return "".join(cells)


def render(now, hist, results, wf_stats, quota):
    e = html.escape
    rows = []
    for name, title, target in CHECKS:
        s = hist.get(name, [])
        good, n = sli(s, now, WINDOW)
        budget = None if good is None else 1 - (1 - good) / (1 - target)
        ok, detail = results[name]
        dot = "ok" if ok else "none" if ok is None else "bad"
        b1, b6 = burn(s, now, 3600, target), burn(s, now, 6 * 3600, target)
        bw = 0 if budget is None else max(0, min(100, budget * 100))
        rows.append(f"""<section class="card"><div class="head"><span class="dot {dot}"></span><h2>{e(title)}</h2>
<a href="{REPO_URL}/blob/main/RUNBOOK.md#{name}">runbook</a></div>
<p class="detail">{e(detail)}</p><div class="bars">{day_bars(s, now)}</div>
<dl><div><dt>SLO</dt><dd>{pct(target, 1)}</dd></div><div><dt>30-day SLI</dt><dd>{pct(good)}</dd></div>
<div><dt>samples</dt><dd>{n}</dd></div><div><dt>burn 1h / 6h</dt><dd>{'–' if b1 is None else f'{b1:.1f}x'} / {'–' if b6 is None else f'{b6:.1f}x'}</dd></div></dl>
<div class="budget"><span style="width:{bw:.0f}%"></span></div><p class="small">error budget left: {pct(budget, 0)}</p></section>""")
    wf_rows = "".join(
        f"<tr><td>{e(r)}/{e(w)}</td><td>{s['runs']}</td><td>{s['fails']}</td><td>{pct(s['rate'], 1)}</td>"
        f"<td>{fmt_min(s['last_ok_min'])}</td></tr>" for (r, w), s in wf_stats.items())
    if quota:
        q = (f"<p>Today: <b>{quota['today']:,.0f}</b> commands. On this pace: <b>{quota['projected']:,.0f}</b> of "
             f"{quota['limit']:,} this month ({quota['projected'] / quota['limit'] * 100:.0f}%).</p>")
    else:
        q = "<p class='small'>Upstash usage not configured (UPSTASH_DB_ID / UPSTASH_EMAIL / UPSTASH_API_KEY).</p>"
    gen = datetime.fromtimestamp(now, IST).strftime("%d %b %Y, %H:%M IST")
    return PAGE.replace("{{CARDS}}", "".join(rows)).replace("{{WF}}", wf_rows).replace("{{QUOTA}}", q) \
        .replace("{{GEN}}", gen).replace("{{TS}}", str(int(now))).replace("{{REPO}}", REPO_URL)


def fmt_min(m):
    if m is None:
        return "never"
    return f"{m:.0f} min ago" if m < 120 else f"{m / 60:.1f} h ago"


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ops Status</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1b;--muted:#6b6b66;--line:#e4e4df;--ok:#1f9d55;--warn:#d69e2e;--bad:#d64545;--none:#c9c9c3}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141413;--card:#1e1e1c;--fg:#ecebe6;--muted:#9c9b95;--line:#2e2e2b;--none:#3a3a37}}
:root[data-theme="dark"]{--bg:#141413;--card:#1e1e1c;--fg:#ecebe6;--muted:#9c9b95;--line:#2e2e2b;--none:#3a3a37}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:900px;margin:0 auto;padding:24px 16px}h1{font-size:24px;margin:0}h2{font-size:16px;margin:0;flex:1}
.sub{color:var(--muted);margin:4px 0 20px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:12px}
.head{display:flex;align-items:center;gap:10px}.head a,a{color:var(--muted)}.dot{width:10px;height:10px;border-radius:50%;flex:none}
.dot.ok{background:var(--ok)}.dot.bad{background:var(--bad)}.dot.none{background:var(--none)}
.detail{margin:6px 0 10px;color:var(--muted)}.bars{display:flex;gap:2px}.bars i{flex:1;height:26px;border-radius:2px}
.bars .ok{background:var(--ok)}.bars .warn{background:var(--warn)}.bars .bad{background:var(--bad)}.bars .none{background:var(--none)}
dl{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0 8px}dt{color:var(--muted);font-size:12px}dd{margin:0;font-variant-numeric:tabular-nums}
.budget{height:6px;background:var(--line);border-radius:3px;overflow:hidden}.budget span{display:block;height:100%;background:var(--ok)}
.small{font-size:13px;color:var(--muted);margin:4px 0 0}table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
td,th{text-align:left;padding:6px 4px;border-bottom:1px solid var(--line);font-size:14px}.wrap{overflow-x:auto}
#stale{display:none;background:var(--bad);color:#fff;padding:10px 14px;border-radius:8px;margin-bottom:12px}
@media (max-width:560px){dl{grid-template-columns:repeat(2,1fr)}}
</style></head><body><main>
<h1>Ops Status</h1><p class="sub">The systems I run 24/7, probed every 15 minutes. Updated {{GEN}} ·
<a href="{{REPO}}/blob/main/SLO.md">SLOs</a> · <a href="{{REPO}}/tree/main/postmortems">incidents</a></p>
<div id="stale">This page has not updated for over 45 minutes: the monitor itself may be down.</div>
{{CARDS}}
<section class="card"><h2>GitHub Actions, last 30 days</h2><div class="wrap"><table>
<tr><th>workflow</th><th>runs</th><th>failed</th><th>success</th><th>last success</th></tr>{{WF}}</table></div></section>
<section class="card"><h2>Free-tier quota (Upstash Redis)</h2>{{QUOTA}}
<p class="small">Vercel Hobby has no usage API, so Vercel usage is checked by hand on its dashboard.</p></section>
</main><script>if(Date.now()/1000-{{TS}}>2700)document.getElementById("stale").style.display="block"</script></body></html>"""

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    main(ap.parse_args().out)
