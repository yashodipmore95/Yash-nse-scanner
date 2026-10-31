"""Backtest tests on hand-made candles (made-up data)."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest  # noqa: E402
import engine  # noqa: E402

DT = datetime.datetime
D = datetime.date(2026, 10, 29)


def bars(rows, start="09:35"):
    """rows: (o, h, l, c, v) from `start`, one per 5 minutes."""
    t0 = DT.combine(D, datetime.time(*map(int, start.split(":"))))
    return [{"start": t0 + engine.BAR * k, "o": o, "h": h, "l": l, "c": c, "v": v}
            for k, (o, h, l, c, v) in enumerate(rows)]


ENTRY, STOP = 304.0, 300.0                    # risk 4: target 312, lock 308, trail at 310 -> stop 306


class Manage(unittest.TestCase):
    def run_it(self, rows, mode="current", nmap=None):
        b = bars([(303, 304.5, 302.5, 304.0, 1000)] + rows)
        return backtest.manage(b, 0, "buy", ENTRY, STOP, mode, nmap or {}, {})

    def test_stop_and_target(self):
        legs, _ = self.run_it([(304, 305, 299.5, 300.5, 1000)])
        self.assertEqual(legs, [(1.0, 300.0, "stop")])
        legs, _ = self.run_it([(304, 312.5, 303.5, 312.2, 1000)])
        self.assertEqual(legs, [(1.0, 312.0, "target")])
        legs, _ = self.run_it([(298, 299, 297, 298, 1000)])        # gap through the stop fills at the open
        self.assertEqual(legs, [(1.0, 298, "stop")])

    def test_lock_then_trail_protect_the_trade(self):
        legs, _ = self.run_it([(304, 308.5, 303.9, 308.2, 1000), (308, 308.4, 303.8, 304.5, 1000)])
        self.assertEqual(legs, [(1.0, 304.0, "protected stop")])  # lock moved the stop to the buy price
        legs, _ = self.run_it([(304, 310.5, 303.9, 310.2, 1000), (310, 310.4, 308.5, 309.5, 1000),
                               (309.5, 309.6, 305.5, 306.5, 1000)])
        self.assertEqual(legs, [(1.0, 306.0, "protected stop")])  # lock, then trail to +0.5x, like the live app

    def test_time_exit_and_flat(self):
        rows = [(304, 304.6, 303.6, 304.2, 1000)] * 14
        legs, t = self.run_it(rows)
        self.assertEqual((legs[0][2], t.time()), ("time exit", datetime.time(10, 40)))

    def test_market_drop(self):
        b0 = DT.combine(D, datetime.time(9, 40))
        nmap = {b0 - engine.BAR * 3: 25000.0, b0: 24880.0}
        legs, _ = self.run_it([(304, 304.6, 303.6, 304.2, 1000)], nmap=nmap)
        self.assertEqual(legs[0][2], "market drop")

    def test_half_and_vwap_modes(self):
        rows = [(304, 310.2, 303.9, 310.0, 1000), (310, 316.5, 309.5, 316.2, 1000)]
        legs, _ = self.run_it(rows, "half_3r")
        self.assertEqual(legs, [(0.5, 310.0, "half at 1.5x"), (0.5, 316.0, "3x target")])
        net = backtest.settle("buy", 10, ENTRY, legs)
        self.assertAlmostEqual(net, 5 * 6 + 5 * 12 - backtest.charges_legs("buy", 10, ENTRY, [(5, 310.0), (5, 316.0)]),
                               places=2)
        legs, _ = self.run_it([(304, 304.5, 290, 300.5, 900000)], "vwap_exit")
        self.assertEqual(legs[0][2], "stop")
        legs, _ = self.run_it([(304, 304.2, 300.5, 301.0, 900000)], "vwap_exit")
        self.assertEqual(legs[0][2], "VWAP exit")
        legs, _ = self.run_it([(304, 313, 303.9, 312.5, 1000), (312, 312.2, 307, 307.5, 2000000)], "vwap_trail")
        self.assertEqual(legs[0][2], "VWAP trail")                  # no 2x target in this mode

    def test_charges_match_the_engine(self):
        self.assertAlmostEqual(backtest.charges_legs("buy", 7, 685, [(7, 693)]), engine.charges(7, 685, 693), places=2)


class Pieces(unittest.TestCase):
    def test_retest(self):
        b = bars([(300, 304.2, 302.2, 304.0, 1000), (304, 304.3, 302.4, 302.9, 1000),
                  (302.9, 303.8, 302.45, 303.6, 1000)])
        self.assertEqual(backtest.find_retest(b, 0, "buy", 302.5, 300.75), 2)
        b2 = bars([(300, 304.2, 302.2, 304.0, 1000), (304, 306, 304, 305.8, 1000)])
        self.assertIsNone(backtest.find_retest(b2, 0, "buy", 302.5, 300.75))   # never came back

    def test_indicators(self):
        self.assertEqual(backtest.rsi([float(x) for x in range(1, 40)]), 100.0)
        self.assertIsNone(backtest.rsi([1.0] * 5))
        up = [100 + k * 0.5 for k in range(60)]
        self.assertGreater(backtest.macd_hist(up)[-1], -1e9)
        rows = [(D, 100 + k + 2, 100 + k - 1, 100 + k + 1, 1) for k in range(40)]
        self.assertGreater(backtest.adx(rows), 20)                    # a steady uptrend is trending

    def test_your_way(self):
        t = [{"date": "2026-10-29", "time": "09:40", "score": 8, "symbol": "A", "net": -50.0, "exit_time": "09:55"},
             {"date": "2026-10-29", "time": "09:45", "score": 9, "symbol": "B", "net": 80.0, "exit_time": "10:30"},
             {"date": "2026-10-29", "time": "10:00", "score": 7, "symbol": "C", "net": -40.0, "exit_time": "10:20"},
             {"date": "2026-10-29", "time": "11:00", "score": 7, "symbol": "D", "net": 60.0, "exit_time": "11:30"},
             {"date": "2026-10-29", "time": "12:00", "score": 7, "symbol": "E", "net": 60.0, "exit_time": "12:30"}]
        took = backtest.your_way(t)
        self.assertEqual([x["symbol"] for x in took], ["A", "C"])     # B overlapped A; then 2 trades a day
        s = backtest.summary(took)
        self.assertEqual((s["trades"], s["win_rate"], s["total"]), (2, 0, -90.0))

    def test_reason_groups(self):
        self.assertEqual(backtest.reason_group("Weak volume: 1.2x normal"), "Weak volume")
        self.assertEqual(backtest.reason_group("Against its daily trend (below the 20-day average)"),
                         "Against the daily trend")


if __name__ == "__main__":
    unittest.main()
