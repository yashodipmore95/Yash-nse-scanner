"""Visual components for the v2 home page and the My progress page. HTML / SVG strings, no Streamlit."""
import datetime
import html as _html

import engine

BLUE, GREEN, AMBER, ORANGE, RED, GREY = "#378ADD", "#2e9e4f", "#EF9F27", "#E8743B", "#d64545", "rgba(127,127,127,.3)"
STATE_COL = {"green": GREEN, "amber": AMBER, "orange": ORANGE, "red": RED}

CSS = """<style>
.v2c{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:9px 11px;margin:7px 0}
.v2row{display:flex;justify-content:space-between;align-items:center;gap:8px}
.v2mut{font-size:11px;color:var(--mut)}
.v2sec{font-size:13px;color:var(--mut);margin:16px 0 2px;font-weight:600}
.v2act{font-size:12px;font-weight:600;padding:3px 9px;border-radius:8px;white-space:nowrap}
.v2ic{display:inline-flex;width:24px;height:24px;border-radius:6px;align-items:center;justify-content:center;
font-size:13px;margin:2px 2px 0 0}
.v2chip{display:inline-flex;align-items:center;gap:3px;font-size:12px;padding:2px 8px 2px 2px;border-radius:999px;
border:1px solid var(--line);margin:2px 3px 2px 0}
.v2box{background:rgba(127,127,127,.08);border-radius:8px;padding:6px 8px;margin-top:6px}
.v2grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;text-align:center;font-size:10px}
.v2grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}
</style>"""


def esc(x):
    return _html.escape(str(x))


def p2(x):
    return "%.2f" % float(x)


def ring(n, col=BLUE, size=34, maxv=10, label=None):
    """A score ring. `label` is shown as given (it may hold an HTML entity such as &#10003;)."""
    c = 2 * 3.14159 * 15
    frac = max(0.0, min(1.0, float(n) / maxv)) if n is not None else 0
    return ('<svg viewBox="0 0 40 40" width="%d" height="%d"><circle cx="20" cy="20" r="15" fill="none" '
            'stroke="%s" stroke-width="5"/><circle cx="20" cy="20" r="15" fill="none" stroke="%s" stroke-width="5" '
            'stroke-dasharray="%.1f %.1f" transform="rotate(-90 20 20)"/><text x="20" y="24.5" text-anchor="middle" '
            'font-size="12" font-weight="600" fill="currentColor">%s</text></svg>'
            % (size, size, GREY, col, c * frac, c, label if label is not None else ("-" if n is None else int(n))))


def countdown(seconds):
    seconds = max(0, int(seconds))
    c = 2 * 3.14159 * 14
    frac = seconds / 300.0
    return ('<svg viewBox="0 0 36 36" width="34" height="34"><circle cx="18" cy="18" r="14" fill="none" stroke="%s" '
            'stroke-width="4"/><circle cx="18" cy="18" r="14" fill="none" stroke="%s" stroke-width="4" '
            'stroke-dasharray="%.1f %.1f" transform="rotate(-90 18 18)"/><text x="18" y="22" text-anchor="middle" '
            'font-size="9" fill="currentColor">%d:%02d</text></svg>' % (GREY, AMBER, c * frac, c, seconds // 60,
                                                                       seconds % 60))


# ---------------------------------------------------------------- top 5 and market mood

def top5(items, prev):
    """items: [(symbol, rating, kind)] best first; kind 'pick' (green ring) or 'setup' (blue ring)."""
    if not items:
        return ""
    chips = []
    for k, (sym, rating, kind) in enumerate(items[:5]):
        mark = ""
        if sym not in prev:
            mark = ('<span style="font-size:9px;background:var(--bg-b);color:var(--b);padding:0 4px;'
                    'border-radius:4px">NEW</span>')
        elif prev.index(sym) > k:
            mark = '<span style="color:var(--g);font-size:10px">&#9650;</span>'
        chips.append('<span class="v2chip">%s%s %s</span>' % (ring(rating, GREEN if kind == "pick" else BLUE, 22),
                                                              esc(sym), mark))
    return '<div class="v2c" style="padding:6px 8px"><div class="v2mut">Top 5 to watch</div>%s</div>' % "".join(chips)


