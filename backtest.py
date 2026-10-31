"""60-day backtest for the NSE scanner: the scanner's own rules (engine.analyse) replayed on past
5-minute bars, every breakout managed the way the app manages a live trade, with Groww's charges.

Variants, each compared with the Phase 1 rules (15-minute range, stop at the range middle, entry at
the breakout close, 2x target with safety lock, trailing stop, time exit and market-drop exit):

  touch        buy the moment the price touches the breakout price (an advance stop-limit order), with only
               the checks known in advance (trend, ATR room, range size, money, charges); no volume, candle
               or VWAP confirmation
  old_rules    the rules before Phase 1 (no must-pass volume, candle, ATR room, trend, charges checks)
  retest       wait for a pullback to the range high that holds, with a firm candle, then enter
  range30      a 30-minute opening range instead of 15
  stop_candle  stop just beyond the breakout candle instead of the range middle
  half_3r      sell half at 1.5x risk (stop to the buy price), trail the rest under 15-minute lows to 3x
  vwap_exit    current exits, plus exit on a 5-minute close on the wrong side of VWAP
  vwap_trail   after +1x risk: no target, exit on a close on the wrong side of VWAP (never below the buy price)

Filters (win rate with and without, on the Phase 1 signals): RSI(14, 5-minute) above 60, MACD histogram
expanding, daily ADX(14) above 20, plus the filter-lab fields.

"Your way" applies your day rules on top: one trade at a time, at most `max_trades` a day, stop after
`max_losses` losses or the daily loss limit, first signals first.

Limits: Yahoo keeps 60 days of 5-minute bars; no slippage beyond the candle prices; the stock list is
today's (survivorship); no news check for past days. A backtest is evidence, not a promise.
"""

import datetime

import engine

BAR = engine.BAR
VARIANTS = ["phase1", "touch", "old_rules", "retest", "range30", "stop_candle", "half_3r", "vwap_exit", "vwap_trail"]
VARIANT_NAMES = {
    "phase1": "Phase 1 rules (now)",
    "touch": "Buy on touch (order in advance)",
    "old_rules": "Old rules (before Phase 1)",
    "retest": "Entry: wait for the retest",
    "range30": "30-minute opening range",
    "stop_candle": "Stop below the breakout candle",
    "half_3r": "Half at 1.5x, trail rest to 3x",
    "vwap_exit": "Exit on a close below VWAP",
    "vwap_trail": "Trail with VWAP after +1x",
}
FILTERS = [("rsi60", "RSI above 60 (below 40 for shorts)"), ("macd_up", "MACD histogram expanding"),
           ("adx20", "Daily ADX above 20"), ("before_11", "Breakout before 11 AM"),
           ("in_play", "In play (2x volume)"), ("trend_rising", "20-day average rising"),
           ("nr7", "Yesterday was NR7"), ("narrow_cpr", "Narrow CPR"),
           ("open_extreme", "Opened at the day's low"), ("near_52w", "Within 5% of 52-week high")]


# ---------------------------------------------------------------- data preparation

def prepare(series):
    """Precompute IST times and session days once (makes the replay fast)."""
    if not series:
        return series
    s = dict(series)
    s["_ist"] = [engine.scan.ts_to_ist(ts) if ts else None for ts in (s.get("t") or [])]
    s["_days"] = sorted({x.date() for x in s["_ist"] if x})
    return s


def window(series, day, prev=4, meta=None):
    """The series cut to `day` and the `prev` sessions before it, like the live 5-day download."""
    days = [d for d in series["_days"] if d <= day]
    keep = set(days[-(prev + 1):])
    idx = [i for i, x in enumerate(series["_ist"]) if x and x.date() in keep]
    out = {k: [series[k][i] for i in idx] if series.get(k) is not None else None for k in ("t", "o", "h", "l", "c", "v")}
    out["_ist"] = [series["_ist"][i] for i in idx]
    out["_days"] = sorted(keep)
    out["meta"] = dict(meta or {})
    return out


def daily_rows(dchart):
    return engine.daily_ohlc(dchart, datetime.date(2100, 1, 1)) if dchart else []


# ---------------------------------------------------------------- indicators for the filters

