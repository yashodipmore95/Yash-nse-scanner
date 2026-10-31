"""The decision engine behind the NSE scanner website (version 1). Standard library only.

It reads Yahoo Finance bars through trader-scanner/scan.py, finds 15-minute opening-range
breakouts, scores each one out of 10, applies hard safety checks, sizes the trade to your
capital and max loss with Groww's intraday charges, and works out the stop, target, safety
lock and exit time. It also watches open trades for the safety lock, stop, target, a sharp
Nifty drop and the time exit.

Every rule here is a rule, not a prediction. Not financial advice.
"""

import datetime
import importlib.util
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("scan", os.path.join(HERE, "trader-scanner", "scan.py"))
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)

IST_OPEN = datetime.time(9, 15)
OR_BARS = 3                       # 9:15, 9:20, 9:25: the 15-minute opening range
BAR = datetime.timedelta(minutes=5)
NIFTY = "^NSEI"
WATCH_PCT = 2.0          # watchlist: within 2% below the breakout price

DEFAULTS = {
    "capital": 5000.0,
    "max_loss": 75.0,
    "max_trades": 2,
    "max_losses": 2,
    "daily_loss": 150.0,
    "min_price": 100.0,
    "max_price": 500.0,
    "shorts": False,
    "no_entries_before": datetime.time(9, 30),
    "no_entries_after": datetime.time(14, 30),
    "flat_by": datetime.time(14, 55),
    "time_stop_minutes": 60,
    "reward_r": 2.0,
    "max_gap_pct": 2.0,
    "max_extended_pct": 3.0,
    "market_drop_pct": 0.4,
}

FACTORS = [  # key, label on the card, points (13 in all, shown as a score out of 10)
    ("breakout", "Breakout", 2),
    ("volume", "Buying power", 2),
    ("inplay", "In play", 2),
    ("vwap", "Buyers in control", 1),
    ("relative", "Beats market", 2),
    ("trend", "Trend", 1),
    ("room", "Room to move", 1),
    ("market", "Market okay", 1),
    ("early", "Early breakout", 1),
]
RAW_MAX = sum(p for _, _, p in FACTORS)

SECTORS = [("Bank", "^NSEBANK"), ("IT", "^CNXIT"), ("Auto", "^CNXAUTO"), ("Pharma", "^CNXPHARMA"),
           ("Metal", "^CNXMETAL"), ("FMCG", "^CNXFMCG"), ("Energy", "^CNXENERGY"), ("Realty", "^CNXREALTY")]
INDUSTRY_SECTOR = [  # NSE industry name (Nifty 500 list) -> sector tile
    ("financial", "Bank"), ("bank", "Bank"), ("information technology", "IT"), ("automobile", "Auto"),
    ("healthcare", "Pharma"), ("pharma", "Pharma"), ("metal", "Metal"), ("fast moving consumer", "FMCG"),
    ("oil", "Energy"), ("power", "Energy"), ("energy", "Energy"), ("realty", "Realty"),
]


def sector_of(industry):
    low = (industry or "").lower()
    for key, name in INDUSTRY_SECTOR:
        if key in low:
            return name
    return None
WEAK_REASON = {
    "breakout": "weak breakout candle",
    "volume": "weak buying",
    "vwap": "below the day's average price",
    "relative": "weaker than the market",
    "trend": "against its longer trend",
    "room": "resistance just above",
    "market": "market falling",
    "inplay": "not much trading interest today",
    "early": "late in the day",
}
WEAK_REASON_SHORT = dict(WEAK_REASON, volume="weak selling", vwap="above the day's average price",
                         relative="stronger than the market", room="support just below", market="market rising")
DEFAULTS.update({"narrow_cpr_pct": 0.25, "near_52w_pct": 5.0})
# Phase 1 must-pass rules (strict=False turns them off, for the backtest's "old rules" comparison)
DEFAULTS.update({"strict": True, "min_volume_x": 1.5, "min_body": 0.5, "min_close_pos": 2.0 / 3.0,
                 "max_atr_used": 0.7, "max_charges_share": 0.25, "event_window_min": 30, "events": [],
                 "or_bars": 3, "stop_rule": "mid"})
DEFAULTS.update({"range_min": 0.25, "range_max": 1.2, "early_until": datetime.time(11, 0),
                 "strong_only_after": datetime.time(13, 0)})


# ---------------------------------------------------------------- money and ticks

def tick_size(price):
    """NSE cash-market tick for a price (revised 15 April 2025; NSE reviews it monthly)."""
    p = float(price)
    for limit, tick, inclusive in ((250.0, 0.01, False), (1000.0, 0.05, True), (5000.0, 0.10, True),
                                   (10000.0, 0.50, True), (20000.0, 1.00, True)):
        if p < limit or (inclusive and p == limit):
            return tick
    return 5.0


def snap(x, mode="nearest", ref=None):
    t = tick_size(ref if ref is not None else x)
    n = float(x) / t
    k = math.floor(n + 1e-9) if mode == "down" else math.ceil(n - 1e-9) if mode == "up" else math.floor(n + 0.5 + 1e-9)
    return round(k * t, 2)


def _brokerage(value):
    return max(min(20.0, value * 0.001), min(5.0, value * 0.025))


def charges(qty, buy, sell):
    """Groww's published intraday equity charges for a round trip, in rupees (an estimate)."""
    if qty <= 0:
        return 0.0
    bv, sv = qty * float(buy), qty * float(sell)
    t = bv + sv
    br = _brokerage(bv) + _brokerage(sv)
    exch, sebi, ipft = t * 0.0000297, t * 0.000001, t * 0.000001
    return round(br + sv * 0.00025 + bv * 0.00003 + exch + sebi + ipft + (br + exch + sebi + ipft) * 0.18, 2)


def net(side, qty, entry, exit_price):
    """Net rupees after charges for a trade closed at exit_price."""
    gross = qty * (exit_price - entry) if side == "buy" else qty * (entry - exit_price)
    buy, sell = (entry, exit_price) if side == "buy" else (exit_price, entry)
    return round(gross - charges(qty, buy, sell), 2)


