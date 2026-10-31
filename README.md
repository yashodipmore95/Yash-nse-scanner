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

## The home page, top to bottom

1. Header: refresh badge (60 s before 9:15, 30 s in market hours, off otherwise).
2. Top 5 to watch: the best five right now with rating rings (blue = setup rating before the
   breakout, green = signal score after it), with ▲ for a stock that moved up and NEW for a newcomer.
   Before 9:30 it is a pre-market top 5 rated on daily closes.
3. Market mood: one needle from India VIX, breadth and Nifty, with the sectors as a colour strip.
4. ⚡ Get ready: watchlist stocks whose live price is past the buy price but whose candle has not
   closed. A Now → Buy → Target bar (green below the buy price; amber, orange then red above it),
   a countdown to the candle close, icon checks, and "I took this trade (early)" (saved with the tag
   Early entry). The best one first, at most two backups.
5. 🟢 Picks: confirmed signals, freshest first. Fresh: at most 0.2x the risk past the buy price and
   under 15 minutes old. Late: reward:risk at the live price still 1.2 : 1 or better and under 30
   minutes old (shares and reward recalculated). Missed: moved to Skipped, don't chase. Each fresh
   card has a price ladder, icon checks, a risk vs reward row (lose / win / ratio, wins needed to break
   even, share of capital, backtest win rate for that score once you have run the backtest), a copy box
   and "I took this trade".
6. 👁 Watchlist: stocks within 2% below their buy price that pass every advance check, by setup rating
   (pinned first). Tap Details to open one (one at a time): countdown, bar, checks, plan, and the two
   ways to buy (A wait for the close, B an advance stop-limit order that buys on touch).
7. Folded lists: Finished today and Skipped right now.
8. Bottom: icon legend, status messages, disclaimer.

Setup rating (0-10, before the breakout): with the daily trend 2, 20-day average rising 1, in play so
far 2 (1.5x) / 1 (1.2x), stronger than Nifty 1, sector moving the same way 1, range size okay 1, under
half the ATR used 1, NR7 or narrow CPR 1. It ranks setups; it is not a win probability.

## My progress page

Side panel → Page → My progress: the four readiness rings, running total with the worst dip shaded,
a 5-week calendar, a lose-small-win-big chart in R, win % by signal score and by entry time, how
trades ended, mistakes and what they cost, charges vs profit, your buy price vs the signal, early vs
confirmed entries, signals you took vs skipped, then all signals, the filter lab and the exit test.

## The rules it uses

- Stocks: your chosen list (F&O stocks by default), priced between your min and max (₹100–500).
- Signal: a 5-minute candle closes above the 9:15–9:30 high (BUY), or below the low (SELL, only
  with the short switch on).
- Score out of 10 (13 points scaled to 10): breakout candle (2), buying power on the breakout (2),
  in play: today's volume at least 1.3× / 2× its usual by this time (1 / 2), above the day's
  average price VWAP (1), stronger than Nifty (2), above its 20-day average (1), room to the target
  (1), market not falling (1), breakout before 11 AM (1). Strong buy 8–10, buy 6–7, skip under 6.
  After 1 PM only 8+ counts.
- Range size: the 9:15–9:30 range must be 0.25× to 1.2× the stock's normal daily move (14-day
  ATR); a range outside that is skipped.
- Phase 1 must-pass rules (any one failing means SKIP, whatever the score):
  - Volume: the breakout candle at least 1.5x the same 5-minute slot's volume on recent days.
  - Firm candle: body at least half the candle, close in its top third (bottom third for shorts).
  - Room left: today's range has used under 70% of the 14-day ATR (falls back to "up more than 3%"
    when the ATR is unknown).
  - With the daily trend: a BUY only above the 20-day average, a SELL only below it.
  - Worth the charges: Groww charges under 25% of the gain at the target.
  - Big events: no new signals within 30 minutes of an event in `trader/events.json`.
- VWAP must pass: a BUY's breakout candle must close above the day's average price (VWAP), a SELL's
  below it. Otherwise the stock is skipped, whatever its score.
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

- While a trade is open, only the trade panel refreshes (every 30 seconds); the rest of the page
  stays still and the market scan pauses until you close the trade.
- After **I took this trade**, the page shows only that trade until you close it: live price,
  profit or loss, a progress bar from stop to target, a live chart since your entry, and a
  **Next** line that always says the one thing to do now.
- Safety lock: at 1× your risk in profit, move the stop-loss to your buy price.
- Trailing stop: at 1.5× your risk, move the stop-loss to lock in half a risk of profit.
- Exit now: Nifty falls sharply, no real move within an hour, or 2:55 PM.
- When it ends, tap Hit target, Hit stop-loss or Sold at another price. The "I followed my rules"
  switch (on by default) feeds your discipline score.

