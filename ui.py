"""HTML pieces for the scanner website: cards, rings, bars and charts. No Streamlit here."""
import html

import engine

CSS = """<style>
:root{--g:#2e9e4f;--r:#d64545;--a:#c98a12;--b:#2f74c0;--bg-g:rgba(46,158,79,.15);--bg-r:rgba(214,69,69,.15);
--bg-a:rgba(201,138,18,.17);--bg-b:rgba(47,116,192,.15);--card:rgba(127,127,127,.06);--line:rgba(127,127,127,.3);
--mut:rgba(127,127,127,1)}
.v1card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px;margin:6px 0}
.v1g{border:2px solid var(--g)}.v1r{border:2px solid var(--r)}.v1a{border:2px solid var(--a)}.v1b{border:2px solid var(--b)}
.v1row{display:flex;justify-content:space-between;align-items:center;gap:8px}
.v1pill{display:inline-block;font-size:12px;padding:2px 9px;border-radius:8px;margin:2px 4px 2px 0}
.v1tag{font-weight:600;font-size:14px;padding:3px 10px;border-radius:8px}
.v1mut{color:var(--mut);font-size:12px}
.v1sec{color:var(--mut);font-size:13px;margin:14px 0 2px}
.v1bar{display:flex;height:24px;border-radius:8px;overflow:hidden;margin:6px 0 4px;font-size:12px}
.v1bar div{display:flex;align-items:center;justify-content:center}
.v1grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;font-size:12px}
.v1grid div{border:1px solid var(--line);border-radius:8px;padding:5px 7px}
.v1fb{display:flex;align-items:center;gap:6px;margin-bottom:3px;font-size:11px}
.v1fb span{width:96px;color:var(--mut)}.v1fb div{flex:1;height:7px;border-radius:4px}
</style>"""


def esc(x):
    return html.escape(str(x))


def p2(x):
    return "%.2f" % float(x)


def ring(score, size=66):
    c = 2 * 3.14159 * 32
    col = "#2e9e4f" if score >= 8 else "#7fbf3f" if score >= 6 else "#a0a0a0"
    return ('<svg viewBox="0 0 80 80" width="%d" height="%d"><circle cx="40" cy="40" r="32" fill="none" '
            'stroke="rgba(127,127,127,.25)" stroke-width="9"/><circle cx="40" cy="40" r="32" fill="none" '
            'stroke="%s" stroke-width="9" stroke-dasharray="%.1f %.1f" stroke-linecap="round" '
            'transform="rotate(-90 40 40)"/><text x="40" y="47" text-anchor="middle" font-size="21" '
            'font-weight="600" fill="currentColor">%d</text></svg>' % (size, size, col, c * score / 10.0, c, score))


def factor_bars(factors):
    out = []
    for _, label, p, mx in factors:
        col = "#2e9e4f" if p == mx else "#9ccc65" if p > 0 else "rgba(127,127,127,.25)"
        out.append('<div class="v1fb"><span>%s</span><div style="background:%s"></div></div>' % (esc(label), col))
    return "".join(out)


def chips(checks):
    out = []
    for _, label, ok in checks:
        if ok is None:
            out.append('<span class="v1pill" style="background:var(--bg-a);color:var(--a)">%s: check yourself</span>'
                       % esc(label))
        elif ok:
            out.append('<span class="v1pill" style="background:var(--bg-g);color:var(--g)">&#10003; %s</span>'
                       % esc(label))
        else:
            out.append('<span class="v1pill" style="background:var(--bg-r);color:var(--r)">&#10007; %s</span>'
                       % esc(label))
    return "".join(out)


