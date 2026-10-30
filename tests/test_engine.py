"""Offline tests for the scanner website's engine and journal, on SYNTHETIC bars (made-up stocks)."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine  # noqa: E402
import journal  # noqa: E402

DT = datetime.datetime
DAY = datetime.date(2026, 10, 29)        # a Thursday, NSE open
PREV = datetime.date(2026, 10, 28)


def ts(d, hh, mm):
    utc = engine.scan.ist_to_utc(DT.combine(d, datetime.time(hh, mm)))
    return int((utc - DT(1970, 1, 1)).total_seconds())


def series(rows, meta=None):
    """rows: (date, 'HH:MM', o, h, l, c, v)"""
    s = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": [], "meta": meta or {}}
    for d, hm, o, h, l, c, v in rows:
        hh, mm = map(int, hm.split(":"))
        s["t"].append(ts(d, hh, mm))
        for k, x in zip("ohlcv", (o, h, l, c, v)):
            s[k].append(x)
    return s


def flat_day(d, price, n=75, high=None):
    rows = []
    for k in range(n):
        t = DT.combine(d, datetime.time(9, 15)) + datetime.timedelta(minutes=5 * k)
        rows.append((d, t.strftime("%H:%M"), price, price + 0.5, price - 0.5, price, 10000))
    if high:
        rows[10] = (d, rows[10][1], price, high, price - 0.5, price, 10000)
    return rows


def breakout_stock(extra=()):
    rows = flat_day(PREV, 300.0, high=305.0)
    rows += [(DAY, "09:15", 300.5, 302.0, 299.0, 301.0, 50000),
             (DAY, "09:20", 301.0, 302.5, 300.0, 301.5, 30000),
             (DAY, "09:25", 301.5, 302.0, 300.5, 301.8, 25000),
             (DAY, "09:30", 301.8, 302.4, 301.5, 302.2, 20000),
             (DAY, "09:35", 302.3, 304.2, 302.2, 304.0, 60000)]
    rows += list(extra)
    return series(rows)


def nifty(moves=None):
    rows = flat_day(PREV, 25000.0)
    p = 25010.0
    for k, hm in enumerate(["09:15", "09:20", "09:25", "09:30", "09:35", "09:40", "09:45", "09:50", "09:55"]):
        p = (moves or {}).get(hm, p + 5)
        rows.append((DAY, hm, p, p + 3, p - 3, p, 0))
    return series(rows)


DAILY = [290.0 + i * 0.2 for i in range(25)]
NOW = DT.combine(DAY, datetime.time(9, 41))


class Money(unittest.TestCase):
    def test_ticks_charges_and_sizing(self):
        self.assertEqual((engine.tick_size(249), engine.tick_size(300), engine.tick_size(1200)), (0.01, 0.05, 0.1))
        self.assertEqual(engine.snap(300.75, "down", 304), 300.75)
        self.assertEqual(engine.snap(300.77, "down", 304), 300.75)
        self.assertEqual(engine.charges(7, 685, 693), 13.52)          # matches the pack's size.py
        self.assertEqual(engine.size("buy", 304.0, 300.75, 5000, 75), 16)
        self.assertEqual(engine.size("buy", 304.0, 290.0, 5000, 75), 4)
        self.assertEqual(engine.size("buy", 304.0, 200.0, 5000, 75), 0)
        self.assertEqual(engine.rupees(123456), "\u20b91,23,456")
        self.assertEqual(engine.rupees(-72.4, sign=True), "\u2212\u20b972")


class Analyse(unittest.TestCase):
    def test_strong_buy(self):
        r = engine.analyse("ACMEAUTO", breakout_stock(), DAILY, nifty(), NOW, news_flag="")
        self.assertEqual((r["kind"], r["side"], r["reason"]), ("pick", "buy", None))
        self.assertEqual((r["or_high"], r["or_low"]), (302.5, 299.0))
        self.assertEqual((r["entry"], r["stop"], r["target"], r["lock"]), (304.0, 300.75, 310.5, 307.25))
        pts = {k: p for k, _, p, _ in r["factors"]}
        self.assertEqual(pts, {"breakout": 2, "volume": 2, "vwap": 1, "relative": 2, "trend": 1, "room": 0,
                               "market": 1})
        self.assertEqual((r["score"], r["strength"]), (9, "Strong"))
        self.assertEqual((r["qty"], r["signal_time"].time()), (16, datetime.time(9, 40)))
        self.assertEqual(r["exit_by"].time(), datetime.time(10, 40))
        self.assertLessEqual(r["loss_at_stop"], 75)
        self.assertTrue(all(ok for _, _, ok in r["checks"]))

    def test_the_bar_must_be_complete(self):
        r = engine.analyse("X", breakout_stock(), DAILY, nifty(), DT.combine(DAY, datetime.time(9, 39)))
        self.assertEqual(r["kind"], "watch")                            # the 9:35 bar closes at 9:40

    def test_skips_say_why(self):
        r = engine.analyse("X", breakout_stock(), DAILY, nifty(), NOW, news_flag="results")
        self.assertEqual((r["kind"], r["reason"]), ("skip", "News today: results"))
        r = engine.analyse("X", breakout_stock(), DAILY, nifty(), NOW, cfg={"capital": 200})
        self.assertEqual(r["reason"], "Too risky for your capital")
        r = engine.analyse("X", breakout_stock(), DAILY, nifty(), NOW, cfg={"max_price": 250})
        self.assertIn("Price outside", r["reason"])
        s = breakout_stock()
        s["o"][75] = 310.0                                            # a 3% gap up at the open
        self.assertEqual(engine.analyse("X", s, DAILY, nifty(), NOW)["reason"], "Opened with a big gap")
        down = nifty({"09:30": 24900.0, "09:35": 24880.0})
        r = engine.analyse("X", breakout_stock(), [320.0] * 25, down, NOW, news_flag="")
        self.assertEqual(r["kind"], "pick")                           # one weak factor does not kill it
        self.assertEqual(r["score"], 7)

    def test_after_the_signal(self):
        ran = breakout_stock([(DAY, "09:40", 304.0, 306.0, 303.9, 305.9, 30000)])
        r = engine.analyse("X", ran, DAILY, nifty(), DT.combine(DAY, datetime.time(9, 46)))
        self.assertEqual(r["reason"], "Price has moved on from the entry")
        failed = breakout_stock([(DAY, "09:40", 304.0, 304.1, 300.5, 300.9, 30000)])
        r = engine.analyse("X", failed, DAILY, nifty(), DT.combine(DAY, datetime.time(9, 46)))
        self.assertEqual(r["reason"], "Broke out, then fell back to the stop")
        r = engine.analyse("X", breakout_stock(), DAILY, nifty(), DT.combine(DAY, datetime.time(14, 40)))
        self.assertEqual(r["reason"], "Too late in the day for a new trade")

    def test_watch_and_shorts(self):
        rows = flat_day(PREV, 300.0)
        rows += [(DAY, "09:15", 300.5, 302.0, 299.0, 301.0, 50000), (DAY, "09:20", 301.0, 302.5, 300.0, 301.5, 30000),
                 (DAY, "09:25", 301.5, 302.0, 300.5, 301.8, 25000), (DAY, "09:30", 301.8, 302.4, 301.5, 302.2, 20000)]
        r = engine.analyse("NEAR", series(rows), DAILY, nifty(), DT.combine(DAY, datetime.time(9, 36)))
        self.assertEqual((r["kind"], r["distance"]), ("watch", 0.3))
        rows2 = rows[:-1] + [(DAY, "09:30", 299.5, 299.6, 297.0, 297.2, 70000)]
        self.assertIsNone(engine.analyse("DOWN", series(rows2), DAILY, nifty(), DT.combine(DAY, datetime.time(9, 36))))
        r = engine.analyse("DOWN", series(rows2), [320.0] * 25, nifty({"09:30": 24950.0}),
                           DT.combine(DAY, datetime.time(9, 36)), cfg={"shorts": True}, news_flag="")
        self.assertEqual((r["kind"], r["side"]), ("pick", "sell"))
        self.assertGreater(r["stop"], r["entry"])
        self.assertLess(r["target"], r["entry"])

    def test_rank(self):
        a = engine.analyse("A", breakout_stock(), DAILY, nifty(), NOW, news_flag="")
        b = dict(a, symbol="B", score=7)
        c = dict(a, symbol="C", score=8)
        d = dict(a, symbol="D", score=6)
        picks, watch, skipped = engine.rank([b, a, None, d, c])
        self.assertEqual([p["symbol"] for p in picks], ["A", "C", "B"])
        self.assertEqual([s["symbol"] for s in skipped], ["D"])

    def test_stage_one_keeps_breakouts_and_near_ones(self):
        spark = {"A": breakout_stock(), "Q": series(flat_day(PREV, 300.0) + [
            (DAY, "09:15", 300, 300, 300, 300, 0), (DAY, "09:20", 300, 300, 300, 300, 0),
            (DAY, "09:25", 300, 300, 300, 300, 0), (DAY, "09:30", 290, 290, 290, 290, 0)])}
        self.assertEqual(engine.stage_one(spark, NOW), ["A"])

    def test_news_flag(self):
        xml = ("<rss><channel><item><title>Acme Q2 results today</title><pubDate>Thu, 29 Oct 2026 02:00:00 +0000"
               "</pubDate></item></channel></rss>")
        self.assertIn("results", engine.news_flag(xml, NOW))
        old = xml.replace("29 Oct", "20 Oct")
        self.assertEqual(engine.news_flag(old, NOW), "")
        self.assertIsNone(engine.news_flag("<html", NOW))


class Trades(unittest.TestCase):
    def trade(self, **kw):
        t = journal.new_trade("ACMEAUTO", "buy", 304.0, 300.75, 16, "paper", DT.combine(DAY, datetime.time(9, 41)))
        t.update(kw)
        return t

    def test_new_trade_and_levels(self):
        t = self.trade()
        self.assertEqual((t["target"], t["lock"], t["exit_by"][-8:]), (310.5, 307.25, "10:41:00"))
        mp = journal.money_plan("buy", 304.0, 300.75, 16)
        self.assertEqual((mp["loss"] <= 75, mp["gain"] > 0, mp["break_even"] > 304.0), (True, True, True))
        for bad, msg in (((300.0, 304.0, 16), "below your buy price"), ((304.0, 300.0, 1.5), "whole number"),
                         ((0, 0, 1), "buy price")):
            with self.assertRaises(journal.JournalError) as cm:
                journal.new_trade("X", "buy", bad[0], bad[1], bad[2], "paper", NOW)
            self.assertIn(msg, str(cm.exception))

    def bars_after(self, rows):
        return breakout_stock(rows)

    def test_alerts(self):
        n = nifty()
        t = self.trade()
        s = self.bars_after([(DAY, "09:40", 304.0, 305.0, 303.5, 304.8, 1000)])
        self.assertIsNone(engine.trade_status(t, s, n, DT.combine(DAY, datetime.time(9, 46)))["alert"])
        s = self.bars_after([(DAY, "09:40", 304.0, 307.5, 303.5, 307.0, 1000)])
        self.assertEqual(engine.trade_status(t, s, n, DT.combine(DAY, datetime.time(9, 46)))["alert"], "lock")
        moved = dict(t, stop=304.0, stop_moved_at="2026-10-29T09:46:00")
        self.assertIsNone(engine.trade_status(moved, s, n, DT.combine(DAY, datetime.time(9, 46)))["alert"])
        s = self.bars_after([(DAY, "09:40", 304.0, 311.0, 303.5, 310.8, 1000)])
        self.assertEqual(engine.trade_status(t, s, n, DT.combine(DAY, datetime.time(9, 46)))["alert"], "target")
        s = self.bars_after([(DAY, "09:40", 304.0, 311.0, 300.0, 305.0, 1000)])
        self.assertEqual(engine.trade_status(t, s, n, DT.combine(DAY, datetime.time(9, 46)))["alert"], "stop")
        s = self.bars_after([(DAY, "09:40", 304.0, 304.5, 303.5, 304.2, 1000)])
        drop = nifty({"09:45": 24950.0, "09:50": 24930.0, "09:55": 24900.0})
        st = engine.trade_status(t, s, drop, DT.combine(DAY, datetime.time(10, 1)))
        self.assertEqual(st["alert"], "exit")
        self.assertIn("Nifty fell", st["message"])
        st = engine.trade_status(t, s, n, DT.combine(DAY, datetime.time(10, 45)))
        self.assertIn("No real move", st["message"])
        st = engine.trade_status(t, s, n, DT.combine(DAY, datetime.time(14, 56)))
        self.assertIn("square off", st["message"])

    def test_close_guard_and_results(self):
        data = journal.empty()
        a = journal.close_trade(self.trade(), 310.5, "target", NOW)
        b = journal.close_trade(self.trade(), 300.75, "stop", NOW)
        self.assertGreater(a["net"], 0)
        self.assertLess(b["net"], 0)
        data = journal.replace(journal.replace(data, a), b)
        done, why, counts = journal.guard(data, "paper", DAY)
        self.assertTrue(done)
        self.assertEqual(counts["dots"], ["win", "loss"])
        self.assertFalse(journal.guard(data, "real", DAY)[0])
        r = journal.results(data, "paper")
        self.assertEqual((r["count"], r["wins"], r["losses"], r["win_rate"]), (2, 1, 1, 50))
        self.assertEqual(len(r["running"]), 2)
        with self.assertRaises(journal.JournalError):
            journal.close_trade(self.trade(), "abc", "other", NOW)


if __name__ == "__main__":
    unittest.main()
