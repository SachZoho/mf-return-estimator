"""
Stock data module — resolves Indian stock names to NSE tickers
and fetches current-day price changes via yfinance.

Uses NSE's official EQUITY_L.csv (2,400+ companies) for comprehensive
ticker resolution with fuzzy matching, instead of a hardcoded dictionary.
"""

import re
import time
import csv
import io
import requests
import yfinance as yf
import pandas as pd
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher
import warnings

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# NSE Company List — fetched once at startup, cached for the session
# ---------------------------------------------------------------------------

_NSE_EQUITY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

_nse_companies: Optional[List[Dict]] = None
_exact_map: Optional[Dict[str, str]] = None


# Common aliases that don't match NSE's exact naming
_ALIAS_MAP = {
    "icici bank": "ICICIBANK", "hdfc bank": "HDFCBANK", "state bank of india": "SBIN",
    "axis bank": "AXISBANK", "tvs motor company": "TVSMOTOR",
    "maruti suzuki india": "MARUTI", "maruti suzuki": "MARUTI",
    "avenue supermarts": "DMART", "larsen & toubro": "LT", "larsen and toubro": "LT",
    "mahindra & mahindra": "M&M", "mahindra and mahindra": "M&M",
    "tata consultancy services": "TCS", "bharat petroleum": "BPCL",
    "hindustan petroleum": "HINDPETRO", "oil & natural gas corporation": "ONGC",
    "oil and natural gas corporation": "ONGC", "zomato": "ETERNAL", "eternal": "ETERNAL",
    "divi's laboratories": "DIVISLAB", "divis laboratories": "DIVISLAB",
    "dr reddy's laboratories": "DRREDDY", "dr reddys laboratories": "DRREDDY",
    "m&m": "M&M", "bajaj-auto": "BAJAJ-AUTO", "bajaj auto": "BAJAJ-AUTO",
    "sona blw precision": "SONACOMS", "sona blw precision forgings": "SONACOMS",
    "sundaram-clayton": "SCLT", "sundaram clayton": "SCLT",
    "sundaram - clayton dcd": "SCLT", "samvardhana motherson": "MOTHERSON",
    "samvardhana motherson international": "MOTHERSON", "motherson sumi wiring": "MSUMI",
    "fsn e-commerce ventures": "NYKAA", "fsn e-commerce": "NYKAA", "nykaa": "NYKAA",
    "interglobe aviation": "INDIGO", "interglob aviation": "INDIGO",
    "jindal steel & power": "JINDALSTEL", "jindal steel and power": "JINDALSTEL",
    "ratnamani metals & tubes": "RATNAMANI", "ratnamani metals and tubes": "RATNAMANI",
    "ge t&d india": "GET&D", "multi commodity exchange of india": "MCEVENT",
    "multi commodity exchange": "MCEVENT", "the federal bank": "FEDERALBNK",
    "federal bank": "FEDERALBNK", "punjab national bank": "PNB",
    "bank of baroda": "BANKBARODA", "canara bank": "CANBK", "idbi bank": "IDBI",
    "rbl bank": "RBLBANK", "bandhan bank": "BANDHANBNK",
    "au small finance bank": "AUBANK", "indusind bank": "INDUSINDBK",
    "yes bank": "YESBANK", "kotak mahindra bank": "KOTAKBANK",
    "tata steel": "TATASTEEL", "tata motors": "TATAMOTORS", "tata power": "TATAPOWER",
    "tata consumer products": "TATACONSUM", "tata chemicals": "TATACHEM",
    "tata investment corporation": "TATAINVEST", "tata technologies": "TATATECH",
    "tata elxsi": "TATAELXSI", "reliance industries": "RELIANCE",
    "hindustan unilever": "HINDUNILVR", "hindustan zinc": "HINDZINC",
    "coal india": "COALINDIA", "indian oil corporation": "IOC",
    "gail india": "GAIL", "ntpc": "NTPC", "power grid corporation": "POWERGRID",
    "adani green energy": "ADANIGREEN", "adani power": "ADANIPOWER",
    "adani enterprises": "ADANIENT", "adani total gas": "ATGL",
    "adani wilmar": "AWL", "varun beverages": "VBL",
    "godrej consumer products": "GODREJCP", "godrej properties": "GODREJPROP",
    "dabur india": "DABUR", "nestle india": "NESTLEIND", "itc": "ITC",
    "wipro": "WIPRO", "infosys": "INFY", "tech mahindra": "TECHM",
    "hcl technologies": "HCLTECH", "ltimindtree": "LTIM", "lti mindtree": "LTIM",
    "mphasis": "MPHASIS", "coforge": "COFORGE",
    "persistent systems": "PERSISTENT", "bharti airtel": "BHARTIARTL",
    "sun pharmaceutical": "SUNPHARMA", "sun pharma": "SUNPHARMA",
    "cipla": "CIPLA", "apollo hospitals": "APOLLOHOSP",
    "max healthcare": "MAXHEALTH", "max financial services": "MFSL",
    "sbi life insurance": "SBILIFE", "hdfc life insurance": "HDFCLIFE",
    "hdfc asset management": "HDFCAMC",
    "icici prudential life insurance": "ICICIPRULI",
    "icici lombard": "ICICIGI",
    "life insurance corporation of india": "LICI", "lic of india": "LICI",
    "bajaj finance": "BAJFINANCE", "bajaj finserv": "BAJAJFINSV",
    "bajaj holdings & investment": "BAJAJHLDNG",
    "bajaj holdings and investment": "BAJAJHLDNG",
    "shriram finance": "SHRIRAMFIN", "muthoot finance": "MUTHOOTFIN",
    "cholamandalam investment & finance": "CHOLAFIN",
    "cholamandalam investment and finance": "CHOLAFIN",
    "pb fintech": "POLICYBZR", "360 one wam": "360ONE",
    "iifl wealth management": "IIFLWAM",
    "prudent corporate advisory services": "PRUDENT",
    "ultratech cement": "ULTRACEMCO", "shree cement": "SHREECEM",
    "grasim industries": "GRASIM", "ambuja cements": "AMBUJACEM",
    "jsw steel": "JSWSTEEL", "hindalco industries": "HINDALCO",
    "hindalco": "HINDALCO", "vedanta": "VEDL", "vedanta ltd": "VEDL",
    "national aluminium": "NATIONALUM", "apar industries": "APARIND",
    "pi industries": "PIIND", "upl": "UPL", "srf": "SRF",
    "century plyboards": "CENTURYPLY", "greenpanel industries": "GREENPANEL",
    "asian paints": "ASIANPAINT", "berger paints": "BERGEPAINT",
    "pidilite industries": "PIDILITIND", "deepak nitrite": "DEEPAKNTR",
    "aarti industries": "AARTIIND", "coromandel international": "COROMANDEL",
    "dlf": "DLF", "oberoi realty": "OBEROIRLTY", "prestige estates": "PRESTIGE",
    "phoenix mills": "PHOENIXLTD", "trent": "TRENT",
    "britannia industries": "BRITANNIA", "radico khaitan": "RADICO",
    "united spirits": "UNITDSPR", "eicher motors": "EICHERMOT",
    "bajaj auto": "BAJAJ-AUTO", "hero motocorp": "HEROMOTOCO",
    "ashok leyland": "ASHOKLEY", "bosch": "BOSCHLTD",
    "endurance technologies": "ENDURANCE", "marico": "MARICO",
    "titan company": "TITAN", "titan": "TITAN",
    "blue star": "BLUESTARCO", "siemens": "SIEMENS", "abb india": "ABB",
    "cummins india": "CUMMINSIND",
    "irb infrastructure developers": "IRB", "rail vikas nigam": "RVNL",
    "irfc": "IRFC", "ircon international": "IRCON", "hudco": "HUDCO",
    "rec": "RECLTD", "power finance corporation": "PFC",
    "engineers india": "ENGINERSIN", "rites": "RITES",
    "idea cellular": "IDEA", "vodafone idea": "IDEA",
    "zee entertainment": "ZEEL", "sun tv network": "SUNTV",
    "tips music": "TIPSMUSIC", "pvr inox": "PVRINOX",
    "chalet hotels": "CHALET", "indraprastha gas": "IGL",
    "mahanagar gas": "MGL", "gujarat gas": "GUJGASLTD",
    "itd cementation india": "ITDCEM", "tejas networks": "TEJAS",
    "aditya birla fashion": "ABFRL", "aditya birla sun life amc": "ABSLAMC",
    "aditya birla real estate": "ABREL", "utiamc": "UTIAMC",
    "shriram asset management": "SHRIRAMAMC",
    "brainbees solutions": "FIRSTCRY", "firstcry": "FIRSTCRY",
    "smartworks": "SMARTWORKS", "force motors": "FORCEMOTORS",
    "rolex rings": "ROLEXRINGS", "pearl global industries": "PGIL",
    "safari industries": "SAFARI", "sai silks": "KALAMANDIR",
    "ethos": "ETHOSLTD", "redtape": "REDTAPE",
    "lenskart solutions": "LENSKART", "crizac": "CRIZAC",
    "kaynes technology": "KAYNES", "azad engineering": "AZAD",
    "pg electroplast": "PGEL", "shadowfax technologies": "SHADOWFAX",
    "travel food services": "TFS", "neuland laboratories": "NEULANDLAB",
    "vijaya diagnostic centre": "VIJAYA", "syngene international": "SYNGENE",
    "netweb technologies": "NETWEB", "ce info systems": "CEINFO",
    "sagility": "SAGILITY", "tbo tek": "TBOTEK",
    "physicswallah": "PHYSICSWALLAH", "omnitech engineering": "OMNITECH",
    "sedemac mechatronics": "SEDEMAC",
    "sharda motor industries": "SHARDAMOTR", "tvs holdings": "TVSHOLDINGS",
    "motherson sumi wiring india": "MSUMI",
    "international gemmological institute": "IGIL",
    "lg electronics india": "LGEL", "indiamart intermesh": "INDIAMART",
    "cartrade tech": "CARTRADE", "delhivery": "DELHIVERY",
    "paytm": "PAYTM", "one 97 communications": "PAYTM",
    "sonata software": "SONATSOFTW", "aegon life": "AEGON",
    "anglo eastern": "ANGLOEAST",
}