def chart(r, w=340, h=130):
    """Candles of today with the morning range band and the target / entry / stop lines."""
    bars = r["bars"][-36:]
    lows = [b["l"] for b in bars] + [r["stop"], r["or_low"]]
    highs = [b["h"] for b in bars] + [r["target"], r["or_high"]]
    lo, hi = min(lows), max(highs)
    pad = (hi - lo) * 0.06 or 1
    lo, hi = lo - pad, hi + pad
    plot_w = w - 56

    def y(v):
        return 6 + (hi - v) / (hi - lo) * (h - 22)
    n = max(len(bars), 1)
    step = plot_w / n
    cw = max(2.0, min(10.0, step * 0.6))
    first = r["bars"][0]["start"]
    parts = ['<svg viewBox="0 0 %d %d" width="100%%">' % (w, h)]
    or_n = sum(1 for b in bars if (b["start"] - first).seconds < 900)
    if or_n:
        parts.append('<rect x="2" y="%.1f" width="%.1f" height="%.1f" fill="rgba(47,116,192,.16)"/>'
                     % (y(r["or_high"]), step * or_n, max(1, y(r["or_low"]) - y(r["or_high"]))))
    for val, col, dash, lab in ((r["target"], "#2e9e4f", "5 4", "Target"), (r["entry"], "currentColor", "", "Buy"
                                if r["side"] == "buy" else "Sell"), (r["stop"], "#d64545", "5 4", "Stop")):
        parts.append('<line x1="2" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1.4" stroke-dasharray="%s"/>'
                     % (y(val), plot_w, y(val), col, dash))
        parts.append('<text x="%d" y="%.1f" font-size="11" fill="%s">%s %s</text>'
                     % (plot_w + 3, y(val) + 4, col, lab, p2(val)))
    ti = r.get("trigger_index")
    for k, b in enumerate(bars):
        x = 2 + step * k + step / 2
        idx = len(r["bars"]) - len(bars) + k
        col = "#2e9e4f" if b["c"] >= b["o"] else "#d64545"
        if idx < 3:
            col = "#909090"
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.2"/>'
                     % (x, y(b["h"]), x, y(b["l"]), col))
        top, bot = y(max(b["o"], b["c"])), y(min(b["o"], b["c"]))
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                     % (x - cw / 2, top, cw, max(1.0, bot - top), col))
        if ti is not None and idx == ti:
            parts.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="#2e9e4f" stroke-width="2"/>'
                         % (x, y(b["c"]), cw + 2))
    parts.append('<text x="4" y="%d" font-size="11" fill="currentColor" opacity=".6">Morning range shaded</text>' % (h - 3))
    parts.append("</svg>")
    return "".join(parts)


def rr_bar(loss, gain):
    loss, gain = abs(loss), max(gain, 0)
    return ('<div class="v1bar"><div style="flex:%.2f;background:var(--bg-r);color:var(--r)">%s</div>'
            '<div style="flex:%.2f;background:var(--bg-g);color:var(--g);font-weight:600">%s</div></div>'
            % (max(loss, 1), engine.rupees(-loss, True), max(gain, 1), engine.rupees(gain, True)))


def pick_card(r):
    long = r["side"] == "buy"
    tag = ("Strong buy" if r["score"] >= 8 else "Buy") if long else ("Strong sell" if r["score"] >= 8 else "Sell (short)")
    col = "g" if long else "r"
    arrow = "&#8599;" if long else "&#8600;"
    return "".join([
        '<div class="v1card v1%s">' % col,
        '<div class="v1row"><span class="v1tag" style="background:var(--bg-%s);color:var(--%s)">%s %s</span>'
        '<b style="font-size:16px">%s</b><span class="v1mut">%s</span></div>'
        % (col, col, arrow, tag, esc(r["symbol"]), engine.hhmm(r["signal_time"].time())),
        '<div style="display:flex;align-items:center;gap:10px;margin:8px 0">%s<div style="flex:1">%s</div></div>'
        % (ring(r["score"]), factor_bars(r["factors"])),
        '<div>%s</div>' % chips(r["checks"]),
        chart(r),
        rr_bar(r["loss_at_stop"], r["gain_at_target"]),
        '<div class="v1mut" style="margin-bottom:8px">%s %d shares at &#8377;%s &middot; Intraday &middot; Limit '
        '&middot; Cost %s &middot; Break-even &#8377;%s</div>'
        % ("Buy" if long else "Sell", r["qty"], p2(r["entry"]), engine.rupees(r["cost"]),
           p2(r["break_even"]) if r["break_even"] else "-"),
        '<div class="v1grid">',
        '<div><span style="color:var(--r)">&#9632;</span> Stop-loss &#8377;%s at once</div>' % p2(r["stop"]),
        '<div><span style="color:var(--a)">&#128274;</span> Lock at &#8377;%s</div>' % p2(r["lock"]),
        '<div><span style="color:var(--a)">&#8600;</span> Market-drop alarm</div>',
        '<div>&#8987; Exit by %s</div>' % engine.hhmm(r["exit_by"].time()),
        '</div>',
        '<div class="v1mut" style="margin-top:8px">Before you %s: results or big news today? calm? stop-loss ready?</div>'
        % ("buy" if long else "sell"),
        '</div>'])