def mood(label, score, vix, up, down, nifty_chg, sectors):
    ang = {-3: 160, -2: 140, -1: 115, 0: 90, 1: 65, 2: 40, 3: 20}.get(max(-3, min(3, score)), 90)
    import math
    x = 60 + 30 * math.cos(math.radians(ang))
    y = 60 - 30 * math.sin(math.radians(ang))
    col = {"good": GREEN, "mixed": AMBER, "weak": RED}[label]
    share = round(100.0 * up / (up + down)) if (up + down) else None

    def tag(txt, good):
        bg, fg = ("var(--bg-g)", "var(--g)") if good is True else ("var(--bg-r)", "var(--r)") if good is False else \
            ("var(--card)", "var(--mut)")
        return '<span style="padding:2px 6px;border-radius:6px;background:%s;color:%s">%s</span>' % (bg, fg, txt)
    tags = []
    if vix:
        tags.append(tag("VIX %.0f" % vix[0], vix[0] <= 18))
    if share is not None:
        tags.append(tag("%d%% up" % share, share >= 50))
    if nifty_chg is not None:
        tags.append(tag("Nifty %s" % ("&#9650;" if nifty_chg >= 0 else "&#9660;"), nifty_chg >= 0))
    strip = ""
    if sectors:
        cells = []
        for name, chg in sorted(sectors.items(), key=lambda kv: -kv[1]):
            a = min(abs(chg) / 1.5, 1.0)
            bg = ("rgba(46,158,79,%.2f)" % (0.2 + 0.7 * a)) if chg > 0.05 else \
                ("rgba(214,69,69,%.2f)" % (0.2 + 0.7 * a)) if chg < -0.05 else GREY
            cells.append('<div title="%s %+.1f%%" style="height:10px;border-radius:2px;background:%s"></div>'
                         % (esc(name), chg, bg))
        strip = ('<div style="display:grid;grid-template-columns:repeat(%d,minmax(0,1fr));gap:2px;margin-top:5px">%s'
                 '</div><div class="v2mut" style="font-size:9px">%s</div>'
                 % (len(cells), "".join(cells), " &middot; ".join(esc(n) for n, _ in sorted(sectors.items(),
                                                                                          key=lambda kv: -kv[1]))))
    return ('<div class="v2c v2row"><svg viewBox="0 0 120 66" width="110" height="60">'
            '<path d="M10 60 A50 50 0 0 1 43 14" fill="none" stroke="%s" stroke-width="10"/>'
            '<path d="M46 12 A50 50 0 0 1 74 12" fill="none" stroke="%s" stroke-width="10"/>'
            '<path d="M77 14 A50 50 0 0 1 110 60" fill="none" stroke="%s" stroke-width="10"/>'
            '<line x1="60" y1="60" x2="%.1f" y2="%.1f" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>'
            '<circle cx="60" cy="60" r="4" fill="currentColor"/></svg><div style="flex:1">'
            '<b style="font-size:15px;color:%s">Market: %s</b><div style="display:flex;gap:4px;flex-wrap:wrap;'
            'margin-top:3px;font-size:10px">%s</div>%s</div></div>'
            % (RED, AMBER, GREEN, x, y, col, label.title(), "".join(tags), strip))


# ---------------------------------------------------------------- bars, icons, ladder

def price_bar(now, buy, target, state, small=False):
    """Now (left) -> Buy (middle) -> Target (right). The marker shows the live price."""
    lo = min(now, buy) - (target - buy) * 0.15
    span_l = buy - lo or 1
    span_r = target - buy or 1

    def x(v):
        return 10 + (150 * (v - lo) / span_l if v <= buy else 150 + 150 * min(1.0, (v - buy) / span_r))
    px = max(10, min(310, x(now)))
    col = STATE_COL.get(state, GREEN)
    if small:
        return ('<svg viewBox="0 0 320 16" width="100%%"><rect x="10" y="5" width="300" height="6" rx="3" fill="%s"/>'
                '<rect x="10" y="5" width="%.1f" height="6" rx="3" fill="%s"/><line x1="160" y1="1" x2="160" y2="15" '
                'stroke="currentColor" stroke-width="1.5"/><circle cx="%.1f" cy="8" r="5" fill="%s"/></svg>'
                % (GREY, max(0, px - 10), GREEN if px <= 160 else col, px, col))
    over = ""
    if px > 160:
        over = '<rect x="160" y="17" width="%.1f" height="9" fill="%s"/>' % (px - 160, col)
    return ('<svg viewBox="0 0 320 46" width="100%%"><rect x="10" y="17" width="300" height="9" rx="4" fill="%s"/>'
            '<rect x="10" y="17" width="%.1f" height="9" rx="4" fill="%s"/>%s'
            '<line x1="160" y1="11" x2="160" y2="32" stroke="currentColor" stroke-width="2"/>'
            '<circle cx="%.1f" cy="21.5" r="6.5" fill="%s" stroke="white" stroke-width="1.5"/>'
            '<text x="10" y="43" font-size="11" fill="currentColor" opacity=".7">Now %s</text>'
            '<text x="160" y="9" text-anchor="middle" font-size="11" font-weight="600" fill="currentColor">Buy %s</text>'
            '<text x="310" y="43" text-anchor="end" font-size="11" fill="%s">Target %s</text></svg>'
            % (GREY, min(px, 160) - 10, GREEN, over, px, col, p2(now), p2(buy), GREEN, p2(target)))


