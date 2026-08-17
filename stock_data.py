"""
Stock data module — resolves Indian and foreign stock names to tickers
and fetches current-day price changes via yfinance.

Uses NSE's official EQUITY_L.csv (2,500+ companies) for Indian stock
resolution, plus a foreign-stock map for US/global stocks commonly held
by Indian mutual funds (Alphabet, Microsoft, Amazon, etc.).

Resolution pipeline:
1. Skip non-equity items (bonds, T-bills, futures, cash, derivatives)
2. Check foreign stock map (US/global stocks)
3. Check REIT map (Embassy, Brookfield, Mindspace)
4. Exact match on normalized name
5. Exact match on token set
6. Fuzzy match (SequenceMatcher + token-set Jaccard), threshold 0.60
7. yfinance search API fallback
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
_token_map: Optional[Dict[frozenset, str]] = None


# ---------------------------------------------------------------------------
# Foreign stocks commonly held by Indian mutual funds (US-listed)
# yfinance returns these without any exchange suffix
# ---------------------------------------------------------------------------

FOREIGN_STOCKS = {
    # Big tech
    "alphabet inc class a": "GOOGL",
    "alphabet inc class c": "GOOG",
    "alphabet inc": "GOOGL",
    "alphabet": "GOOGL",
    "amazon.com inc": "AMZN",
    "amazon com inc": "AMZN",
    "amazon.com": "AMZN",
    "amazon": "AMZN",
    "microsoft corp": "MSFT",
    "microsoft corporation": "MSFT",
    "microsoft": "MSFT",
    "meta platforms inc class a": "META",
    "meta platforms inc class c": "META",
    "meta platforms inc": "META",
    "meta platforms": "META",
    "meta": "META",
    "apple inc": "AAPL",
    "apple": "AAPL",
    "netflix inc": "NFLX",
    "netflix": "NFLX",
    "nvidia corp": "NVDA",
    "nvidia corporation": "NVDA",
    "nvidia": "NVDA",
    "tesla inc": "TSLA",
    "tesla": "TSLA",
    "oracle corp": "ORCL",
    "oracle corporation": "ORCL",
    "oracle": "ORCL",
    "adobe inc": "ADBE",
    "adobe": "ADBE",
    "salesforce inc": "CRM",
    "salesforce": "CRM",
    "intel corp": "INTC",
    "intel corporation": "INTC",
    "intel": "INTC",
    "cisco systems": "CSCO",
    "cisco": "CSCO",
    "qualcomm inc": "QCOM",
    "qualcomm": "QCOM",
    "broadcom inc": "AVGO",
    "broadcom": "AVGO",
    "advanced micro devices": "AMD",
    "amd": "AMD",
    "paypal holdings": "PYPL",
    "paypal": "PYPL",
    # Financial
    "berkshire hathaway": "BRK-B",
    "johnson and johnson": "JNJ",
    "jpmorgan chase": "JPM",
    "visa inc": "V",
    "visa": "V",
    "goldman sachs": "GS",
    "bank of america": "BAC",
    "wells fargo": "WFC",
    "morgan stanley": "MS",
    "hsbc holdings": "HSBC",
    "hsbc": "HSBC",
    # Consumer
    "walt disney": "DIS",
    "disney": "DIS",
    "costco wholesale": "COST",
    "costco": "COST",
    "procter and gamble": "PG",
    "coca cola": "KO",
    "coca-cola": "KO",
    "pepsi co": "PEP",
    "pepsico": "PEP",
    "mcdonald": "MCD",
    "starbucks": "SBUX",
    "nike": "NKE",
    "walmart": "WMT",
    "target": "TGT",
    "home depot": "HD",
    # Pharma / healthcare
    "johnson & johnson": "JNJ",
    "pfizer": "PFE",
    "abbott laboratories": "ABT",
    "merck": "MRK",
    "eli lilly": "LLY",
    "astrazeneca plc": "AZN",
    "novartis ag": "NVS",
    "sanofi sa": "SNY",
    "nestle sa": "NSRGY",
    "unilever plc": "UL",
    "unilever": "UL",
    # Other
    "spotify technology": "SPOT",
    "spotify": "SPOT",
    "shopify inc": "SHOP",
    "shopify": "SHOP",
    "uber technologies": "UBER",
    "uber": "UBER",
    "airbnb inc": "ABNB",
    "airbnb": "ABNB",
    "snowflake inc": "SNOW",
    "snowflake": "SNOW",
    "palantir technologies": "PLTR",
    "palantir": "PLTR",
    "crowdstrike holdings": "CRWD",
    "crowdstrike": "CRWD",
    "sap se": "SAP",
    "sap": "SAP",
    "samsung electronics": "005930.KS",
    "samsung": "005930.KS",
    "alibaba group": "BABA",
    "alibaba": "BABA",
    "tencent holdings": "0700.HK",
    "tencent": "0700.HK",
    "toyota motor": "TM",
    "toyota": "TM",
}


# ---------------------------------------------------------------------------
# Indian REITs — not in NSE EQUITY_L.csv, listed separately
# ---------------------------------------------------------------------------

REIT_MAP = {
    "embassy office parks": "EMBASSY.NS",
    "embassy office parks reit": "EMBASSY.NS",
    "embassy reit": "EMBASSY.NS",
    "brookfield india real estate": "BIRET.NS",
    "brookfield india real estate trust": "BIRET.NS",
    "brookfield india reit": "BIRET.NS",
    "brookfield reit": "BIRET.NS",
    "mindspace business parks": "MINDSPACE.NS",
    "mindspace business parks reit": "MINDSPACE.NS",
    "mindspace reit": "MINDSPACE.NS",
    "nexsquare offices": "NEXSQUARE.NS",
    "nexsquare reit": "NEXSQUARE.NS",
}


# ---------------------------------------------------------------------------
# Non-equity patterns — these should be skipped, not resolved
# ---------------------------------------------------------------------------

SKIP_PATTERNS = [
    "cash offset", "net receivables", "net payables",
    "t-bill", "tbill", "t bill",
    "cblo", "commercial paper", "certificate of deposit",
    "reverse repo", "repo",
    "parag parikh liquid",  # internal liquid fund
    "future on", "august 2026 future", "september 2026 future",
    "october 2026 future", "november 2026 future",
    "december 2026 future", "future",
    "treasury", "trs_", "trp_",
    "national bank for agriculture",
    "small industries development bank",
    "small industries dev bank",
    "export-import bank", "export import bank",
    "development bank",
    "net current assets",
    "margin money",
    "security deposits",
]


def _should_skip(name: str) -> bool:
    """Check if a holding name is non-equity (bonds, futures, cash, etc.)."""
    nl = name.lower().strip()
    for pattern in SKIP_PATTERNS:
        if pattern in nl:
            return True
    # Date patterns like (16/10/2026) indicate bonds/T-bills
    if re.search(r'\(\d{2}/\d{2}/\d{4}\)', name):
        return True
    # Named futures like "Bajaj Finance Limited August 2026 Future"
    if re.search(r'\d{4}\s+future', nl):
        return True
    return False


# ---------------------------------------------------------------------------
# Name normalization — expand abbreviations, strip suffixes, unify format
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    """Normalize a company name for matching."""
    name = name.lower().strip()
    # Remove trailing punctuation
    name = name.rstrip(".")
    # Remove parenthetical info like (18/09/2026) or (Formerly ...)
    name = re.sub(r'\([^)]*\)', '', name).strip()
    # Expand abbreviations BEFORE stripping suffixes
    name = name.replace("corp.", "corporation").replace(" corp ", " corporation ")
    name = name.replace("co.", "company").replace(" co ", " company ")
    name = name.replace("pharms", "pharmaceutical")
    name = name.replace("labs", "laboratories").replace("lab ", "laboratories ")
    name = name.replace("tech.", "technologies").replace(" tech ", " technologies ")
    name = name.replace("&", "and")
    # Remove legal entity suffixes (word-boundary aware)
    for suffix in ["ltd.", "ltd", "limited", "pvt.", "pvt", "inc.", "inc",
                   "plc", "sa", "se", "ag", "reit", "ordinary"]:
        name = re.sub(r'\b' + re.escape(suffix) + r'\b', '', name)
    # Clean up residual
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _tokenize(name: str) -> List[str]:
    """Tokenize a normalized name into sorted tokens."""
    return sorted(_normalize(name).split())


def _token_set_ratio(tokens_a: List[str], tokens_b: List[str]) -> float:
    """Jaccard-like ratio on token sets."""
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union


# ---------------------------------------------------------------------------
# NSE list loading
# ---------------------------------------------------------------------------

def _load_nse_companies() -> None:
    """Fetch NSE EQUITY_L.csv and build lookup maps."""
    global _nse_companies, _exact_map, _token_map
    if _nse_companies is not None:
        return

    _exact_map = {}
    _token_map = {}
    _nse_companies = []

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/csv,application/octet-stream",
        }
        resp = requests.get(_NSE_EQUITY_URL, headers=headers, timeout=15)
        resp.raise_for_status()

        reader = csv.DictReader(io.StringIO(resp.text))
        for row in reader:
            symbol = row.get("SYMBOL", "").strip()
            name = row.get("NAME OF COMPANY", "").strip()
            if not symbol or not name:
                continue
            _nse_companies.append({"symbol": symbol, "name": name})

            # Build exact match map (normalized name -> symbol)
            norm = _normalize(name)
            _exact_map[norm] = symbol
            if norm.startswith("the "):
                _exact_map[norm[4:]] = symbol

            # Build token-set map (frozenset of tokens -> symbol)
            tokens = frozenset(_tokenize(name))
            if tokens:
                _token_map[tokens] = symbol

    except Exception:
        # If NSE list fails, we still have fuzzy matching via yfinance search
        _nse_companies = []
        _exact_map = {}
        _token_map = {}


# ---------------------------------------------------------------------------
# Ticker resolution
# ---------------------------------------------------------------------------

def resolve_ticker(company_name: str) -> Optional[str]:
    """
    Resolve a company name to a yfinance-compatible ticker.

    Pipeline:
    1. Skip non-equity items (returns None)
    2. Check foreign stock map
    3. Check REIT map
    4. Exact match on normalized name (NSE list)
    5. Exact match on token set (NSE list)
    6. Fuzzy match (SequenceMatcher + token Jaccard), threshold 0.60
    7. yfinance search API fallback

    Returns the ticker string (e.g. "HDFCBANK.NS", "GOOGL") or None.
    """
    if not company_name or not company_name.strip():
        return None

    name = company_name.strip()
    nl = name.lower().strip()

    # Step 1: Skip non-equity
    if _should_skip(name):
        return None

    # Step 2: Foreign stocks
    if nl in FOREIGN_STOCKS:
        return FOREIGN_STOCKS[nl]

    # Also try normalized foreign stock lookup
    norm = _normalize(name)
    if norm in FOREIGN_STOCKS:
        return FOREIGN_STOCKS[norm]

    # Step 3: REITs
    for reit_name, ticker in REIT_MAP.items():
        if reit_name in nl:
            return ticker

    # Load NSE list if not loaded
    _load_nse_companies()

    # Step 4: Exact normalized match
    if norm in _exact_map:
        return _exact_map[norm] + ".NS"

    # Step 5: Token-set exact match
    tokens = _tokenize(name)
    token_set = frozenset(tokens)
    if token_set and token_set in _token_map:
        return _token_map[token_set] + ".NS"

    # Step 6: Fuzzy match
    if _nse_companies:
        best_score = 0.0
        best_sym = None
        for nse_norm, sym in _exact_map.items():
            s1 = SequenceMatcher(None, norm, nse_norm).ratio()
            s2 = _token_set_ratio(tokens, sorted(nse_norm.split()))
            score = max(s1, s2)
            if score > best_score:
                best_score = score
                best_sym = sym

        if best_score >= 0.60:
            return best_sym + ".NS"

    # Step 7: yfinance search fallback
    return _yfinance_search(name)


def _yfinance_search(name: str) -> Optional[str]:
    """Use yfinance search API as last resort."""
    try:
        # yfinance doesn't have a public search API, but we can try
        # common NSE suffix patterns
        clean = re.sub(r'[^A-Za-z\s]', '', name).strip()
        if not clean:
            return None

        # Try first word + NS
        words = clean.split()
        if words:
            # Try the first significant word
            guess = words[0].upper()
            ticker = yf.Ticker(guess + ".NS")
            info = ticker.history(period="2d")
            if len(info) >= 1:
                return guess + ".NS"
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Price fetching
# ---------------------------------------------------------------------------

def fetch_price_changes(tickers: List[str], batch_size: int = 10) -> Dict[str, Dict]:
    """
    Fetch current-day price changes for a list of tickers.

    Returns dict: ticker -> {
        "curr_price": float,
        "prev_close": float,
        "change_pct": float,
    }
    """
    results = {}
    unique = list(set(tickers))

    for i in range(0, len(unique), batch_size):
        batch = unique[i:i + batch_size]
        for ticker in batch:
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="5d")
                if len(hist) >= 2:
                    curr_price = float(hist["Close"].iloc[-1])
                    prev_close = float(hist["Close"].iloc[-2])
                    if prev_close > 0:
                        change_pct = ((curr_price - prev_close) / prev_close) * 100
                    else:
                        change_pct = 0.0
                    results[ticker] = {
                        "curr_price": curr_price,
                        "prev_close": prev_close,
                        "change_pct": change_pct,
                    }
                elif len(hist) == 1:
                    curr_price = float(hist["Close"].iloc[-1])
                    results[ticker] = {
                        "curr_price": curr_price,
                        "prev_close": curr_price,
                        "change_pct": 0.0,
                    }
            except Exception:
                pass
        # Small delay between batches to avoid rate limiting
        if i + batch_size < len(unique):
            time.sleep(0.3)

    return results


# ---------------------------------------------------------------------------
# Test / debug
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_names = [
        "HDFC Bank Ltd", "Power Grid Corp Of India Ltd", "Coal India Ltd",
        "Tata Consultancy Services Ltd", "Alphabet Inc Class A",
        "Amazon.com Inc", "Microsoft Corp", "Meta Platforms Inc Class A",
        "Bajaj Holdings and Investment Ltd", "Embassy Office Parks REIT",
        "Brookfield India Real Estate Trust", "Eternal Ltd",
        "Dr Reddy's Laboratories Ltd", "Zydus Lifesciences Ltd",
        "Indian Energy Exchange Ltd", "E I D Parry India Ltd",
        "Central Depository Services (India) Ltd", "Great Eastern Shipping Co Ltd",
        "Canara Bank", "Bank Of Baroda", "Indian Bank",
        "Narayana Hrudayalaya Ltd", "Mahanagar Gas Ltd", "REC Ltd.",
        "Sun Pharmaceuticals Industries Ltd", "Cipla Ltd",
        "HCL Technologies Ltd", "Infosys Ltd", "Bharti Airtel Ltd",
        "Maruti Suzuki India Ltd", "Axis Bank Ltd", "Axis Bank Limited",
        "Axis Bank Ltd.", "Kotak Mahindra Bank Ltd",
        "Kotak Mahindra Bank Limited", "Kotak Mahindra Bank Ltd.",
        "ICICI Bank Ltd", "ICICI Bank Limited", "HDFC Bank Limited",
        "Reliance Industries Ltd", "Reliance Industries Limited",
        "Bharat Petroleum Corp Ltd.", "Hindustan Petroleum Corp Ltd.",
        "ITC Ltd", "Petronet LNG Ltd",
        # Non-equity (should return None)
        "Tbill", "Cash Offset For Derivatives", "Net Receivables / (Payables)",
        "Bajaj Finance Limited August 2026 Future", "Future on BANK Index",
        "National Bank For Agriculture And Rural Development",
        "Export-Import Bank of India", "Parag Parikh Liquid Dir Gr",
        "Small Industries Development Bank of India",
        "Bank Of Baroda (16/10/2026)",
        "Trp_030826",
    ]

    resolved = 0
    skipped = 0
    failed = 0
    for name in test_names:
        ticker = resolve_ticker(name)
        if ticker:
            resolved += 1
            status = "OK"
        elif _should_skip(name):
            skipped += 1
            status = "SKIP"
        else:
            failed += 1
            status = "FAIL"
        print(f"  [{status:4s}] {name:55s} -> {ticker}")

    print(f"\nResolved: {resolved}, Skipped: {skipped}, Failed: {failed}")
    print(f"Total: {len(test_names)}")
