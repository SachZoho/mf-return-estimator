"""
index_data.py - Fetch Indian market index values and daily changes.
Uses yfinance batch download for speed, with individual fallback.
"""

import yfinance as yf

# Index definitions: (display_name, yfinance_ticker)
INDEXES = [
    ("NIFTY 50", "^NSEI"),
    ("SENSEX", "^BSESN"),
    ("NIFTY BANK", "^NSEBANK"),
    ("NIFTY IT", "^CNXIT"),
    ("NIFTY AUTO", "^CNXAUTO"),
    ("NIFTY FMCG", "^CNXFMCG"),
    ("NIFTY PHARMA", "^CNXPHARMA"),
    ("NIFTY METAL", "^CNXMETAL"),
    ("NIFTY ENERGY", "^CNXENERGY"),
    ("NIFTY REALTY", "^CNXREALTY"),
    ("INDIA VIX", "^INDIAVIX"),
]

# Map ticker -> display name for quick lookup
_TICKER_MAP = {t: n for n, t in INDEXES}


def fetch_index_data():
    """Fetch current value and daily change for all tracked indexes.

    Returns a list of dicts: [{name, value, change, change_pct, ticker}, ...]
    Only returns indexes that have valid data.
    """
    results = []
    tickers = [t for _, t in INDEXES]

    # Batch download for speed
    try:
        data = yf.download(tickers, period="2d", progress=False)
        close = data["Close"] if "Close" in data else None
        for _, ticker in INDEXES:
            if close is not None and ticker in close.columns:
                col = close[ticker].dropna()
                if len(col) >= 2:
                    curr = float(col.iloc[-1])
                    prev = float(col.iloc[-2])
                elif len(col) == 1:
                    curr = float(col.iloc[-1])
                    prev = curr
                else:
                    continue
                change = curr - prev
                change_pct = (change / prev) * 100 if prev != 0 else 0.0
                results.append({
                    "name": _TICKER_MAP[ticker],
                    "ticker": ticker,
                    "value": curr,
                    "change": change,
                    "change_pct": change_pct,
                    "prev_close": prev,
                })
    except Exception:
        pass

    # Fallback: fetch any missing tickers individually
    fetched_tickers = {r["ticker"] for r in results}
    for name, ticker in INDEXES:
        if ticker in fetched_tickers:
            continue
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="2d")
            if hist.empty:
                continue
            curr = float(hist["Close"].iloc[-1])
            if len(hist) >= 2:
                prev = float(hist["Close"].iloc[-2])
            else:
                prev = curr
            change = curr - prev
            change_pct = (change / prev) * 100 if prev != 0 else 0.0
            results.append({
                "name": name,
                "ticker": ticker,
                "value": curr,
                "change": change,
                "change_pct": change_pct,
                "prev_close": prev,
            })
        except Exception:
            continue

    # Preserve original order
    order = {name: i for i, (name, _) in enumerate(INDEXES)}
    results.sort(key=lambda r: order.get(r["name"], 999))
    return results