def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for k in range(1, n + 1):
        d = closes[k] - closes[k - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for k in range(n + 1, len(closes)):
        d = closes[k] - closes[k - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def ema(vals, n):
    k = 2.0 / (n + 1)
    out, e = [], None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def macd_hist(closes):
    if len(closes) < 35:
        return None
    m = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
    sig = ema(m, 9)
    return [a - b for a, b in zip(m, sig)]


def adx(rows, n=14):
    """Wilder's ADX from daily (date, high, low, close, vol) rows, or None."""
    if len(rows) < 2 * n + 1:
        return None
    trs, pdm, ndm = [], [], []
    for k in range(1, len(rows)):
        _, h, l, _, _ = rows[k]
        _, ph, pl, pc, _ = rows[k - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        up, dn = h - ph, pl - l
        pdm.append(up if up > dn and up > 0 else 0.0)
        ndm.append(dn if dn > up and dn > 0 else 0.0)
    atr_, p_, n_ = sum(trs[:n]), sum(pdm[:n]), sum(ndm[:n])
    dxs = []
    for k in range(n, len(trs)):
        atr_ = atr_ - atr_ / n + trs[k]
        p_ = p_ - p_ / n + pdm[k]
        n_ = n_ - n_ / n + ndm[k]
        pdi, ndi = 100 * p_ / atr_ if atr_ else 0, 100 * n_ / atr_ if atr_ else 0
        dxs.append(100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) else 0)
    if len(dxs) < n:
        return None
    a = sum(dxs[:n]) / n
    for d in dxs[n:]:
        a = (a * (n - 1) + d) / n
    return a


# ---------------------------------------------------------------- managing a trade on past bars

def charges_legs(side, qty, entry, legs):
    """Groww intraday charges for one entry order and one exit order per leg [(shares, price)]."""
    buy_side = side == "buy"
    entry_value = qty * entry
    exit_values = [q * p for q, p in legs if q > 0]
    br = engine._brokerage(entry_value) + sum(engine._brokerage(v) for v in exit_values)
    buys = entry_value if buy_side else sum(exit_values)
    sells = sum(exit_values) if buy_side else entry_value
    t = buys + sells
    exch, sebi, ipft = t * 0.0000297, t * 0.000001, t * 0.000001
    return br + sells * 0.00025 + buys * 0.00003 + exch + sebi + ipft + (br + exch + sebi + ipft) * 0.18


def manage(bars, k, side, entry, stop, mode, nmap, cfg):
    """Replay a trade entered at the close of bars[k]. -> (legs [(fraction, price, how)], exit time)."""
    c = dict(engine.DEFAULTS)
    c.update(cfg or {})
    long = side == "buy"
    sgn = 1 if long else -1
    risk = abs(entry - stop) or 0.01
    target = entry + sgn * c["reward_r"] * risk
    day = bars[k]["start"].date()
    flat = datetime.datetime.combine(day, c["flat_by"])
    exit_by = min(bars[k]["start"] + BAR + datetime.timedelta(minutes=c["time_stop_minutes"]), flat)
    cur, stage, remaining, legs = stop, 0, 1.0, []
    pv = vol = 0.0
    for x in bars[:k + 1]:
        if x["v"]:
            pv += (x["h"] + x["l"] + x["c"]) / 3.0 * x["v"]
            vol += x["v"]

    def reached(b, level):
        return b["h"] >= level if long else b["l"] <= level

    def hit(b, level):
        return b["l"] <= level if long else b["h"] >= level

    for j in range(k + 1, len(bars)):
        b = bars[j]
        end = b["start"] + BAR
        if b["v"]:
            pv += (b["h"] + b["l"] + b["c"]) / 3.0 * b["v"]
            vol += b["v"]
        vw = pv / vol if vol else None
        if hit(b, cur):                                        # stop (a gap through it fills at the open)
            price = min(b["o"], cur) if long else max(b["o"], cur)
            legs.append((remaining, price, "stop" if stage == 0 else "protected stop"))
            return legs, end
        if mode == "half_3r":
            tp1 = entry + sgn * 1.5 * risk
            tp2 = entry + sgn * 3.0 * risk
            if stage == 0 and reached(b, tp1):
                legs.append((0.5, tp1, "half at 1.5x"))
                remaining, stage = 0.5, 1
            if stage == 1 and reached(b, tp2):
                legs.append((remaining, tp2, "3x target"))
                return legs, end
        elif mode != "vwap_trail" or stage == 0:
            if mode != "vwap_trail" and reached(b, target):
                legs.append((remaining, target, "target"))
                return legs, end
        n0 = nmap.get(b["start"])
        n3 = nmap.get(b["start"] - BAR * 3)
        if n0 and n3 and sgn * (n0 / n3 - 1) * 100 <= -c["market_drop_pct"]:
            legs.append((remaining, b["c"], "market drop"))
            return legs, end
        wrong = vw is not None and (b["c"] < vw if long else b["c"] > vw)
        if mode == "vwap_exit" and wrong:
            legs.append((remaining, b["c"], "VWAP exit"))
            return legs, end
        if mode == "vwap_trail" and stage >= 1 and wrong:
            legs.append((remaining, max(b["c"], entry) if long else min(b["c"], entry), "VWAP trail"))
            return legs, end
        if end >= exit_by and stage == 0 and sgn * (b["c"] - entry) < 0.5 * risk:
            legs.append((remaining, b["c"], "time exit"))
            return legs, end
        if end >= flat:
            legs.append((remaining, b["c"], "2:55 PM"))
            return legs, end
        # stage changes take effect from the next candle (the order inside a candle is unknown)
        if mode == "half_3r":
            if stage == 1:
                lows = [x["l"] if long else x["h"] for x in bars[max(k + 1, j - 2):j + 1]]
                cur = max(cur, entry, min(lows)) if long else min(cur, entry, max(lows))
        else:
            if stage == 0 and reached(b, entry + sgn * risk):
                stage, cur = 1, entry
            elif stage == 1 and mode != "vwap_trail" and reached(b, entry + sgn * 1.5 * risk):
                stage, cur = 2, entry + sgn * 0.5 * risk
    last = bars[-1]
    legs.append((remaining, last["c"], "close"))
    return legs, last["start"] + BAR


def settle(side, qty, entry, legs):
    if qty < 1:
        return None
    if len(legs) == 2 and qty >= 2:
        q1 = qty // 2
        shares = [(q1, legs[0][1]), (qty - q1, legs[1][1])]
    else:
        price = sum(f * p for f, p, _ in legs) / max(sum(f for f, _, _ in legs), 1e-9)
        shares = [(qty, price)]
    gross = sum(q * ((p - entry) if side == "buy" else (entry - p)) for q, p in shares)
    return round(gross - charges_legs(side, qty, entry, shares), 2)


def find_retest(bars, i, side, level, stop, look=6):
    """Index of the first candle within `look` candles after the breakout that dips back to the broken
    level and closes firmly beyond it, or None (no retest, or the stop came first)."""
    long = side == "buy"
    for j in range(i + 1, min(len(bars), i + 1 + look)):
        b = bars[j]
        if (b["l"] <= stop) if long else (b["h"] >= stop):
            return None
        span = b["h"] - b["l"]
        firm = span > 0 and ((b["c"] - b["l"]) / span >= 0.5 if long else (b["h"] - b["c"]) / span >= 0.5)
        if long and b["l"] <= level * 1.001 and b["c"] > level and b["c"] > b["o"] and firm:
            return j
        if not long and b["h"] >= level * 0.999 and b["c"] < level and b["c"] < b["o"] and firm:
            return j
    return None


# ---------------------------------------------------------------- the replay

def run(charts, dailies, nifty, cfg, days=None, progress=None):
    """charts {SYM: 60-day 5-minute series}, dailies {SYM: 1-year daily series}, nifty: 60-day 5-minute series.
    -> {"trades": {variant: [trade]}, "filters": [...], "days": n, "stocks": n}"""
    c = dict(engine.DEFAULTS)
    c.update(cfg or {})
    charts = {k: prepare(v) for k, v in charts.items() if v}
    nifty = prepare(nifty)
    all_days = [d for d in nifty["_days"]][:-1] if nifty and nifty.get("_days") else []
    if days:
        all_days = all_days[-days:]
    trades = {v: [] for v in VARIANTS}
    rejected = {}
    total = len(all_days) * max(len(charts), 1)
    done = 0
    for d in all_days:
        now = datetime.datetime.combine(d, datetime.time(15, 31))
        nwin = window(nifty, d)
        nmap = {b["start"]: b["c"] for b in engine.day_bars(nwin, d)}
        for sym, ser in charts.items():
            done += 1
            if progress and done % 25 == 0:
                progress(done / float(total))
            if d not in ser["_days"]:
                continue
            rows = [r for r in daily_rows(dailies.get(sym)) if r[0] < d]
            closes = [r[3] for r in rows]
            last250 = rows[-250:]
            meta = {"fiftyTwoWeekHigh": max(r[1] for r in last250), "fiftyTwoWeekLow": min(r[2] for r in last250)} \
                if last250 else {}
            win = window(ser, d, meta=meta)
            bars = engine.day_bars(win, d)
            dchart = dailies.get(sym)
            for variant, extra in (("phase1", {}), ("old_rules", {"strict": False}), ("range30", {"or_bars": 6}),
                                   ("stop_candle", {"stop_rule": "candle"})):
                r = engine.analyse(sym, win, closes, nwin, now, dict(c, **extra), daily_chart=dchart)
                if variant == "phase1" and r and r.get("kind") != "watch" and not r.get("signal_valid"):
                    key = reason_group(r.get("signal_reason") or "")
                    rejected[key] = rejected.get(key, 0) + 1
                if not r or r.get("kind") == "watch" or not r.get("signal_valid"):
                    continue
                k = r["trigger_index"]
                legs, out_t = manage(bars, k, r["side"], r["entry"], r["stop"], "current", nmap, c)
                trades[variant].append(_trade(sym, d, r, r["entry"], r["qty"], legs, out_t))
                if variant != "phase1":
                    continue
                for mode in ("half_3r", "vwap_exit", "vwap_trail"):
                    lg, ot = manage(bars, k, r["side"], r["entry"], r["stop"], mode, nmap, c)
                    trades[mode].append(_trade(sym, d, r, r["entry"], r["qty"], lg, ot))
                level = r["or_high"] if r["side"] == "buy" else r["or_low"]
                j = find_retest(bars, k, r["side"], level, r["stop"])
                if j is not None:
                    e2 = engine.snap(bars[j]["c"])
                    q2 = engine.size(r["side"], e2, r["stop"], c["capital"], c["max_loss"])
                    if q2 >= 1 and abs(e2 - r["stop"]) > 0:
                        lg, ot = manage(bars, j, r["side"], e2, r["stop"], "current", nmap, c)
                        t = _trade(sym, d, r, e2, q2, lg, ot)
                        t["time"] = (bars[j]["start"] + BAR).strftime("%H:%M")
                        trades["retest"].append(t)
                else:
                    trades["retest"].append(dict(_blank(sym, d, r), missed=True))
                # filters for the Phase 1 signal
                cl = []
                for dd in win["_days"]:
                    bb = engine.day_bars(win, dd)
                    cl += [x["c"] for x in (bb if dd < d else bb[:k + 1])]
                rv = rsi(cl)
                mh = macd_hist(cl)
                ad = adx(rows[-60:])
                long = r["side"] == "buy"
                f = dict(r.get("lab") or {})
                f["rsi60"] = None if rv is None else (rv > 60 if long else rv < 40)
                f["macd_up"] = None if not mh or len(mh) < 2 else \
                    ((mh[-1] > mh[-2] and mh[-1] > 0) if long else (mh[-1] < mh[-2] and mh[-1] < 0))
                f["adx20"] = None if ad is None else ad > 20
                trades["phase1"][-1]["filters"] = f
            t = touch_trade(sym, win, closes, nwin, bars, d, c, dchart, nmap)
            if t:
                trades["touch"].append(t)
    if progress:
        progress(1.0)
    return {"trades": trades, "days": len(all_days), "stocks": len(charts), "rejected": rejected}


REASON_GROUPS = [("Weak volume", "Weak volume"), ("Weak candle", "Weak candle (wick or small body)"),
                 ("Against its daily trend", "Against the daily trend"), ("Already used", "No ATR room left"),
                 ("Already moved", "Already moved too far"), ("big gap", "Big opening gap"),
                 ("VWAP", "Wrong side of VWAP"), ("Morning range", "Range too wide or tiny"),
                 ("Charges", "Charges too large"), ("Too risky", "Too risky for capital"),
                 ("Price outside", "Outside price range"), ("outside 9:30", "Outside 9:30 AM-2:30 PM"),
                 ("Afternoon", "Afternoon, score under 8"), ("Score", "Score under 6"), ("Big event", "Big event")]


def reason_group(reason):
    for key, label in REASON_GROUPS:
        if key.lower() in reason.lower():
            return label
    return "Other"


def touch_trade(sym, win, closes, nwin, bars, d, c, dchart, nmap):
    """Option B: an order placed in advance at the breakout price fills on the first touch."""
    n_or = int(c["or_bars"])
    if len(bars) <= n_or:
        return None
    or_high = max(b["h"] for b in bars[:n_or])
    for j in range(n_or, len(bars)):
        b = bars[j]
        t = b["start"].time()
        if t > c["no_entries_after"]:
            return None
        if b["h"] <= or_high:
            continue
        if t < c["no_entries_before"]:
            return None                     # touched inside the no-entry window: no order would be live
        w = engine.watch_info(sym, win, closes, nwin, b["start"], c, daily_chart=dchart)
        if not w:
            return None                     # an advance check failed: you would not have placed the order
        entry = max(b["o"], w["entry"])
        qty = engine.size("buy", entry, w["stop"], c["capital"], c["max_loss"])
        if qty < 1:
            return None
        r = {"signal_time": b["start"], "side": "buy", "score": w["rating"]}
        if b["l"] <= w["stop"]:             # fell back to the stop within the same candle
            legs, out_t = [(1.0, w["stop"], "stop")], b["start"] + BAR
        else:
            legs, out_t = manage(bars, j, "buy", entry, w["stop"], "current", nmap, c)
        tr = _trade(sym, d, r, entry, qty, legs, out_t)
        tr["time"] = b["start"].strftime("%H:%M")
        return tr
    return None


def _blank(sym, d, r):
    return {"symbol": sym, "date": d.isoformat(), "time": r["signal_time"].strftime("%H:%M"), "side": r["side"],
            "score": r["score"], "entry": r["entry"], "qty": 0, "net": None, "how": "no retest", "exit_time": None}


def _trade(sym, d, r, entry, qty, legs, out_t):
    price = sum(f * p for f, p, _ in legs) / max(sum(f for f, _, _ in legs), 1e-9)
    return {"symbol": sym, "date": d.isoformat(), "time": r["signal_time"].strftime("%H:%M"), "side": r["side"],
            "score": r["score"], "entry": entry, "exit": round(price, 2), "qty": qty,
            "how": " + ".join(h for _, _, h in legs), "net": settle(r["side"], qty, entry, legs),
            "exit_time": out_t.strftime("%H:%M")}


# ---------------------------------------------------------------- results

def your_way(trades, cfg=None):
    """Your day rules on top: one trade at a time, max trades and losses a day, the daily loss limit."""
    c = dict(engine.DEFAULTS)
    c.update(cfg or {})
    out = []
    by_day = {}
    for t in trades:
        if t.get("net") is not None:
            by_day.setdefault(t["date"], []).append(t)
    for d in sorted(by_day):
        free_at, n, losses, total = "00:00", 0, 0, 0.0
        for t in sorted(by_day[d], key=lambda x: (x["time"], -x["score"], x["symbol"])):
            if n >= c["max_trades"] or losses >= c["max_losses"] or total <= -c["daily_loss"]:
                break
            if t["time"] < free_at:
                continue
            out.append(t)
            n += 1
            total += t["net"]
            losses += 1 if t["net"] < 0 else 0
            free_at = t["exit_time"] or "23:59"
    return out


def summary(trades):
    done = [t for t in trades if t.get("net") is not None]
    missed = sum(1 for t in trades if t.get("missed"))
    if not done:
        return {"trades": 0, "missed": missed}
    wins = [t["net"] for t in done if t["net"] > 0]
    losses = [t["net"] for t in done if t["net"] <= 0]
    eq, peak, dd = 0.0, 0.0, 0.0
    curve = []
    for t in sorted(done, key=lambda x: (x["date"], x["time"])):
        eq += t["net"]
        curve.append(round(eq, 2))
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    gross_win, gross_loss = sum(wins), -sum(losses)
    return {"trades": len(done), "missed": missed, "win_rate": round(100.0 * len(wins) / len(done)),
            "total": round(eq, 2), "avg": round(eq / len(done), 2),
            "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
            "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
            "max_drawdown": round(dd, 2), "curve": curve}


def filter_table(trades):
    rows = []
    done = [t for t in trades if t.get("net") is not None and t.get("filters")]
    for key, label in FILTERS:
        yes = [t["net"] for t in done if t["filters"].get(key) is True]
        no = [t["net"] for t in done if t["filters"].get(key) is False]

        def stat(xs):
            if not xs:
                return (0, None, None)
            return (len(xs), round(100.0 * sum(1 for x in xs if x > 0) / len(xs)), round(sum(xs) / len(xs), 2))
        rows.append((label, stat(yes), stat(no)))
    return rows


# ---------------------------------------------------------------- data (Yahoo, via scan.py)

def fetch_intraday(sym):
    """60 days of 5-minute bars (Yahoo's limit for 5-minute history)."""
    return engine.scan.parse_chart(engine.scan.yahoo_get(engine.scan.chart_path(sym, "60d", "5m")), sym)


def fetch_daily(sym):
    """One year of daily bars (ATR, 20-day trend, ADX, NR7, 52-week high)."""
    return engine.scan.parse_chart(engine.scan.yahoo_get(engine.scan.chart_path(sym, "1y", "1d")), sym)
