import unittest
from datetime import datetime, timezone

import ops

NOW = 1_800_000_000


def samples(pattern, end=NOW, step=900):
    """pattern like '1110' -> oldest first, one sample per 15 minutes ending at `end`."""
    n = len(pattern)
    return [[end - (n - 1 - i) * step, int(c)] for i, c in enumerate(pattern)]


class SLO(unittest.TestCase):
    def test_sli_ignores_old_samples(self):
        s = [[NOW - ops.WINDOW - 10, 0]] + samples("1111")
        self.assertEqual(ops.sli(s, NOW, ops.WINDOW), (1.0, 4))

    def test_burn_rate(self):
        # 1 bad of 4 in the last hour at a 99% target = 25% / 1% = 25x
        self.assertAlmostEqual(ops.burn(samples("1110"), NOW, 3600, 0.99), 25.0)
        self.assertIsNone(ops.burn([], NOW, 3600, 0.99))

    def test_alert_levels(self):
        self.assertIsNone(ops.alert_level(samples("1" * 24), NOW, 0.995))
        self.assertEqual(ops.alert_level(samples("1" * 20 + "1110"), NOW, 0.995), "page")
        # recovered on the latest probe: no longer a page, but the 6h burn still opens a ticket
        self.assertEqual(ops.alert_level(samples("1" * 20 + "1101"), NOW, 0.995), "ticket")

    def test_merge_skips_uncounted_and_trims(self):
        h = {"a": [[NOW - ops.WINDOW - 1, 1], [NOW - 60, 1]]}
        out = ops.merge(h, {"a": (False, ""), "b": (None, "market closed")}, NOW)
        self.assertEqual(out, {"a": [[NOW - 60, 1], [NOW, 0]]})
        self.assertEqual(len(h["a"]), 2)  # input untouched

    def test_project_month(self):
        noon = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
        projected, days_left = ops.project_month(5000, noon)  # 5000 by noon -> 10000/day
        self.assertAlmostEqual(projected, 300000)
        self.assertAlmostEqual(days_left, (ops.UPSTASH_MONTHLY_LIMIT - 300000) / 10000)

    def test_market_hours(self):
        ist = ops.IST
        self.assertTrue(ops.market_open(datetime(2026, 11, 20, 10, 0, tzinfo=ist)))   # Friday
        self.assertFalse(ops.market_open(datetime(2026, 11, 21, 10, 0, tzinfo=ist)))  # Saturday
        self.assertFalse(ops.market_open(datetime(2026, 11, 20, 15, 31, tzinfo=ist)))

    def test_render_has_no_secrets_or_urls(self):
        res = {n: (True, "ok") for n, _, _ in ops.CHECKS}
        page = ops.render(NOW, {"trader-web": samples("1101")}, res, {}, None)
        self.assertIn("Ops Status", page)
        self.assertNotIn("vercel.app", page)


if __name__ == "__main__":
    unittest.main()