def _normalize(name: str) -> str:
    """Normalize a company name for lookup."""
    name = name.lower().strip()
    for suffix in ["ltd.", "ltd", "limited", "co.", "co", "company", "corporation", "corp", "pvt.", "pvt"]:
        name = name.replace(suffix, "")
    name = re.sub(r'[^\w\s&-]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _load_nse_companies():
    """Fetch NSE's complete equity list and build lookup maps. Cached per session."""
    global _nse_companies, _exact_map
    if _nse_companies is not None and _exact_map is not None:
        return

    _nse_companies = []
    _exact_map = {}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/csv,application/csv",
    }

    try:
        resp = requests.get(_NSE_EQUITY_URL, headers=headers, timeout=15)
        if resp.status_code == 200:
            reader = csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                symbol = row.get("SYMBOL", "").strip()
                name = row.get("NAME OF COMPANY", "").strip()
                if symbol and name:
                    norm = _normalize(name)
                    _nse_companies.append({"symbol": symbol, "name": name, "norm_name": norm})
                    _exact_map[norm] = symbol
                    if norm.startswith("the "):
                        _exact_map[norm[4:]] = symbol
    except Exception:
        pass


def resolve_ticker(company_name: str) -> Optional[str]:
    """
    Resolve an Indian company name to a Yahoo Finance (.NS) ticker.
    Uses NSE's complete company list (2,400+) with fuzzy matching.
    Returns the ticker (e.g. 'TVSMOTOR.NS') or None if not found.
    """
    norm = _normalize(company_name)

    # 1. Try alias map
    if norm in _ALIAS_MAP:
        return f"{_ALIAS_MAP[norm]}.NS"

    lower = company_name.lower().strip()
    if lower in _ALIAS_MAP:
        return f"{_ALIAS_MAP[lower]}.NS"

    # 2. Load NSE companies (cached after first call)
    _load_nse_companies()

    # 3. Try exact match against NSE company names
    if norm in _exact_map:
        return f"{_exact_map[norm]}.NS"

    if norm.startswith("the "):
        if norm[4:] in _exact_map:
            return f"{_exact_map[norm[4:]]}.NS"

    # 4. Fuzzy match against all NSE company names
    if _nse_companies:
        best_score = 0.0
        best_symbol = None

        for c in _nse_companies:
            score = SequenceMatcher(None, norm, c["norm_name"]).ratio()
            if score > best_score:
                best_score = score
                best_symbol = c["symbol"]

        if best_score >= 0.72:
            return f"{best_symbol}.NS"

    # 5. Yahoo Finance search API as last resort
    ticker = _yahoo_search(company_name)
    if ticker:
        return ticker

    return None


