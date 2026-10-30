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
    st.header("Settings")
    mode_label = st.radio("Mode", ["Practice (paper)", "Real money"], index=0)
    mode = "paper" if mode_label.startswith("Practice") else "real"
    capital = st.number_input("Capital (\u20b9)", min_value=500.0, value=5000.0, step=500.0)
    max_loss = st.number_input("Max loss per trade (\u20b9)", min_value=10.0, value=75.0, step=5.0)
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
    auto = st.toggle("Auto-refresh every 30 seconds", value=True)
    if st.button("Refresh now"):
        st.session_state["bump"] = st.session_state.get("bump", 0) + 1
    st.caption("Groww intraday charges are included in every rupee figure. Estimates: your contract note is "
               "the real number.")

CFG = {"capital": capital, "max_loss": max_loss, "max_trades": int(max_trades), "daily_loss": daily_loss,
       "min_price": min_price, "max_price": max_price, "shorts": shorts}


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
def other_price_dialog(trade, price_now, followed=None):
    st.write("**%s**: the price you %s at." % (trade["symbol"], "sold" if trade["side"] == "buy" else "bought back"))
    price = st.number_input("Price (\u20b9)", value=float(price_now), step=0.05, format="%.2f")
    st.caption("Result after charges: %s" % engine.rupees(engine.net(trade["side"], trade["qty"], trade["entry"],
                                                                          price), True))
    if st.button("Save", type="primary", use_container_width=True):
        close(trade, price, "other", followed)


def close(trade, price, how, followed=None):
    try:
        done = journal.close_trade(trade, price, how, engine.now_ist(), followed)
    except journal.JournalError as e:
        st.error(str(e))
        return
    save_journal(journal.replace(load_journal(), done), "Close %s" % trade["symbol"])
    st.rerun()


# ---------------------------------------------------------------- the page

def scan_market(now, day, key, key30, nifty, data):
    """Scan the chosen stocks. Returns (picks, watch, skipped, note, scanned, checked)."""
    syms, note = symbols_for(source, typed, day.isoformat())
    if not syms:
        return [], [], [], note or "empty", 0, 0   # 4th item is the note when there is no list
    daily, _ = daily_data(tuple(syms), day.isoformat())
    inrange = []
    for s_ in syms:
        m = (daily.get(s_) or {}).get("meta") or {}
        p = m.get("regularMarketPrice")
        if p and min_price <= p <= max_price:
            inrange.append((-(p * (m.get("regularMarketVolume") or 0)), s_))
    inrange = [s_ for _, s_ in sorted(inrange)][:250]
    spark, _ = spark_5m(tuple(inrange), key) if inrange else ({}, {})
    cands = set(engine.stage_one(spark, now, CFG))
    cands = [s_ for s_ in inrange if s_ in cands][:25]
    results = []
    for s_ in cands:
        series = chart(s_, key)
        if not series:
            continue
        closes = engine.closes_before(daily.get(s_) or {}, day)
        r = engine.analyse(s_, series, closes, nifty, now, CFG)
        if r and r["kind"] == "pick":
            r = engine.analyse(s_, series, closes, nifty, now, CFG, news_flag=news(s_, now.hour))
        results.append(r)
    traded = {t["symbol"] for t in journal.today(data, mode, day)}
    for r in results:
        if r and r["kind"] == "pick" and r["symbol"] in traded:
            r.update(kind="skip", reason="You already traded it today")
    picks, watch, skipped = engine.rank(results)
    allpicks = [r for r in results if r and (r["kind"] == "pick" or r.get("reason") == "You already traded it today")]
    return picks, watch, skipped, allpicks, len(inrange), len(cands)


def track_signals(data, allpicks, now, key):
    """Record every new signal and settle finished ones, saving once if anything changed."""
    changed = False
    for r in allpicks:
        if r.get("score") is not None and r.get("qty", 0) >= 1:
            data, c = journal.add_signal(data, r, CFG)
            changed = changed or c
    pending = sorted({x["symbol"] for x in data.get("signals", []) if not x.get("outcome")})[:15]
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
    followed = st.toggle("I followed my rules on this trade", value=True, key="f" + t["id"])
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
    html('<div class="v1row"><b style="font-size:20px">&#128200; NSE scanner</b><span class="v1mut">%s</span>'
         '</div>' % ("&#8635; " + now.strftime("%I:%M:%S %p").lstrip("0") if clock else ""))
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


def focus_panel():
    """Focus mode: only this panel refreshes. No market scan runs while a trade is open."""
    renew_login()
    now = engine.now_ist()
    key, key30 = keys(now)
    phase, _ = engine.market_phase(now)
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

    picks = watch = skipped = []
    scanned = checked = 0
    note = ""
    if phase in ("open", "after"):
        with st.spinner("Updating..."):
            picks, watch, skipped, allpicks, scanned, checked = scan_market(now, day, key, key30, nifty, data)
            if isinstance(allpicks, str):
                note, allpicks = allpicks, []
            data = track_signals(load_journal(), allpicks, now, key)

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
        with st.expander("Skipped today: %d stocks" % len(skipped)):
            html(ui.skipped_rows(skipped) or '<span class="v1mut">None yet.</span>')
        st.caption("Scanned %d stocks priced \u20b9%g\u2013%g from %s; %d had a full check."
                   % (scanned, min_price, max_price, source, checked))

    results_section(data)
    html('<div class="v1mut" style="text-align:center;margin-top:12px">A pick matches rules, it is not a promise. '
         'Free Yahoo data can lag. Not financial advice.</div>')


def results_section(data):
    html('<div class="v1sec">My results (%s)</div>' % ("practice" if mode == "paper" else "real money"))
    html(ui.results_card(journal.results(data, mode), mode))
    html(ui.signals_card(journal.signal_stats(data)))


run_every = 30 if auto else None
fragment = (lambda f: st.fragment(run_every=run_every)(f)) if (hasattr(st, "fragment") and run_every) else (lambda f: f)
_now = engine.now_ist()
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
