# PM-001: Himalayas job source reset the connection on deep pagination

| | |
|---|---|
| Date | 2026-11-19 |
| Severity | Low (found in pre-launch testing) |
| Status | Mitigated |
| Detected by | A local end-to-end run |

## Summary
The job-autopilot source for the Himalayas job board paged through offsets 0–400 (20 pages). Past about 5 pages, the server reset the connection (`ConnectionResetError 10054`). The whole source then failed and returned no jobs.

## Timeline (UTC)
| Time | Event |
|---|---|
| 2026-11-19 ~21:30 | A local run logs `Connection aborted` / `ConnectionResetError 10054` from Himalayas. |
| 21:33 | Pagination capped at 5 pages (offsets 0–80, ≤100 jobs). The early stop on a short page is kept. |
| 21:33 | Re-test: 100 jobs returned, no resets, and `tests.selfcheck` passes. |

## Impact
None in production (pre-launch). Had it shipped, one of the 8 sources would have returned 0 jobs on every run without anyone noticing.

## Root cause
An upstream limit on deep pagination: probably rate limiting or a cap on connections per client. **This is not confirmed.** Himalayas does not document it.

## Trade-off accepted
Up to ~100 jobs per run instead of ~400. The newest postings come first, and the source runs every hour, so the lost tail is mostly old jobs.

## Action items
| Action | Status |
|---|---|
| Cap the pagination at 5 pages | done |
| Retry with backoff before giving up on a page | open |
| Track jobs per source per run, and alert when a source that usually returns jobs returns 0 | open: the silent-failure case |

## Lesson
A source that fails silently is worse than one that crashes. Measure each dependency's output, not just whether the run succeeded.