def pick_row(r):
    long = r["side"] == "buy"
    return "".join([
        '<div class="v1card"><div class="v1row">%s<div style="flex:1;min-width:0">' % ring(r["score"], 40),
        '<div class="v1row"><b>%s</b><span style="color:var(--%s);font-size:13px">%s</span></div>'
        % (esc(r["symbol"]), "g" if long else "r", ("Strong " if r["score"] >= 8 else "") + ("buy" if long else "sell")),
        rr_bar(r["loss_at_stop"], r["gain_at_target"]),
        '<div class="v1mut">%s &#8377;%s &middot; %d shares &middot; %s</div></div></div></div>'
        % ("Buy" if long else "Sell", p2(r["entry"]), r["qty"], engine.hhmm(r["signal_time"].time()))])


def watch_rows(watch):
    rows = []
    for w in watch:
        pct_full = int(max(5, min(100, w["closeness"] * 100)))
        rows.append('<div style="display:flex;align-items:center;gap:8px;font-size:13px;margin:4px 0">'
                    '<span style="width:96px">%s</span><div style="flex:1;height:8px;border-radius:4px;'
                    'background:rgba(127,127,127,.2);overflow:hidden"><div style="width:%d%%;height:100%%;'
                    'background:var(--a)"></div></div><span class="v1mut" style="width:72px;text-align:right">'
                    '&#8377;%s away</span></div>' % (esc(w["symbol"]), pct_full, p2(w["distance"])))
    return '<div class="v1card">%s</div>' % "".join(rows)


def open_trade(t, st):
    long = t["side"] == "buy"
    lo, hi = (t["stop"], t["target"]) if long else (t["target"], t["stop"])
    span = (hi - lo) or 1
    pos = max(0.0, min(1.0, (st["price"] - lo) / span))
    red = (t["entry"] - lo) / span if long else (hi - t["entry"]) / span
    pnl_col = "g" if st["pnl"] >= 0 else "r"
    left, right = ("Stop", "Target") if long else ("Target", "Stop")
    return "".join([
        '<div class="v1card v1b"><div class="v1row"><b>%s &middot; %d shares%s</b>'
        % (esc(t["symbol"]), t["qty"], "" if long else " (short)"),
        '<span class="v1pill" style="background:var(--bg-b);color:var(--b)">%s</span>'
        % ("Practice" if t["mode"] == "paper" else "Real money"),
        '<b style="color:var(--%s)">%s now</b></div>' % (pnl_col, engine.rupees(st["pnl"], True)),
        '<div style="position:relative;height:10px;border-radius:5px;margin:12px 0 4px;background:linear-gradient('
        'to right,%s 0 %.0f%%,%s %.0f%% 100%%)">'
        % (("var(--bg-r)", red * 100, "var(--bg-g)", red * 100) if long else
           ("var(--bg-g)", (1 - red) * 100, "var(--bg-r)", (1 - red) * 100)),
        '<div style="position:absolute;left:calc(%.0f%% - 2px);top:-4px;width:4px;height:18px;border-radius:2px;'
        'background:currentColor"></div></div>' % (pos * 100),
        '<div class="v1row v1mut"><span>%s %s</span><span>Now %s</span><span>%s %s</span></div>'
        % (left, p2(lo), p2(st["price"]), right, p2(hi)),
        '<div class="v1mut" style="margin-top:6px">Bought %s at &#8377;%s &middot; stop-loss &#8377;%s &middot; '
        'lock at &#8377;%s &middot; exit by %s</div></div>'
        % (t["opened_at"][11:16], p2(t["entry"]), p2(t["stop"]), p2(t["lock"]), t["exit_by"][11:16])])


def alert(kind, message):
    col, title = {"lock": ("a", "&#128274; Safety lock"), "exit": ("r", "&#10140; Exit now"),
                  "stop": ("r", "&#9632; Stop-loss reached"), "target": ("g", "&#127919; Target reached")}[kind]
    return ('<div class="v1card v1%s"><span class="v1tag" style="background:var(--bg-%s);color:var(--%s)">%s</span>'
            '<div style="font-size:14px;margin-top:6px">%s</div></div>' % (col, col, col, title, esc(message)))


