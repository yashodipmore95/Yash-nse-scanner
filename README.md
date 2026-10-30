# NSE intraday scanner, version 1

A private website for intraday trading on NSE: it scans liquid stocks for 15-minute
opening-range breakouts, scores each one out of 10, checks safety rules, sizes the trade to
your capital and max loss with Groww's charges, and tracks the trades you tell it you took.

It never places orders and never asks for a Groww login. A pick is a chart that matched
rules, not a promise. Free Yahoo data can lag. Not financial advice.

## Files

```
streamlit_app.py          the page
engine.py                 scanning, scoring, sizing, alerts
journal.py                your trades and results
lists.py                  stock lists (F&O, Nifty indices, whole NSE)
ui.py                     the cards, rings and charts
trader-scanner/scan.py    the data reader and NSE calendar (from the India pack)
tests/test_engine.py      offline tests on made-up data
requirements.txt          streamlit>=1.37
```

## The rules it uses

- Stocks: your chosen list (F&O stocks by default), priced between your min and max (₹100–500).
- Signal: a 5-minute candle closes above the 9:15–9:30 high (BUY), or below the low (SELL, only
  with the short switch on).
- Score out of 10: breakout candle (2), buying power / volume (2), above the day's average price
  VWAP (1), stronger than Nifty (2), above its 20-day average (1), room to the target (1), market
  not falling (1). Strong buy 8–10, buy 6–7, skip under 6.
- Always skipped: results or big news in the headlines, a big opening gap, already up more than
  3%, a signal outside 9:30 AM–2:30 PM, too risky for your capital, outside your price range,
  price already moved on, hit its stop or target, or a stock you already traded today.
- Plan: stop-loss at the middle of the morning range, target 2× the risk, safety lock at 1× the
  risk (move the stop to your buy price), exit within an hour if nothing happens, and always by
  2:55 PM.
- Size: whole shares, the loss at the stop plus charges within your max loss, the cost within
  your capital.
- Day guard: after your max trades, 2 losses, or your daily loss limit, new picks pause.

## While you are in a trade (focus mode)

- After **I took this trade**, the page shows only that trade until you close it: live price,
  profit or loss, a progress bar from stop to target, a live chart since your entry, and a
  **Next** line that always says the one thing to do now.
- Safety lock: at 1× your risk in profit, move the stop-loss to your buy price.
- Trailing stop: at 1.5× your risk, move the stop-loss to lock in half a risk of profit.
- Exit now: Nifty falls sharply, no real move within an hour, or 2:55 PM.
- When it ends, tap Hit target, Hit stop-loss or Sold at another price. The "I followed my rules"
  switch (on by default) feeds your discipline score.

## What your results show

- Running total after charges, win rate, average win and loss.
- Discipline: how often you followed your rules. Slippage: your real entry versus the signal
  price (positive means you paid more than the signal).
- All signals: every BUY signal the scanner found while the page was open, taken or not, settled
  with the simple rules (stop, target, time exit, 2:55 PM) at your size. After a few weeks this
  shows whether the strategy itself works, including score 8+ versus 6–7.
- A copy box under each pick and in the trade form has the order details for Groww.

## Update your Streamlit app (you already have one)

1. Unzip this file. In your GitHub repository (`Yash-nse-scanner`), click **Add file → Upload
   files** and drag in: `streamlit_app.py`, `engine.py`, `journal.py`, `lists.py`, `ui.py`,
   `requirements.txt` and the `tests` folder. Click **Commit changes**. Existing files with the
   same name are replaced.
2. Make sure `trader-scanner/scan.py` is still there (it is from last time).
3. Streamlit rebuilds the app in a minute or two. If it shows an error, open **Manage app →
   ⋮ → Reboot app**.

## Keep your trades safe: the private journal (5 minutes, once)

The free Streamlit server forgets its own files when the app sleeps. Your trades are saved in a
second, **private** GitHub repository instead.

1. **Create the journal repository.** On GitHub: **+ → New repository**, name it
   `Yash-trading-journal`, choose **Private**, turn **Add README** on, and click
   **Create repository**.
2. **Create an access key** that can only touch that one repository. GitHub: your picture →
   **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new
   token**.
   - Name: `nse-scanner-journal`. Expiration: 1 year (set a reminder to renew it).
   - Repository access: **Only select repositories** → `Yash-trading-journal`.
   - Permissions → Repository permissions → **Contents: Read and write**.
   - Click **Generate token** and copy it (it starts with `github_pat_`). GitHub shows it once.
3. **Add it to the app's Secrets.** Streamlit: **Manage app → ⋮ → Settings → Secrets**, so the
   box has these three lines (your own values):

   ```
   APP_PASSWORD = "your-password"
   GITHUB_TOKEN = "github_pat_paste-the-key-here"
   JOURNAL_REPO = "yashodipmore95/Yash-trading-journal"
   ```

   Click **Save changes**. Keep straight quotes. Never post the key anywhere else.

Without these, the app still works, but trades last only while the page is open: use **Journal
backup → Download my journal** at the bottom of the page.

## If a stock list will not load

NSE and NSE Indices sometimes refuse cloud servers. Download the file in your browser and add it
to the repository as `trader/lists/<file name>`:

- F&O stocks: `https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv` → `trader/lists/fo_mktlots.csv`
- Nifty 200: `https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv` → `trader/lists/ind_nifty200list.csv`

(GitHub: **Add file → Create new file**, type the path as the name, paste the file's text, commit.)

## Run it on your own computer instead

```bash
pip install streamlit
streamlit run streamlit_app.py
```

Tests (no internet needed): `python3 -m unittest discover -s tests`

## Good to know

- Keep the site password-protected. Yahoo's data is for personal use, and publishing buy or sell
  calls to others can count as investment advice under SEBI's rules.
- The page refreshes every 30 seconds while it is open. Live prices update every 30 seconds;
  new candles are scanned 20 seconds after each 5-minute candle closes (9:40:20, 9:45:20 ...).
- "Get ready" cards appear when a stock's live price crosses its morning high during a candle. It
  only becomes a BUY if the candle closes above the high. The page cannot send phone
  notifications when it is closed.
- Times are IST. NSE's 2026 holidays are built into `scan.py`; add 2027's when NSE publishes them.