ICONS = [("trend", "&#128200;"), ("room", "&#128207;"), ("news", "&#128240;"), ("charges", "&#128176;"),
         ("volume", "&#128266;"), ("candle", "&#128367;"), ("vwap", "&#9878;")]


def icons(checks):
    out = []
    for key, sym in ICONS:
        v = checks.get(key)
        bg = "var(--bg-g)" if v is True else "var(--bg-r)" if v is False else "var(--bg-a)"
        out.append('<span class="v2ic" style="background:%s" title="%s">%s</span>' % (bg, key, sym))
    return "<div>%s</div>" % "".join(out)


def pick_checks(r):
    d = {k: ok for k, _, ok in r.get("checks", [])}
    return {"trend": d.get("trend"), "room": d.get("late") if d.get("range", True) is not False else False,
            "news": d.get("news"), "charges": d.get("charges", d.get("money")), "volume": d.get("volume"),
            "candle": d.get("candle"), "vwap": d.get("vwap")}


def ladder(r, now_price):
    long = r["side"] == "buy"
    lv = [("Target", r["target"], GREEN), ("Lock", r["lock"], AMBER), ("Buy" if long else "Sell", r["entry"], None),
          ("Now", now_price, BLUE), ("Stop", r["stop"], RED)]
    hi, lo = max(v for _, v, _ in lv), min(v for _, v, _ in lv)
    rng = (hi - lo) or 1

    def y(v):
        return 10 + (hi - v) / rng * 100
    ys = {}
    out = ['<svg viewBox="0 0 130 122" width="126" height="118">',
           '<line x1="36" y1="%.1f" x2="36" y2="%.1f" stroke="#97C459" stroke-width="6"/>' % (y(r["target"]),
                                                                                             y(r["entry"])),
           '<line x1="36" y1="%.1f" x2="36" y2="%.1f" stroke="#F09595" stroke-width="6"/>' % (y(r["entry"]),
                                                                                             y(r["stop"]))]
    last_y = -99
    for name, v, col in sorted(lv, key=lambda t: -t[1] if long else t[1]):
        yy = y(v)
        ty = max(yy + 4, last_y + 12)
        last_y = ty
        if name == "Now":
            out.append('<polygon points="18,%.1f 28,%.1f 18,%.1f" fill="%s"/>' % (yy - 4, yy, yy + 4, BLUE))
        elif col:
            out.append('<circle cx="36" cy="%.1f" r="5" fill="%s"/>' % (yy, col))
        else:
            out.append('<rect x="26" y="%.1f" width="20" height="4" fill="currentColor"/>' % (yy - 2))
        out.append('<text x="50" y="%.1f" font-size="10" fill="%s"%s>%s %s</text>'
                   % (ty, col or "currentColor", ' font-weight="600"' if name in ("Buy", "Sell") else "", name, p2(v)))
        ys[name] = yy
    out.append("</svg>")
    return "".join(out)


