"""
Mutual Fund data module — handles fund search and holdings retrieval.

Data sources (in priority order):
1. FinAPI (finapi.upvaly.com) — free JSON API. The scheme-code endpoint returns
   the full portfolio holdings (name, sector, marketValue, weightage) plus a
   latestNavDate that doubles as a holdings "as of" date. Zero auth.
   Docs: https://www.finapi.upvaly.com/
2. FinAPI name search — same API, looked up by scheme name when no scheme code
   is available. Uses the `schemeName` query param (NOT `q`).
3. mfdata.in — free JSON API for holdings via family-id lookup (no date).
4. AMFI NAV flat-file — used only to resolve/validate scheme codes; the AMFI
   portal does NOT expose per-scheme holdings JSON, so it is no longer used as a
   holdings source.
5. Groww — fallback HTML scraping (JS-rendered page; best-effort, no date).

All sources are free and require no API key.

NOTE (2026-08): The previous version called AMFI's DownloadSchemeData_Po.aspx
with invented params (mession/mession_code/mf/yr/myession) expecting a per-scheme
holdings table. That endpoint actually returns the full scheme master list (a
semicolon-delimited text dump), so it never contained holdings — which is why
"AMFI: no holdings found in last 3 months" fired for every fund. FinAPI's
scheme-code endpoint is the reliable holdings source and is now primary.
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
AMFI_SCHEME_MASTER_URL = "https://portal.amfiindia.com/DownloadSchemeData_Po.aspx?mf=0"

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
        resp = requests.get(f"{MFAPI_BASE}", timeout=30)
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

    Returns (holdings_list, error_msg, holdings_date).
    holdings_date is taken from the fund's latestNavDate when present.
    """
    try:
        resp = requests.get(
            f"{FINAPI_BASE}/scheme-code/{scheme_code}",
            params={"fields": "holdings"},
            headers={**HEADERS, "Accept": "application/json"},
            timeout=20,
        )
        if resp.status_code == 404:
            return None, f"FinAPI HTTP 404 (scheme code {scheme_code} not found)", None
        if resp.status_code == 429:
            return None, "FinAPI HTTP 429 (rate limited — retry shortly)", None
        if resp.status_code != 200:
            return None, f"FinAPI returned HTTP {resp.status_code}", None

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

    except requests.Timeout:
        return None, "FinAPI error: request timed out", None
    except Exception as e:
        return None, f"FinAPI error: {str(e)[:100]}", None


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
        if not isinstance(h, dict):
            continue
        name = h.get("name", "")
        sector = h.get("sector")
        if not sector or not isinstance(sector, str) or not sector.strip():
            sector = "N/A"
        weight = h.get("weightage") or h.get("weight") or h.get("percentage")
        instrument = _classify_instrument(name, sector)

        if name and weight is not None:
            try:
                weight_float = float(weight)
            except (ValueError, TypeError):
                continue
            if weight_float <= 0:
                continue
            holdings.append({
                "name": name,
                "sector": sector,
                "instrument": instrument,
                "weight": weight_float,
            })
    return holdings


def _classify_instrument(name: str, sector: str) -> str:
    """Classify a holding as Equity, Debt, Cash, etc. based on name/sector."""
    name_lower = name.lower()
    if any(w in name_lower for w in ["tbill", "treasury", "treps", "cblo", "repo", "reverse repo"]):
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
# FinAPI search by name (fallback when scheme code lookup is unavailable/fails)
# IMPORTANT: the query param is `schemeName`, NOT `q`. Using `q` returns HTTP 500.
# ---------------------------------------------------------------------------

def _fetch_holdings_finapi_by_name(scheme_name: str) -> Tuple[Optional[List[Dict]], str, Optional[str]]:
    """Search FinAPI by name, then fetch holdings for best match."""
    search_query = scheme_name.replace(" - ", " ").strip()
    try:
        resp = requests.get(
            f"{FINAPI_BASE}/search",
            params={"schemeName": search_query},
            headers={**HEADERS, "Accept": "application/json"},
            timeout=20,
        )
        if resp.status_code != 200:
            return None, f"FinAPI search HTTP {resp.status_code}", None

        data = resp.json()
        if data.get("status") != "success":
            return None, "FinAPI search failed", None

        results = data.get("data", [])
        if not results:
            return None, "FinAPI search: 0 results", None

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
            headers={**HEADERS, "Accept": "application/json"},
            timeout=20,
        )
        if resp.status_code != 200:
            return None, f"mfdata.in scheme lookup HTTP {resp.status_code}", None

        data = resp.json()
        if data.get("status") != "success":
            return None, "mfdata.in scheme lookup failed", None

        scheme_data = data.get("data", {})
        if isinstance(scheme_data, list):
            scheme_data = scheme_data[0] if scheme_data else {}
        family_id = scheme_data.get("family_id") or scheme_data.get("familyId") or scheme_data.get("family")
        if not family_id:
            return None, "mfdata.in: no family_id found", None

        resp2 = requests.get(
            f"{MFDATA_BASE}/families/{family_id}/holdings",
            headers={**HEADERS, "Accept": "application/json"},
            timeout=20,
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
            return None, "mfdata.in holdings parsed to empty", None

        return holdings, "", None

    except requests.Timeout:
        return None, "mfdata.in error: connection timed out", None
    except Exception as e:
        return None, f"mfdata.in error: {str(e)[:100]}", None


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

    On success: (holdings, "FinAPI", "August 2026") etc.
    On failure: (None, "Detailed error from all sources", None).
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

    # 3. Try mfdata.in (no date)
    if scheme_code:
        holdings, err, _ = fetch_holdings_mfdata(scheme_code)
        if holdings:
            return holdings, "mfdata.in", None
        errors.append(f"mfdata.in: {err}")

    # 4. Try Groww scraping (last resort, no date)
    holdings, err = fetch_holdings_groww(scheme_name)
    if holdings:
        return holdings, "Groww", None
    errors.append(err)

    # All sources failed
    detail = " | ".join(errors)
    return None, f"All data sources failed: {detail}", None
