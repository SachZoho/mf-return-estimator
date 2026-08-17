"""
Mutual Fund data module — handles fund search and holdings retrieval.

Data sources (in priority order):
1. AMFI Portal (portal.amfiindia.com) — SEBI-mandated monthly portfolio
   disclosures with a known "as of" date. Complete holdings (not just top 10).
2. FinAPI (finapi.upvaly.com) — free JSON API for portfolio holdings (no date)
3. mfdata.in — free JSON API for holdings (alternative, no date)
4. Groww — fallback holdings scraping (JS-rendered, may not work)

All sources are free and require no API key.
"""

import re
import json
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MFAPI_BASE = "https://api.mfapi.in/mf"
FINAPI_BASE = "https://finapi.upvaly.com/api/mf"
MFDATA_BASE = "https://mfdata.in/api/v1"
AMFI_PORTFOLIO_URL = "https://portal.amfiindia.com/DownloadSchemeData_Po.aspx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Cache the full scheme list once per session
_scheme_cache: Optional[List[Dict]] = None


# ---------------------------------------------------------------------------
# Fund Search via mfapi.in
# ---------------------------------------------------------------------------

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
    """Search for mutual fund schemes matching the query."""
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
# Holdings via AMFI Portal — SEBI monthly portfolio disclosures (WITH DATE)
# ---------------------------------------------------------------------------

def fetch_holdings_amfi(scheme_code: str, month: int, year: int) -> Tuple[Optional[List[Dict]], str, Optional[str]]:
    """
    Fetch holdings from AMFI's SEBI-mandated monthly portfolio disclosure.

    Returns (holdings_list, error_msg, holdings_date).
    holdings_date is a string like "July 2025" or None on failure.
    """
    try:
        resp = requests.get(
            AMFI_PORTFOLIO_URL,
            params={
                "mession": "24",
                "mession_code": scheme_code,
                "mf": month,
                "yr": year,
                "myession": "S",
            },
            headers=HEADERS,
            timeout=30,
        )
        if resp.status_code != 200:
            return None, f"AMFI HTTP {resp.status_code}", None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Try to extract the "as on" date from the page
        holdings_date = _extract_amfi_date(soup, month, year)

        table = soup.find("table")
        if not table:
            return None, "AMFI: no holdings table found", None

        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) >= 5:
                rows.append(cells)

        if not rows:
            return None, "AMFI: table has no data rows", None

        # AMFI table format: Company, Sector, Quantity, Market Value (Rs lakh), % to NAV
        # Skip header rows (first row(s) with non-numeric quantity)
        holdings = []
        for cells in rows:
            company = cells[0].strip()
            sector = cells[1].strip() if len(cells) > 1 else "N/A"
            qty_str = cells[2].strip().replace(",", "") if len(cells) > 2 else ""
            mv_str = cells[3].strip().replace(",", "") if len(cells) > 3 else ""
            pct_str = cells[4].strip().replace("%", "").replace(",", "") if len(cells) > 4 else ""

            # Skip rows where quantity is not a number (header rows)
            try:
                float(qty_str)
            except (ValueError, TypeError):
                continue

            try:
                weight = float(pct_str)
            except (ValueError, TypeError):
                continue

            if not company or weight <= 0:
                continue

            instrument = _classify_instrument(company, sector)
            holdings.append({
                "name": company,
                "sector": sector,
                "instrument": instrument,
                "weight": weight,
            })

        if not holdings:
            return None, "AMFI: no valid holdings parsed", None

        return holdings, "", holdings_date

    except Exception as e:
        return None, f"AMFI error: {str(e)[:100]}", None