def rr_row(loss, gain, cost, capital, bt_rate=None):
    loss, gain = abs(loss), max(gain, 0.0)
    ratio = gain / loss if loss else 0
    be = 100.0 * loss / (loss + gain) if (loss + gain) else 0
    cells = ['<div><b style="font-size:13px">%d%%</b><br><span class="v2mut">wins to break even</span></div>' % round(be),
             '<div><b style="font-size:13px">%d%%</b><br><span class="v2mut">of capital (%s)</span></div>'
             % (round(100.0 * cost / capital) if capital else 0, engine.rupees(cost))]
    if bt_rate is not None:
        cells.append('<div><b style="font-size:13px;color:var(--g)">%d%%</b><br><span class="v2mut">won in backtest'
                     '</span></div>' % bt_rate)
    else:
        cells.append('<div><b style="font-size:13px">&ndash;</b><br><span class="v2mut">run backtest for win %%'
                     '</span></div>')
    return ('<div class="v2box"><div class="v2row" style="font-size:12px"><span style="color:var(--r)">Lose %s</span>'
            '<b>1 : %.1f</b><span style="color:var(--g);font-weight:600">Win %s</span></div>'
            '<div style="display:flex;height:7px;border-radius:4px;overflow:hidden;margin:4px 0">'
            '<div style="flex:%.1f;background:#F09595"></div><div style="flex:%.1f;background:#97C459"></div></div>'
            '<div class="v2grid3">%s</div></div>'
            % (engine.rupees(loss), ratio, engine.rupees(gain), max(loss, 1), max(gain, 1), "".join(cells)))


# ---------------------------------------------------------------- cards

def getready(h, best, now):
    state = engine.bar_state(h["price"], h["entry"], h["risk"])
    if not best:
        return ('<div class="v2c v2row" style="opacity:.7"><span class="v2act" style="background:var(--card);'
                'color:var(--mut)">backup</span><b style="flex:1;font-size:13px">%s</b>%s<div style="width:120px">%s'
                '</div></div>' % (esc(h["symbol"]), ring(h["rating"], BLUE, 26), price_bar(h["price"], h["entry"],
                                                                                    h["target"], state, True)))
    secs = (h["closes_at"] - now).total_seconds()
    badge = {"green": ("WAIT", "a"), "amber": ("WAIT &middot; crossing", "a"), "orange": ("LATE", "a"),
             "red": ("DON'T CHASE", "r")}[state]
    return "".join([
        '<div class="v2c" style="border:2px solid var(--a)"><div class="v2row">',
        '<span class="v2act" style="background:var(--bg-%s);color:var(--%s)">%s &middot; best now</span>'
        % (badge[1], badge[1], badge[0]),
        '<b style="font-size:15px">%s</b>%s%s</div>' % (esc(h["symbol"]), ring(h["rating"], BLUE, 30), countdown(secs)),
        price_bar(h["price"], h["entry"], h["target"], state), icons(h["checks"]),
        '<div class="v2row v2mut" style="margin-top:4px"><span>%d shares</span><span style="color:var(--r)">stop %s'
        '</span><span>1 : %.1f</span></div></div>'
        % (h["qty"], p2(h["stop"]), (h["gain"] / h["loss"]) if h["loss"] else 0)])


def pick_card(r, status, d, capital, bt_rate=None):
    long = r["side"] == "buy"
    score_col = GREEN
    if status == "fresh":
        badge = ('<span class="v2act" style="background:var(--bg-g);color:var(--g)">%s NOW &middot; fresh</span>'
                 % ("BUY" if long else "SELL"))
    else:
        badge = '<span class="v2act" style="background:var(--bg-a);color:var(--a)">LATE &middot; smaller reward</span>'
    qty = r["qty"] if status == "fresh" else d.get("qty_now", r["qty"])
    loss = r["loss_at_stop"] if status == "fresh" else -engine.net(r["side"], qty, d["price"], r["stop"])
    gain = r["gain_at_target"] if status == "fresh" else engine.net(r["side"], qty, d["price"], r["target"])
    cost = qty * (r["entry"] if status == "fresh" else d["price"])
    age = "%d min ago" % d["age_min"]
    chase = ('<div class="v2mut" style="margin-top:4px">Now %s &middot; %s &middot; don\'t chase past %s</div>'
             % (p2(d["price"]), age, p2(d["chase_limit"])))
    return "".join([
        '<div class="v2c" style="border:2px solid var(--%s)"><div class="v2row">%s<b style="font-size:15px">%s</b>%s'
        '</div>' % ("g" if status == "fresh" else "a", badge, esc(r["symbol"]), ring(r["score"], score_col, 38)),
        chase,
        '<div class="v2row" style="align-items:stretch;margin-top:4px">%s<div style="flex:1;display:flex;'
        'flex-direction:column;justify-content:space-between;text-align:right"><div><div style="font-size:22px;'
        'font-weight:600">%d</div><div class="v2mut">shares</div></div>%s</div></div>'
        % (ladder(r, d["price"]), qty, icons(pick_checks(r))),
        rr_row(loss, gain, cost, capital, bt_rate), '</div>'])


