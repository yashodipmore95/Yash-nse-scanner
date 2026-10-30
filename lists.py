"""Stock lists for the scanner: NSE Indices constituents, NSE's F&O list, NSE's equity list."""
import csv
import io
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCAN = os.path.join(HERE, "trader-scanner", "scan.py")
UNIVERSE = os.path.join(HERE, "trader", "universe.txt")
EQUITY_L = os.path.join(HERE, "trader", "EQUITY_L.csv")
BUILT = os.path.join(HERE, "trader", ".universe-built.txt")
LISTS = os.path.join(HERE, "trader", "lists")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")

PRESETS = {
    "F&O stocks (best for intraday)": "fo_mktlots.csv",
    "Nifty 200": "ind_nifty200list.csv",
    "Nifty 500": "ind_nifty500list.csv",
    "Nifty 100": "ind_nifty100list.csv",
    "Nifty 50": "ind_nifty50list.csv",
    "Nifty Midcap 100": "ind_niftymidcap100list.csv",
}
INDEX_URLS = ("https://www.niftyindices.com/IndexConstituent/%s",
              "https://nsearchives.nseindia.com/content/indices/%s")
FNO_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
INDEX_NAMES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"}


def parse_list(text):
    """A constituents CSV (Symbol, Industry columns) or NSE's fo_mktlots.csv -> [(symbol, industry)]."""
    text = (text or "").lstrip("\ufeff")
    if not text.strip() or text.lstrip().startswith("<"):
        return []
    rows = list(csv.reader(io.StringIO(text)))
    head_i = sym_i = ind_i = None
    for i, r in enumerate(rows[:5]):
        cells = [c.strip().upper() for c in r]
        if "SYMBOL" in cells:
            head_i, sym_i = i, cells.index("SYMBOL")
            ind_i = cells.index("INDUSTRY") if "INDUSTRY" in cells else None
            break
    if head_i is None:
        return []
    out, seen = [], set()
    for r in rows[head_i + 1:]:
        if len(r) <= sym_i:
            continue
        sym = r[sym_i].strip().upper()
        if not sym or sym == "SYMBOL" or sym in INDEX_NAMES or sym in seen:
            continue
        seen.add(sym)
        out.append((sym, r[ind_i].strip() if ind_i is not None and len(r) > ind_i else ""))
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*",
                                               "Referer": "https://www.nseindia.com/"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8-sig", "replace")


def load_preset(fname):
    """(rows, note): trader/lists/<fname> if it is in the repository, else a download."""
    local = os.path.join(LISTS, fname)
    if os.path.exists(local):
        with open(local, encoding="utf-8-sig", errors="replace") as fh:
            rows = parse_list(fh.read())
        return rows, "" if rows else "%s in the repository has no Symbol column." % fname
    urls = [FNO_URL] if fname == "fo_mktlots.csv" else [u % fname for u in INDEX_URLS]
    last = ""
    for url in urls:
        try:
            rows = parse_list(fetch(url))
            if rows:
                return rows, ""
            last = "%s did not send a stock list" % url.split("/")[2]
        except Exception as e:  # blocked, offline, changed
            last = "%s: %s" % (url.split("/")[2], e)
    return [], last


def universe():
    """(symbols, note): trader/universe.txt, else built from trader/EQUITY_L.csv or NSE."""
    path = UNIVERSE
    note = ""
    if not os.path.exists(path):
        args = [sys.executable, SCAN, "universe", "--out", BUILT]
        if os.path.exists(EQUITY_L):
            args += ["--offline", EQUITY_L]
        try:
            p = subprocess.run(args, cwd=HERE, capture_output=True, text=True, timeout=120)
            note = (p.stderr or "").strip()
        except subprocess.TimeoutExpired:
            note = "NSE took too long to answer."
        path = BUILT
    if not os.path.exists(path):
        return [], note
    with open(path, encoding="utf-8") as fh:
        return [ln.split("|", 1)[0].strip() for ln in fh if ln.strip()], ""
