"""NSE intraday scanner, version 1. A Streamlit page around engine.py, journal.py and ui.py.

Run on your computer:   pip install streamlit  &&  streamlit run streamlit_app.py
Host it for free:       Streamlit Community Cloud (see README.md)

It scans, scores and sizes trades and tracks the ones you tell it you took. It never places
orders and never asks for a broker login. A pick is a chart that matched rules, not a promise.
Not financial advice.
"""

import datetime
import hashlib
import hmac
import json
import os
import time

import streamlit as st

import backtest
import engine
import journal
import lists
import ui

st.set_page_config(page_title="NSE scanner", page_icon="\U0001F4C8", layout="centered")
st.markdown(ui.CSS, unsafe_allow_html=True)


def html(s):
    st.markdown(s, unsafe_allow_html=True)


def secret(name):
    """Streamlit Cloud Secrets, or an environment variable (Hugging Face Spaces, your own computer)."""
    try:
        v = st.secrets.get(name)
        if v:
            return v
    except Exception:  # no secrets file
        pass
    return os.environ.get(name) or None


# ---------------------------------------------------------------- password (remembered for 1 hour of inactivity)

LOGIN_SECONDS = 3600


def _sign(exp, pw):
    return hmac.new(pw.encode("utf-8"), str(exp).encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def _token(pw):
    exp = int(time.time()) + LOGIN_SECONDS
    return "%d.%s" % (exp, _sign(exp, pw))


def _expiry(tok, pw):
    """Expiry (unix seconds) of a valid, unexpired login code, else None."""
    try:
        exp_s, sig = str(tok).split(".", 1)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        return None
    if exp < time.time() or not hmac.compare_digest(sig, _sign(exp, pw)):
        return None
    return exp


def renew_login():
    """Keep the login code in the address bar fresh while the page is in use (every ~10 minutes)."""
    pw = secret("APP_PASSWORD")
    if not pw or not st.session_state.get("pw_ok"):
        return
    exp = _expiry(st.query_params.get("s"), pw)
    if exp is None or exp - time.time() < LOGIN_SECONDS - 600:
        st.query_params["s"] = _token(pw)


def password_ok():
    pw = secret("APP_PASSWORD")
    if not pw or st.session_state.get("pw_ok"):
        return True
    if _expiry(st.query_params.get("s"), pw):          # same address, used within the last hour
        st.session_state["pw_ok"] = True
        return True
    st.title("\U0001F4C8 NSE scanner")
    typed = st.text_input("Password", type="password")
    if typed and hmac.compare_digest(typed, pw):
        st.session_state["pw_ok"] = True
        st.query_params["s"] = _token(pw)
        st.rerun()
    elif typed:
        st.error("Wrong password.")
    return False


if not password_ok():
    st.stop()
renew_login()


# ---------------------------------------------------------------- journal storage

def store():
    token, repo = secret("GITHUB_TOKEN"), secret("JOURNAL_REPO")
    if token and repo:
        if "store" not in st.session_state:
            st.session_state["store"] = journal.GitHubStore(token, repo, secret("JOURNAL_PATH") or "journal.json")
        return st.session_state["store"]
    return None


def load_journal():
    if "journal" not in st.session_state:
        s = store()
        data = journal.empty()
        if s:
            try:
                data = s.load()
            except journal.JournalError as e:
                st.session_state["journal_error"] = str(e)
        st.session_state["journal"] = data
    return st.session_state["journal"]


def save_journal(data, message):
    st.session_state["journal"] = data
    s = store()
    if s:
        try:
            s.save(data, message)
            st.session_state.pop("journal_error", None)
        except journal.JournalError as e:
            st.session_state["journal_error"] = str(e)


# ---------------------------------------------------------------- settings (side panel)

with st.sidebar:
    page_choice = st.radio("Page", ["Scanner", "Backtest (60 days)"], index=0, horizontal=True)
    st.header("Settings")
    mode_label = st.radio("Mode", ["Practice (paper)", "Real money"], index=0)
    mode = "paper" if mode_label.startswith("Practice") else "real"
    capital = st.number_input("Capital (\u20b9)", min_value=500.0, value=5000.0, step=500.0)
    max_loss = st.number_input("Max loss per trade (\u20b9)", min_value=10.0,
                               value=75.0 if mode == "paper" else 50.0, step=5.0, key="max_loss_" + mode,
                               help="Practice: \u20b975. Real money: start at \u20b950 (1% of \u20b95,000), "
                                    "move to \u20b975 once your results stay positive after charges.")
    max_trades = st.number_input("Max trades per day", min_value=1, max_value=5, value=2, step=1)
    daily_loss = st.number_input("Stop for the day after losing (\u20b9)", min_value=10.0, value=150.0, step=10.0)
    c1, c2 = st.columns(2)
    min_price = c1.number_input("Min price \u20b9", min_value=1.0, value=100.0, step=10.0)
    max_price = c2.number_input("Max price \u20b9", min_value=10.0, value=500.0, step=10.0)
    source = st.selectbox("Stocks to scan", list(lists.PRESETS) + ["Whole NSE list", "My symbols"])
    typed = ""
    if source == "My symbols":
        typed = st.text_area("NSE symbols, comma separated", "RELIANCE, TCS, INFY, ITC, SBIN, TATASTEEL")
    shorts = st.toggle("Show SELL (short) signals", value=False)
    auto = st.toggle("Auto-refresh in market hours", value=True,
                     help="Every 30 s from 9:15 AM to 3:30 PM, once a minute before the open, off otherwise.")
    if st.button("Refresh now"):
        st.session_state["bump"] = st.session_state.get("bump", 0) + 1
    st.caption("Groww intraday charges are included in every rupee figure. Estimates: your contract note is "
               "the real number.")

def load_events():
    """trader/events.json in the repository: [{"date": "YYYY-MM-DD", "time": "HH:MM", "name": "RBI policy"}]."""
    try:
        with open(os.path.join(lists.HERE, "trader", "events.json"),
                  encoding="utf-8") as fh:
            ev = json.load(fh)
        return [e for e in ev if isinstance(e, dict) and e.get("date")]
    except (OSError, ValueError):
        return []


EVENTS = load_events()
CFG = {"capital": capital, "max_loss": max_loss, "max_trades": int(max_trades), "daily_loss": daily_loss,
       "min_price": min_price, "max_price": max_price, "shorts": shorts, "events": EVENTS}


# ---------------------------------------------------------------- cached data

@st.cache_data(ttl=24 * 3600, show_spinner=False)
def symbols_for(source, typed, day):
    if source == "My symbols":
        return [s.strip().upper() for s in typed.replace("\n", ",").split(",") if s.strip()], ""
    if source == "Whole NSE list":
        return lists.universe()
    rows, note = lists.load_preset(lists.PRESETS[source])
    return [s for s, _ in rows], note


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def daily_data(symbols, day):
    return engine.fetch_daily(symbols)


@st.cache_data(ttl=60, show_spinner=False)
def live(symbols, key):
    try:
        return engine.live_prices(symbols)
    except Exception:
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def spark_5m(symbols, key):
    return engine.fetch_intraday_closes(symbols)


@st.cache_data(ttl=600, show_spinner=False)
def chart(sym, key):
    try:
        return engine.fetch_chart(sym)
    except Exception:
        return None


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def daily_chart(sym, day):
    try:
        return engine.fetch_daily_chart(sym)
    except Exception:
        return None


@st.cache_data(ttl=240, show_spinner=False)
def sectors(key):
    try:
        return engine.fetch_sectors()
    except Exception:
        return {}


@st.cache_data(ttl=240, show_spinner=False)
def vix(key):
    try:
        return engine.fetch_vix()
    except Exception:
        return None


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def industry_map(day):
    rows, _ = lists.load_preset("ind_nifty500list.csv")
    return {sym: engine.sector_of(ind) for sym, ind in rows if engine.sector_of(ind)}


@st.cache_data(ttl=1800, show_spinner=False)
def news(sym, hour):
    try:
        return engine.news_flag(engine.fetch_news(sym), engine.now_ist())
    except Exception:
        return None


# ---------------------------------------------------------------- dialogs

@st.dialog("I took this trade")
def took_dialog(pick):
    long = pick["side"] == "buy"
    st.write("**%s** %s. Enter what actually happened in Groww." % (pick["symbol"], "buy" if long else "short sell"))
    c1, c2 = st.columns(2)
    entry = c1.number_input("My %s price (\u20b9)" % ("buy" if long else "sell"), value=float(pick["entry"]),
                            step=0.05, format="%.2f")
    qty = c2.number_input("Quantity (shares)", value=int(max(pick["qty"], 1)), min_value=1, step=1)
    stop = st.number_input("My stop-loss (\u20b9)", value=float(pick["stop"]), step=0.05, format="%.2f")
    bad = None
    if entry <= 0:
        bad = "Enter your price."
    elif long and stop >= entry:
        bad = "Stop-loss must be below your buy price."
    elif not long and stop <= entry:
        bad = "Stop-loss must be above your sell price."
    if bad:
        st.error(bad)
        return
    mp = journal.money_plan(pick["side"], entry, stop, int(qty), CFG)
    html('<div class="v1grid" style="margin:6px 0"><div>&#127919; Target <b style="color:var(--g)">&#8377;%s</b></div>'
         '<div>&#128274; Safety lock <b style="color:var(--a)">&#8377;%s</b></div>'
         '<div>If stop hits <b style="color:var(--r)">%s</b></div><div>If target hits <b style="color:var(--g)">%s</b>'
         '</div></div>' % (ui.p2(mp["target"]), ui.p2(mp["lock"]), engine.rupees(-mp["loss"], True),
                           engine.rupees(mp["gain"], True)))
    html(ui.rr_bar(mp["loss"], mp["gain"]))
    st.caption("Break-even \u20b9%s \u00b7 Cost %s \u00b7 Exit by 2:55 PM at the latest"
               % (ui.p2(mp["break_even"]), engine.rupees(mp["cost"])))
    st.code(ui.order_text(pick["symbol"], pick["side"], int(qty), entry, stop, mp["target"]), language=None)
    fit = engine.size(pick["side"], entry, stop, capital, max_loss)
    if mp["loss"] > max_loss + 0.005 or mp["cost"] > capital + 0.005:
        st.warning("This is over your limits (max loss %s, capital %s). Reduce to %d shares."
                   % (engine.rupees(max_loss), engine.rupees(capital), fit))
    if st.button("Start tracking", type="primary", use_container_width=True):
        try:
            t = journal.new_trade(pick, pick["side"], entry, stop, int(qty), mode, engine.now_ist(), CFG)
        except journal.JournalError as e:
            st.error(str(e))
            return
        save_journal(journal.replace(load_journal(), t), "Open %s" % t["symbol"])
        st.rerun()


@st.dialog("Sold at another price")
def other_price_dialog(trade, price_now, tag=None):
    st.write("**%s**: the price you %s at." % (trade["symbol"], "sold" if trade["side"] == "buy" else "bought back"))
    price = st.number_input("Price (\u20b9)", value=float(price_now), step=0.05, format="%.2f")
    st.caption("Result after charges: %s" % engine.rupees(engine.net(trade["side"], trade["qty"], trade["entry"],
                                                                          price), True))
    if st.button("Save", type="primary", use_container_width=True):
        close(trade, price, "other", tag)


def close(trade, price, how, tag=None):
    try:
        done = journal.close_trade(trade, price, how, engine.now_ist(), tag=tag)
    except journal.JournalError as e:
        st.error(str(e))
        return
    save_journal(journal.replace(load_journal(), done), "Close %s" % trade["symbol"])
    st.rerun()


# ---------------------------------------------------------------- the page

def scan_market(now, day, key, key30, nifty, data):
    """Scan the chosen stocks -> dict(picks, watch, skipped, allpicks, scanned, checked, note, up, down, sectors)."""
    out = {"picks": [], "watch": [], "skipped": [], "finished": [], "allpicks": [], "scanned": 0, "checked": 0,
           "note": "",
           "up": 0, "down": 0, "sectors": sectors(key)}
    syms, note = symbols_for(source, typed, day.isoformat())
    if not syms:
        out["note"] = note or "empty"
        return out
    daily, _ = daily_data(tuple(syms), day.isoformat())
    inrange = []
    for s_ in syms:
        m = (daily.get(s_) or {}).get("meta") or {}
        p = m.get("regularMarketPrice")
        if p and min_price <= p <= max_price:
            inrange.append((-(p * (m.get("regularMarketVolume") or 0)), s_))
    inrange = [s_ for _, s_ in sorted(inrange)][:250]
    spark, _ = spark_5m(tuple(inrange), key) if inrange else ({}, {})
    out["up"], out["down"] = engine.breadth(daily, spark, day, now)
    cands = set(engine.stage_one(spark, now, CFG))
    cands = [s_ for s_ in inrange if s_ in cands][:25]
    industries = industry_map(day.isoformat())
    results = []
    for s_ in cands:
        series = chart(s_, key)
        if not series:
            continue
        closes = engine.closes_before(daily.get(s_) or {}, day)
        sec_name = industries.get(s_)
        sec = (sec_name, out["sectors"].get(sec_name)) if sec_name else None
        dchart = daily_chart(s_, day.isoformat())
        r = engine.analyse(s_, series, closes, nifty, now, CFG, daily_chart=dchart, sector=sec)
        if r and r["kind"] == "pick":
            r = engine.analyse(s_, series, closes, nifty, now, CFG, news_flag=news(s_, now.hour),
                               daily_chart=dchart, sector=sec)
        results.append(r)
    traded = {t["symbol"] for t in journal.today(data, mode, day)}
    for r in results:
        if r and r["kind"] == "pick" and r["symbol"] in traded:
            r.update(kind="skip", reason="You already traded it today")
    out["picks"], out["watch"], skipped = engine.rank(results)
    out["finished"] = [r for r in skipped if r.get("outcome") in ("target", "stop")]
    out["skipped"] = [r for r in skipped if r.get("outcome") not in ("target", "stop")]
    # every breakout that was a valid signal AT ITS TIME is tracked, even if the page opened later
    out["allpicks"] = [r for r in results if r and r.get("signal_valid")]
    out["scanned"], out["checked"] = len(inrange), len(cands)
    return out


def track_signals(data, allpicks, now, key):
    """Record every new signal and settle finished ones, saving once if anything changed."""
    changed = False
    for r in allpicks:
        if r.get("score") is not None and r.get("qty", 0) >= 1:
            data, c = journal.add_signal(data, r, CFG)
            changed = changed or c
    pending = journal.pending_symbols(data)[:15]
    charts = {s_: chart(s_, key) for s_ in pending}
    data, c = journal.settle_signals(data, {k: v for k, v in charts.items() if v}, now, CFG)
    if changed or c:
        save_journal(data, "Signals %s" % now.strftime("%Y-%m-%d %H:%M"))
    return data


def focus(t, now, key, key30, nifty, phase):
    s_ = chart(t["symbol"], key)
    live_p = live((t["symbol"],), key30).get(t["symbol"]) if phase == "open" else None
    stt = engine.trade_status(t, s_, nifty, now, CFG, live=live_p)
    html(ui.focus_tile(t, stt))
    if stt["alert"] in ("lock", "trail", "exit", "stop", "target"):
        html(ui.alert("lock" if stt["alert"] == "trail" else stt["alert"], stt["message"]))
    if stt["new_stop"] is not None:
        if st.button("Done: I moved my stop-loss to %s" % ui.p2(stt["new_stop"]), key="mv" + t["id"],
                     type="primary", use_container_width=True):
            save_journal(journal.replace(load_journal(), dict(t, stop=stt["new_stop"], stop_moved_at=now.replace(
                microsecond=0).isoformat())), "Move stop %s" % t["symbol"])
            try:
                st.rerun(scope="fragment")
            except TypeError:  # older Streamlit
                st.rerun()
    st.caption("How did it end?" if stt["alert"] in ("stop", "target", "exit") else "Closed it already?")
    tag = st.radio("How did this trade go, honestly?", journal.TAGS, index=0, horizontal=True, key="tag" + t["id"])
    followed = tag
    b1, b2, b3 = st.columns(3)
    if b1.button("Hit target %s" % ui.p2(t["target"]), key="t" + t["id"], use_container_width=True,
                 type="primary" if stt["alert"] == "target" else "secondary"):
        close(t, t["target"], "target", followed)
    if b2.button("Hit stop-loss %s" % ui.p2(t["stop"]), key="s" + t["id"], use_container_width=True,
                 type="primary" if stt["alert"] == "stop" else "secondary"):
        close(t, t["stop"], "stop", followed)
    if b3.button("Sold at another price", key="o" + t["id"], use_container_width=True,
                 type="primary" if stt["alert"] == "exit" else "secondary"):
        other_price_dialog(t, stt["price"], followed)


def keys(now):
    bump = st.session_state.get("bump", 0)
    key = "%s-%d" % (engine.candle_key(now), bump)                 # new candles: 20 s after each 5-minute close
    key30 = "%s-%d" % (now.strftime("%Y%m%d%H%M") + str(now.second // 30), bump)   # live prices: every 30 s
    return key, key30


def header(now, clock=True):
    html('<div class="v1row"><b style="font-size:20px">&#128200; NSE scanner</b><span>%s <span class="v1mut">%s'
         '</span></span></div>' % (ui.refresh_badge(RUN_EVERY, focus=not clock),
                                   now.strftime("%I:%M:%S %p").lstrip("0") if clock else ""))
    html('<span class="v1pill" style="background:var(--bg-b);color:var(--b)">%s</span>'
         '<span class="v1pill" style="border:1px solid var(--line)">%s capital</span>'
         '<span class="v1pill" style="border:1px solid var(--line)">Max loss %s</span>'
         '<span class="v1pill" style="border:1px solid var(--line)">&#8377;%g&ndash;%g</span>'
         % ("Practice mode" if mode == "paper" else "Real money", engine.rupees(capital),
            engine.rupees(max_loss), min_price, max_price))
    if st.session_state.get("journal_error"):
        st.warning("Journal not saved to GitHub: %s" % st.session_state["journal_error"])
    elif not store():
        st.caption("Trades are kept only while this page is open (no GITHUB_TOKEN / JOURNAL_REPO in Secrets). "
                   "Use the download button at the bottom to keep them.")


def schedule_message(now, phase, msg):
    nxt = engine.next_open(now)
    when = "today" if nxt == now.date() else nxt.strftime("%a %d %b")
    if phase == "after":
        return "Market closed at 3:30 PM. Auto-refresh is off. Next open: %s, 9:15 AM. " \
               "Today's signals stay below for review." % when
    if phase == "closed":
        return "%s. Auto-refresh is off. Next open: %s, 9:15 AM." % (msg, when)
    if phase == "pre":
        return "NSE opens at 9:15 AM. This page checks once a minute and starts by itself at the open."
    return msg


def focus_panel():
    """Focus mode: only this panel refreshes. No market scan runs while a trade is open."""
    renew_login()
    now = engine.now_ist()
    key, key30 = keys(now)
    phase, _ = engine.market_phase(now)
    if phase != st.session_state.get("phase_at_start"):
        st.rerun()
    opens = journal.open_trades(load_journal(), mode)
    if not opens:                                   # closed in another tab: back to the full page
        st.rerun()
    nifty = chart(engine.NIFTY, key) if phase in ("open", "forming", "after") else None
    html('<div class="v1mut" style="text-align:right">&#8635; Updated %s</div>' % now.strftime("%I:%M:%S %p").lstrip("0"))
    for t in opens:
        focus(t, now, key, key30, nifty, phase)


def page():
    renew_login()
    now = engine.now_ist()
    day = now.date()
    key, key30 = keys(now)
    data = load_journal()
    phase, phase_msg = engine.market_phase(now)
    if phase != st.session_state.get("phase_at_start"):      # e.g. 9:15 or 3:30 passed: reset the schedule
        st.rerun()
    phase_msg = schedule_message(now, phase, phase_msg)
    header(now)
    html('<span class="v1pill" style="background:var(--bg-b);color:var(--b)">%s</span>'
         '<span class="v1pill" style="border:1px solid var(--line)">%s capital</span>'
         '<span class="v1pill" style="border:1px solid var(--line)">Max loss %s</span>'
         '<span class="v1pill" style="border:1px solid var(--line)">&#8377;%g&ndash;%g</span>'
         % ("Practice mode" if mode == "paper" else "Real money", engine.rupees(capital),
            engine.rupees(max_loss), min_price, max_price))
    nifty = chart(engine.NIFTY, key) if phase in ("open", "forming", "after") else None
    n_today = [b["c"] for b in engine.day_bars(nifty or {}, day, now)]
    done, why, counts = journal.guard(data, mode, day, CFG)
    html(ui.day_strip(counts, int(max_trades), n_today))
    if phase_msg:
        st.info(phase_msg)
    todays = [e for e in EVENTS if e.get("date") == day.isoformat()]
    for e in todays:
        st.warning("Big event today: %s%s. No new trades within %d minutes of it."
                   % (e.get("name", "event"), (" at " + e["time"]) if e.get("time") else " (no time set: be careful all day)",
                      engine.DEFAULTS["event_window_min"]))

    res = {"picks": [], "watch": [], "skipped": [], "finished": [], "scanned": 0, "checked": 0, "note": "",
           "up": 0, "down": 0, "sectors": {}}
    if phase in ("open", "after"):
        with st.spinner("Updating..."):
            res = scan_market(now, day, key, key30, nifty, data)
            data = track_signals(load_journal(), res["allpicks"], now, key)
        html(ui.vix_chip(vix(key)))
        html(ui.sector_tiles(res["sectors"]))
        html(ui.breadth_bar(res["up"], res["down"]))
    picks, watch, skipped = res["picks"], res["watch"], res["skipped"]
    scanned, checked, note = res["scanned"], res["checked"], res["note"]

    if journal.open_trades(data, mode):            # a trade was just opened: switch to focus mode
        st.rerun()
    elif phase in ("closed", "pre", "forming"):
        pass
    elif done:
        html(ui.done_card(why, counts))
    elif note and not scanned:
        st.error("Could not get the stock list (%s). See README: upload the list file into trader/lists/ in the "
                 "GitHub repository, or choose another list." % note)
    else:
        if phase == "open" and watch:
            prices = live(tuple(sorted(w["symbol"] for w in watch)), key30)
            ready = [h for h in (engine.heads_up(w, prices.get(w["symbol"]), now, CFG) for w in watch) if h]
            if ready:
                html('<div class="v1sec">Breaking out right now</div>')
                for h in ready:
                    html(ui.heads_up_card(h))
        html('<div class="v1sec">Today\'s top picks</div>')
        if not picks:
            st.write("No stock passes every rule right now. No signal means no trade.")
        for k, r in enumerate(picks):
            if k == 0:
                html(ui.pick_card(r))
            else:
                html(ui.pick_row(r))
                with st.expander("Details: %s" % r["symbol"]):
                    html(ui.pick_card(r))
            if phase == "open":
                st.code(ui.order_text(r["symbol"], r["side"], r["qty"], r["entry"], r["stop"], r["target"]),
                        language=None)
                if st.button("I took this trade: %s" % r["symbol"], key="took" + r["symbol"], type="primary",
                             use_container_width=True):
                    took_dialog(r)
        if watch:
            html('<div class="v1sec">Getting close</div>')
            html(ui.watch_rows(watch))
        if res["finished"]:
            with st.expander("Already finished today: %d breakouts" % len(res["finished"])):
                html(ui.finished_rows(res["finished"]))
        with st.expander("Skipped right now: %d stocks" % len(skipped)):
            html(ui.skipped_rows(skipped) or '<span class="v1mut">None yet.</span>')
        st.caption("Scanned %d stocks priced \u20b9%g\u2013%g from %s; %d had a full check."
                   % (scanned, min_price, max_price, source, checked))

    results_section(data)
    html('<div class="v1mut" style="text-align:center;margin-top:12px">A pick matches rules, it is not a promise. '
         'Free Yahoo data can lag. Not financial advice.</div>')


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def bt_series(sym, kind, day):
    try:
        return backtest.fetch_intraday(sym) if kind == "5m" else backtest.fetch_daily(sym)
    except Exception:
        return None


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def bt_run(symbols, cfg_key, day):
    cfg = json.loads(cfg_key)
    for k in ("no_entries_before", "no_entries_after", "flat_by", "early_until", "strong_only_after"):
        if k in cfg:
            cfg[k] = datetime.time(*map(int, cfg[k].split(":")))
    charts = {s_: bt_series(s_, "5m", day) for s_ in symbols}
    dailies = {s_: bt_series(s_, "1d", day) for s_ in symbols}
    nifty = bt_series(engine.NIFTY, "5m", day)
    if not nifty:
        return None
    return backtest.run(charts, dailies, nifty, cfg)


def backtest_page():
    now = engine.now_ist()
    day = now.date()
    html('<b style="font-size:20px">&#128202; 60-day backtest</b>')
    st.caption("Replays the scanner's exact rules on the last 60 days of 5-minute data from Yahoo (its limit), "
               "with Groww charges, and compares the variants we discussed. Evidence, not a promise: no slippage "
               "beyond candle prices, today's stock list, and no news check for past days.")
    n = st.select_slider("How many stocks (most traded first)", options=[20, 40, 60, 80], value=40)
    if not st.button("Run backtest", type="primary", use_container_width=True):
        st.write("It downloads about %d charts the first time (a few minutes); results are kept for 12 hours." % (2 * n))
        return
    syms, note = symbols_for(source, typed, day.isoformat())
    if not syms:
        st.error("Could not get the stock list (%s)." % (note or "empty"))
        return
    with st.spinner("Choosing stocks..."):
        daily, _ = daily_data(tuple(syms), day.isoformat())
        ranked = []
        for s_ in syms:
            m = (daily.get(s_) or {}).get("meta") or {}
            p = m.get("regularMarketPrice")
            if p and min_price <= p <= max_price:
                ranked.append((-(p * (m.get("regularMarketVolume") or 0)), s_))
        chosen = tuple(s_ for _, s_ in sorted(ranked)[:n])
    if not chosen:
        st.error("No stocks in your price range.")
        return
    cfg = {k: (v.strftime("%H:%M") if isinstance(v, datetime.time) else v) for k, v in CFG.items()}
    with st.spinner("Downloading and replaying %d stocks x 60 days... (a few minutes the first time)" % len(chosen)):
        res = bt_run(chosen, json.dumps(cfg, sort_keys=True), day.isoformat())
    if not res:
        st.error("Yahoo did not send the Nifty data. Try again in a few minutes.")
        return
    tr = res["trades"]
    yw = backtest.summary(backtest.your_way(tr["phase1"], CFG))
    html(ui.bt_headline(yw, res["days"], res["stocks"]))
    st.markdown("**Variants compared** (all signals; *your way* applies 2 trades a day, one at a time)")
    rows = []
    for v in backtest.VARIANTS:
        a = backtest.summary(tr[v])
        y = backtest.summary(backtest.your_way(tr[v], CFG))
        rows.append({"Variant": backtest.VARIANT_NAMES[v], "Trades": a.get("trades", 0),
                     "Win %": a.get("win_rate"), "Total \u20b9": a.get("total"), "Avg \u20b9": a.get("avg"),
                     "Profit factor": a.get("profit_factor"), "Worst dip \u20b9": a.get("max_drawdown"),
                     "Your way \u20b9": y.get("total"),
                     "No retest": a.get("missed") if v == "retest" else None})
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.markdown("**Why breakouts were skipped** (Phase 1 rules)")
    html(ui.rejected_bars(res.get("rejected")))
    st.markdown("**Filters** (on Phase 1 signals: win rate and average result with and without)")
    frows = []
    for label, yes, no in backtest.filter_table(tr["phase1"]):
        frows.append({"Condition": label, "With: trades": yes[0], "With: win %": yes[1], "With: avg \u20b9": yes[2],
                      "Without: trades": no[0], "Without: win %": no[1], "Without: avg \u20b9": no[2]})
    st.dataframe(frows, use_container_width=True, hide_index=True)
    st.caption("Read it carefully: a handful of trades proves little. Look for big, consistent gaps over many "
               "trades before changing a rule.")


def results_section(data):
    html('<div class="v1sec">My results (%s)</div>' % ("practice" if mode == "paper" else "real money"))
    res = journal.results(data, mode)
    if mode == "paper":
        html(ui.readiness_card(res["ready"]))
    html(ui.results_card(res, mode))
    html(ui.signals_card(journal.signal_stats(data)))
    html(ui.lab_card(journal.lab_stats(data), journal.exit_test(data)))


_now = engine.now_ist()
st.session_state["phase_at_start"] = engine.market_phase(_now)[0]
if page_choice.startswith("Backtest"):
    backtest_page()
    st.stop()
RUN_EVERY = engine.refresh_seconds(_now) if auto else None     # Option A: 60 s before 9:15, 30 s open, else off
run_every = RUN_EVERY
fragment = (lambda f: st.fragment(run_every=run_every)(f)) if (hasattr(st, "fragment") and run_every) else (lambda f: f)
_data = load_journal()
if journal.open_trades(_data, mode):
    # Focus mode: the header, day bar and results stay still; only the trade panel refreshes.
    header(_now, clock=False)
    _phase, _msg = engine.market_phase(_now)
    _done, _why, _counts = journal.guard(_data, mode, _now.date(), CFG)
    html(ui.day_strip(_counts, int(max_trades), []))
    fragment(focus_panel)()
    results_section(_data)
else:
    fragment(page)()

# ---------------------------------------------------------------- journal backup (outside the auto-refresh)
with st.expander("Journal backup"):
    data = load_journal()
    st.download_button("Download my journal", json.dumps(data, indent=1), file_name="journal.json",
                       mime="application/json")
    up = st.file_uploader("Restore a journal file", type=["json"])
    if up is not None and st.button("Restore it"):
        try:
            doc = json.loads(up.getvalue().decode("utf-8"))
            if not isinstance(doc.get("trades"), list):
                raise ValueError
            save_journal(doc, "Restore journal")
            st.success("Journal restored.")
        except (ValueError, AttributeError):
            st.error("That file is not a journal from this app.")