def watch_row(w, is_open):
    pts = w.get("spark") or []
    line = ""
    if len(pts) >= 2:
        lo, hi = min(pts + [w["entry"]]), max(pts + [w["entry"]])
        rng = (hi - lo) or 1
        poly = " ".join("%.1f,%.1f" % (k * 70.0 / (len(pts) - 1), 18 - (v - lo) / rng * 15) for k, v in enumerate(pts))
        ty = 18 - (w["entry"] - lo) / rng * 15
        line = ('<svg viewBox="0 0 70 20" width="70" height="20"><line x1="0" y1="%.1f" x2="70" y2="%.1f" '
                'stroke="%s" stroke-dasharray="2 2"/><polyline fill="none" stroke="currentColor" stroke-opacity=".6" '
                'stroke-width="1.5" points="%s"/></svg>' % (ty, ty, BLUE, poly))
    return ('<div class="v2c v2row" style="%s;margin-bottom:0">%s<b style="flex:1;font-size:13px">%s</b>%s'
            '<span class="v2mut" style="text-align:right">%s<br>to go</span></div>'
            % ("border:2px solid var(--b)" if is_open else "", ring(w["rating"], BLUE, 28), esc(w["symbol"]), line,
               engine.rupees(w["to_go"]) if w["to_go"] >= 1 else "&#8377;%s" % p2(w["to_go"])))


def watch_detail(w, now):
    state = engine.bar_state(w["price"], w["entry"], w["risk"])
    secs = (w["closes_at"] - now).total_seconds()
    return "".join([
        '<div class="v2c" style="margin-top:0;border-top:none;border-radius:0 0 12px 12px">',
        '<div class="v2row"><span class="v2act" style="background:var(--card);color:var(--mut)">WAIT</span>'
        '<span class="v2mut">candle closes in</span>%s</div>' % countdown(secs),
        price_bar(w["price"], w["entry"], w["target"], state), icons(w["checks"]),
        '<div class="v2row v2mut" style="margin-top:4px"><span>%d shares</span><span style="color:var(--r)">stop %s'
        '</span><span>target %s</span><span>1 : %.1f</span></div>'
        % (w["qty"], p2(w["stop"]), p2(w["target"]), (w["gain"] / w["loss"]) if w["loss"] else 0),
        '<div class="v2grid2" style="margin-top:6px;font-size:11px;text-align:center">'
        '<div style="border:1px solid var(--g);color:var(--g);border-radius:6px;padding:4px">A &middot; wait for the '
        'close (recommended)</div><div style="border:1px solid var(--a);color:var(--a);border-radius:6px;padding:4px">'
        'B &middot; order in advance: buys on touch</div></div></div>'])


def late_row(r, d):
    state = "orange" if d["moved_r"] < 0.4 else "red"
    return ('<div class="v2c v2row" style="border:1.5px solid var(--a)"><span class="v2act" style="background:var(--bg-a);'
            'color:var(--a)">LATE</span><b style="flex:1;font-size:13px">%s</b><div style="width:110px">%s</div>'
            '<span class="v2mut">1 : %.1f</span></div>'
            % (esc(r["symbol"]), price_bar(d["price"], r["entry"], r["target"], state, True), d["rr_now"]))


LEGEND = ('<div class="v2c v2mut" style="font-size:10px;line-height:1.9">&#128200; trend &middot; &#128207; room left '
          '&middot; &#128240; news &middot; &#128176; charges &middot; &#128266; volume &middot; &#128367; candle '
          '&middot; &#9878; VWAP &nbsp;|&nbsp; green ok &middot; amber pending &middot; red failed &nbsp;|&nbsp; '
          '<span style="color:%s">blue ring</span> setup rating &middot; <span style="color:%s">green ring</span> '
          'signal score</div>' % (BLUE, GREEN))


# ---------------------------------------------------------------- My progress charts