def day_strip(counts, max_trades, nifty_closes):
    dots = []
    for k in range(max_trades):
        state = counts["dots"][k] if k < len(counts["dots"]) else None
        col = {"win": "var(--g)", "loss": "var(--r)", "open": "var(--b)"}.get(state, "rgba(127,127,127,.25)")
        dots.append('<span style="display:inline-block;width:26px;height:10px;border-radius:5px;margin-right:5px;'
                    'background:%s"></span>' % col)
    spark = ""
    if len(nifty_closes) >= 2:
        lo, hi = min(nifty_closes), max(nifty_closes)
        rng = (hi - lo) or 1
        pts = " ".join("%.1f,%.1f" % (k * 70.0 / (len(nifty_closes) - 1), 18 - (c - lo) / rng * 16)
                       for k, c in enumerate(nifty_closes))
        col = "#2e9e4f" if nifty_closes[-1] >= nifty_closes[0] else "#d64545"
        spark = ('<svg viewBox="0 0 70 20" width="70" height="20"><polyline fill="none" stroke="%s" '
                 'stroke-width="2" points="%s"/></svg>' % (col, pts))
    return ('<div class="v1card"><div class="v1row"><div><div class="v1mut">Trades today</div>%s</div>'
            '<div style="text-align:right"><div class="v1mut">Nifty today (info only)</div>%s</div></div></div>'
            % ("".join(dots), spark))


def done_card(reason, counts):
    return ('<div class="v1card" style="text-align:center;padding:16px"><div style="font-size:24px">&#127769;</div>'
            '<div style="font-size:16px;font-weight:600;margin:4px 0">Done for today</div>'
            '<div class="v1mut" style="font-size:13px">%s New picks are paused until tomorrow 9:15 AM.</div>'
            '<div class="v1mut" style="margin-top:6px">%d win &middot; %d loss &middot; today %s</div></div>'
            % (esc(reason), counts["wins"], counts["losses"], engine.rupees(counts["net"], True)))


def results_card(res, mode):
    if not res["count"]:
        return ('<div class="v1card"><div class="v1mut">No closed %s trades yet. Your running total, win rate and '
                'average win and loss appear here.</div></div>' % ("practice" if mode == "paper" else "real"))
    run = [0.0] + res["running"]
    lo, hi = min(run), max(run)
    rng = (hi - lo) or 1
    pts = " ".join("%.1f,%.1f" % (6 + k * 328.0 / max(len(run) - 1, 1), 8 + (hi - v) / rng * 56)
                   for k, v in enumerate(run))
    zero = 8 + (hi - 0) / rng * 56
    col = "g" if res["total"] >= 0 else "r"
    wr = res["win_rate"] or 0
    goal = min(100, int(100 * res["count"] / res["goal"]))
    return "".join([
        '<div class="v1card"><div class="v1row"><span class="v1mut">Running total after charges</span>'
        '<b style="font-size:17px;color:var(--%s)">%s</b></div>' % (col, engine.rupees(res["total"], True)),
        '<svg viewBox="0 0 340 72" width="100%%"><line x1="6" y1="%.1f" x2="334" y2="%.1f" '
        'stroke="rgba(127,127,127,.35)"/><polyline fill="none" stroke="%s" stroke-width="2.5" points="%s"/></svg>'
        % (zero, zero, "#2e9e4f" if res["total"] >= 0 else "#d64545", pts),
        '<div class="v1row" style="font-size:13px"><span>Win rate %d%% (%d of %d)</span>'
        '<span style="color:var(--g)">Avg win %s</span><span style="color:var(--r)">Avg loss %s</span></div>'
        % (wr, res["wins"], res["count"], engine.rupees(res["avg_win"] or 0, True),
           engine.rupees(res["avg_loss"] or 0, True)),
        '<div class="v1mut" style="margin-top:8px">%s goal: %d trades &middot; %d of %d</div>'
        % ("Practice" if mode == "paper" else "Tracking", res["goal"], res["count"], res["goal"]),
        '<div style="height:6px;border-radius:3px;background:rgba(127,127,127,.2);overflow:hidden;margin-top:4px">'
        '<div style="width:%d%%;height:100%%;background:var(--b)"></div></div></div>' % goal])


def skipped_rows(skipped):
    return "".join('<div class="v1row" style="font-size:13px;margin:3px 0"><span>%s</span><span class="v1mut">%s'
                   '</span></div>' % (esc(s["symbol"]), esc(s.get("reason") or "lower score"))
                   for s in skipped)
