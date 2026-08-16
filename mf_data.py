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

        query_words = query_lower.split()
        matches = sum(1 for w in query_words if w in name_lower)

        if matches == len(query_words):
            score = matches
            if "direct" in name_lower:
                score += 2
            if "growth" in name_lower:
                score += 2
            if "regular" in name_lower:
                score -= 1
            results.append({
                "scheme_code": s.get("schemeCode"),
                "scheme_name": name,
                "score": score,
            })

    results.sort(key=lambda x: (-x["score"], x["scheme_name"]))
    return results[:limit]


def get_fund_nav(scheme_code: str) -> Tuple[Optional[str], Optional[str]]:
    """Get latest NAV for a fund."""
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

def _clean_scheme_name_for_groww(scheme_name: str) -> str:
    """
    Clean an AMFI scheme name to match Groww's naming convention.
    AMFI: 'ICICI Prudential Flexicap Fund - Direct Plan - Growth'
    Groww URL: 'icici-prudential-flexicap-fund-direct-growth'
    """
    name = scheme_name
    name = name.replace(" - ", " ").replace("-", " ")
    name = re.sub(r'\bplan\b', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\bscheme\b', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _slugify(name: str) -> str:
    """Convert a name to a URL slug."""
    slug = re.sub(r'[^a-z0-9\s-]', '', name.lower())
    slug = re.sub(r'\s+', '-', slug.strip())
    slug = re.sub(r'-+', '-', slug)
    return slug


def _generate_groww_slug_variants(scheme_name: str) -> List[str]:
    """Generate multiple possible Groww URL slugs from a scheme name."""
    variants = []
    cleaned = _clean_scheme_name_for_groww(scheme_name)
    slug = _slugify(cleaned)
    if slug:
        variants.append(slug)

    no_fund = re.sub(r'\bfund\b', '', cleaned, flags=re.IGNORECASE)
    slug_no_fund = _slugify(no_fund)
    if slug_no_fund and slug_no_fund not in variants:
        variants.append(slug_no_fund)

    raw_slug = _slugify(scheme_name.replace(" - ", " "))
    if raw_slug and raw_slug not in variants:
        variants.append(raw_slug)

    parts = cleaned.lower().split()
    no_plan_type = [p for p in parts if p not in ("direct", "regular", "growth", "dividend", "plan", "scheme", "option")]
    if no_plan_type:
        slug_generic = _slugify(" ".join(no_plan_type))
        if slug_generic and slug_generic not in variants:
            variants.append(slug_generic)

    if "flexi" in cleaned.lower():
        for v in list(variants):
            if "flexi-cap" in v:
                alt = v.replace("flexi-cap", "flexicap")
                if alt not in variants:
                    variants.append(alt)
            if "flexi" in v and "cap" in v and "flexicap" not in v and "flexi-cap" not in v:
                alt = v.replace("flexi", "flexicap").replace("-cap", "")
                if alt not in variants:
                    variants.append(alt)

    return variants


def fetch_holdings_groww(scheme_name: str) -> Optional[List[Dict]]:
    """
    Fetch holdings from Groww by scheme name.
    Tries multiple URL slug variations to handle name mismatches.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    slug_variants = _generate_groww_slug_variants(scheme_name)

    for slug in slug_variants:
        url = f"https://groww.in/mutual-funds/{slug}"
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            holdings = _parse_groww_holdings(soup)
            if holdings:
                return holdings

            holdings = _parse_groww_json_data(soup)
            if holdings:
                return holdings
        except Exception:
            continue

    holdings = _groww_search_and_fetch(scheme_name)
    if holdings:
        return holdings

    return None


def _groww_search_and_fetch(scheme_name: str) -> Optional[List[Dict]]:
    """Use Groww's search API to find the correct fund URL, then fetch holdings."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        search_query = _clean_scheme_name_for_groww(scheme_name)
        search_words = search_query.lower().split()
        search_words = [w for w in search_words if w not in ("direct", "regular", "growth", "dividend", "plan", "scheme")]
        search_query = " ".join(search_words)

        resp = requests.get(
            "https://groww.in/v1/api/search/v1/derivedentity",
            params={"query": search_query, "q": search_query, "types": "MF"},
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            funds = []
            if isinstance(data, dict):
                for key in ("results", "data", "derived_entities"):
                    if key in data and isinstance(data[key], list):
                        funds = data[key]
                        break
            elif isinstance(data, list):
                funds = data

            for fund in funds:
                fund_url = fund.get("url") or fund.get("link") or fund.get("canonical_url")
                if fund_url:
                    if not fund_url.startswith("http"):
                        fund_url = f"https://groww.in{fund_url}"
                    holdings = _fetch_groww_url(fund_url)
                    if holdings:
                        return holdings
    except Exception:
        pass

    return None


def _fetch_groww_url(url: str) -> Optional[List[Dict]]:
    """Fetch and parse holdings from a specific Groww URL."""
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
        holdings = _parse_groww_json_data(soup)
        if holdings:
            return holdings
    except Exception:
        pass
    return None


def _parse_groww_holdings(soup: BeautifulSoup) -> List[Dict]:
    """Parse Groww holdings from the page HTML."""
    holdings = []
    tables = soup.find_all("table")

    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        header_cells = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        header_text = " ".join(header_cells)

        if "name" in header_text and ("asset" in header_text or "holding" in header_text or "weight" in header_text):
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) >= 4:
                    name = cells[0].get_text(strip=True)
                    sector = cells[1].get_text(strip=True)
                    instrument = cells[2].get_text(strip=True)
                    assets_str = cells[3].get_text(strip=True)
                    weight = _parse_percentage(assets_str)
                    if name and weight is not None:
                        holdings.append({
                            "name": name,
                            "sector": sector,
                            "instrument": instrument,
                            "weight": weight,
                        })
                elif len(cells) >= 2:
                    name = cells[0].get_text(strip=True)
                    assets_str = cells[-1].get_text(strip=True)
                    weight = _parse_percentage(assets_str)
                    if name and weight is not None:
                        holdings.append({
                            "name": name,
                            "sector": "N/A",
                            "instrument": "Equity",
                            "weight": weight,
                        })

    return holdings


def _parse_groww_json_data(soup: BeautifulSoup) -> List[Dict]:
    """Try to extract holdings from JSON data embedded in Groww's page."""
    holdings = []

    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        if not text:
            continue
        if "holding" not in text.lower() and "stock" not in text.lower():
            continue

        try:
            for pattern in [
                r'window\.__INITIAL_STATE__\s*=\s*({.*?});\s*</script>',
                r'window\.__NUXT__\s*=\s*({.*?});\s*</script>',
                r'"holdings"\s*:\s*(\[.*?\])',
                r'"stocks"\s*:\s*(\[.*?\])',
            ]:
                match = re.search(pattern, text, re.DOTALL)
                if match:
                    json_str = match.group(1)
                    data = json.loads(json_str)
                    found = _extract_holdings_from_json(data)
                    if found:
                        return found
        except (json.JSONDecodeError, TypeError):
            continue

    return holdings


def _extract_holdings_from_json(data, depth=0) -> List[Dict]:
    """Recursively search JSON data for holdings-like arrays."""
    if depth > 5:
        return []

    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in ("holdings", "stocks", "topHoldings", "portfolio"):
                if isinstance(value, list):
                    parsed = _parse_holdings_array(value)
                    if parsed:
                        return parsed
            result = _extract_holdings_from_json(value, depth + 1)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _extract_holdings_from_json(item, depth + 1)
            if result:
                return result

    return []


def _parse_holdings_array(arr: list) -> List[Dict]:
    """Parse a holdings array from Groww's JSON format."""
    holdings = []
    for item in arr:
        if not isinstance(item, dict):
            continue

        name = (
            item.get("name")
            or item.get("stockName")
            or item.get("company")
            or item.get("securityName")
            or item.get("holdingName")
        )
        sector = item.get("sector") or item.get("industry") or "N/A"
        instrument = item.get("instrument") or item.get("type") or "Equity"
        weight = (
            item.get("assets")
            or item.get("weight")
            or item.get("percentage")
            or item.get("assetPercentage")
        )

        if name and weight is not None:
            if isinstance(weight, str):
                weight = _parse_percentage(weight)
            if weight is not None:
                holdings.append({
                    "name": name,
                    "sector": str(sector),
                    "instrument": str(instrument),
                    "weight": float(weight),
                })

    return holdings if len(holdings) >= 3 else []


def _parse_percentage(s) -> Optional[float]:
    """Parse a percentage string like '9.29%' -> 9.29"""
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace("%", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Main holdings fetcher with fallback chain
# ---------------------------------------------------------------------------

def fetch_holdings(scheme_name: str, scheme_code: str = None) -> Tuple[Optional[List[Dict]], str]:
    """
    Fetch holdings for a fund, trying multiple sources.
    Returns (holdings_list, source_name) or (None, error_message).
    """
    holdings = fetch_holdings_groww(scheme_name)
    if holdings and len(holdings) > 0:
        return holdings, "Groww"

    return None, "Unable to fetch holdings. The scheme name from AMFI may not match Groww's URL format. Try searching with a simpler name (e.g. 'ICICI Prudential FlexiCap' instead of the full AMFI name)."