def readiness_rings(ready):
    goals = ready["goals"]
    cells = []
    for name, ok, val, frac in goals:
        r = ring(1, GREEN, 40, maxv=1, label="&#10003;") if ok else ring(frac, AMBER, 40, maxv=1, label=esc(val)[:7])
        cells.append('<div>%s<br><span class="v2mut" style="font-size:10px">%s</span></div>' % (r, esc(name)))
    return ('<div class="v2c"><div class="v2row"><b>Ready for real money?</b><b style="color:var(--%s)">%d of 4</b>'
            '</div><div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;text-align:center;'
            'margin-top:4px">%s</div></div>' % ("g" if ready["done"] == 4 else "a", ready["done"], "".join(cells)))


def equity(curve, total):
    if not curve:
        return ""
    run = [0.0] + list(curve)
    lo, hi = min(run), max(run)
    rng = (hi - lo) or 1
    n = len(run)

    def X(k):
        return 6 + k * 308.0 / max(n - 1, 1)

    def Y(v):
        return 6 + (hi - v) / rng * 60
    peak, start, worst, best_span = run[0], 0, 0.0, None
    k0 = 0
    for k, v in enumerate(run):
        if v >= peak:
            peak, k0 = v, k
        elif v - peak < worst:
            worst, best_span = v - peak, (k0, k)
    shade = ""
    if best_span:
        shade = ('<rect x="%.1f" y="2" width="%.1f" height="68" fill="var(--bg-r)"/>'
                 % (X(best_span[0]), max(4, X(best_span[1]) - X(best_span[0]))))
    pts = " ".join("%.1f,%.1f" % (X(k), Y(v)) for k, v in enumerate(run))
    return ('<div class="v2c"><div class="v2row"><span class="v2mut">Running total &middot; worst dip shaded</span>'
            '<b style="color:var(--%s)">%s</b></div><svg viewBox="0 0 320 74" width="100%%">%s'
            '<line x1="6" y1="%.1f" x2="314" y2="%.1f" stroke="%s"/><polyline fill="none" stroke="%s" stroke-width="2.2" '
            'points="%s"/></svg><div class="v2mut">Worst dip %s</div></div>'
            % ("g" if total >= 0 else "r", engine.rupees(total, True), shade, Y(0), Y(0), GREY,
               GREEN if total >= 0 else RED, pts, engine.rupees(worst, True)))


def calendar(day_totals, today):
    """Last 5 weeks of trading days, Mon-Fri grid, coloured by the day's result."""
    start = today - datetime.timedelta(days=today.weekday() + 28)
    cells = []
    big = max([abs(v) for v in day_totals.values()] + [1])
    for w in range(5):
        for dd in range(5):
            d = start + datetime.timedelta(days=w * 7 + dd)
            v = day_totals.get(d.isoformat())
            if d > today:
                col = "transparent"
            elif v is None:
                col = GREY
            else:
                a = 0.25 + 0.7 * min(abs(v) / big, 1)
                col = ("rgba(46,158,79,%.2f)" % a) if v > 0 else ("rgba(214,69,69,%.2f)" % a) if v < 0 else GREY
            cells.append('<div title="%s %s" style="height:16px;border-radius:3px;background:%s"></div>'
                         % (d.isoformat(), engine.rupees(v, True) if v is not None else "", col))
    return ('<div class="v2c"><div class="v2mut">Last 5 weeks (darker = bigger)</div><div style="display:grid;'
            'grid-template-columns:repeat(5,minmax(0,1fr));gap:3px;margin-top:4px">%s</div><div class="v2row v2mut" '
            'style="font-size:9px"><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span>'
            '</div></div>' % "".join(cells))


def bars(title, items, note=""):
    """items: [(label, value 0-100 or None, count)] -> a small bar chart of win %."""
    if not items:
        return ""
    w = 300.0 / len(items)
    out = ['<svg viewBox="0 0 310 82" width="100%">']
    for k, (lab, v, n) in enumerate(items):
        x = 8 + k * w
        h = 0 if v is None else 56 * v / 100.0
        col = GREY if v is None else (GREEN if v >= 55 else "#97C459" if v >= 45 else "#F09595")
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="%s"/>'
                   % (x + w * 0.15, 62 - h, w * 0.7, max(h, 1), col))
        out.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="10" fill="currentColor">%s</text>'
                   % (x + w / 2, 58 - h, "" if v is None else "%d%%" % v))
        out.append('<text x="%.1f" y="76" text-anchor="middle" font-size="9" fill="currentColor" opacity=".7">%s (%d)'
                   '</text>' % (x + w / 2, esc(lab), n))
    out.append("</svg>")
    return '<div class="v2c"><div class="v2mut">%s</div>%s%s</div>' % (esc(title), "".join(out),
                                                                       ('<div class="v2mut">%s</div>' % esc(note)) if note else "")