## Big-event calendar

Edit `trader/events.json` in the repository (GitHub: open the file, pencil icon, commit). Example:

```json
[
  {"date": "2026-12-04", "time": "10:00", "name": "RBI policy"},
  {"date": "2027-02-01", "name": "Union Budget"}
]
```

An event with a time blocks new signals 30 minutes before and after it; one without a time shows a
warning all day. Check the dates on the RBI and Government websites: the app does not invent them.

## Risk per trade

Practice mode starts at ₹75 per trade, Real money at ₹50 (1% of ₹5,000). Move up only after your
results stay positive after charges.

## 60-day backtest (side panel: Page → Backtest)

Replays the scanner's exact rules on the last 60 days of 5-minute data (Yahoo's limit) for your
most-traded stocks in range, with Groww charges, managing every trade the way the app does. It shows:
the Phase 1 result "your way" (2 trades a day, one at a time) with a running-total line; a table of
variants (buy on touch with an advance order, old rules, retest entry, 30-minute range, stop below the breakout candle, half at 1.5x with a
3x trail, VWAP exit, VWAP trail); why breakouts were skipped; and filters with and without (RSI above
60, MACD expanding, daily ADX above 20, and the filter-lab fields). The first run downloads about two
charts per stock and takes a few minutes; results are kept for 12 hours. Limits: no slippage beyond
candle prices, today's stock list, no news check for past days. A handful of trades proves little.

## Opening the page late

Breakouts that already finished today appear under **Already finished today**: each with its
breakout time, its score at that moment, whether the scanner would have taken it, and whether it
hit the target or the stop (whichever came first). Every breakout that was a valid signal at its
own time is recorded in the signal tracker and the filter lab, even if the page was opened later.
**Skipped right now** lists only stocks that fail a rule at the moment.

## Market view

- Sector tiles: Bank, IT, Auto, Pharma, Metal, FMCG, Energy and Realty indices, green or red by
  today's move (a tile Yahoo has no data for is hidden). A pick card shows "Sector strong" when the
  stock's sector (from the Nifty 500 list's industry; financial services use the Bank index) is
  moving its way.
- Market breadth: how many of the scanned stocks are up versus down today.
- India VIX: the market's fear gauge with a rough guide (calm under 13, normal 13 to 18, high above
  18: wider swings, so consider a smaller size or fewer trades). A guide, not a rule.
- Refresh: once a minute before 9:15 AM on a trading day (so it starts by itself), every 30
  seconds from 9:15 AM to 3:30 PM, off after the close and on weekends and NSE holidays. The badge
  at the top shows which.

## What your results show

- Ready for real money? (practice mode): 50 practice trades, a positive total after charges, a win
  rate of 50% or more, and your rules followed 90%+ of the time.
- When you close a trade, one tap says how it went: Followed plan, Entered late, Moved stop-loss,
  Exited early, Skipped stop-loss or Other mistake. Your results show your most common mistake.
- Filter lab: every signal also records whether it came before 11 AM, was in play, had a rising
  20-day average, had its sector moving the same way, came the day after an NR7 day (narrowest range
  of 7), had a narrow CPR (central pivot range under 0.25% of price, from yesterday's high, low and
  close), opened at the day's low (high for a short) and was within 5% of its 52-week high. Its win rate with and without each
  appears here, so you can see which extra rule is worth turning on.
- Exit test (in the filter lab, from the end of each day): every signal is also replayed with two
  VWAP exits, (1) exit at the close of any candle on the wrong side of VWAP, and (2) after +1× risk,
  no target and trail with VWAP (never worse than the buy price), next to the normal exits. After a
  few weeks it shows which exit made more money on your signals.

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

- Password: asked once, then remembered for 1 hour of inactivity through a login code in the
  page's address (it renews itself while the page is open). Reloading, or coming back from the
  Groww app, does not ask again within that hour. Don't share the address bar link: share the
  plain app address instead. Changing APP_PASSWORD in Secrets cancels all login codes.

- Keep the site password-protected. Yahoo's data is for personal use, and publishing buy or sell
  calls to others can count as investment advice under SEBI's rules.
- The page refreshes every 30 seconds while it is open. Live prices update every 30 seconds;
  new candles are scanned 20 seconds after each 5-minute candle closes (9:40:20, 9:45:20 ...).
- "Get ready" cards appear when a stock's live price crosses its morning high during a candle. It
  only becomes a BUY if the candle closes above the high. The page cannot send phone
  notifications when it is closed.
- Times are IST. NSE's 2026 holidays are built into `scan.py`; add 2027's when NSE publishes them.
