"""
Stock data module — resolves Indian stock names to NSE tickers
and fetches current-day price changes via yfinance.
"""

import re
import time
import yfinance as yf
import pandas as pd
import requests
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# NSE Ticker Dictionary
# Maps common fund holding names to Yahoo Finance (.NS) tickers.
# Covers ~250+ stocks that frequently appear in Indian MF portfolios.
# ---------------------------------------------------------------------------

_TICKER_MAP_RAW = {
    # Large caps - Banks & Financials
    "icici bank": "ICICIBANK.NS",
    "icici bank ltd": "ICICIBANK.NS",
    "hdfc bank": "HDFCBANK.NS",
    "hdfc bank ltd": "HDFCBANK.NS",
    "state bank of india": "SBIN.NS",
    "axis bank": "AXISBANK.NS",
    "axis bank ltd": "AXISBANK.NS",
    "kotak mahindra bank": "KOTAKBANK.NS",
    "kotak mahindra bank ltd": "KOTAKBANK.NS",
    "indusind bank": "INDUSINDBK.NS",
    "yes bank": "YESBANK.NS",
    "punjab national bank": "PNB.NS",
    "bank of baroda": "BANKBARODA.NS",
    "canara bank": "CANBK.NS",
    "idbi bank": "IDBI.NS",
    "federal bank": "FEDERALBNK.NS",
    "rbl bank": "RBLBANK.NS",
    "bandhan bank": "BANDHANBNK.NS",
    "au small finance bank": "AUBANK.NS",

    # Financial services
    "bajaj finance": "BAJFINANCE.NS",
    "bajaj finserv": "BAJAJFINSV.NS",
    "sbi life insurance": "SBILIFE.NS",
    "sbi life insurance company ltd": "SBILIFE.NS",
    "hdfc life insurance": "HDFCLIFE.NS",
    "hdfc life insurance company": "HDFCLIFE.NS",
    "icici prudential life insurance": "ICICIPRULI.NS",
    "icici lombard": "ICICIGI.NS",
    "icici lombard general insurance": "ICICIGI.NS",
    "cholamandalam investment & finance": "CHOLAFIN.NS",
    "cholamandalam investment and finance company ltd": "CHOLAFIN.NS",
    "cholamandalam investment and finance": "CHOLAFIN.NS",
    "shriram finance": "SHRIRAMFIN.NS",
    "bajaj holdings & investment": "BAJAJHLDNG.NS",
    "life insurance corporation of india": "LICI.NS",
    "lic of india": "LICI.NS",
    "max financial services": "MFSL.NS",
    "max financial services ltd": "MFSL.NS",
    "hdfc asset management": "HDFCAMC.NS",
    "hdfc asset management company ltd": "HDFCAMC.NS",
    "hdfc asset management company": "HDFCAMC.NS",
    "prudent corporate advisory services": "PRUDENT.NS",
    "prudent corporate advisory services ltd": "PRUDENT.NS",
    "iifl wealth management": "IIFLWAM.NS",
    "iifl wealth management ltd": "IIFLWAM.NS",
    "360 one wam": "360ONE.NS",
    "360 one wam ltd": "360ONE.NS",
    "360 one wam ltd ordinary shares": "360ONE.NS",
    "pb fintech": "POLICYBZR.NS",
    "pb fintech ltd": "POLICYBZR.NS",

    # IT / Technology
    "infosys": "INFY.NS",
    "infosys ltd": "INFY.NS",
    "tata consultancy services": "TCS.NS",
    "tata consultancy services ltd": "TCS.NS",
    "wipro": "WIPRO.NS",
    "wipro ltd": "WIPRO.NS",
    "hcl technologies": "HCLTECH.NS",
    "hcl technologies ltd": "HCLTECH.NS",
    "tech mahindra": "TECHM.NS",
    "tech mahindra ltd": "TECHM.NS",
    "ltimindtree": "LTIM.NS",
    "lti mindtree": "LTIM.NS",
    "mphasis": "MPHASIS.NS",
    "mphasis ltd": "MPHASIS.NS",
    "coforge": "COFORGE.NS",
    "coforge ltd": "COFORGE.NS",
    "persistent systems": "PERSISTENT.NS",
    "bharti airtel": "BHARTIARTL.NS",
    "bharti airtel ltd": "BHARTIARTL.NS",
    "tata elxsi": "TATAELXSI.NS",
    "netweb technologies": "NETWEB.NS",
    "netweb technologies india": "NETWEB.NS",
    "netweb technologies india ltd": "NETWEB.NS",
    "sonata software": "SONATSOFTW.NS",
    "ce info systems": "CEINFO.NS",
    "ce info systems ltd": "CEINFO.NS",
    "ce info systems (mapmyindia)": "CEINFO.NS",
    "sagility": "SAGILITY.NS",
    "sagility ltd": "SAGILITY.NS",
    "tbo tek": "TBOTEK.NS",
    "tbo tek ltd": "TBOTEK.NS",

    # Automobile
    "tvs motor company": "TVSMOTOR.NS",
    "tvs motor company ltd": "TVSMOTOR.NS",
    "maruti suzuki india": "MARUTI.NS",
    "maruti suzuki india ltd": "MARUTI.NS",
    "tata motors": "TATAMOTORS.NS",
    "tata motors ltd": "TATAMOTORS.NS",
    "mahindra & mahindra": "M&M.NS",
    "mahindra and mahindra": "M&M.NS",
    "mahindra & mahindra ltd": "M&M.NS",
    "mahindra and mahindra ltd": "M&M.NS",
    "eicher motors": "EICHERMOT.NS",
    "eicher motors ltd": "EICHERMOT.NS",
    "bajaj auto": "BAJAJ-AUTO.NS",
    "hero motocorp": "HEROMOTOCO.NS",
    "ashok leyland": "ASHOKLEY.NS",
    "sundaram clayton": "SCLT.NS",
    "sundaram-clayton": "SCLT.NS",
    "sundaram - clayton dcd": "SCLT.NS",
    "sundaram - clayton dcd ltd": "SCLT.NS",
    "sharda motor industries": "SHARDAMOTR.NS",
    "sharda motor industries ltd": "SHARDAMOTR.NS",
    "sona blw precision": "SONACOMS.NS",
    "sona blw precision forgings": "SONACOMS.NS",
    "sona blw precision forgings ltd": "SONACOMS.NS",
    "samvardhana motherson": "MOTHERSON.NS",
    "samvardhana motherson international": "MOTHERSON.NS",
    "samvardhana motherson international ltd": "MOTHERSON.NS",
    "motherson sumi wiring": "MSUMI.NS",
    "motherson sumi wiring india": "MSUMI.NS",
    "motherson sumi wiring india ltd": "MSUMI.NS",
    "tvs holdings": "TVSHOLDINGS.NS",
    "tvs holdings ltd": "TVSHOLDINGS.NS",
    "bosch": "BOSCHLTD.NS",
    "bosch ltd": "BOSCHLTD.NS",
    "endurance technologies": "ENDURANCE.NS",
    "marico": "MARICO.NS",

    # Consumer
    "avenue supermarts": "DMART.NS",
    "avenue supermarts ltd": "DMART.NS",
    "trent": "TRENT.NS",
    "trent ltd": "TRENT.NS",
    "britannia industries": "BRITANNIA.NS",
    "britannia industries ltd": "BRITANNIA.NS",
    "hindustan unilever": "HINDUNILVR.NS",
    "hindustan unilever ltd": "HINDUNILVR.NS",
    "itc": "ITC.NS",
    "itc ltd": "ITC.NS",
    "nestle india": "NESTLEIND.NS",
    "varun beverages": "VBL.NS",
    "tata consumer products": "TATACONSUM.NS",
    "godrej consumer products": "GODREJCP.NS",
    "dabur india": "DABUR.NS",
    "radico khaitan": "RADICO.NS",
    "radico khaitan ltd": "RADICO.NS",
    "united spirits": "UNITDSPR.NS",
    "pearl global industries": "PGIL.NS",
    "pearl global industries ltd": "PGIL.NS",
    "safari industries": "SAFARI.NS",
    "safari industries (india) ltd": "SAFARI.NS",
    "safari industries (india)": "SAFARI.NS",
    "sai silks": "KALAMANDIR.NS",
    "sai silks (kalamandir) ltd": "KALAMANDIR.NS",
    "sai silks (kalamandir)": "KALAMANDIR.NS",

    # Consumer discretionary / Retail
    "fsn e-commerce ventures": "NYKAA.NS",
    "fsn e-commerce ventures ltd": "NYKAA.NS",
    "fsn e-commerce ventures ltd (nykaa)": "NYKAA.NS",
    "tata technologies": "TATATECH.NS",
    "lg electronics india": "LGEL.NS",
    "lg electronics india ltd": "LGEL.NS",
    "international gemmological institute": "IGIL.NS",
    "international gemmological institute (india) ltd": "IGIL.NS",
    "ethos": "ETHOSLTD.NS",
    "ethos ltd": "ETHOSLTD.NS",
    "redtape": "REDTAPE.NS",
    "redtape ltd": "REDTAPE.NS",
    "lenskart solutions": "LENSKART.NS",
    "lenskart solutions ltd": "LENSKART.NS",
    "pvr inox": "PVRINOX.NS",
    "pvr inox ltd": "PVRINOX.NS",
    "chalet hotels": "CHALET.NS",
    "chalet hotels ltd": "CHALET.NS",

    # Industrials / Capital Goods
    "larsen & toubro": "LT.NS",
    "larsen & toubro ltd": "LT.NS",
    "larsen and toubro": "LT.NS",
    "larsen and toubro ltd": "LT.NS",
    "siemens": "SIEMENS.NS",
    "siemens ltd": "SIEMENS.NS",
    "abb india": "ABB.NS",
    "cummins india": "CUMMINSIND.NS",
    "blue star": "BLUESTARCO.NS",
    "blue star ltd": "BLUESTARCO.NS",
    "pg electroplast": "PGEL.NS",
    "pg electroplast ltd": "PGEL.NS",
    "azad engineering": "AZAD.NS",
    "azad engineering ltd": "AZAD.NS",
    "omnitech engineering": "OMNITECH.NS",
    "omnitech engineering ltd": "OMNITECH.NS",
    "sedemac mechatronics": "SEDEMAC.NS",
    "sedemac mechatronics ltd": "SEDEMAC.NS",
    "kaynes technology": "KAYNES.NS",
    "kaynes technology india": "KAYNES.NS",
    "kaynes technology india ltd": "KAYNES.NS",
    "crizac": "CRIZAC.NS",
    "crizac ltd": "CRIZAC.NS",
    "interglob aviation": "INDIGO.NS",
    "interglob aviation ltd": "INDIGO.NS",
    "interglobe aviation": "INDIGO.NS",
    "interglobe aviation ltd": "INDIGO.NS",
    "travel food services": "TFS.NS",
    "travel food services ltd": "TFS.NS",
    "shadowfax technologies": "SHADOWFAX.NS",
    "shadowfax technologies ltd": "SHADOWFAX.NS",
    "talwandi sabo power": "TSPL.NS",
    "talwandi sabo power ltd": "TSPL.NS",
    "vedanta power": "VEDL.NS",
    "vedanta power ltd": "VEDL.NS",
    "vedanta aluminium metal": "VEDL.NS",
    "vedanta aluminium metal ltd": "VEDL.NS",
    "vedanta oil and gas": "VEDL.NS",
    "vedanta oil and gas ltd": "VEDL.NS",
    "vedanta iron and steel": "VEDL.NS",
    "vedanta iron and steel ltd": "VEDL.NS",
    "vedanta": "VEDL.NS",
    "vedanta ltd": "VEDL.NS",
    "physicswallah": "PHYSICSWALLAH.NS",
    "physicswallah ltd": "PHYSICSWALLAH.NS",

    # Materials / Metals / Cement
    "ultratech cement": "ULTRACEMCO.NS",
    "ultratech cement ltd": "ULTRACEMCO.NS",
    "shree cement": "SHREECEM.NS",
    "grasim industries": "GRASIM.NS",
    "ambuja cements": "AMBUJACEM.NS",
    "tata steel": "TATASTEEL.NS",
    "tata steel ltd": "TATASTEEL.NS",
    "jsw steel": "JSWSTEEL.NS",
    "jindal steel & power": "JINDALSTEL.NS",
    "jindal steel and power": "JINDALSTEL.NS",
    "jindal steel & power ltd": "JINDALSTEL.NS",
    "jindal steel and power ltd": "JINDALSTEL.NS",
    "jindal steel": "JINDALSTEL.NS",
    "hindalco industries": "HINDALCO.NS",
    "hindalco": "HINDALCO.NS",
    "hindalco industries ltd": "HINDALCO.NS",
    "vedanta aluminium": "VEDL.NS",
    "hindustan zinc": "HINDZINC.NS",
    "coal india": "COALINDIA.NS",
    "national aluminium": "NATIONALUM.NS",
    "ratnamani metals & tubes": "RATNAMANI.NS",
    "ratnamani metals and tubes": "RATNAMANI.NS",
    "ratnamani metals & tubes ltd": "RATNAMANI.NS",
    "apar industries": "APARIND.NS",
    "apar industries ltd": "APARIND.NS",
    "pi industries": "PIIND.NS",
    "pi industries ltd": "PIIND.NS",
    "upl": "UPL.NS",
    "upl ltd": "UPL.NS",
    "srf": "SRF.NS",
    "srf ltd": "SRF.NS",
    "century plyboards": "CENTURYPLY.NS",
    "century plyboards (india) ltd": "CENTURYPLY.NS",
    "century plyboards (india)": "CENTURYPLY.NS",
    "greenpanel industries": "GREENPANEL.NS",
    "greenpanel industries ltd": "GREENPANEL.NS",

    # Healthcare
    "sun pharmaceutical": "SUNPHARMA.NS",
    "sun pharmaceutical industries": "SUNPHARMA.NS",
    "sun pharmaceutical industries ltd": "SUNPHARMA.NS",
    "sun pharma": "SUNPHARMA.NS",
    "dr reddy's laboratories": "DRREDDY.NS",
    "dr reddys laboratories": "DRREDDY.NS",
    "cipla": "CIPLA.NS",
    "cipla ltd": "CIPLA.NS",
    "divi's laboratories": "DIVISLAB.NS",
    "divis laboratories": "DIVISLAB.NS",
    "apollo hospitals": "APOLLOHOSP.NS",
    "apollo hospitals enterprise": "APOLLOHOSP.NS",
    "max healthcare": "MAXHEALTH.NS",
    "max healthcare institute": "MAXHEALTH.NS",
    "neuland laboratories": "NEULANDLAB.NS",
    "neuland laboratories ltd": "NEULANDLAB.NS",
    "vijaya diagnostic centre": "VIJAYA.NS",
    "vijaya diagnostic centre ltd": "VIJAYA.NS",
    "syngene international": "SYNGENE.NS",
    "syngene international ltd": "SYNGENE.NS",
    "lal pathlabs": "LALPATHLAB.NS",

    # Energy / Oil & Gas
    "reliance industries": "RELIANCE.NS",
    "reliance industries ltd": "RELIANCE.NS",
    "oil & natural gas corporation": "ONGC.NS",
    "oil and natural gas corporation": "ONGC.NS",
    "indian oil corporation": "IOC.NS",
    "bharat petroleum": "BPCL.NS",
    "hindustan petroleum": "HINDPETRO.NS",
    "gail india": "GAIL.NS",
    "ntpc": "NTPC.NS",
    "power grid corporation": "POWERGRID.NS",
    "tata power": "TATAPOWER.NS",
    "adani green energy": "ADANIGREEN.NS",
    "adani power": "ADANIPOWER.NS",
    "adani enterprises": "ADANIENT.NS",

    # Telecom / Media
    "idea cellular": "IDEA.NS",
    "vodafone idea": "IDEA.NS",
    "zee entertainment": "ZEEL.NS",
    "sun tv network": "SUNTV.NS",
    "network18 media": "NETWORK18.NS",
    "tips music": "TIPSMUSIC.NS",
    "sony pictures networks": "SONYPICS.NS",

    # Construction / Real Estate
    "dlf": "DLF.NS",
    "godrej properties": "GODREJPROP.NS",
    "oberoi realty": "OBEROIRLTY.NS",
    "prestige estates": "PRESTIGE.NS",
    "phoenix mills": "PHOENIXLTD.NS",
    "mahanagar gas": "MGL.NS",
    "indraprastha gas": "IGL.NS",
    "gujarat gas": "GUJGASLTD.NS",

    # Chemicals / Fertilizers
    "coromandel international": "COROMANDEL.NS",
    "chambal fertilisers": "CHAMBLFERT.NS",
    "deepak nitrite": "DEEPAKNTR.NS",
    "aarti industries": "AARTIIND.NS",
    "tata chemicals": "TATACHEM.NS",
    "pidilite industries": "PIDILITIND.NS",
    "asian paints": "ASIANPAINT.NS",
    "berger paints": "BERGEPAINT.NS",

    # Retail / E-commerce / New age
    "zomato": "ETERNAL.NS",
    "zomato ltd": "ETERNAL.NS",
    "eternal": "ETERNAL.NS",
    "eternal ltd": "ETERNAL.NS",
    "paytm": "PAYTM.NS",
    "one 97 communications": "PAYTM.NS",
    "delhivery": "DELHIVERY.NS",
    "cartrade tech": "CARTRADE.NS",
    "indiamart intermesh": "INDIAMART.NS",
    "nykaa": "NYKAA.NS",
    "fsn e-commerce": "NYKAA.NS",

    # Real estate / Infra
    "irb infrastructure developers": "IRB.NS",
    "engineers india": "ENGINERSIN.NS",
    "rites": "RITES.NS",
    "rail vikas nigam": "RVNL.NS",
    "irfc": "IRFC.NS",
    "ircon international": "IRCON.NS",
    "hudco": "HUDCO.NS",
    "rec": "RECLTD.NS",
    "power finance corporation": "PFC.NS",
    "muthoot finance": "MUTHOOTFIN.NS",

    # Misc
    "rolex rings": "ROLEXRINGS.NS",
    "rolex rings ltd": "ROLEXRINGS.NS",
    "aditya birla fashion": "ABFRL.NS",
    "titan company": "TITAN.NS",
    "titan": "TITAN.NS",
    "titan company ltd": "TITAN.NS",

    # Telecom equipment
    "itd cementation india": "ITDCEM.NS",
    "tejas networks": "TEJAS.NS",

    # Diversified
    "tata investment corporation": "TATAINVEST.NS",
    "aditya birla sun life amc": "ABSLAMC.NS",
    "shriram asset management": "SHRIRAMAMC.NS",
    "utiamc": "UTIAMC.NS",
    "aditya birla real estate": "ABREL.NS",

    # New IPOs / Recent additions
    "brainbees solutions": "FIRSTCRY.NS",
    "firstcry": "FIRSTCRY.NS",
    "smartworks": "SMARTWORKS.NS",

    # Autos / 2W / CV
    "bajaj auto ltd": "BAJAJ-AUTO.NS",
    "force motors": "FORCEMOTORS.NS",
    "maruti suzuki": "MARUTI.NS",
    "maruti": "MARUTI.NS",
    "tata technologies ltd": "TATATECH.NS",
    "ashok leyland ltd": "ASHOKLEY.NS",
}