def histogram(counts):
    """R-multiple buckets -> bars (losses red, wins green)."""
    labels = ["-1R or worse", "-0.5R", "~0", "+0.5R", "+1R", "+2R or more"]
    top = max(counts + [1])
    w = 300.0 / len(labels)
    out = ['<svg viewBox="0 0 310 84" width="100%">']
    for k, (lab, n) in enumerate(zip(labels, counts)):
        x = 8 + k * w
        h = 52 * n / top
        col = RED if k < 2 else GREY if k == 2 else GREEN
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="%s"/>'
                   % (x + w * 0.15, 60 - h, w * 0.7, max(h, 1), col))
        out.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="10" fill="currentColor">%d</text>'
                   % (x + w / 2, 56 - h, n))
        out.append('<text x="%.1f" y="76" text-anchor="middle" font-size="8" fill="currentColor" opacity=".7">%s'
                   '</text>' % (x + w / 2, lab))
    out.append("</svg>")
    return ('<div class="v2c"><div class="v2mut">Lose small, win big? (R = your risk on the trade)</div>%s</div>'
            % "".join(out))


def stacked(title, parts):
    """parts: [(label, count, colour)]"""
    total = sum(n for _, n, _ in parts)
    if not total:
        return ""
    segs = "".join('<div title="%s %d" style="flex:%d;background:%s;color:white;display:flex;align-items:center;'
                   'justify-content:center;font-size:9px">%s</div>' % (esc(l), n, n, c, esc(l) if n / total > 0.12 else "")
                   for l, n, c in parts if n)
    leg = " &middot; ".join("%s %d" % (esc(l), n) for l, n, _ in parts if n)
    return ('<div class="v2c"><div class="v2mut">%s</div><div style="display:flex;height:18px;border-radius:5px;'
            'overflow:hidden;margin-top:4px">%s</div><div class="v2mut" style="margin-top:3px">%s</div></div>'
            % (esc(title), segs, leg))


def donut(title, parts, note):
    total = sum(v for _, v, _ in parts) or 1
    c = 2 * 3.14159 * 26
    off = 0.0
    segs = []
    for _, v, col in parts:
        L = c * v / total
        segs.append('<circle cx="40" cy="40" r="26" fill="none" stroke="%s" stroke-width="12" stroke-dasharray="%.1f %.1f" '
                    'stroke-dashoffset="%.1f" transform="rotate(-90 40 40)"/>' % (col, L, c, -off))
        off += L
    leg = "<br>".join('<span style="color:%s">&#9632;</span> %s' % (col, esc(l)) for l, v, col in parts if v)
    return ('<div class="v2c" style="text-align:center"><div class="v2mut">%s</div><svg viewBox="0 0 80 80" width="72" '
            'height="72">%s</svg><div style="font-size:10px;text-align:left">%s</div><div class="v2mut">%s</div></div>'
            % (esc(title), "".join(segs), leg, note))


def slippage_dots(values, avg):
    if not values:
        return ""
    m = max([abs(v) for v in values] + [0.5])
    dots = "".join('<circle cx="%.1f" cy="15" r="4" fill="%s" opacity=".85"/>'
                   % (160 + 140 * v / m, GREEN if v <= 0 else AMBER if v <= m / 2 else RED) for v in values)
    return ('<div class="v2c"><div class="v2row"><span class="v2mut">Your buy price vs the signal</span><b style="font-size:12px;'
            'color:var(--%s)">%s%.2f a share on average</b></div><svg viewBox="0 0 320 30" width="100%%"><line x1="160" '
            'y1="3" x2="160" y2="27" stroke="currentColor"/>%s<text x="160" y="30" text-anchor="middle" font-size="8" '
            'fill="currentColor" opacity=".7">signal price &middot; right = paid more</text></svg></div>'
            % ("g" if avg <= 0 else "a", "+" if avg > 0 else "", avg, dots))