def size(side, entry, stop, capital, max_loss):
    """Whole shares: the loss at the stop plus charges stays within max_loss, and the cost within capital."""
    risk = abs(entry - stop)
    if risk <= 0 or entry <= 0:
        return 0
    q = min(int(max_loss // risk), int(capital // entry))
    while q > 0 and -net(side, q, entry, stop) > max_loss + 0.005:
        q -= 1
    return max(q, 0)


def break_even(side, qty, entry):
    t = tick_size(entry)
    p = entry
    for _ in range(2000):
        if net(side, qty, entry, p) >= 0:
            return round(p, 2)
        p = p + t if side == "buy" else p - t
    return round(p, 2)


def rupees(x, sign=False):
    v = round(float(x))
    s = "{:,}".format(abs(v))
    if len(s.replace(",", "")) > 3:  # Indian grouping
        d = str(abs(v))
        head, tail = d[:-3], d[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    pre = ("+" if v > 0 else "\u2212" if v < 0 else "") if sign else ("\u2212" if v < 0 else "")
    return "%s\u20b9%s" % (pre, s)


# ---------------------------------------------------------------- time

def now_ist():
    return scan.to_ist(datetime.datetime.utcnow())


def market_phase(now):
    """('closed'|'pre'|'forming'|'open'|'after', reason) for an IST datetime."""
    ok, why = scan.trading_day(now.date())
    if not ok:
        return "closed", "NSE is closed today (%s)" % why
    t = now.time()
    if t < IST_OPEN:
        return "pre", "NSE opens at 9:15 AM"
    if t < datetime.time(9, 35):
        return "forming", "The opening range is forming (9:15 to 9:30). First signals after 9:35 AM."
    if t >= datetime.time(15, 30):
        return "after", "The market has closed. These are today's signals, for review only."
    return "open", ""


def hhmm(t):
    return t.strftime("%I:%M %p").lstrip("0")


def candle_key(now, delay=20):
    """Changes once per 5-minute candle, `delay` seconds after it closes (Yahoo needs a moment)."""
    t = now - datetime.timedelta(seconds=delay)
    return "%s%02d" % (t.strftime("%Y%m%d%H"), t.minute // 5)


def candle_close(now):
    """End of the 5-minute candle that is forming at `now` (naive IST)."""
    start = now.replace(minute=now.minute - now.minute % 5, second=0, microsecond=0)
    return start + BAR


# ---------------------------------------------------------------- bars

def day_bars(series, day, cutoff=None):
    """Complete 5-minute bars of `day` (naive IST), each {start, o, h, l, c, v}. A bar counts once
    start + 5 minutes <= cutoff. Off-grid ticks and empty bars are dropped."""
    out = []
    t, c = series.get("t") or [], series.get("c") or []
    o, h, l, v = (series.get(k) or [None] * len(t) for k in ("o", "h", "l", "v"))
    ist = series.get("_ist")
    for i, ts in enumerate(t):
        if ts is None or i >= len(c) or c[i] is None:
            continue
        st = ist[i] if ist else scan.ts_to_ist(ts)
        if st.date() != day or st.second or st.minute % 5:
            continue
        if st.time() < IST_OPEN or st.time() >= datetime.time(15, 30):
            continue
        if cutoff is not None and st + BAR > cutoff:
            continue
        cl = float(c[i])
        out.append({"start": st, "o": float(o[i]) if o[i] is not None else cl,
                    "h": float(h[i]) if h[i] is not None else cl, "l": float(l[i]) if l[i] is not None else cl,
                    "c": cl, "v": float(v[i]) if v[i] is not None else None})
    return out


def series_days(series):
    if series.get("_days"):
        return series["_days"]
    ist = series.get("_ist")
    if ist:
        return sorted({x.date() for x in ist if x})
    return sorted({scan.ts_to_ist(ts).date() for ts in (series.get("t") or []) if ts})


def previous_day(series, day):
    """(date, bars) of the last session before `day` in the series, or (None, [])."""
    days = series_days(series)
    prev = [d for d in days if d < day]
    if not prev:
        return None, []
    return prev[-1], day_bars(series, prev[-1])


def vwap(bars):
    pv = vol = 0.0
    for b in bars:
        if not b["v"]:
            continue
        pv += (b["h"] + b["l"] + b["c"]) / 3.0 * b["v"]
        vol += b["v"]
    return pv / vol if vol else None


def sma(values, n=20):
    vals = [x for x in values if x is not None]
    return sum(vals[-n:]) / n if len(vals) >= n else None


def pct(a, b):
    return (a / b - 1.0) * 100.0 if a and b else None


def daily_ohlc(series, day):
    """[(date, high, low, close, volume)] of full sessions before `day`, from a daily v8 chart."""
    out = []
    series = series or {}
    t = series.get("t") or []
    col = {k: (series.get(k) or [None] * len(t)) for k in ("h", "l", "c", "v")}
    for k, ts in enumerate(t):
        if ts is None:
            continue
        d = scan.ts_to_ist(ts).date()
        h, l, c = col["h"][k], col["l"][k], col["c"][k]
        if d < day and None not in (h, l, c):
            out.append((d, float(h), float(l), float(c), col["v"][k]))
    return out


def atr(rows, n=14):
    """Average true range of the last n sessions from daily_ohlc rows, or None."""
    if len(rows) < n + 1:
        return None
    trs = []
    for k in range(len(rows) - n, len(rows)):
        _, h, l, _, _ = rows[k]
        pc = rows[k - 1][3]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n


def slot_volume_ratio(series, day, start, vol, max_days=4):
    """The breakout candle's volume against the same 5-minute slot on up to `max_days` earlier days
    (time-of-day normal: morning candles are always busier). None without history."""
    if not vol:
        return None
    t = start.time()
    days = series_days(series)
    past = []
    for d in [x for x in days if x < day][-max_days:]:
        v = [b["v"] for b in day_bars(series, d) if b["start"].time() == t and b["v"]]
        if v:
            past.append(v[0])
    if not past:
        return None
    avg = sum(past) / len(past)
    return vol / avg if avg else None


def event_near(events, when, window_min=30):
    """The first event (from the editable calendar) within `window_min` minutes of `when`, or None.
    Events: {"date": "YYYY-MM-DD", "time": "HH:MM", "name": "..."}; one without a time never blocks."""
    for e in events or []:
        try:
            if e.get("date") != when.date().isoformat() or not e.get("time"):
                continue
            hh, mm = map(int, e["time"].split(":"))
            t = datetime.datetime.combine(when.date(), datetime.time(hh, mm))
        except (ValueError, AttributeError):
            continue
        if abs((when - t).total_seconds()) <= window_min * 60:
            return e
    return None


def is_nr7(rows):
    """True when the last full session's range (high - low) was the smallest of the last 7 (None if too short)."""
    if len(rows) < 7:
        return None
    ranges = [h - l for _, h, l, _, _ in rows[-7:]]
    return ranges[-1] <= min(ranges)


def cpr(high, low, close):
    """Central pivot range from yesterday's high, low and close: (pivot, bottom, top, width % of pivot)."""
    p = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = 2 * p - bc
    lo, hi = min(bc, tc), max(bc, tc)
    return p, lo, hi, (hi - lo) / p * 100.0


def sma_rising(closes, n=20, back=5):
    """True when the n-day average today is above where it was `back` sessions ago (None if too short)."""
    if len(closes) < n + back:
        return None
    return sum(closes[-n:]) / n > sum(closes[-n - back:-back]) / n


def relative_volume(series, day, upto):
    """Today's volume up to and including the bar starting at `upto`, against the average of earlier
    days in the series up to the same time of day. None without earlier days."""
    days = series_days(series)
    t_end = upto.time()

    def cum(d):
        return sum(b["v"] or 0 for b in day_bars(series, d) if b["start"].time() <= t_end)
    today = cum(day)
    past = [cum(d) for d in days if d < day]
    past = [x for x in past if x > 0]
    if not past or not today:
        return None
    return today / (sum(past) / len(past))


# ---------------------------------------------------------------- the analysis

def analyse(sym, series, daily, nifty, now, cfg=None, news_flag=None, daily_chart=None, sector=None):
    """One stock -> a result dict, or None when there is nothing to show.

    series  Yahoo v8 5-minute bars, a few days (today and yesterday)
    daily   daily closes BEFORE today, oldest first (for the 20-day trend)
    nifty   Yahoo v8 5-minute bars for ^NSEI, same days
    now     naive IST datetime
    news_flag  None (not checked), "" (nothing found) or a short reason (results, board meeting...)
    daily_chart  Yahoo v8 daily bars (3 months) for the range-size check (ATR); optional
    sector     (name, % move today) of the stock's sector index, for the filter lab; optional

    result kind: "pick" (a BUY / SELL that passed), "skip" (a breakout that failed a check or scored
    under 6, with the reason), "watch" (no breakout yet, close to it)."""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    day = now.date()
    cutoff = min(now, datetime.datetime.combine(day, datetime.time(15, 30)))
    bars = day_bars(series, day, cutoff)
    n_or = int(c["or_bars"])
    if len(bars) < n_or or bars[0]["start"].time() != IST_OPEN:
        return None
    rng = bars[:n_or]
    first = datetime.datetime.combine(day, IST_OPEN)
    if [b["start"] for b in rng] != [first + BAR * k for k in range(n_or)]:
        return None
    or_high, or_low = max(b["h"] for b in rng), min(b["l"] for b in rng)
    prev_day, ybars = previous_day(series, day)
    prev_close = ybars[-1]["c"] if ybars else (series.get("meta") or {}).get("chartPreviousClose")
    y_high = max(b["h"] for b in ybars) if ybars else None
    y_low = min(b["l"] for b in ybars) if ybars else None
    nbars = day_bars(nifty or {}, day, cutoff)
    _, nyb = previous_day(nifty or {}, day)
    n_prev = nyb[-1]["c"] if nyb else ((nifty or {}).get("meta") or {}).get("chartPreviousClose")
    last = bars[-1]

    trig = None
    for i in range(n_or, len(bars)):
        b = bars[i]
        if b["c"] > or_high:
            trig = ("buy", i)
            break
        if c["shorts"] and b["c"] < or_low:
            trig = ("sell", i)
            break
    base = {"symbol": sym, "or_high": or_high, "or_low": or_low, "price": last["c"], "bars": bars,
            "prev_close": prev_close, "as_of": last["start"] + BAR}

    if trig is None:
        if last["c"] < or_high and last["c"] >= or_high * 0.99:
            return dict(base, kind="watch", side="buy", distance=round(or_high - last["c"], 2),
                        closeness=max(0.0, 1.0 - (or_high - last["c"]) / (or_high * 0.01)))
        if c["shorts"] and last["c"] > or_low and last["c"] <= or_low * 1.01:
            return dict(base, kind="watch", side="sell", distance=round(last["c"] - or_low, 2),
                        closeness=max(0.0, 1.0 - (last["c"] - or_low) / (or_low * 0.01)))
        return None

    side, i = trig
    long = side == "buy"
    b = bars[i]
    when = b["start"] + BAR
    entry = snap(b["c"])
    mid = (or_high + or_low) / 2.0
    if c["stop_rule"] == "candle":                  # backtest variant: just beyond the breakout candle
        stop = snap(b["l"] if long else b["h"], "down" if long else "up", entry)
        stop = stop - tick_size(entry) if long else stop + tick_size(entry)
    else:
        stop = snap(mid, "down" if long else "up", entry)
    risk = abs(entry - stop)
    target = snap(entry + c["reward_r"] * risk if long else entry - c["reward_r"] * risk, ref=entry)
    lock = snap(entry + risk if long else entry - risk, ref=entry)
    flat = datetime.datetime.combine(day, c["flat_by"])
    exit_by = min(when + datetime.timedelta(minutes=c["time_stop_minutes"]), flat)
    qty = size(side, entry, stop, c["capital"], c["max_loss"])

    # factors
    pts = {}
    span = b["h"] - b["l"]
    strength = ((b["c"] - b["l"]) / span if long else (b["h"] - b["c"]) / span) if span > 0 else 1.0
    pts["breakout"] = 2 if strength >= 0.6 else 1
    vr = slot_volume_ratio(series, day, b["start"], b["v"])
    if vr is None:
        earlier = [x["v"] for x in bars[1:i] if x["v"]]
        avg = sum(earlier) / len(earlier) if earlier else None
        vr = (b["v"] / avg) if (avg and b["v"]) else None
    pts["volume"] = 2 if vr and vr >= 1.5 else 1 if vr and vr >= 1.0 else 0
    vw = vwap(bars[:i + 1])
    pts["vwap"] = 1 if vw and ((b["c"] > vw) if long else (b["c"] < vw)) else 0
    s_chg = pct(b["c"], prev_close)
    nb = [x for x in nbars if x["start"] <= b["start"]]
    n_chg = pct(nb[-1]["c"], n_prev) if nb and n_prev else None
    if s_chg is not None and n_chg is not None:
        edge = (s_chg - n_chg) if long else (n_chg - s_chg)
        pts["relative"] = 2 if edge >= 0.5 else 1 if edge > 0 else 0
    else:
        pts["relative"] = 0
    avg20 = sma(daily or [])
    pts["trend"] = 1 if (avg20 and prev_close and ((prev_close > avg20) if long else (prev_close < avg20))) else 0
    if long:
        pts["room"] = 1 if (y_high is None or y_high <= entry or y_high >= target) else 0
    else:
        pts["room"] = 1 if (y_low is None or y_low >= entry or y_low <= target) else 0
    pts["market"] = 1 if (n_chg is not None and ((n_chg >= 0) if long else (n_chg <= 0))) else 0
    rv = relative_volume(series, day, b["start"])
    pts["inplay"] = 2 if rv and rv >= 2.0 else 1 if rv and rv >= 1.3 else 0
    pts["early"] = 1 if when.time() <= c["early_until"] else 0
    raw = sum(pts.values())
    score = int(math.floor(raw * 10.0 / RAW_MAX + 0.5))
    factors = [(k, label, pts[k], mx) for k, label, mx in FACTORS]
    rows = daily_ohlc(daily_chart, day) if daily_chart else []
    a14 = atr(rows)
    range_ratio = (or_high - or_low) / a14 if a14 else None
    edge_pct = round(edge, 2) if (s_chg is not None and n_chg is not None) else None
    cp = cpr(max(x["h"] for x in ybars), min(x["l"] for x in ybars), ybars[-1]["c"]) if ybars else None
    tick = tick_size(bars[0]["o"])
    upto = bars[:i + 1]
    open_extreme = (min(x["l"] for x in upto) >= bars[0]["o"] - tick / 2.0) if long else \
        (max(x["h"] for x in upto) <= bars[0]["o"] + tick / 2.0)
    hi52 = ((series.get("meta") or {}).get("fiftyTwoWeekHigh") if long else
            (series.get("meta") or {}).get("fiftyTwoWeekLow"))
    near52 = None
    if hi52:
        near52 = (entry >= float(hi52) * (1 - c["near_52w_pct"] / 100.0)) if long else \
            (entry <= float(hi52) * (1 + c["near_52w_pct"] / 100.0))

    # hard checks, in the order a trader reads them
    gap = pct(bars[0]["o"], prev_close)
    moved = pct(entry, prev_close)
    strict = c["strict"]
    checks = []
    reason = None
    if news_flag:
        reason = reason or "News today: %s" % news_flag
    checks.append(("news", "No big news" if news_flag == "" else ("News check" if news_flag is None else "News today"),
                   None if news_flag is None else (news_flag == "")))
    late = when.time() > c["no_entries_after"] or when.time() < c["no_entries_before"]
    big_gap = gap is not None and abs(gap) > c["max_gap_pct"]
    day_range = max(x["h"] for x in bars[:i + 1]) - min(x["l"] for x in bars[:i + 1])
    atr_used = day_range / a14 if a14 else None
    if strict and atr_used is not None:
        too_far = atr_used >= c["max_atr_used"]
        far_msg = "Already used %d%% of its normal daily move (ATR)" % round(atr_used * 100)
    else:
        too_far = moved is not None and ((moved > c["max_extended_pct"]) if long else (moved < -c["max_extended_pct"]))
        far_msg = "Already moved more than %g%% today" % c["max_extended_pct"]
    checks.append(("late", "Room left today" if strict and atr_used is not None else "Not too late",
                   not (late or big_gap or too_far)))
    if late:
        reason = reason or "Breakout came outside 9:30 AM to 2:30 PM"
    elif big_gap:
        reason = reason or "Opened with a big gap"
    elif too_far:
        reason = reason or far_msg
    ev = event_near(c["events"], when, c["event_window_min"]) if strict else None
    if ev:
        reason = reason or "Big event: %s at %s" % (ev["name"], ev["time"])
    vw_ok = None if not vw else ((b["c"] > vw) if long else (b["c"] < vw))
    checks.append(("vwap", "Above VWAP" if long else "Below VWAP", vw_ok))
    if vw_ok is False:
        reason = reason or ("Closed below the day's average price (VWAP %.2f)" % vw if long
                            else "Closed above the day's average price (VWAP %.2f)" % vw)
    if strict:
        trend_ok = None if not (avg20 and prev_close) else ((prev_close > avg20) if long else (prev_close < avg20))
        checks.append(("trend", "With daily trend", trend_ok))
        if trend_ok is False:
            reason = reason or ("Against its daily trend (below the 20-day average)" if long
                                else "Against its daily trend (above the 20-day average)")
        vol_ok = None if vr is None else vr >= c["min_volume_x"]
        checks.append(("volume", "Volume %.1f\u00d7" % vr if vr else "Volume", vol_ok))
        if vol_ok is False:
            reason = reason or "Weak volume: %.1f\u00d7 normal (needs %.1f\u00d7)" % (vr, c["min_volume_x"])
        body = abs(b["c"] - b["o"])
        candle_ok = span <= 0 or (body >= c["min_body"] * span and strength >= c["min_close_pos"])
        checks.append(("candle", "Firm candle", candle_ok))
        if not candle_ok:
            reason = reason or ("Weak candle: long wick or small body" if strength < c["min_close_pos"]
                                else "Weak candle: small body")
    if range_ratio is not None:
        okr = c["range_min"] <= range_ratio <= c["range_max"]
        checks.append(("range", "Range size okay", okr))
        if not okr:
            reason = reason or ("Morning range too wide (%.1f\u00d7 its normal daily move)" % range_ratio
                                if range_ratio > c["range_max"] else
                                "Morning range too tiny (%.2f\u00d7 its normal daily move)" % range_ratio)
    fits = qty >= 1 and c["min_price"] <= entry <= c["max_price"]
    checks.append(("money", "Fits your money", fits))
    if not fits:
        reason = reason or ("Price outside \u20b9%g to \u20b9%g" % (c["min_price"], c["max_price"])
                            if not (c["min_price"] <= entry <= c["max_price"]) else "Too risky for your capital")
    if strict and qty >= 1:
        gross = qty * abs(target - entry)
        ch = charges(qty, entry, target) if long else charges(qty, target, entry)
        share = ch / gross if gross > 0 else 1.0
        checks.append(("charges", "Worth the charges", share <= c["max_charges_share"]))
        if share > c["max_charges_share"]:
            reason = reason or "Charges would take %d%% of the gain at the target" % round(share * 100)
    if risk < entry * 0.0005:
        reason = reason or "Stop too close to the entry"
    if reason is None and when.time() > c["strong_only_after"] and score < 8:
        reason = "Afternoon: only strong signals (8+) count; this one scored %d" % score
    if reason is None and score < 6:
        weakest = min((p / mx, k) for k, _, p, mx in factors)[1]
        reason = "Score %d: %s" % (score, (WEAK_REASON if long else WEAK_REASON_SHORT).get(weakest, "weak signal"))
    signal_reason = reason            # how it looked AT the breakout (None = it was a valid signal then)

    # what happened after the breakout: whichever of stop or target came FIRST
    after = bars[i + 1:]
    outcome, now_reason = "running", None
    k_stop = next((k for k, x in enumerate(after) if ((x["l"] <= stop) if long else (x["h"] >= stop))), None)
    k_tgt = next((k for k, x in enumerate(after) if ((x["h"] >= target) if long else (x["l"] <= target))), None)
    if k_stop is not None and (k_tgt is None or k_stop <= k_tgt):
        outcome, now_reason = "stop", "Broke out, then fell back to the stop"
    elif k_tgt is not None:
        outcome, now_reason = "target", "Already reached its target"
    elif after and (last["c"] - entry if long else entry - last["c"]) > 0.5 * risk:
        now_reason = "Price has moved on from the entry"
    if now_reason is None and (when > flat or now.time() > c["no_entries_after"]):
        now_reason = "Broke out at %s, still running. Too late to enter now (after %s)" % (
            hhmm(when.time()), hhmm(c["no_entries_after"]))
    reason = signal_reason or now_reason

    out = dict(base, kind="skip" if reason else "pick", side=side, reason=reason, score=score,
               signal_reason=signal_reason, signal_valid=signal_reason is None, outcome=outcome,
               now_reason=now_reason,
               factors=factors, checks=checks, trigger_index=i, signal_time=when, entry=entry, stop=stop,
               target=target, lock=lock, risk=round(risk, 2), exit_by=exit_by, qty=qty,
               cost=round(qty * entry, 2), loss_at_stop=-net(side, qty, entry, stop) if qty else 0.0,
               gain_at_target=net(side, qty, entry, target) if qty else 0.0,
               break_even=break_even(side, qty, entry) if qty else None,
               volume_ratio=round(vr, 1) if vr else None, vwap=round(vw, 2) if vw else None,
               strength="Strong" if score >= 8 else "Normal", raw_score=raw, rvol=round(rv, 1) if rv else None,
               range_ratio=round(range_ratio, 2) if range_ratio is not None else None, edge=edge_pct,
               atr_used=round(atr_used, 2) if atr_used is not None else None,
               lab={"before_11": when.time() <= c["early_until"], "in_play": bool(rv and rv >= 2.0),
                    "trend_rising": sma_rising(daily or []) if long else (
                        None if sma_rising(daily or []) is None else not sma_rising(daily or [])),
                    "sector_up": None if not sector or sector[1] is None else (
                        sector[1] > 0 if long else sector[1] < 0),
                    "range_ratio": round(range_ratio, 2) if range_ratio is not None else None,
                    "nr7": is_nr7(rows) if rows else None,
                    "narrow_cpr": (cp[3] < c["narrow_cpr_pct"]) if cp else None,
                    "cpr_width": round(cp[3], 3) if cp else None,
                    "open_extreme": open_extreme,
                    "near_52w": near52},
               sector=sector)
    out["why"] = why_line(out)
    return out


def why_line(r):
    """Plain English: what makes this signal strong, and what to watch."""
    long = r["side"] == "buy"
    good, watch = [], []
    pts = {k: p for k, _, p, _ in r["factors"]}
    if pts["volume"] == 2 and r.get("volume_ratio"):
        good.append("%s %.1f\u00d7 normal on the breakout" % ("buying" if long else "selling", r["volume_ratio"]))
    if pts["inplay"] and r.get("rvol"):
        good.append("in play (%.1f\u00d7 its usual volume today)" % r["rvol"])
    if pts["relative"] and r.get("edge") is not None:
        good.append("%.1f%% %s than Nifty" % (abs(r["edge"]), "stronger" if long else "weaker"))
    if pts["vwap"]:
        good.append("%s the day's average price" % ("above" if long else "below"))
    if pts["early"]:
        good.append("early in the day")
    sec = r.get("sector")
    if sec and sec[1] is not None and ((sec[1] > 0) if long else (sec[1] < 0)):
        good.append("%s sector %+.1f%%" % (sec[0], sec[1]))
    if not pts["market"]:
        watch.append("market %s" % ("falling" if long else "rising"))
    if not pts["room"]:
        watch.append("yesterday's %s is between entry and target" % ("high" if long else "low"))
    if not pts["trend"]:
        watch.append("against its 20-day trend")
    if not pts["inplay"]:
        watch.append("normal trading interest only")
    out = ("Strong because: " + ", ".join(good[:4]) + ".") if good else ""
    if watch:
        out += (" " if out else "") + "Watch: " + ", ".join(watch[:2]) + "."
    return out


def heads_up(w, live, now, cfg=None):
    """A 'get ready' card for a stock close to its breakout whose LIVE price is already past the
    morning range. Nothing is confirmed until the candle closes; this only gives time to open Groww."""
    if not w or w.get("kind") != "watch" or not live:
        return None
    c = dict(DEFAULTS)
    c.update(cfg or {})
    long = w["side"] == "buy"
    level = w["or_high"] if long else w["or_low"]
    if (live <= level) if long else (live >= level):
        return None
    if now.time() > c["no_entries_after"] or now.time() < c["no_entries_before"]:
        return None
    entry = snap(live)
    stop = snap((w["or_high"] + w["or_low"]) / 2.0, "down" if long else "up", entry)
    risk = abs(entry - stop)
    target = snap(entry + c["reward_r"] * risk if long else entry - c["reward_r"] * risk, ref=entry)
    qty = size(w["side"], entry, stop, c["capital"], c["max_loss"])
    return {"symbol": w["symbol"], "side": w["side"], "live": round(live, 2), "level": level,
            "closes_at": candle_close(now), "entry": entry, "stop": stop, "target": target, "qty": qty}


def rank(results, limit=3):
    """(picks, watch, skipped): the best `limit` picks by score then time, watch by closeness."""
    picks = sorted([r for r in results if r and r["kind"] == "pick"],
                   key=lambda r: (-r["score"], r["signal_time"], r["symbol"]))
    watch = sorted([r for r in results if r and r["kind"] == "watch"], key=lambda r: -r["closeness"])
    skipped = sorted([r for r in results if r and r["kind"] == "skip"], key=lambda r: r["symbol"])
    return picks[:limit], watch[:6], skipped + picks[limit:]


# ---------------------------------------------------------------- open trades

def stage_of(trade):
    """0: stop below the buy price, 1: stop at or above it (locked), 2: stop at or past +0.5R (trailed)."""
    long = trade["side"] == "buy"
    entry, stop = trade["entry"], trade["stop"]
    risk = abs(entry - trade.get("first_stop", stop)) or 0.01
    gained = (stop - entry) if long else (entry - stop)
    if gained < -1e-9:
        return 0
    return 2 if gained >= 0.5 * risk - tick_size(entry) - 1e-9 else 1   # the trail price is rounded down a tick


def trade_status(trade, series, nifty, now, cfg=None, live=None):
    """Live state of an open trade: price, P&L, the one alert that matters most, and the Next line.

    alert kinds: "stop", "target" (close it), "exit" (exit now: market drop, time, square-off),
    "lock" (move the stop to the buy price), "trail" (move the stop to lock in half a risk), or None.
    new_stop is the price to move the stop to, for "lock" and "trail"."""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    long = trade["side"] == "buy"
    day = now.date()
    t_day = datetime.date.fromisoformat(trade["date"])
    bars = day_bars(series or {}, t_day, now)
    entered = datetime.datetime.fromisoformat(trade["opened_at"])
    since = [b for b in bars if b["start"] + BAR > entered]
    meta = (series or {}).get("meta") or {}
    price = meta.get("regularMarketPrice") if t_day == day else None
    if price is None:
        price = since[-1]["c"] if since else (bars[-1]["c"] if bars else trade["entry"])
    if live is not None and t_day == day:
        price = live
    price = float(price)
    entry, stop, target = trade["entry"], trade["stop"], trade["target"]
    risk = abs(entry - trade.get("first_stop", stop)) or 0.01
    stage = stage_of(trade)
    trail_at = snap(entry + 1.5 * risk if long else entry - 1.5 * risk, ref=entry)
    trail_to = snap(entry + 0.5 * risk if long else entry - 0.5 * risk, "down" if long else "up", entry)
    exit_by = datetime.datetime.fromisoformat(trade["exit_by"])
    nb = day_bars(nifty or {}, t_day, now)
    n_at = [x for x in nb if x["start"] + BAR <= entered]
    n_pct = pct(nb[-1]["c"], n_at[-1]["c"]) if nb and n_at else None
    st = {"price": price, "pnl": net(trade["side"], trade["qty"], entry, price), "alert": None, "message": "",
          "next": "Hold. Nothing to do: your stop-loss and target are set.", "stage": stage, "new_stop": None,
          "bars": since, "trail_at": trail_at, "nifty_since": n_pct,
          "minutes_left": max(0, int((exit_by - now).total_seconds() // 60)) if t_day == day else 0,
          "reached_lock": False, "reached_trail": False}

    def best(level):
        return any((b["h"] >= level) if long else (b["l"] <= level) for b in since) or \
            ((price >= level) if long else (price <= level))
    st["reached_lock"] = best(trade["lock"])
    st["reached_trail"] = best(trail_at)

    first_stop = first_target = None
    moved_at = trade.get("stop_moved_at")
    stop_from = datetime.datetime.fromisoformat(moved_at) if moved_at else entered
    for k, b in enumerate(since):
        if first_stop is None and b["start"] + BAR > stop_from and ((b["l"] <= stop) if long else (b["h"] >= stop)):
            first_stop = k
        if first_target is None and ((b["h"] >= target) if long else (b["l"] <= target)):
            first_target = k
    if (long and price <= stop) or (not long and price >= stop):
        first_stop = len(since) if first_stop is None else first_stop
    if (long and price >= target) or (not long and price <= target):
        first_target = len(since) if first_target is None else first_target
    if first_stop is not None and (first_target is None or first_stop <= first_target):
        msg = "The price reached your stop-loss %.2f." % stop
        st.update(alert="stop", message=msg, next="Record it: tap Hit stop-loss below.")
        return st
    if first_target is not None:
        st.update(alert="target", message="The price reached your target %.2f." % target,
                  next="Sell if it hasn't sold, then tap Hit target below.")
        return st
    if t_day < day:
        st.update(alert="exit", message="This trade is from %s. Intraday trades close the same day: "
                  "record how it ended." % t_day.strftime("%d %b"), next="Record how it ended below.")
        return st
    if now.time() >= c["flat_by"]:
        st.update(alert="exit", message="It's %s: square off now, before Groww does it for you." % hhmm(c["flat_by"]),
                  next="Sell now at market price, then tap Sold at another price.")
        return st
    if len(nb) >= 4:
        move = pct(nb[-1]["c"], nb[-4]["c"])
        if move is not None and ((move <= -c["market_drop_pct"]) if long else (move >= c["market_drop_pct"])):
            st.update(alert="exit", message="Nifty %s %.1f%% in 15 minutes. Exit %s now."
                      % ("fell" if long else "rose", abs(move), trade["symbol"]),
                      next="Exit now, then tap Sold at another price.")
            return st
    moved = (price - entry) if long else (entry - price)
    if now >= exit_by and moved < 0.5 * risk:
        st.update(alert="exit", message="No real move since %s. Exit and free your money." % hhmm(entered.time()),
                  next="Exit now, then tap Sold at another price.")
        return st
    if stage == 0 and st["reached_lock"]:
        st.update(alert="lock", new_stop=entry, message="%s reached %.2f. Move your stop-loss to your buy price %.2f."
                  % (trade["symbol"], trade["lock"], entry),
                  next="Move your stop-loss to %.2f (your buy price) in Groww." % entry)
    elif stage == 1 and st["reached_trail"]:
        st.update(alert="trail", new_stop=trail_to, message="%s reached %.2f. Move your stop-loss up to %.2f to lock "
                  "in some profit." % (trade["symbol"], trail_at, trail_to),
                  next="Move your stop-loss to %.2f in Groww." % trail_to)
    elif stage >= 1:
        st["next"] = "Hold. Your stop-loss protects you: the worst case is now %s." % \
            rupees(net(trade["side"], trade["qty"], entry, stop), True)
    return st


def evaluate_variants(sig, series, now, cfg=None):
    """Filter-lab exits for a signal, once its day is over: {"vwap_exit": (how, price), "vwap_trail": (how, price)}.

    vwap_exit   the normal plan, plus: exit at the close of any 5-minute candle that closes on the wrong
                side of VWAP (below it for a buy)
    vwap_trail  the normal stop until the price reaches 1x the risk; then no target, and exit at the
                close of the first candle on the wrong side of VWAP (never worse than the buy price), or at
                2:55 PM
    None while the day is not over."""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    long = sig["side"] == "buy"
    d = datetime.date.fromisoformat(sig["date"])
    flat = datetime.datetime.combine(d, c["flat_by"])
    if not (d < now.date() or now >= flat):
        return None
    t0 = datetime.datetime.fromisoformat(sig["time"])
    allbars = day_bars(series or {}, d, now)
    if not allbars:
        return None
    entry, stop, target = sig["entry"], sig["stop"], sig["target"]
    risk = abs(entry - stop) or 0.01
    lock = entry + risk if long else entry - risk
    out = {}
    for name in ("vwap_exit", "vwap_trail"):
        pv = vol = 0.0
        locked = False
        res = None
        for b in allbars:
            if b["v"]:
                pv += (b["h"] + b["l"] + b["c"]) / 3.0 * b["v"]
                vol += b["v"]
            if b["start"] < t0:
                continue
            vw = pv / vol if vol else None
            end = b["start"] + BAR
            wrong = vw is not None and ((b["c"] < vw) if long else (b["c"] > vw))
            if name == "vwap_exit":
                if (b["l"] <= stop) if long else (b["h"] >= stop):
                    res = ("stop", stop)
                elif (b["h"] >= target) if long else (b["l"] <= target):
                    res = ("target", target)
                elif wrong:
                    res = ("vwap", b["c"])
            else:
                if not locked and ((b["l"] <= stop) if long else (b["h"] >= stop)):
                    res = ("stop", stop)
                elif locked and wrong:
                    res = ("vwap", max(b["c"], entry) if long else min(b["c"], entry))
                elif locked and ((b["l"] <= entry) if long else (b["h"] >= entry)):
                    res = ("entry", entry)
                elif (b["h"] >= lock) if long else (b["l"] <= lock):
                    locked = True        # the trail starts from the next candle (order inside a candle is unknown)
            if res is None and end >= flat:
                res = ("close", b["c"])
            if res:
                break
        if res is None:
            res = ("close", allbars[-1]["c"])
        out[name] = res
    return out


def evaluate_signal(sig, series, now, cfg=None):
    """How a recorded signal would have ended with the simple rules: stop or target first, else the
    time exit (no 0.5R move within the hour), else the 2:55 PM close. None while still undecided."""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    long = sig["side"] == "buy"
    d = datetime.date.fromisoformat(sig["date"])
    t0 = datetime.datetime.fromisoformat(sig["time"])
    flat = datetime.datetime.combine(d, c["flat_by"])
    exit_by = min(t0 + datetime.timedelta(minutes=c["time_stop_minutes"]), flat)
    bars = [b for b in day_bars(series or {}, d, now) if b["start"] >= t0]
    entry, stop, target = sig["entry"], sig["stop"], sig["target"]
    risk = abs(entry - stop) or 0.01
    for b in bars:
        if (b["l"] <= stop) if long else (b["h"] >= stop):
            return "stop", stop
        if (b["h"] >= target) if long else (b["l"] <= target):
            return "target", target
        end = b["start"] + BAR
        if end >= exit_by and end < flat and ((b["c"] - entry) if long else (entry - b["c"])) < 0.5 * risk:
            return "time", b["c"]
        if end >= flat:
            return "close", b["c"]
    if bars and (d < now.date() or now >= flat):
        return "close", bars[-1]["c"]
    return None


# ---------------------------------------------------------------- news (Yahoo headlines)

NEWS_RX = re.compile(r"\b(results?|earnings|Q[1-4] (?:profit|results)|board meeting|dividend|bonus|split|"
                     r"merger|demerger|acquisition|SEBI|raid|fraud|default|insolvency|downgrade|resign)", re.I)


def news_flag(xml_text, now, hours=20):
    """'' when the headlines from the last `hours` mention nothing big, else a short reason."""
    import email.utils
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    cutoff = scan.ist_to_utc(now) - datetime.timedelta(hours=hours)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        when = it.findtext("pubDate") or ""
        try:
            d = email.utils.parsedate_to_datetime(when)
            d = d.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError):
            d = None
        if d is not None and d < cutoff:
            continue
        m = NEWS_RX.search(title)
        if m:
            return m.group(1).lower()
    return ""


# ---------------------------------------------------------------- fetching (Yahoo, via scan.py)

def fetch_daily(symbols):
    """{SYM: series} of 3 months of daily closes (spark, 20 symbols a request)."""
    data, failed = scan.fetch_spark(list(symbols), "3mo", "1d", scan.PAUSE)
    return data, failed


def fetch_intraday_closes(symbols):
    """{SYM: series} of today's 5-minute closes (spark), the cheap first pass."""
    data, failed = scan.fetch_spark(list(symbols), "1d", "5m", scan.PAUSE)
    return data, failed


def fetch_chart(sym, rng="5d"):
    """Full 5-minute bars (open, high, low, close, volume) for a few days."""
    text = scan.yahoo_get(scan.chart_path(sym, rng, "5m"))
    return scan.parse_chart(text, sym)


def fetch_news(sym):
    url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=IN&lang=en-IN" % scan._q(scan.to_yahoo(sym))
    return scan.http_get(url, timeout=15)


def live_prices(symbols):
    """{SYM: last price} from one spark request per 20 symbols (Yahoo's regularMarketPrice, can lag)."""
    if not symbols:
        return {}
    data, _ = scan.fetch_spark(list(symbols), "1d", "5m", 0.2)
    out = {}
    for sym, s in data.items():
        p = (s.get("meta") or {}).get("regularMarketPrice")
        if p:
            out[sym] = float(p)
    return out


def fetch_daily_chart(sym):
    """Three months of daily bars (high, low, close, volume) for the ATR range-size check."""
    return scan.parse_chart(scan.yahoo_get(scan.chart_path(sym, "3mo", "1d")), sym)


def fetch_sectors():
    """{tile name: % move today} for NSE sector indices on Yahoo (a tile without data is left out)."""
    data, _ = scan.fetch_spark([y for _, y in SECTORS], "1d", "5m", 0.2)
    out = {}
    for name, y in SECTORS:
        sres = data.get(y) or data.get(y.upper())
        m = (sres or {}).get("meta") or {}
        price, prev = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
        if price and prev:
            out[name] = round((float(price) / float(prev) - 1) * 100, 2)
    return out


def fetch_vix():
    """(India VIX level, % change today) from Yahoo's ^INDIAVIX, or None."""
    data, _ = scan.fetch_spark(["^INDIAVIX"], "1d", "5m", 0.2)
    sres = data.get("^INDIAVIX")
    m = (sres or {}).get("meta") or {}
    price, prev = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
    if not price:
        return None
    return round(float(price), 2), (round((float(price) / float(prev) - 1) * 100, 1) if prev else None)


def vix_mood(level):
    """A rough guide, not a rule: calm under 13, normal 13 to 18, high above 18."""
    if level is None:
        return None
    if level < 13:
        return "calm", "Calm market: smaller moves, breakouts may lack follow-through."
    if level <= 18:
        return "normal", "Normal volatility."
    return "high", "High volatility: wider swings. Consider a smaller size or fewer trades."


def breadth(daily, spark, day, now):
    """(up, down) among stocks with a last 5-minute close today and a previous close."""
    up = down = 0
    for sym, s5 in spark.items():
        bars = day_bars(s5, day, now)
        prev = closes_before(daily.get(sym) or {}, day)
        if not bars or not prev:
            continue
        if bars[-1]["c"] > prev[-1]:
            up += 1
        elif bars[-1]["c"] < prev[-1]:
            down += 1
    return up, down


def next_open(now):
    d = now.date() + datetime.timedelta(days=1 if now.time() >= datetime.time(9, 15) else 0)
    for _ in range(15):
        if scan.trading_day(d)[0]:
            return d
        d += datetime.timedelta(days=1)
    return d


def refresh_seconds(now):
    """Option A: 60 s before the open on a trading day, 30 s in market hours, None (off) otherwise."""
    phase, _ = market_phase(now)
    return {"pre": 60, "forming": 30, "open": 30}.get(phase)


def closes_before(series, day):
    """Daily closes before `day` from a daily series."""
    out = []
    for ts, c in zip(series.get("t") or [], series.get("c") or []):
        if ts is None or c is None:
            continue
        if scan.ts_to_ist(ts).date() < day:
            out.append(float(c))
    return out


def stage_one(spark_5m, now, cfg=None, near_pct=WATCH_PCT):
    """Symbols worth a full chart: a 5-minute close past the opening-range closes, or within near_pct % of it."""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    day = now.date()
    keep = []
    for sym, s in spark_5m.items():
        bars = day_bars(s, day, now)
        if len(bars) < OR_BARS + 1:
            continue
        hi = max(b["c"] for b in bars[:OR_BARS])
        lo = min(b["c"] for b in bars[:OR_BARS])
        later = bars[OR_BARS:]
        last = later[-1]["c"]
        if any(b["c"] > hi for b in later) or last >= hi * (1 - near_pct / 100.0) or \
                (c["shorts"] and (any(b["c"] < lo for b in later) or last <= lo * (1 + near_pct / 100.0))):
            keep.append(sym)
    return keep


# ---------------------------------------------------------------- v2 screen: watchlist, get ready, freshness, mood



def watch_info(sym, series, daily, nifty, now, cfg=None, daily_chart=None, sector=None, live=None):
    """A stock that has NOT broken out yet: its setup rating (0-10, before the breakout), the checks that
    can be known in advance, and the trade plan if it triggers. None if it is not a watch candidate.

    Rating points: with the daily trend 2, 20-day average rising 1, in play so far 2 (1.5x) / 1 (1.2x),
    stronger than Nifty so far 1, sector moving the same way 1, range size okay 1, ATR room (under half
    used) 1, NR7 or narrow CPR 1. Stocks failing an advance must-pass check are left out."""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    day = now.date()
    cutoff = min(now, datetime.datetime.combine(day, datetime.time(15, 30)))
    bars = day_bars(series, day, cutoff)
    n_or = int(c["or_bars"])
    if len(bars) < n_or or bars[0]["start"].time() != IST_OPEN:
        return None
    rng = bars[:n_or]
    or_high, or_low = max(b["h"] for b in rng), min(b["l"] for b in rng)
    if any(b["c"] > or_high for b in bars[n_or:]):
        return None                                        # already broke out: it is a pick or a skip now
    last = bars[-1]
    price = float(live) if live else last["c"]
    tick = tick_size(or_high)
    entry = snap(or_high + tick, "up", or_high)
    if price < entry * (1 - WATCH_PCT / 100.0):
        return None
    stop = snap((or_high + or_low) / 2.0, "down", entry)
    risk = entry - stop
    if risk <= 0:
        return None
    target = snap(entry + c["reward_r"] * risk, ref=entry)
    qty = size("buy", entry, stop, c["capital"], c["max_loss"])
    _, ybars = previous_day(series, day)
    prev_close = ybars[-1]["c"] if ybars else None
    avg20 = sma(daily or [])
    rows = daily_ohlc(daily_chart, day) if daily_chart else []
    a14 = atr(rows)
    range_ratio = (or_high - or_low) / a14 if a14 else None
    day_range = max(b["h"] for b in bars) - min(b["l"] for b in bars)
    atr_used = day_range / a14 if a14 else None
    rv = relative_volume(series, day, last["start"])
    nb = [x for x in day_bars(nifty or {}, day, cutoff) if x["start"] <= last["start"]]
    _, nyb = previous_day(nifty or {}, day)
    n_chg = pct(nb[-1]["c"], nyb[-1]["c"]) if nb and nyb else None
    s_chg = pct(last["c"], prev_close)
    vw = vwap(bars)
    trend = None if not (avg20 and prev_close) else prev_close > avg20
    room = None if atr_used is None else atr_used < c["max_atr_used"]
    range_ok = None if range_ratio is None else c["range_min"] <= range_ratio <= c["range_max"]
    fits = qty >= 1 and c["min_price"] <= entry <= c["max_price"]
    ch_share = None
    if qty >= 1:
        gross = qty * (target - entry)
        ch_share = charges(qty, entry, target) / gross if gross > 0 else 1.0
    worth = None if ch_share is None else ch_share <= c["max_charges_share"]
    if trend is False or room is False or range_ok is False or not fits or worth is False:
        return None
    cp = cpr(max(x["h"] for x in ybars), min(x["l"] for x in ybars), ybars[-1]["c"]) if ybars else None
    pts = 0
    pts += 2 if trend else 0
    pts += 1 if sma_rising(daily or []) else 0
    pts += 2 if rv and rv >= 1.5 else 1 if rv and rv >= 1.2 else 0
    pts += 1 if (s_chg is not None and n_chg is not None and s_chg > n_chg) else 0
    pts += 1 if (sector and sector[1] is not None and sector[1] > 0) else 0
    pts += 1 if range_ok else 0
    pts += 1 if (atr_used is not None and atr_used < 0.5) else 0
    pts += 1 if ((rows and is_nr7(rows)) or (cp and cp[3] < c["narrow_cpr_pct"])) else 0
    loss = -net("buy", qty, entry, stop)
    gain = net("buy", qty, entry, target)
    return {"symbol": sym, "kind": "watch", "side": "buy", "rating": min(pts, 10), "price": round(price, 2),
            "or_high": or_high, "or_low": or_low, "entry": entry, "stop": stop, "target": target,
            "lock": snap(entry + risk, ref=entry), "risk": round(risk, 2), "qty": qty,
            "loss": loss, "gain": gain, "to_go": round(max(entry - price, 0.0), 2),
            "closeness": max(0.0, min(1.0, 1 - (entry - price) / (entry * WATCH_PCT / 100.0))),
            "spark": [b["c"] for b in bars][-24:], "rvol": round(rv, 1) if rv else None, "sector": sector,
            "checks": {"trend": trend, "room": room if room is not None else range_ok, "news": None,
                       "charges": worth, "volume": None, "candle": None,
                       "vwap": None if not vw else price > vw},
            "closes_at": candle_close(now)}


def bar_state(price, entry, risk):
    """Get ready / freshness colour: green below the buy price; above it amber, orange, then red."""
    if price is None or not risk:
        return "green"
    over = (price - entry) / risk
    if over <= 0:
        return "green"
    if over < 0.2:          # reward:risk at this price still 1.5 : 1 or better (2x target)
        return "amber"
    if over < 0.4:          # 1.2 : 1 or better
        return "orange"
    return "red"


def freshness(pick, live, now, cfg=None):
    """('fresh'|'late'|'missed', details) for a BUY / SELL pick, from the live price and the signal's age.
    Fresh: at most 0.2x the risk past the buy price (reward:risk at this price 1.5 : 1 or better with a 2x
    target) and under 15 minutes old. Late: reward:risk at the live price still 1.2 : 1 or better and under
    30 minutes old (shares and reward recalculated). Missed: beyond that, don't chase."""
    long = pick["side"] == "buy"
    price = float(live) if live else pick["price"]
    risk = pick["risk"] or 0.01
    moved = ((price - pick["entry"]) if long else (pick["entry"] - price)) / risk
    age = (now - pick["signal_time"]).total_seconds() / 60.0
    risk_now = abs(price - pick["stop"])
    reward_now = abs(pick["target"] - price)
    rr_now = reward_now / risk_now if risk_now > 0 else 0.0
    c = dict(DEFAULTS)
    c.update(cfg or {})
    qty_now = size(pick["side"], price, pick["stop"], c["capital"], c["max_loss"])
    d = {"qty_now": qty_now, "price": round(price, 2), "moved_r": round(moved, 2), "age_min": int(age), "rr_now": round(rr_now, 2),
         "past_entry": round(max(0.0, (price - pick["entry"]) if long else (pick["entry"] - price)), 2),
         "chase_limit": snap(pick["entry"] + (0.2 * risk if long else -0.2 * risk), ref=pick["entry"])}
    if moved <= 0.2 and age <= 15:
        return "fresh", d
    if moved <= 0.4 and age <= 30 and rr_now >= 1.2:
        return "late", d
    return "missed", d


def premarket_rating(closes):
    """Before 9:30 (no opening range yet): a rating from daily closes only. Above the 20-day average 3,
    average rising 2, within 2% of the 20-day high 3, RSI 14 between 50 and 70 2."""
    if len(closes) < 25:
        return None
    pts = 0
    avg = sum(closes[-20:]) / 20.0
    pts += 3 if closes[-1] > avg else 0
    pts += 2 if sma_rising(closes) else 0
    pts += 3 if closes[-1] >= max(closes[-20:]) * 0.98 else 0
    r = scan.rsi(closes)
    pts += 2 if r is not None and 50 <= r <= 70 else 0
    return pts


def market_mood(vix, up, down, nifty_chg):
    """('good'|'mixed'|'weak', score -3..3) from India VIX, breadth and Nifty's move today."""
    score = 0
    if up + down:
        share = up / float(up + down)
        score += 1 if share >= 0.6 else -1 if share <= 0.4 else 0
    if nifty_chg is not None:
        score += 1 if nifty_chg > 0.2 else -1 if nifty_chg < -0.2 else 0
    if vix:
        score += -1 if vix[0] > 18 else 1 if vix[0] < 15 else 0
    return ("good" if score >= 1 else "weak" if score <= -1 else "mixed"), score