def _yahoo_search(company_name: str) -> Optional[str]:
    """Use Yahoo Finance search API to resolve a ticker."""
    try:
        resp = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": f"{company_name} NSE India", "quotesCount": 5, "newsCount": 0},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        data = resp.json()
        quotes = data.get("quotes", [])
        ns_quotes = [q for q in quotes if q.get("symbol", "").endswith(".NS")]
        if ns_quotes:
            return ns_quotes[0]["symbol"]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Price Change Fetcher
# ---------------------------------------------------------------------------

def fetch_price_changes(tickers: List[str]) -> Dict[str, Dict]:
    """
    Fetch current-day price change for a list of tickers using yfinance.
    Returns dict: {ticker: {"prev_close": float, "curr_price": float, "change_pct": float}}
    """
    if not tickers:
        return {}

    results = {}
    unique_tickers = list(set(tickers))

    batch_size = 10
    for i in range(0, len(unique_tickers), batch_size):
        batch = unique_tickers[i:i + batch_size]
        batch_results = _fetch_batch(batch)
        results.update(batch_results)
        if i + batch_size < len(unique_tickers):
            time.sleep(0.5)

    missing = [t for t in unique_tickers if t not in results]
    for ticker in missing:
        result = _fetch_single(ticker)
        if result:
            results[ticker] = result
        time.sleep(0.2)

    return results


