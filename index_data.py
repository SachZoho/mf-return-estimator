"""
index_data.py - Fetch Indian market index values and daily changes.
Uses yfinance batch download for speed, with individual fallback.
Also provides render_index_bar() to render a scrollable index bar in Streamlit.
"""

import yfinance as yf
import streamlit as st

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


def _fetch_ticker_history(ticker):
    """Fetch current close and previous close for one ticker via per-ticker history.

    Returns (curr, prev) or (None, None) if no data is available.
    """
    try:
        hist = yf.Ticker(ticker).history(period="2d")
        if hist.empty:
            return (None, None)
        curr = float(hist["Close"].iloc[-1])
        if len(hist) >= 2:
            prev = float(hist["Close"].iloc[-2])
        else:
            prev = curr
        return (curr, prev)
    except Exception:
        return (None, None)


def _fetch_ticker_info(ticker):
    """Fetch change via yfinance .info as a last-resort fallback.

    Returns (value, change, change_pct) or (None, None, None).
    """
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        return (None, None, None)
    value = info.get("regularMarketPrice")
    change = info.get("regularMarketChange")
    change_pct = info.get("regularMarketChangePercent")
    # Some fields may be None; keep whatever is present
    if value is None and change is None and change_pct is None:
        return (None, None, None)
    return (
        float(value) if value is not None else None,
        float(change) if change is not None else None,
        float(change_pct) if change_pct is not None else None,
    )


def fetch_index_data():
    """Fetch current value and daily change for all tracked indexes.

    Returns a list of dicts: [{name, value, change, change_pct, ticker}, ...]
    Only returns indexes that have valid data. Uses a batch yfinance download
    for speed, then falls back to per-ticker history() whenever the batch
    returns a zero/None change (which happens for indexes like NIFTY AUTO,
    FMCG, METAL, ENERGY that only report intraday data in batch mode), and
    finally to .info for regularMarketChange as a last resort.
    """
    results = []
    tickers = [t for _, t in INDEXES]

    # Batch download for speed
    batch_close = None
    try:
        data = yf.download(tickers, period="2d", progress=False)
        if "Close" in data:
            batch_close = data["Close"]
    except Exception:
        batch_close = None

    for name, ticker in INDEXES:
        curr = None
        prev = None
        change = None
        change_pct = None

        # 1) Try batch download for this ticker
        if batch_close is not None and ticker in batch_close.columns:
            col = batch_close[ticker].dropna()
            if len(col) >= 2:
                curr = float(col.iloc[-1])
                prev = float(col.iloc[-2])
            elif len(col) == 1:
                # Only intraday data from batch -> change unknown, force fallback
                curr = float(col.iloc[-1])
                prev = None
            # else: empty -> leave None
            if curr is not None and prev is not None:
                change = curr - prev
                change_pct = (change / prev) * 100 if prev != 0 else 0.0

        # 2) If batch gave no/zero change, fall back to per-ticker history
        if change is None or change == 0 or curr is None:
            h_curr, h_prev = _fetch_ticker_history(ticker)
            if h_curr is not None:
                if curr is None:
                    curr = h_curr
                if h_prev is not None:
                    prev = h_prev
                change = curr - prev
                change_pct = (change / prev) * 100 if prev not in (None, 0) else 0.0

        # 3) Last resort: .info for regularMarketChange / regularMarketChangePercent
        if (change is None or change == 0) and curr is None:
            i_val, i_chg, i_pct = _fetch_ticker_info(ticker)
            if i_val is not None:
                curr = i_val
            if i_chg is not None:
                change = i_chg
            if i_pct is not None:
                change_pct = i_pct
            # Derive prev close from value/change if we only got change
            if curr is not None and change is not None and prev is None:
                prev = curr - change if change is not None else curr

        # 4) Skip indexes with no usable data at all
        if curr is None:
            continue
        if change is None:
            change = 0.0
        if change_pct is None:
            change_pct = (change / prev) * 100 if prev not in (None, 0) else 0.0

        results.append({
            "name": name,
            "ticker": ticker,
            "value": curr,
            "change": change,
            "change_pct": change_pct,
            "prev_close": prev if prev is not None else curr,
        })

    # Preserve original order
    order = {name: i for i, (name, _) in enumerate(INDEXES)}
    results.sort(key=lambda r: order.get(r["name"], 999))
    return results


