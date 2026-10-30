"""NSE Chart Scanner, online. A small Streamlit page around trader-scanner/scan.py.

Run on your computer:   pip install streamlit  &&  streamlit run streamlit_app.py
Host it for free:       Streamlit Community Cloud (see README.md)

It only scans charts. It never places, sizes or checks an order, and a hit is a
chart that matched a rule, not a stock to buy. Not financial advice.
"""

import datetime
import json
import os
import subprocess
import sys

import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
SCAN = os.path.join(HERE, "trader-scanner", "scan.py")
UNIVERSE = os.path.join(HERE, "trader", "universe.txt")
EQUITY_L = os.path.join(HERE, "trader", "EQUITY_L.csv")
BUILT = os.path.join(HERE, "trader", ".universe-built.txt")
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

SETUP_WORDS = {
    "orb": "Opening-range breakout",
    "breakout_20d": "20-day closing high",
    "bull_flag": "Bull flag",
    "reclaim_ma20": "Reclaimed 20-day average",
    "oversold": "Oversold (RSI under 30)",
    "oversold_bounce": "Oversold bounce",
}

st.set_page_config(page_title="NSE Chart Scanner", page_icon="\U0001F4C8", layout="wide")


# ---------------------------------------------------------------- optional password

def secret(name):
    try:
        return st.secrets.get(name)
    except Exception:  # no secrets file: no password
        return None


def password_ok():
    pw = secret("APP_PASSWORD")
    if not pw:
        return True
    if st.session_state.get("pw_ok"):
        return True
    typed = st.text_input("Password", type="password")
    if typed and typed == pw:
        st.session_state["pw_ok"] = True
        st.rerun()
    elif typed:
        st.error("Wrong password.")
    return False


# ---------------------------------------------------------------- running the scanner

def run_scan(args):
    """Run scan.py with --json and return (doc or None, error text)."""
    cmd = [sys.executable, SCAN] + args + ["--json", "--no-write"]
    try:
        p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None, "The scan took longer than 10 minutes and was stopped. Try a smaller list."
    out = (p.stdout or "").strip()
    if out.startswith("{"):
        try:
            return json.loads(out), (p.stderr or "").strip()
        except ValueError:
            pass
    return None, (p.stderr or out or "The scanner stopped without saying why.").strip()


