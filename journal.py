"""Your trades: open trades, closed trades and results, for the NSE scanner website.

Where they are kept:
  - a PRIVATE GitHub repository, when the app's Secrets have GITHUB_TOKEN and JOURNAL_REPO
    (the free Streamlit server forgets its own files when the app sleeps or restarts);
  - otherwise only while the page is open, with a download / upload button as a backup.
"""

import base64
import datetime
import json
import urllib.error
import urllib.request
import uuid

import engine

API = "https://api.github.com/repos/%s/contents/%s"


class JournalError(Exception):
    pass


class GitHubStore(object):
    """journal.json in a private GitHub repository, through GitHub's contents API."""

    def __init__(self, token, repo, path="journal.json"):
        self.token, self.repo, self.path = token, repo.strip().strip("/"), path
        self.sha = None

    def _req(self, method, body=None):
        req = urllib.request.Request(API % (self.repo, self.path), method=method,
                                     data=json.dumps(body).encode("utf-8") if body is not None else None,
                                     headers={"Authorization": "Bearer %s" % self.token,
                                              "Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28",
                                              "User-Agent": "nse-scanner-journal"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404 and method == "GET":
                return None
            if e.code in (401, 403):
                raise JournalError("GitHub refused the key (HTTP %d): check GITHUB_TOKEN in Secrets and that it "
                                   "can read and write %s" % (e.code, self.repo))
            if e.code == 404:
                raise JournalError("GitHub can't find %s: check JOURNAL_REPO in Secrets" % self.repo)
            if e.code == 409:
                raise JournalError("The journal changed in another tab. Reload the page and try again.")
            raise JournalError("GitHub answered HTTP %d" % e.code)
        except urllib.error.URLError as e:
            raise JournalError("Could not reach GitHub: %s" % e.reason)

    def load(self):
        doc = self._req("GET")
        if doc is None:
            self.sha = None
            return empty()
        self.sha = doc.get("sha")
        return json.loads(base64.b64decode(doc.get("content", "")).decode("utf-8") or "{}") or empty()

    def save(self, data, message):
        body = {"message": message, "content": base64.b64encode(json.dumps(data, indent=1).encode("utf-8")).decode()}
        if self.sha:
            body["sha"] = self.sha
        res = self._req("PUT", body)
        self.sha = ((res or {}).get("content") or {}).get("sha", self.sha)


def empty():
    return {"version": 1, "trades": []}


# ---------------------------------------------------------------- trades

def new_trade(pick_or_symbol, side, entry, stop, qty, mode, now, cfg=None):
    """A trade record from what the user actually did. Raises JournalError with a plain message."""
    c = dict(engine.DEFAULTS)
    c.update(cfg or {})
    sym = pick_or_symbol if isinstance(pick_or_symbol, str) else pick_or_symbol["symbol"]
    try:
        entry, stop = float(entry), float(stop)
    except (TypeError, ValueError):
        raise JournalError("Enter your buy price and stop-loss.")
    if entry <= 0:
        raise JournalError("Enter your buy price.")
    if qty is None or int(qty) != qty or int(qty) < 1:
        raise JournalError("Quantity must be a whole number, 1 or more.")
    qty = int(qty)
    long = side == "buy"
    if long and stop >= entry:
        raise JournalError("Stop-loss must be below your buy price.")
    if not long and stop <= entry:
        raise JournalError("Stop-loss must be above your sell price for a short.")
    plan = levels(side, entry, stop, c)
    exit_by = min(now + datetime.timedelta(minutes=c["time_stop_minutes"]),
                  datetime.datetime.combine(now.date(), c["flat_by"]))
    return {"id": uuid.uuid4().hex[:10], "symbol": sym, "side": side, "mode": mode, "date": now.date().isoformat(),
            "opened_at": now.replace(microsecond=0).isoformat(), "entry": round(entry, 2), "stop": round(stop, 2),
            "first_stop": round(stop, 2), "qty": qty, "target": plan["target"], "lock": plan["lock"],
            "exit_by": exit_by.replace(microsecond=0).isoformat(), "status": "open",
            "score": None if isinstance(pick_or_symbol, str) else pick_or_symbol.get("score"),
            "signal_entry": None if isinstance(pick_or_symbol, str) else pick_or_symbol.get("entry")}


def slippage(trade):
    """Rupees per share paid versus the signal price (positive = worse than the signal), or None."""
    sig = trade.get("signal_entry")
    if not sig:
        return None
    d = trade["entry"] - sig if trade["side"] == "buy" else sig - trade["entry"]
    return round(d, 2)


def levels(side, entry, stop, cfg=None):
    """Target, safety lock, money at the stop and at the target, break-even, for any entry/stop/qty."""
    c = dict(engine.DEFAULTS)
    c.update(cfg or {})
    long = side == "buy"
    risk = abs(entry - stop)
    target = engine.snap(entry + c["reward_r"] * risk if long else entry - c["reward_r"] * risk, ref=entry)
    lock = engine.snap(entry + risk if long else entry - risk, ref=entry)
    return {"target": target, "lock": lock, "risk": round(risk, 2)}


def money_plan(side, entry, stop, qty, cfg=None):
    lv = levels(side, entry, stop, cfg)
    return dict(lv, loss=-engine.net(side, qty, entry, stop), gain=engine.net(side, qty, entry, lv["target"]),
                break_even=engine.break_even(side, qty, entry), cost=round(qty * entry, 2))


def close_trade(trade, exit_price, how, now, followed=None):
    try:
        exit_price = float(exit_price)
    except (TypeError, ValueError):
        raise JournalError("Enter the price you sold at.")
    if exit_price <= 0:
        raise JournalError("Enter the price you sold at.")
    trade = dict(trade)
    trade.update(status="closed", exit=round(exit_price, 2), how=how, followed=followed,
                 closed_at=now.replace(microsecond=0).isoformat(),
                 net=engine.net(trade["side"], trade["qty"], trade["entry"], exit_price))
    return trade


def replace(data, trade):
    data = dict(data)
    data["trades"] = [trade if t["id"] == trade["id"] else t for t in data.get("trades", [])]
    if not any(t["id"] == trade["id"] for t in data["trades"]):
        data["trades"].append(trade)
    return data


def open_trades(data, mode):
    return [t for t in data.get("trades", []) if t["status"] == "open" and t["mode"] == mode]


def closed_trades(data, mode):
    return sorted([t for t in data.get("trades", []) if t["status"] == "closed" and t["mode"] == mode],
                  key=lambda t: t.get("closed_at", ""))


def today(data, mode, day):
    return [t for t in data.get("trades", []) if t["mode"] == mode and t["date"] == day.isoformat()]


def guard(data, mode, day, cfg=None):
    """(done_for_today, reason, counts) from today's trades: max trades, max losses, daily loss."""
    c = dict(engine.DEFAULTS)
    c.update(cfg or {})
    ts = today(data, mode, day)
    closed = [t for t in ts if t["status"] == "closed"]
    losses = sum(1 for t in closed if t["net"] < 0)
    total = round(sum(t["net"] for t in closed), 2)
    counts = {"taken": len(ts), "losses": losses, "wins": sum(1 for t in closed if t["net"] > 0), "net": total,
              "dots": [("open" if t["status"] == "open" else "win" if t["net"] > 0 else "loss") for t in ts]}
    if len(ts) >= c["max_trades"]:
        return True, "%d of %d trades taken." % (len(ts), c["max_trades"]), counts
    if losses >= c["max_losses"]:
        return True, "%d losses today. The best traders stop here." % losses, counts
    if total <= -c["daily_loss"]:
        return True, "Daily loss limit of %s reached." % engine.rupees(c["daily_loss"]), counts
    return False, "", counts


def results(data, mode, goal=50):
    closed = closed_trades(data, mode)
    asked = [t for t in closed if t.get("followed") is not None]
    slips = [slippage(t) for t in closed if slippage(t) is not None]
    running, total = [], 0.0
    for t in closed:
        total += t["net"]
        running.append(round(total, 2))
    wins = [t["net"] for t in closed if t["net"] > 0]
    losses = [t["net"] for t in closed if t["net"] <= 0]
    return {"count": len(closed), "total": round(total, 2), "running": running,
            "win_rate": round(100.0 * len(wins) / len(closed)) if closed else None,
            "wins": len(wins), "losses": len(losses),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
            "goal": goal,
            "discipline": round(100.0 * sum(1 for t in asked if t["followed"]) / len(asked)) if asked else None,
            "slippage": round(sum(slips) / len(slips), 2) if slips else None}


# ---------------------------------------------------------------- every signal, tracked in the background

def add_signal(data, pick, cfg=None):
    """Record a BUY / SELL signal once (symbol + day), sized to today's settings. -> (data, changed)."""
    sigs = data.get("signals", [])
    day = pick["signal_time"].date().isoformat()
    if any(x["symbol"] == pick["symbol"] and x["date"] == day for x in sigs):
        return data, False
    rec = {"symbol": pick["symbol"], "side": pick["side"], "date": day,
           "time": pick["signal_time"].replace(microsecond=0).isoformat(), "score": pick["score"],
           "entry": pick["entry"], "stop": pick["stop"], "target": pick["target"], "qty": pick["qty"],
           "outcome": None, "exit": None, "net": None}
    data = dict(data)
    data["signals"] = sigs + [rec]
    return data, True


def settle_signals(data, charts, now, cfg=None):
    """Fill in the outcome of open signals from `charts` {symbol: series}. -> (data, changed)."""
    changed = False
    out = []
    for x in data.get("signals", []):
        if x.get("outcome") is None and x["symbol"] in charts:
            res = engine.evaluate_signal(x, charts[x["symbol"]], now, cfg)
            if res:
                x = dict(x, outcome=res[0], exit=round(res[1], 2),
                         net=engine.net(x["side"], max(x["qty"], 1), x["entry"], res[1]))
                changed = True
        out.append(x)
    if changed:
        data = dict(data)
        data["signals"] = out
    return data, changed


def signal_stats(data):
    done = [x for x in data.get("signals", []) if x.get("outcome")]

    def wr(xs):
        return round(100.0 * sum(1 for x in xs if x["net"] > 0) / len(xs)) if xs else None
    strong = [x for x in done if x["score"] >= 8]
    normal = [x for x in done if x["score"] < 8]
    return {"count": len(done), "pending": sum(1 for x in data.get("signals", []) if not x.get("outcome")),
            "win_rate": wr(done), "total": round(sum(x["net"] for x in done), 2),
            "avg": round(sum(x["net"] for x in done) / len(done), 2) if done else None,
            "strong": (len(strong), wr(strong)), "normal": (len(normal), wr(normal))}
