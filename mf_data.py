"""
Mutual Fund data module — handles fund search and holdings retrieval.

Data sources (in priority order):
1. FinAPI (finapi.upvaly.com) — free JSON API. The scheme-code endpoint returns
   the full portfolio holdings (name, sector, marketValue, weightage) plus a
   latestNavDate that doubles as a holdings "as of" date. Zero auth.
   Docs: https://www.finapi.upvaly.com/
2. FinAPI name search — same API, looked up by scheme name when no scheme code
   is available or the scheme-code lookup fails. Tries progressively shorter
   queries because long full names often return 0 results.
3. mfdata.in — free JSON API for holdings via family-id lookup (no date).
4. Groww — HTML scrape, last resort (JS-rendered, rarely works).

AMFI portal note: AMFI's DownloadSchemeData_Po.aspx endpoint returns the full
scheme master list (a semicolon-delimited text dump), NOT per-scheme holdings —
so it is no longer used as a holdings source.

Holdings date: FinAPI's scheme-code response includes latestNavDate which we
convert to "Month YYYY" for display (e.g. "August 2026"). Other sources do not
provide a holdings date.

Historical note: the previous AMFI code used invented params (mession, mession_code,
mf, yr, myession) on DownloadSchemeData_Po.aspx. That endpoint actually returns the full
scheme master list (a semicolon-delimited text dump), so it never contained holdings — which is why
"AMFI: no holdings found in last 3 months" fired for every fund. FinAPI's
scheme-code endpoint is the reliable holdings source and is now primary.
"""

import requests
import json
import re
import logging
from datetime import datetime
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)

MFAPI_BASE = "https://api.mfapi.in/mf"
FINAPI_BASE = "https://finapi.upvaly.com/api/mf"
MFDATA_BASE = "https://mfdata.in/api/v1"
AMFI_SCHEME_MASTER_URL = "https://portal.amfiindia.com/DownloadSchemeData_Po.aspx?mf=0"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# Cache for mfapi.in scheme list
_all_schemes_cache = None


# ---------------------------------------------------------------------------
# Fund Search via mfapi.in
# ---------------------------------------------------------------------------

def _get_all_schemes() -> List[Dict]:
    """Fetch the full AMFI scheme list from mfapi.in (cached)."""
    global _all_schemes_cache
    if _all_schemes_cache is not None:
        return _all_schemes_cache
    try:
        resp = requests.get(f"{MFAPI_BASE}", timeout=15, headers=HEADERS)
        resp.raise_for_status()
        _all_schemes_cache = resp.json()
        return _all_schemes_cache
    except Exception as e:
        logger.warning(f"mfapi.in scheme list fetch failed: {e}")
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
        if query_lower in name.lower():
            results.append({
                "scheme_code": str(s.get("schemeCode", "")),
                "scheme_name": name,
            })
            if len(results) >= limit:
                break
    return results