@st.cache_data(ttl=240, show_spinner=False)
def cached_scan(args_tuple, minute_key):
    """Same request in the same few minutes: reuse the answer instead of asking Yahoo again."""
    return run_scan(list(args_tuple))


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def build_universe(source_mtime):
    """Turn NSE's EQUITY_L.csv into the scanner's stock list: the file in the repository if it is
    there, else a download from NSE (which often refuses cloud servers). Returns (path or None, note)."""
    args = [sys.executable, SCAN, "universe", "--out", BUILT]
    if os.path.exists(EQUITY_L):
        args += ["--offline", EQUITY_L]
    try:
        p = subprocess.run(args, cwd=HERE, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None, "NSE took too long to answer."
    if p.returncode == 0 and os.path.exists(BUILT):
        return BUILT, (p.stdout or "").strip().splitlines()[0] if p.stdout else ""
    return None, (p.stderr or p.stdout or "").strip()


def universe_path():
    """trader/universe.txt if you uploaded it, else one built from EQUITY_L.csv or from NSE."""
    if os.path.exists(UNIVERSE):
        return UNIVERSE, ""
    mtime = os.path.getmtime(EQUITY_L) if os.path.exists(EQUITY_L) else datetime.date.today().isoformat()
    return build_universe(mtime)


def universe_count(path):
    if not path or not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as fh:
        return sum(1 for ln in fh if ln.strip())


def rupees(x):
    try:
        return "\u20b9{:,.2f}".format(float(x))
    except (TypeError, ValueError):
        return ""


def hits_table(doc):
    rows = []
    for h in doc.get("hits", []):
        row = {"Symbol": h.get("symbol"),
               "Setup": ", ".join(SETUP_WORDS.get(s, s) for s in h.get("setups", [])),
               "Price": rupees(h.get("price"))}
        if doc.get("mode") == "orb":
            row.update({"Time (IST)": h.get("at"), "Range high": rupees(h.get("or_high")),
                        "Range low": rupees(h.get("or_low")), "% over high": h.get("pct_over")})
        else:
            row.update({"RSI 14": h.get("rsi"), "Volume": h.get("volume"), "Close date": h.get("close_date")})
        rows.append(row)
    return rows


# ---------------------------------------------------------------- the page

st.title("\U0001F4C8 NSE Chart Scanner")
st.caption("Free Yahoo Finance data (unofficial, can lag), 5-minute and daily bars, times in IST. "
           "A scan is a list of charts that match a rule, not a list of stocks to buy. Not financial advice.")

if not password_ok():
    st.stop()

now_ist = datetime.datetime.now(IST)
st.write("It is **%s IST**." % now_ist.strftime("%a %d %b %Y, %I:%M %p"))

with st.sidebar:
    st.header("Scan")
    mode = st.radio("What to scan", ["Opening-range breakouts (after 9:35 AM)", "Daily setups (before 9:15 AM or after 3:30 PM)"])
    is_orb = mode.startswith("Opening")

    uni_path, uni_note = universe_path()
    n_uni = universe_count(uni_path)
    source_opts = ["My symbols (type them)"]
    if n_uni:
        source_opts.insert(0, "Whole stock list (%d NSE stocks)" % n_uni)
    source = st.radio("Which stocks", source_opts)
    symbols = ""
    limit = 0
    if source.startswith("My symbols"):
        symbols = st.text_area("Type any NSE symbols, comma separated (the ones shown are only an example)",
                               "RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, "
                               "ITC, LT, AXISBANK, BHARTIARTL, M&M, TATASTEEL")
    else:
        limit = st.number_input("Scan only the first N (0 = all; the whole list takes a few minutes)",
                                min_value=0, value=0, step=100)

    min_price = st.number_input("Minimum price (\u20b9)", min_value=0.0, value=50.0, step=10.0)
    if is_orb:
        or_minutes = st.selectbox("Opening range (minutes)", [15, 30, 5, 10, 60], index=0)
        at = st.text_input("Cut the clock at (HH:MM IST, empty = now)", "")
    else:
        min_volume = st.number_input("Minimum volume (shares)", min_value=0, value=500000, step=100000)
    go = st.button("Run scan", type="primary", use_container_width=True)

if not n_uni:
    st.info("No NSE stock list yet (NSE refused this server), so you can scan symbols you type. To scan all of "
            "NSE: download EQUITY_L.csv from nsearchives.nseindia.com/content/equities/EQUITY_L.csv in your "
            "browser and upload it into a `trader` folder in this app's GitHub repository. No Python needed.")
    if uni_note:
        with st.expander("Why"):
            st.code(uni_note)

if go:
    args = ["orb" if is_orb else "daily", "--min-price", str(min_price)]
    if source.startswith("My symbols"):
        syms = ",".join(s.strip().upper() for s in symbols.replace("\n", ",").split(",") if s.strip())
        if not syms:
            st.warning("Type at least one symbol.")
            st.stop()
        args += ["--symbols", syms]
    else:
        args += ["--universe", uni_path]
        if limit:
            args += ["--limit", str(int(limit))]
    if is_orb:
        args += ["--or-minutes", str(or_minutes)]
        if at.strip():
            args += ["--at", at.strip()]
    else:
        args += ["--min-volume", str(int(min_volume))]
    minute_key = now_ist.strftime("%Y%m%d%H") + str(now_ist.minute // 4)
    with st.spinner("Scanning... a big list can take a few minutes."):
        doc, err = cached_scan(tuple(args), minute_key)
    if doc is None:
        st.error(err.splitlines()[-1] if err else "The scan could not run.")
    else:
        c = doc.get("counts", {})
        cols = st.columns(4)
        cols[0].metric("Stocks asked for", doc.get("universe", 0))
        cols[1].metric("Charts usable", doc.get("scanned", 0))
        cols[2].metric("Failed / no data", doc.get("failed", 0))
        cols[3].metric("Matched a rule", len(doc.get("hits", [])))
        st.write("Data as of **%s**." % doc.get("as_of", ""))
        if doc.get("unconfirmed"):
            st.warning("Partial: %d candidates were not checked against real highs and lows." % doc["unconfirmed"])
        rows = hits_table(doc)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
            st.download_button("Download watchlist.json (for /trader-news and /trader-entry)",
                               json.dumps(doc, indent=2), file_name="watchlist.json", mime="application/json")
        else:
            st.write("Nothing matched the rule.")
        if err:
            with st.expander("Notes from the scanner"):
                st.code(err)

st.divider()
st.caption("Next steps happen on your own device, not here: check the news, time the entry, set the stop and "
           "size the trade with the day-trader-skill-india pack. This page never places orders and never "
           "stores broker logins.")
