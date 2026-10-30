# NSE Chart Scanner, online

A one-page website around the India pack's Chart Scanner (`trader-scanner/scan.py`).
Open it in any browser, phone included, pick a scan and press **Run scan**.

It only scans. It never places orders, never asks for a Groww login, and a hit is a
chart that matched a rule, not a stock to buy. Not financial advice.

## Files

```
streamlit_app.py          the web page
requirements.txt          one line: streamlit
trader-scanner/scan.py    the scanner (same file as in the pack)
trader/universe.txt       YOU add this: the NSE stock list (see step 2)
.streamlit/config.toml    small settings
```

## Deploy free on Streamlit Community Cloud

1. **Make a GitHub repository.** Sign up at github.com, create a new repository
   (choose **Private**), and upload all the files from this folder, keeping the folders.
2. **Add the stock list.** On your computer or phone (Termux / a-Shell) run
   `python3 trader-scanner/scan.py universe` from the full pack. It writes
   `trader/universe.txt`. Upload that file into the repository's `trader/` folder.
   Redo this every week or two (new listings). NSE often blocks cloud servers, so
   build the list on your own device, not on the website.
3. **Sign in to Streamlit.** Go to share.streamlit.io, sign in with GitHub and allow
   access to your repositories.
4. **Create the app.** Pick your repository, branch `main`, main file
   `streamlit_app.py`, and click **Deploy**. After a minute or two you get a link like
   `https://your-name-nse-scanner.streamlit.app`.
5. **Keep it private.** In the app's settings (Sharing), make it private and add only
   your own email as a viewer. Optional extra lock: in Settings > Secrets add
   `APP_PASSWORD = "something-long"`, and the page asks for it.
6. **Use it.** Open the link on your phone. Before 9:15 AM IST run **Daily setups**;
   after 9:35 AM run **Opening-range breakouts**. Download `watchlist.json` if you want
   to carry on with the pack's other skills.

The free app sleeps after some hours without visitors; opening the link wakes it up in
about a minute.

## Run it on your own computer instead

```bash
pip install streamlit
streamlit run streamlit_app.py
```

## Good to know

- Yahoo Finance's data is free and unofficial: it can lag, and it may limit a busy
  server. If a scan fails, wait a few minutes and run it again, or scan fewer stocks.
- Keep the site private. Yahoo's data is for personal use, and publishing stock lists
  to the public can count as research or advice under SEBI's rules.
- Times are IST. NSE's 2026 holidays are built into `scan.py`.
