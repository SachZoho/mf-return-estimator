"""
Mutual Fund data module — handles fund search and holdings retrieval.

Data sources (in priority order):
1. mfapi.in — free AMFI-backed API for fund search and NAV
2. Groww — holdings scraping (clean HTML tables)
3. MoneyControl — fallback for holdings

All sources are free and require no API key.
"""

import re
import json
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Fund Search via mfapi.in
# ---------------------------------------------------------------------------

MFAPI_BASE = "https://api.mfapi.in/mf"

# Cache the full scheme list once per session
_scheme_cache: Optional[List[Dict]] = None


def _get_all_schemes() -> List[Dict]:
    """Fetch the full list of Indian MF schemes from mfapi.in (cached)."""
    global _scheme_cache
    if _scheme_cache is not None:
        return _scheme_cache
    try:
        resp = requests.get(f"{MFAPI_BASE}", timeout=20)
        resp.raise_for_status()
        _scheme_cache = resp.json()
        return _scheme_cache
    except Exception:
        return []


def search_funds(query: str, limit: int = 20) -> List[Dict]:
    """
    Search for mutual fund schemes matching the query.
    Returns list of dicts: {scheme_code, scheme_name}
    """
    schemes = _get_all_schemes()
    if not schemes:
        return []
    
    query_lower = query.lower().strip()
    results = []
    
    for s in schemes:
        name = s.get("schemeName", "")
        name_lower = name.lower()
        
        # Score: all words present = best match
        query_words = query_lower.split()
        matches = sum(1 for w in query_words if w in name_lower)
        
        if matches == len(query_words):
            # Prefer Direct + Growth
            score = matches
            if "direct" in name_lower:
                score += 2
            if "growth" in name_lower:
                score += 2
            # Penalize regular plan slightly
            if "regular" in name_lower:
                score -= 1
            results.append({
                "scheme_code": s.get("schemeCode"),
                "scheme_name": name,
                "score": score,
            })
    
    # Sort by score descending, then by name
    results.sort(key=lambda x: (-x["score"], x["scheme_name"]))
    return results[:limit]


def get_fund_nav(scheme_code: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Get latest NAV for a fund.
    Returns (nav_value, nav_date) or (None, None) on failure.
    """
    try:
        resp = requests.get(f"{MFAPI_BASE}/{scheme_code}", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if "data" in data and len(data["data"]) > 0:
            latest = data["data"][0]
            return latest.get("nav"), latest.get("date")
        return None, None
    except Exception:
        return None, None


def get_fund_meta(scheme_code: str) -> Dict:
    """Get fund metadata from mfapi.in."""
    try:
        resp = requests.get(f"{MFAPI_BASE}/{scheme_code}", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("meta", {})
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Holdings scraping from Groww
# ---------------------------------------------------------------------------

def _slugify_groww(scheme_name: str) -> str:
    """
    Convert a scheme name to Groww's URL slug.
    e.g. "ICICI Prudential Flexicap Fund Direct Growth" ->
         "icici-prudential-flexicap-fund-direct-growth"
    """
    # Remove common suffixes that Groww doesn't include in URL
    name = scheme_name
    # Remove " - " patterns
    name = name.replace(" - ", " ")
    # Lowercase and slugify
    slug = re.sub(r'[^a-z0-9\s-]', '', name.lower())
    slug = re.sub(r'\s+', '-', slug.strip())
    slug = re.sub(r'-+', '-', slug)
    return slug


def fetch_holdings_groww(scheme_name: str) -> Optional[List[Dict]]:
    """
    Fetch holdings from Groww by scheme name.
    Returns list of {name, sector, instrument, weight} or None on failure.
    """
    slug = _slugify_groww(scheme_name)
    url = f"https://groww.in/mutual-funds/{slug}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        holdings = _parse_groww_holdings(soup)
        
        if holdings:
            return holdings
        return None
    except Exception:
        return None


def _parse_groww_holdings(soup: BeautifulSoup) -> List[Dict]:
    """Parse Groww holdings from the page HTML."""
    holdings = []
    
    # Groww renders holdings in a table with columns: Name | Sector | Instruments | Assets
    # Try to find the holdings section
    tables = soup.find_all("table")
    
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        
        # Check if this looks like a holdings table
        header_cells = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        header_text = " ".join(header_cells)
        
        if "name" in header_text and "asset" in header_text:
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) >= 4:
                    name = cells[0].get_text(strip=True)
                    sector = cells[1].get_text(strip=True)
                    instrument = cells[2].get_text(strip=True)
                    assets_str = cells[3].get_text(strip=True)
                    
                    # Parse percentage
                    weight = _parse_percentage(assets_str)
                    if name and weight is not None:
                        holdings.append({
                            "name": name,
                            "sector": sector,
                            "instrument": instrument,
                            "weight": weight,
                        })
    
    return holdings


def _parse_percentage(s: str) -> Optional[float]:
    """Parse a percentage string like '9.29%' -> 9.29"""
    s = s.strip().replace("%", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Holdings from MoneyControl (fallback)
# ---------------------------------------------------------------------------

def fetch_holdings_moneycontrol(scheme_name: str) -> Optional[List[Dict]]:
    """
    Fallback: fetch holdings from MoneyControl.
    MoneyControl uses scheme-specific URLs, so this requires a lookup.
    """
    # MoneyControl needs a specific MRF code in the URL
    # For now, try searching for the fund on MoneyControl
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html",
    }
    
    try:
        # Search for the fund on MoneyControl
        search_url = "https://www.moneycontrol.com/mutual-funds/fund-ranking"
        # This is a simplified approach — MoneyControl's search is more complex
        # In practice, we'd need to map scheme names to MRF codes
        # For now, return None and let the caller try other sources
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main holdings fetcher with fallback chain
# ---------------------------------------------------------------------------

def fetch_holdings(scheme_name: str, scheme_code: str = None) -> Tuple[Optional[List[Dict]], str]:
    """
    Fetch holdings for a fund, trying multiple sources.
    Returns (holdings_list, source_name) or (None, error_message).
    
    Each holding is: {name, sector, instrument, weight}
    """
    # Try Groww first (best data quality)
    holdings = fetch_holdings_groww(scheme_name)
    if holdings and len(holdings) > 0:
        return holdings, "Groww"
    
    # Try MoneyControl as fallback
    holdings = fetch_holdings_moneycontrol(scheme_name)
    if holdings and len(holdings) > 0:
        return holdings, "MoneyControl"
    
    return None, "Unable to fetch holdings from any source. The fund may be too new or the name may not match."