def _fetch_batch(tickers: List[str]) -> Dict[str, Dict]:
    """Fetch price data for a batch of tickers via yf.download."""
    results = {}
    try:
        data = yf.download(tickers, period="5d", progress=False, group_by="ticker")
        if len(tickers) == 1:
            ticker = tickers[0]
            result = _extract_single(data, ticker)
            if result:
                results[ticker] = result
        else:
            for ticker in tickers:
                try:
                    if ticker in data.columns.get_level_values(0):
                        ticker_data = data[ticker].dropna(how="all")
                        result = _extract_single(ticker_data, ticker)
                        if result:
                            results[ticker] = result
                except Exception:
                    pass
    except Exception:
        pass
    return results


def _extract_single(df, ticker: str) -> Optional[Dict]:
    """Extract price change info from a DataFrame for a single ticker."""
    try:
        if df is None or df.empty:
            return None
        close = df["Close"].dropna()
        if len(close) < 2:
            return None
        prev_close = float(close.iloc[-2])
        curr_price = float(close.iloc[-1])
        if prev_close == 0:
            return None
        change_pct = ((curr_price - prev_close) / prev_close) * 100
        return {"prev_close": prev_close, "curr_price": curr_price, "change_pct": change_pct}
    except Exception:
        return None


def _fetch_single(ticker: str) -> Optional[Dict]:
    """Fetch price data for a single ticker (fallback)."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")
        return _extract_single(hist, ticker)
    except Exception:
        return None
