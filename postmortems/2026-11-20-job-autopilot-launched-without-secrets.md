# PM-002: job-autopilot went live without its secrets

| | |
|---|---|
| Date | 2026-11-20 |
| Severity | Low (before launch, no user impact) |
| Status | Resolved |
| Detected by | Manual check after the first run |

## Summary
I enabled the workflows and triggered the first live run before confirming that the repository secrets existed. The run (`44684423386`) failed in seconds at the Telegram stage. A check afterwards showed the secret list was empty: my earlier `gh secret set` attempts had never saved anything.

## Timeline (UTC)
| Time | Event |
|---|---|
| ~05:57 | Workflows enabled. First live run triggered. |
| 05:57:35 | The run exits with code 1: `Autopilot stages failed: telegram` (`[telegram not paired]`). It finished too fast to cancel. |
| 05:57 | `gh secret list` returns `[]`: no repository or environment secrets exist. |
| 05:57 | Both workflows disabled again to stop more failing runs. |
| 06:01 | A second check: still empty. |
| later that day | Secrets set and checked. Scheduling moved to the public `job-autopilot-runner` repo (search / watchdog / keeper). Runs green since then. |

## Impact
1 failed run. No emails sent, no data lost. It happened before launch, so it cost no error budget.

## Root cause
- **Configuration was never checked before the switch-on.** I treated "the `gh secret set` command printed no error" as "the secret is set". It wasn't.
- **Contributing:** the bot also needs a one-time `/start` pairing, a manual step that was not on any checklist.

## What went well
The pipeline failed loudly and quickly, with a clear stage name, instead of half-running.

## Action items
| Action | Status |
|---|---|
| Fail fast before any stage runs if a required secret is missing, and name the missing secret | open |
| Make "check `gh secret list` shows each name" a launch gate | done (process) |
| Remove the `TELEGRAM_BOT_TOKEN \|\| TELEGRAM_BOT_TOKE` fallback once the misspelled secret is renamed: it hides config drift | open |
| Watch the bot from outside (`jobs-bot` SLI on the ops dashboard) | done |

## Lesson
No error is not the same as success. Check the state you expect to see, not just that the command finished.