def get_fund_nav(scheme_code: str) -> Tuple[Optional[str], Optional[str]]:
    """Fetch latest NAV for a scheme. Returns (nav_value, nav_date)."""
    try:
        resp = requests.get(f"{MFAPI_BASE}/{scheme_code}", timeout=15, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
        nav_data = data.get("data", [])
        if nav_data:
            return nav_data[0].get("nav"), nav_data[0].get("date")
    except Exception as e:
        logger.warning(f"NAV fetch failed for {scheme_code}: {e}")
    return None, None


def get_fund_meta(scheme_code: str) -> Dict:
    """Fetch fund metadata (fund house, category, etc.)."""
    try:
        resp = requests.get(f"{MFAPI_BASE}/{scheme_code}", timeout=15, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
        meta = data.get("meta", {})
        return {
            "fund_house": meta.get("fund_house", "N/A"),
            "scheme_type": meta.get("scheme_type", "N/A"),
            "scheme_category": meta.get("scheme_category", "N/A"),
        }
    except Exception as e:
        logger.warning(f"Meta fetch failed for {scheme_code}: {e}")
        return {}


# ---------------------------------------------------------------------------
# Holdings via FinAPI (finapi.upvaly.com) — primary source
# Docs: https://www.finapi.upvaly.com/
#   GET /api/mf/scheme-code/{schemeCode}          (use fields=holdings)
#   GET /api/mf/search?schemeName=<keyword>        (NOTE: schemeName, not q)
# Returns clean JSON with holdings [{name, sector, marketValue, weightage, ...}]
# and a latestNavDate usable as the holdings "as of" date.
# ---------------------------------------------------------------------------

def fetch_holdings_finapi(scheme_code: str) -> Tuple[Optional[List[Dict]], str, Optional[str]]:
    """
    Fetch holdings from FinAPI by scheme code.
    Retries up to 3 times on 404/429/timeout (intermittent failures on Streamlit Cloud).

    Returns (holdings_list, error_msg, holdings_date).
    holdings_date is taken from the fund's latestNavDate when present.
    """
    import time
    last_error = ""
    resp = None
    for attempt in range(3):
        try:
            resp = requests.get(
                f"{FINAPI_BASE}/scheme-code/{scheme_code}",
                params={"fields": "holdings"},
                headers={**HEADERS, "Accept": "application/json"},
                timeout=20,
            )
            if resp.status_code == 200:
                break
            if resp.status_code == 429:
                last_error = "FinAPI HTTP 429 (rate limited)"
                if attempt < 2:
                    time.sleep(3)
                    continue
                return None, last_error, None
            if resp.status_code == 404:
                last_error = f"FinAPI HTTP 404 (scheme code {scheme_code} not found)"
                if attempt < 2:
                    time.sleep(2)
                    continue
                return None, last_error, None
            return None, f"FinAPI returned HTTP {resp.status_code}", None
        except requests.Timeout:
            last_error = "FinAPI error: request timed out"
            if attempt < 2:
                time.sleep(2)
                continue
            return None, last_error, None
        except Exception as e:
            last_error = f"FinAPI error: {str(e)[:100]}"
            if attempt < 2:
                time.sleep(2)
                continue
            return None, last_error, None
    else:
        return None, last_error or "FinAPI: exhausted retries", None

    # Parse the successful response
    try:
        data = resp.json()
        if data.get("status") != "success":
            return None, f"FinAPI status: {data.get('status', 'unknown')}", None

        fund_data = data.get("data", {})
        if isinstance(fund_data, list):
            fund_data = fund_data[0] if fund_data else {}

        # holdings "as of" date — FinAPI exposes latestNavDate (yyyy-mm-dd)
        holdings_date = _format_finapi_date(fund_data.get("latestNavDate"))

        raw_holdings = fund_data.get("holdings", [])
        if not raw_holdings:
            return None, "FinAPI returned 0 holdings", holdings_date

        holdings = _parse_finapi_holdings(raw_holdings)
        if not holdings:
            return None, "FinAPI holdings parsed to empty list", holdings_date

        return holdings, "", holdings_date
    except Exception as e:
        return None, f"FinAPI parse error: {str(e)[:100]}", None


def _format_finapi_date(date_str: Optional[str]) -> Optional[str]:
    """Convert FinAPI's yyyy-mm-dd latestNavDate into 'Month YYYY' for display."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return dt.strftime("%B %Y")
    except (ValueError, TypeError):
        return None


def _parse_finapi_holdings(raw_holdings: list) -> List[Dict]:
    """Parse FinAPI holdings into standard format."""
    holdings = []
    for h in raw_holdings:
        try:
            name = h.get("name", "").strip()
            if not name:
                continue
            sector = h.get("sector", "") or ""
            market_value_str = h.get("marketValue", "0").replace(",", "")
            weightage_str = h.get("weightage", "0").replace(",", "")

            try:
                weight = float(weightage_str)
            except (ValueError, TypeError):
                weight = 0.0

            # Skip zero or negative weight entries (futures, cash offsets)
            if weight <= 0:
                continue

            instrument = _classify_instrument(name, sector)

            holdings.append({
                "name": name,
                "sector": sector,
                "market_value": market_value_str,
                "weight": weight,
                "instrument": instrument,
            })
        except Exception:
            continue
    return holdings


def _classify_instrument(name: str, sector: str) -> str:
    """Classify a holding as equity, foreign equity, or non-equity."""
    name_lower = name.lower()
    sector_lower = sector.lower() if sector else ""

    # Non-equity indicators
    non_equity_keywords = [
        "treps", "treps_", "trp_", "tbill", "cash offset", "net receiv",
        "liquid", "parag parikh liquid", "reverse repo", "repo",
        "national bank", "export-import", "sidbi", "nabard",
        "future on", "august 2026 future", "september 2026 future",
    ]
    for kw in non_equity_keywords:
        if kw in name_lower:
            return "non_equity"

    # Foreign equity indicators (US/global stocks)
    foreign_keywords = [
        "alphabet", "amazon", "microsoft", "meta platforms", "apple",
        "netflix", "google", "facebook", "tesla", "nvidia",
        "berkshire", "johnson", "jpmorgan", "visa", "mastercard",
        "unitedhealth", "home depot", "bank of america",
    ]
    for kw in foreign_keywords:
        if kw in name_lower:
            return "foreign_equity"

    # REITs
    reit_keywords = ["reit", "embassy office", "brookfield india real estate"]
    for kw in reit_keywords:
        if kw in name_lower:
            return "equity"

    # If it has a sector, it's likely equity
    if sector_lower:
        return "equity"

    # Default to equity
    return "equity"


# ---------------------------------------------------------------------------
# FinAPI search by name (fallback when scheme code lookup is unavailable/fails)
# IMPORTANT: the query param is `schemeName`, NOT `q`. Using `q` returns HTTP 500.
# ---------------------------------------------------------------------------

def _fetch_holdings_finapi_by_name(scheme_name: str) -> Tuple[Optional[List[Dict]], str, Optional[str]]:
    """Search FinAPI by name, then fetch holdings for best match.
    Tries progressively shorter queries since long full names often return 0 results."""
    clean = scheme_name.replace(" - ", " ").strip()
    words = clean.split()
    # Build progressively shorter queries: full, first-4, first-3, first-2 words
    queries = [clean]
    for n in [4, 3, 2]:
        if len(words) > n:
            queries.append(" ".join(words[:n]))
    # Deduplicate preserving order
    seen = set()
    queries = [q for q in queries if not (q in seen or seen.add(q))]

    try:
        results = []
        for sq in queries:
            resp = requests.get(
                f"{FINAPI_BASE}/search",
                params={"schemeName": sq},
                headers={**HEADERS, "Accept": "application/json"},
                timeout=20,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            if data.get("status") != "success":
                continue
            results = data.get("data", [])
            if results:
                break
        if not results:
            return None, "FinAPI search: 0 results (tried: " + ", ".join(queries[:3]) + ")", None

        best_match = None
        best_score = -1
        for r in results:
            r_name = r.get("schemeName", "").lower()
            score = 0
            if "direct" in r_name:
                score += 10
            if "growth" in r_name:
                score += 10
            if "regular" in r_name:
                score -= 5
            if "idcw" in r_name or "dividend" in r_name:
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

        return None, "FinAPI search: no suitable match", None

    except Exception as e:
        return None, f"FinAPI search error: {str(e)[:100]}", None


# ---------------------------------------------------------------------------
# Holdings via mfdata.in (alternative free JSON API, no date)
# Flow: /schemes/{amfi_code} -> family_id -> /families/{family_id}/holdings
# ---------------------------------------------------------------------------

def fetch_holdings_mfdata(scheme_code: str) -> Tuple[Optional[List[Dict]], str, Optional[str]]:
    """Fetch holdings from mfdata.in."""
    try:
        resp = requests.get(
            f"{MFDATA_BASE}/schemes/{scheme_code}",
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            return None, f"mfdata.in scheme lookup HTTP {resp.status_code}", None

        data = resp.json()
        if data.get("status") != "success":
            return None, "mfdata.in scheme lookup failed", None

        scheme_data = data.get("data", {})
        if isinstance(scheme_data, list):
            scheme_data = scheme_data[0] if scheme_data else {}

        family_id = scheme_data.get("family_id") or scheme_data.get("familyId")
        if not family_id:
            return None, "mfdata.in: no family_id found", None

        resp2 = requests.get(
            f"{MFDATA_BASE}/families/{family_id}/holdings",
            headers=HEADERS,
            timeout=15,
        )
        if resp2.status_code != 200:
            return None, f"mfdata.in holdings HTTP {resp2.status_code}", None

        data2 = resp2.json()
        if data2.get("status") != "success":
            return None, "mfdata.in holdings failed", None

        holdings_data = data2.get("data", {})
        if isinstance(holdings_data, list):
            holdings_data = holdings_data[0] if holdings_data else {}
        raw_holdings = (holdings_data.get("equity_holdings", [])
                        or holdings_data.get("stocks", [])
                        or holdings_data.get("holdings", []))
        if not raw_holdings:
            return None, "mfdata.in returned 0 equity holdings", None

        holdings = []
        for h in raw_holdings:
            try:
                name = h.get("stock_name") or h.get("name") or h.get("company", "")
                if not name:
                    continue
                sector = h.get("sector", "") or ""
                weight_str = str(h.get("weightage") or h.get("weight") or h.get("percentage", "0")).replace(",", "")
                try:
                    weight = float(weight_str)
                except (ValueError, TypeError):
                    weight = 0.0
                if weight <= 0:
                    continue
                    holdings.append({
                    "name": name.strip(),
                    "sector": sector,
                    "market_value": str(h.get("market_value", "")),
                    "weight": weight,
                    "instrument": _classify_instrument(name, sector),
                })
            except Exception:
                continue
        if not holdings:
            return None, "mfdata.in holdings parsed to empty", None

        return holdings, "", None

    except requests.Timeout:
        return None, "mfdata.in: request timed out", None
    except Exception as e:
        return None, f"mfdata.in error: {str(e)[:100]}", None


# ---------------------------------------------------------------------------
# Holdings via Groww (HTML scrape, last resort — JS-rendered, rarely works)
# ---------------------------------------------------------------------------

def _clean_scheme_name_for_groww(scheme_name: str) -> str:
    """Clean scheme name for Groww URL slug generation."""
    name = scheme_name.lower()
    # Remove plan/option suffixes
    for suffix in [" - direct plan - growth", " - regular plan - growth",
                   " - direct plan growth", " - regular plan growth",
                   " - direct growth", " - regular growth",
                   " direct plan growth", " regular plan growth",
                   " direct growth", " regular growth"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.strip()


def _slugify(name: str) -> str:
    """Convert a fund name to a Groww-style URL slug."""
    slug = name.lower().strip()
    # Replace common patterns
    slug = re.sub(r'\s+', '-', slug)
    # Remove parentheses content
    slug = re.sub(r'\([^)]*\)', '', slug)
    # Remove non-alphanumeric except hyphens
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    # Collapse multiple hyphens
    slug = re.sub(r'-+', '-', slug)
    # Strip hyphens from ends
    slug = slug.strip('-')
    return slug


def _generate_groww_slug_variants(scheme_name: str) -> List[str]:
    """Generate multiple possible Groww URL slug variants for a fund."""
    clean = _clean_scheme_name_for_groww(scheme_name)
    variants = []
    # Direct slug
    slug = _slugify(clean)
    if slug:
        variants.append(slug)
    # Try with "fund" suffix removed
    if clean.endswith(" fund"):
        slug2 = _slugify(clean[:-5])
        if slug2 and slug2 not in variants:
            variants.append(slug2)
    # Try with "direct plan" variations
    base = clean.replace(" - direct plan - growth", "").replace(" direct plan growth", "")
    if base != clean:
        slug3 = _slugify(base)
        if slug3 and slug3 not in variants:
            variants.append(slug3)
    # Try removing "mutual fund" from name
    if "mutual fund" in clean:
        base2 = clean.replace("mutual fund", "").strip()
        slug4 = _slugify(base2)
        if slug4 and slug4 not in variants:
            variants.append(slug4)
    return variants


def fetch_holdings_groww(scheme_name: str) -> Tuple[Optional[List[Dict]], str]:
    """Fetch holdings from Groww (last resort — JS-rendered, rarely works)."""
    from bs4 import BeautifulSoup

    slugs = _generate_groww_slug_variants(scheme_name)
    for slug in slugs:
        url = f"https://groww.in/mutual-funds/{slug}"
        try:
            resp = requests.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=15)
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
    """Extract holdings from Groww's embedded JSON data."""
    holdings = []
    # Look for script tags with JSON data
    for script in soup.find_all("script"):
        text = script.string or ""
        if not text:
            continue
        # Try to find holdings JSON
        for pattern in [
            r'"holdings"\s*:\s*(\[.*?\])',
            r'"topHoldings"\s*:\s*(\[.*?\])',
            r'"stocks"\s*:\s*(\[.*?\])',
        ]:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    found = _extract_holdings_from_json(data)
                    if found:
                        return found
                except json.JSONDecodeError:
                    pass

    # Also try extracting from text content
    text = soup.get_text()
    for pattern in [
        r'"holdings"\s*:\s*(\[.*?\])',
        r'"topHoldings"\s*:\s*(\[.*?\])',
    ]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                found = _extract_holdings_from_json(data)
                if found:
                    return found
            except json.JSONDecodeError:
                pass
    return holdings


def _extract_holdings_from_json(data, depth=0) -> List[Dict]:
    """Recursively extract holdings from JSON data."""
    if depth > 10:
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
    """Parse a holdings array from Groww JSON."""
    holdings = []
    for h in arr:
        try:
            if isinstance(h, dict):
                name = h.get("stock_name") or h.get("name") or h.get("company") or h.get("stockName", "")
                if not name:
                    continue
                sector = h.get("sector", "") or h.get("sector_name", "") or ""
                weight_str = str(h.get("weightage") or h.get("weight") or h.get("percentage", "0")).replace(",", "")
                try:
                    weight = float(weight_str)
                except (ValueError, TypeError):
                    weight = 0.0
                if weight <= 0:
                    continue
                holdings.append({
                    "name": str(name).strip(),
                    "sector": str(sector),
                    "market_value": str(h.get("market_value", "")),
                    "weight": weight,
                    "instrument": _classify_instrument(str(name), str(sector)),
                })
        except Exception:
            continue
    return holdings if len(holdings) >= 3 else []


# ---------------------------------------------------------------------------
# Main holdings fetcher with fallback chain + date tracking
# ---------------------------------------------------------------------------

def fetch_holdings(scheme_name: str, scheme_code: str = None) -> Tuple[Optional[List[Dict]], str, Optional[str]]:
    """
    Fetch holdings for a fund, trying multiple sources.

    Returns (holdings_list, source_or_error, holdings_date).
    On success: (holdings, "FinAPI", "August 2026") etc.
    On failure: (None, error_detail, None).

    Try order:
    1. FinAPI by scheme code (primary — returns holdings + dated NAV)
    2. FinAPI by name search (fallback — progressively shorter queries)
    3. mfdata.in (alternative free API, no date)
    4. Groww (HTML scrape, last resort)
    """
    errors = []

    # 1. Try FinAPI by scheme code (primary — returns holdings + dated NAV)
    if scheme_code:
        holdings, err, date_str = fetch_holdings_finapi(scheme_code)
        if holdings:
            return holdings, "FinAPI", date_str
        errors.append(f"FinAPI(scheme {scheme_code}): {err}")

    # 2. Try FinAPI by name search (no scheme code, or scheme-code lookup failed)
    holdings, err, date_str = _fetch_holdings_finapi_by_name(scheme_name)
    if holdings:
        return holdings, "FinAPI (name search)", date_str
    errors.append(f"FinAPI(name): {err}")

    # 3. Try mfdata.in
    if scheme_code:
        holdings, err, _ = fetch_holdings_mfdata(scheme_code)
        if holdings:
            return holdings, "mfdata.in", None
        errors.append(f"mfdata.in: {err}")

    # 4. Try Groww (last resort)
    holdings, err = fetch_holdings_groww(scheme_name)
    if holdings:
        return holdings, "Groww", None
    errors.append(f"Groww: {err}")

    # All sources failed
    detail = " | ".join(errors)
    return None, f"All data sources failed: {detail}", None