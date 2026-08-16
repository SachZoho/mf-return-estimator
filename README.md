# MF Return Estimator

Estimate today's mutual fund return based on underlying stock holdings' price changes.

## How It Works

1. **Search** for any Indian mutual fund by name
2. **Fetch holdings** — the fund's latest disclosed portfolio (from Groww)
3. **Resolve tickers** — map each stock name to an NSE ticker (Yahoo Finance)
4. **Fetch prices** — get today's price change for each stock via yfinance
5. **Compute return** — weighted sum: `Σ (holding_weight × stock_daily_change%)`

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app
streamlit run app.py
```

The app opens in your browser at `http://localhost:8501`.

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub (public)
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Sign in with GitHub, click "New app"
4. Select this repo, main file path: `app.py`
5. Click "Deploy"

Your app goes live at `https://<username>-mf-return-estimator.streamlit.app`

## Example

For ICICI Prudential FlexiCap Fund (Direct Growth):

| Holding | Weight | Today's Change | Contribution |
|---------|--------|---------------|-------------|
| TVS Motor | 9.29% | -0.81% | -0.0752% |
| ICICI Bank | 6.56% | +0.73% | +0.0479% |
| Maruti Suzuki | 6.82% | -0.51% | -0.0348% |
| ... | ... | ... | ... |
| **Estimated Return** | | | **+0.12%** |

## Data Sources

| Source | Used For | Cost |
|--------|---------|------|
| [mfapi.in](https://mfapi.in) | Fund search, NAV, metadata | Free |
| [Groww](https://groww.in/mutual-funds) | Holdings (portfolio scraping) | Free |
| [Yahoo Finance](https://finance.yahoo.com) | Stock prices (yfinance) | Free |

No API keys required.

## Limitations

- **Holdings are monthly**: AMCs disclose portfolios monthly. The fund may have traded since the last disclosure.
- **Equity only**: Debt, cash, repo, and treasury bill holdings are excluded from the return calculation.
- **Ticker coverage**: ~250+ common Indian stocks are pre-mapped. Obscure or newly listed stocks may not resolve.
- **Estimate, not actual**: This gives a directional sense of today's return. The actual NAV (published end-of-day by AMFI) may differ.

## Files

| File | Description |
|------|-------------|
| `app.py` | Streamlit web app — main UI |
| `mf_data.py` | Fund search + holdings fetching (mfapi.in + Groww scraping) |
| `stock_data.py` | Ticker resolution + live price fetching (yfinance) |
| `requirements.txt` | Python dependencies |

## Adding More Tickers

If a stock doesn't resolve, add it to `_TICKER_MAP_RAW` in `stock_data.py`:

```python
"company name": "TICKER.NS",
```

The app also falls back to Yahoo Finance's search API for unknown stocks, so many will resolve automatically.