def _extract_amfi_date(soup, month: int, year: int) -> Optional[str]:
    """Try to extract the 'As on' date from the AMFI disclosure page."""
    try:
        text = soup.get_text()
        # Look for "As on" pattern
        match = re.search(r"As on[:\s]+([\w\s,]+?)(?:\n|$)", text)
        if match:
            date_str = match.group(1).strip()
            if len(date_str) < 60:
                return date_str
    except Exception:
        pass
    # Fallback: construct from month/year params
    month_names = ["", "January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    if 1 <= month <= 12:
        return f"{month_names[month]} {year}"
    return None


def fetch_latest_holdings_amfi(scheme_code: str, months_back: int = 3) -> Tuple[Optional[List[Dict]], str, Optional[str]]:
    """
    Try to fetch the latest available holdings from AMFI portal.
    Starts from the current month and goes back up to months_back months.
    Returns (holdings, error_msg, holdings_date).
    """
    now = datetime.now()
    for i in range(months_back):
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        holdings, err, date_str = fetch_holdings_amfi(scheme_code, m, y)
        if holdings:
            return holdings, "", date_str
    return None, f"AMFI: no holdings found in last {months_back} months", None


# ---------------------------------------------------------------------------
# Holdings via FinAPI (finapi.upvaly.com) — clean JSON, no date
# ---------------------------------------------------------------------------

def fetch_holdings_finapi(scheme_code: str) -> Tuple[Optional[List[Dict]], str]:
    """Fetch holdings from FinAPI. Returns (holdings_list, error_msg)."""
    try:
        resp = requests.get(
            f"{FINAPI_BASE}/scheme-code/{scheme_code}",
            params={"fields": "holdings"},
            headers={**HEADERS, "Accept": "application/json"},
            timeout=20,
        )
        if resp.status_code != 200:
            return None, f"FinAPI returned HTTP {resp.status_code}"

        data = resp.json()
        if data.get("status") != "success":
            return None, f"FinAPI status: {data.get('status', 'unknown')}"

        fund_data = data.get("data", {})
        raw_holdings = fund_data.get("holdings", [])
        if not raw_holdings:
            return None, "FinAPI returned 0 holdings"

        holdings = _parse_finapi_holdings(raw_holdings)
        if not holdings:
            return None, "FinAPI holdings parsed to empty list"

        return holdings, ""

    except Exception as e:
        return None, f"FinAPI error: {str(e)[:100]}"


def _parse_finapi_holdings(raw_holdings: list) -> List[Dict]:
    """Parse FinAPI holdings into standard format."""
    holdings = []
    for h in raw_holdings:
        name = h.get("name", "")
        sector = h.get("sector", "N/A")
        weight = h.get("weightage") or h.get("weight") or h.get("percentage")
        instrument = _classify_instrument(name, sector)

        if name and weight is not None:
            try:
                weight_float = float(weight)
                holdings.append({
                    "name": name,
                    "sector": sector,
                    "instrument": instrument,
                    "weight": weight_float,
                })
            except (ValueError, TypeError):
                continue
    return holdings


def _classify_instrument(name: str, sector: str) -> str:
    """Classify a holding as Equity, Debt, Cash, etc. based on name/sector."""
    name_lower = name.lower()
    if any(w in name_lower for w in ["tbill", "treasury", "cblo", "repo", "reverse repo"]):
        return "Treasury/Repo"
    if any(w in name_lower for w in ["future", "option", "derivative"]):
        return "Derivative"
    if any(w in name_lower for w in ["cash", "net receivable", "net payable"]):
        return "Cash/Other"
    if any(w in name_lower for w in ["nabad", "nabard", "sidbi", "exim", "rec ltd",
                                      "pfc", "development bank", "housing board"]):
        return "Debt"
    if "reit" in name_lower or "invit" in name_lower:
        return "REIT/InvIT"
    if any(w in name_lower for w in [" inc", "class a", "class b", " corp"]) and "ltd" not in name_lower:
        return "Foreign Equity"
    if sector == "N/A" and not any(w in name_lower for w in ["bank", "ltd", "limited", "corp", "industries", "company"]):
        return "Debt/Other"
    return "Equity"


# ---------------------------------------------------------------------------
# Holdings via mfdata.in (alternative free JSON API, no date)
# ---------------------------------------------------------------------------

def fetch_holdings_mfdata(scheme_code: str) -> Tuple[Optional[List[Dict]], str]:
    """Fetch holdings from mfdata.in."""
    try:
        resp = requests.get(
            f"{MFDATA_BASE}/schemes/{scheme_code}",
            headers={**HEADERS, "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None, f"mfdata.in scheme lookup HTTP {resp.status_code}"

        data = resp.json()
        if data.get("status") != "success":
            return None, "mfdata.in scheme lookup failed"

        scheme_data = data.get("data", {})
        family_id = scheme_data.get("family_id") or scheme_data.get("familyId")
        if not family_id:
            return None, "mfdata.in: no family_id found"

        resp2 = requests.get(
            f"{MFDATA_BASE}/families/{family_id}/holdings",
            headers={**HEADERS, "Accept": "application/json"},
            timeout=15,
        )
        if resp2.status_code != 200:
            return None, f"mfdata.in holdings HTTP {resp2.status_code}"

        data2 = resp2.json()
        if data2.get("status") != "success":
            return None, "mfdata.in holdings failed"

        holdings_data = data2.get("data", {})
        raw_holdings = holdings_data.get("equity_holdings", []) or holdings_data.get("stocks", [])
        if not raw_holdings:
            return None, "mfdata.in returned 0 equity holdings"

        holdings = []
        for h in raw_holdings:
            name = h.get("stock_name") or h.get("name") or h.get("company_name", "")
            sector = h.get("sector") or h.get("industry") or "N/A"
            weight = h.get("weight_pct") or h.get("weight") or h.get("percentage")
            if name and weight is not None:
                try:
                    holdings.append({
                        "name": name,
                        "sector": str(sector),
                        "instrument": "Equity",
                        "weight": float(weight),
                    })
                except (ValueError, TypeError):
                    continue

        if not holdings:
            return None, "mfdata.in holdings parsed to empty"

        return holdings, ""

    except Exception as e:
        return None, f"mfdata.in error: {str(e)[:100]}"


# ---------------------------------------------------------------------------
# Holdings via FinAPI search by name (fallback when scheme code lookup fails)
# ---------------------------------------------------------------------------

def _fetch_holdings_finapi_by_name(scheme_name: str) -> Tuple[Optional[List[Dict]], str]:
    """Search FinAPI by name, then fetch holdings for best match."""
    search_query = scheme_name.replace(" - ", " ").strip()
    try:
        resp = requests.get(
            f"{FINAPI_BASE}/search",
            params={"q": search_query},
            headers={**HEADERS, "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None, f"FinAPI search HTTP {resp.status_code}"

        data = resp.json()
        if data.get("status") != "success":
            return None, "FinAPI search failed"

        results = data.get("data", [])
        if not results:
            return None, "FinAPI search: 0 results"

        best_match = None
        best_score = -1
        for r in results:
            r_name = r.get("schemeName", "").lower()
            r_plan = r.get("planName", "").lower()
            r_option = r.get("optionName", "").lower()
            score = 0
            if "direct" in r_plan:
                score += 10
            if "growth" in r_option:
                score += 10
            if "regular" in r_plan:
                score -= 5
            from difflib import SequenceMatcher
            score += SequenceMatcher(None, scheme_name.lower(), r_name).ratio() * 5
            if score > best_score:
                best_score = score
                best_match = r

        if best_match:
            code = best_match.get("schemeCode")
            if code:
                return fetch_holdings_finapi(code)

        return None, "FinAPI search: no suitable match"

    except Exception as e:
        return None, f"FinAPI search error: {str(e)[:100]}"


# ---------------------------------------------------------------------------
# Groww fallback (may not work due to JS rendering)
# ---------------------------------------------------------------------------

def _clean_scheme_name_for_groww(scheme_name: str) -> str:
    name = scheme_name.replace(" - ", " ").replace("-", " ")
    name = re.sub(r'\bplan\b', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\bscheme\b', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _slugify(name: str) -> str:
    slug = re.sub(r'[^a-z0-9\s-]', '', name.lower())
    slug = re.sub(r'\s+', '-', slug.strip())
    slug = re.sub(r'-+', '-', slug)
    return slug


def _generate_groww_slug_variants(scheme_name: str) -> List[str]:
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
            if "flexicap" in v:
                alt = v.replace("flexicap", "flexi-cap")
                if alt not in variants:
                    variants.append(alt)
            if "flexi" in v and "cap" in v and "flexicap" not in v and "flexi-cap" not in v:
                alt = v.replace("flexi", "flexicap").replace("-cap", "")
                if alt not in variants:
                    variants.append(alt)
    return variants


def fetch_holdings_groww(scheme_name: str) -> Tuple[Optional[List[Dict]], str]:
    """Fallback: try Groww scraping (may not work due to JS rendering)."""
    slug_variants = _generate_groww_slug_variants(scheme_name)
    for slug in slug_variants:
        url = f"https://groww.in/mutual-funds/{slug}"
        try:
            resp = requests.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=20)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            holdings = _parse_groww_json_data(soup)
            if holdings:
                return holdings, ""
        except Exception:
            continue
    return None, "Groww: no holdings found (JS-rendered page)"


def _parse_groww_json_data(soup) -> List[Dict]:
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        if not text:
            continue
        if "holding" not in text.lower() and "stock" not in text.lower():
            continue
        try:
            for pattern in [
                r'window\.__INITIAL_STATE__\s*=\s*({.*?});\s*<\x2fscript>',
                r'window\.__NUXT__\s*=\s*({.*?});\s*<\x2fscript>',
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
    return []


def _extract_holdings_from_json(data, depth=0) -> List[Dict]:
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
    holdings = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or item.get("stockName") or item.get("company")
                or item.get("securityName") or item.get("holdingName"))
        sector = item.get("sector") or item.get("industry") or "N/A"
        instrument = item.get("instrument") or item.get("type") or "Equity"
        weight = (item.get("assets") or item.get("weight")
                  or item.get("percentage") or item.get("assetPercentage"))
        if name and weight is not None:
            if isinstance(weight, str):
                try:
                    weight = float(weight.replace("%", "").replace(",", "").strip())
                except ValueError:
                    continue
            holdings.append({
                "name": name, "sector": str(sector),
                "instrument": str(instrument), "weight": float(weight),
            })
    return holdings if len(holdings) >= 3 else []


# ---------------------------------------------------------------------------
# Main holdings fetcher with fallback chain + date tracking
# ---------------------------------------------------------------------------

def fetch_holdings(scheme_name: str, scheme_code: str = None) -> Tuple[Optional[List[Dict]], str, Optional[str]]:
    """
    Fetch holdings for a fund, trying multiple sources.

    Returns (holdings_list, source_or_error, holdings_date).

    On success: (holdings, "AMFI Portal", "July 2025") or
                (holdings, "FinAPI", None) etc.
    On failure: (None, "Detailed error from all sources", None).

    The AMFI Portal is tried first because it provides dated, SEBI-mandated
    monthly disclosures. FinAPI and other sources are used as fallbacks
    (they don't expose a holdings date).
    """
    errors = []

    # 1. Try AMFI Portal (dated holdings — SEBI monthly disclosure)
    if scheme_code:
        holdings, err, date_str = fetch_latest_holdings_amfi(scheme_code)
        if holdings:
            return holdings, "AMFI Portal", date_str
        errors.append(f"AMFI(scheme {scheme_code}): {err}")

    # 2. Try FinAPI by scheme code (no date)
    if scheme_code:
        holdings, err = fetch_holdings_finapi(scheme_code)
        if holdings:
            return holdings, "FinAPI", None
        errors.append(f"FinAPI(scheme {scheme_code}): {err}")

    # 3. Try FinAPI by name search (no date)
    holdings, err = _fetch_holdings_finapi_by_name(scheme_name)
    if holdings:
        return holdings, "FinAPI (name search)", None
    errors.append(f"FinAPI(name): {err}")

    # 4. Try mfdata.in (no date)
    if scheme_code:
        holdings, err = fetch_holdings_mfdata(scheme_code)
        if holdings:
            return holdings, "mfdata.in", None
        errors.append(f"mfdata.in: {err}")

    # 5. Try Groww scraping (last resort, no date)
    holdings, err = fetch_holdings_groww(scheme_name)
    if holdings:
        return holdings, "Groww", None
    errors.append(err)

    # All sources failed
    detail = " | ".join(errors)
    return None, f"All data sources failed: {detail}", None