def _normalize(name: str) -> str:
    """Normalize a company name for lookup."""
    name = name.lower().strip()
    for suffix in ["ltd.", "ltd", "limited", "co.", "co", "company", "corporation", "corp"]:
        name = name.replace(suffix, "")
    name = re.sub(r'[^\w\s&-]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


_TICKER_MAP = {}
for k, v in _TICKER_MAP_RAW.items():
    _TICKER_MAP[_normalize(k)] = v
    _TICKER_MAP[k] = v


def resolve_ticker(company_name: str) -> Optional[str]:
    """
    Resolve an Indian company name to a Yahoo Finance (.NS) ticker.
    Returns the ticker (e.g. 'TVSMOTOR.NS') or None if not found.
    """
    norm = _normalize(company_name)
    if norm in _TICKER_MAP:
        return _TICKER_MAP[norm]

    lower = company_name.lower().strip()
    if lower in _TICKER_MAP:
        return _TICKER_MAP[lower]

    cleaned = re.sub(r'\b(ltd|limited|co|company|corporation|corp)\b\.?', '', lower)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if cleaned in _TICKER_MAP:
        return _TICKER_MAP[cleaned]
    cleaned_norm = _normalize(cleaned)
    if cleaned_norm in _TICKER_MAP:
        return _TICKER_MAP[cleaned_norm]

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


def fetch_price_changes(tickers: List[str]) -> Dict[str, Dict]:
    """
    Fetch current-day price change for a list of tickers using yfinance.
    Returns dict: {ticker: {"prev_close": float, "curr_price": float, "change_pct": float}}

    Strategy: batch download (fast), then retry missing individually (resilient).
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

        return {
            "prev_close": prev_close,
            "curr_price": curr_price,
            "change_pct": change_pct,
        }
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