@st.cache_data(ttl=300)
def _cached_index_data():
    return fetch_index_data()


def render_index_bar():
    """Render a horizontal scrollable index bar at the top of the Streamlit page.
    Shows Nifty 50, Sensex, and other Indian market indexes with today's value and change.
    Positioned between the header and the main content tabs.
    """
    _lt = chr(60)
    _cid = "idx-scroll"

    # CSS for the index bar - horizontal scroll with thin scrollbar
    st.markdown(_lt + "style" + chr(62) +
        f"#{_cid} {{"
        " overflow-x: auto;"
        " overflow-y: hidden;"
        " white-space: nowrap;"
        " padding: 8px 0px;"
        " margin: 0px -1rem 0px -1rem;"
        " border-bottom: 1px solid rgba(128,128,128,0.2);"
        " -webkit-overflow-scrolling: touch;"
        " scrollbar-width: thin;"
        " }"
        f"#{_cid}::-webkit-scrollbar {{"
        " height: 4px;"
        " }"
        f"#{_cid}::-webkit-scrollbar-thumb {{"
        " background: rgba(128,128,128,0.3);"
        " border-radius: 2px;"
        " }"
        f"#{_cid} .idx-card {{"
        " display: inline-block;"
        " min-width: 130px;"
        " padding: 6px 14px;"
        " margin-right: 4px;"
        " border-radius: 8px;"
        " text-align: center;"
        " vertical-align: middle;"
        " }"
        ".idx-scroll-btn {{"
        " display: inline-block;"
        " vertical-align: middle;"
        " cursor: pointer;"
        " padding: 4px 8px;"
        " font-size: 1.2rem;"
        " }}"
        + _lt + "/style" + chr(62),
        unsafe_allow_html=True)

    idx_data = _cached_index_data()
    if not idx_data:
        return

    # Build index cards HTML using chr() to avoid tag stripping
    cards = ""
    for d in idx_data:
        val = f"{d['value']:,.2f}"
        chg = d["change"]
        pct = d["change_pct"]
        if pct >= 0:
            bg = "rgba(16,185,129,0.12)"
            tc = "#10b981"
            ar = "\u25b2"
        else:
            bg = "rgba(239,68,68,0.12)"
            tc = "#ef4444"
            ar = "\u25bc"
        cards += (
            _lt + f"div class='idx-card' style='background:{bg};'" + chr(62)
            + _lt + "div style='font-size:0.72rem;color:gray;font-weight:600;letter-spacing:0.5px;'" + chr(62) + d["name"] + _lt + "/div" + chr(62)
            + _lt + "div style='font-size:1.05rem;font-weight:700;'" + chr(62) + val + _lt + "/div" + chr(62)
            + _lt + f"div style='font-size:0.75rem;color:{tc};font-weight:600;'" + chr(62) + f"{ar} {chg:+.2f} ({pct:+.2f}%)" + _lt + "/div" + chr(62)
            + _lt + "/div" + chr(62)
        )

    # Scroll buttons + container + JS for smooth scrolling
    scroll_js = (
        _lt + "script" + chr(62)
        + f"function scrollIdx(dir) {{"
        f"  var el = window.parent.document.getElementById('{_cid}');"
        f"  if (el) {{ el.scrollBy({{left: dir * 200, behavior: 'smooth'}}); }}"
        f"}}"
        + _lt + "/script" + chr(62)
    )
    full_bar = (
        _lt + "div style='display:flex;align-items:center;'" + chr(62)
        + _lt + "span class='idx-scroll-btn' onclick='scrollIdx(-1)' style='color:#888;'" + chr(62) + "\u2e2c" + _lt + "/span" + chr(62)
        + _lt + f"div id='{_cid}'" + chr(62)
        + cards
        + _lt + "/div" + chr(62)
        + _lt + "span class='idx-scroll-btn' onclick='scrollIdx(1)' style='color:#888;'" + chr(62) + "\u2e32" + _lt + "/span" + chr(62)
        + _lt + "/div" + chr(62)
        + scroll_js
    )
    st.markdown(full_bar, unsafe_allow_html=True)
    st.markdown("")
