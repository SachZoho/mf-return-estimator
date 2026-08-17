"""Stock data: resolve Indian/foreign stock names to tickers, fetch price changes."""
import re, time, csv, io, os, requests, yfinance as yf, pandas as pd
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher
import warnings; warnings.filterwarnings("ignore")

_nse_companies=None; _exact_map=None; _token_map=None

FOREIGN_STOCKS={"alphabet inc class a":"GOOGL","alphabet inc class c":"GOOG","alphabet inc":"GOOGL","alphabet":"GOOGL","amazon.com inc":"AMZN","amazon com inc":"AMZN","amazon.com":"AMZN","amazon":"AMZN","microsoft corp":"MSFT","microsoft corporation":"MSFT","microsoft":"MSFT","meta platforms inc class a":"META","meta platforms inc class c":"META","meta platforms inc":"META","meta platforms":"META","meta":"META","apple inc":"AAPL","apple":"AAPL","netflix inc":"NFLX","netflix":"NFLX","nvidia corp":"NVDA","nvidia corporation":"NVDA","nvidia":"NVDA","tesla inc":"TSLA","tesla":"TSLA","oracle corp":"ORCL","oracle corporation":"ORCL","oracle":"ORCL","adobe inc":"ADBE","adobe":"ADBE","salesforce inc":"CRM","salesforce":"CRM","intel corp":"INTC","intel corporation":"INTC","intel":"INTC","cisco systems":"CSCO","cisco":"CSCO","qualcomm inc":"QCOM","qualcomm":"QCOM","broadcom inc":"AVGO","broadcom":"AVGO","advanced micro devices":"AMD","amd":"AMD","paypal holdings":"PYPL","paypal":"PYPL","berkshire hathaway":"BRK-B","johnson and johnson":"JNJ","jpmorgan chase":"JPM","visa inc":"V","visa":"V","goldman sachs":"GS","bank of america":"BAC","wells fargo":"WFC","morgan stanley":"MS","hsbc holdings":"HSBC","hsbc":"HSBC","walt disney":"DIS","disney":"DIS","costco wholesale":"COST","costco":"COST","procter and gamble":"PG","coca cola":"KO","coca-cola":"KO","pepsi co":"PEP","pepsico":"PEP","mcdonald":"MCD","starbucks":"SBUX","nike":"NKE","walmart":"WMT","target":"TGT","home depot":"HD","pfizer":"PFE","abbott laboratories":"ABT","merck":"MRK","eli lilly":"LLY","astrazeneca plc":"AZN","novartis ag":"NVS","sanofi sa":"SNY","nestle sa":"NSRGY","unilever plc":"UL","unilever":"UL","spotify technology":"SPOT","spotify":"SPOT","shopify inc":"SHOP","shopify":"SHOP","uber technologies":"UBER","uber":"UBER","airbnb inc":"ABNB","airbnb":"ABNB","snowflake inc":"SNOW","snowflake":"SNOW","palantir technologies":"PLTR","palantir":"PLTR","crowdstrike holdings":"CRWD","crowdstrike":"CRWD","sap se":"SAP","sap":"SAP","samsung electronics":"005930.KS","samsung":"005930.KS","alibaba group":"BABA","alibaba":"BABA","tencent holdings":"0700.HK","tencent":"0700.HK","toyota motor":"TM","toyota":"TM"}

REIT_MAP={"embassy office parks":"EMBASSY.NS","embassy office parks reit":"EMBASSY.NS","embassy reit":"EMBASSY.NS","brookfield india real estate":"BIRET.NS","brookfield india real estate trust":"BIRET.NS","brookfield india reit":"BIRET.NS","brookfield reit":"BIRET.NS","mindspace business parks":"MINDSPACE.NS","mindspace business parks reit":"MINDSPACE.NS","mindspace reit":"MINDSPACE.NS","nexsquare offices":"NEXSQUARE.NS","nexsquare reit":"NEXSQUARE.NS"}

SKIP_PATTERNS=["cash offset","net receivables","net payables","t-bill","tbill","t bill","cblo","commercial paper","certificate of deposit","reverse repo","repo","parag parikh liquid","future on","august 2026 future","september 2026 future","october 2026 future","november 2026 future","december 2026 future","future","treasury","trs_","trp_","national bank for agriculture","small industries development bank","small industries dev bank","export-import bank","export import bank","development bank","net current assets","margin money","security deposits"]

def _should_skip(name):
    nl=name.lower().strip()
    for p in SKIP_PATTERNS:
        if p in nl: return True
    if re.search(r'\(\d{2}/\d{2}/\d{4}\)',name): return True
    if re.search(r'\d{4}\s+future',nl): return True
    return False

def _normalize(name):
    name=name.lower().strip().rstrip(".")
    name=re.sub(r'\([^)]*\)','',name).strip()
    name=name.replace("corp.","corporation").replace(" corp "," corporation ")
    name=name.replace("co.","company").replace(" co "," company ")
    name=name.replace("pharms","pharmaceutical")
    name=name.replace("labs","laboratories").replace("lab ","laboratories ")
    name=name.replace("tech.","technologies").replace(" tech "," technologies ")
    name=name.replace("&","and")
    for s in ["ltd.","ltd","limited","pvt.","pvt","inc.","inc","plc","sa","se","ag","reit","ordinary"]:
        name=re.sub(r'\b'+re.escape(s)+r'\b','',name)
    name=re.sub(r'[^\w\s-]','',name)
    name=re.sub(r'\s+',' ',name).strip()
    return name

def _tokenize(name): return sorted(_normalize(name).split())
def _token_set_ratio(a,b):
    sa,sb=set(a),set(b)
    if not sa or not sb: return 0.0
    return len(sa&sb)/len(sa|sb)

def _load_nse_companies():
    global _nse_companies,_exact_map,_token_map
    if _nse_companies is not None: return
    _exact_map={}; _token_map={}; _nse_companies=[]
    csv_content=None
    # 1: bundled CSV in same dir
    p=os.path.join(os.path.dirname(os.path.abspath(__file__)),"nse_companies.csv")
    if os.path.exists(p):
        try:
            with open(p,"r",encoding="utf-8") as f: csv_content=f.read()
        except: pass
    # 2: GitHub raw URLs (not blocked on cloud platforms)
    if not csv_content:
        for url in ["https://raw.githubusercontent.com/sachzoho/mf-return-estimator/main/nse_companies.csv","https://raw.githubusercontent.com/swagat2001/systematic_sector_rotation/main/NSE_sector_wise_data/EQUITY_L.csv"]:
            try:
                r=requests.get(url,timeout=15,headers={"User-Agent":"Mozilla/5.0"})
                r.raise_for_status()
                csv_content=r.text
                if "symbol" in csv_content.lower() or "SYMBOL" in csv_content: break
            except: pass
    # 3: NSE direct (often blocked on cloud)
    if not csv_content:
        try:
            r=requests.get("https://archives.nseindia.com/content/equities/EQUITY_L.csv",headers={"User-Agent":"Mozilla/5.0","Accept":"text/csv"},timeout=15)
            r.raise_for_status(); csv_content=r.text
        except: pass
    if not csv_content: return
    try:
        for row in csv.DictReader(io.StringIO(csv_content)):
            sym=row.get("symbol",row.get("SYMBOL","")).strip()
            nm=row.get("name",row.get("NAME OF COMPANY","")).strip()
            if not sym or not nm: continue
            _nse_companies.append({"symbol":sym,"name":nm})
            n=_normalize(nm); _exact_map[n]=sym
            if n.startswith("the "): _exact_map[n[4:]]=sym
            t=frozenset(_tokenize(nm))
            if t: _token_map[t]=sym
    except: pass

_yahoo_cache={}
def _yahoo_search(name):
    if name in _yahoo_cache: return _yahoo_cache[name]
    try:
        r=requests.get("https://query2.finance.yahoo.com/v1/finance/search",params={"q":name,"quotesCount":10,"newsCount":0,"enableFuzzyQuery":True},headers={"User-Agent":"Mozilla/5.0"},timeout=8)
        qs=r.json().get("quotes",[]); ns=[]; bo=[]
        for q in qs:
            s=q.get("symbol",""); e=q.get("exchange",""); qt=q.get("quoteType","")
            if qt!="EQUITY": continue
            if s.endswith(".NS") or e=="NSI": ns.append(s)
            elif s.endswith(".BO") or e=="BSE": bo.append(s)
        res=ns[0] if ns else (bo[0] if bo else None)
        _yahoo_cache[name]=res; return res
    except:
        _yahoo_cache[name]=None; return None

def resolve_ticker(company_name):
    if not company_name or not company_name.strip(): return None
    name=company_name.strip(); nl=name.lower().strip()
    if _should_skip(name): return None
    if nl in FOREIGN_STOCKS: return FOREIGN_STOCKS[nl]
    norm=_normalize(name)
    if norm in FOREIGN_STOCKS: return FOREIGN_STOCKS[norm]
    for rn,ticker in REIT_MAP.items():
        if rn in nl: return ticker
    _load_nse_companies()
    if norm in _exact_map: return _exact_map[norm]+".NS"
    tokens=_tokenize(name); ts=frozenset(tokens)
    if ts and ts in _token_map: return _token_map[ts]+".NS"
    if _nse_companies:
        best=0.0; best_sym=None
        for nn,sym in _exact_map.items():
            s1=SequenceMatcher(None,norm,nn).ratio()
            s2=_token_set_ratio(tokens,sorted(nn.split()))
            sc=max(s1,s2)
            if sc>best: best=sc; best_sym=sym
        if best>=0.60: return best_sym+".NS"
    result=_yahoo_search(name)
    if result: return result
    return None

def resolve_tickers(holdings):
    resolved=[]; unresolved=[]
    for h in holdings:
        name=h.get("name",""); ticker=resolve_ticker(name)
        if ticker:
            item=dict(h); item["ticker"]=ticker; resolved.append(item)
        elif _should_skip(name): pass
        else: unresolved.append(h)
    return resolved,unresolved

def fetch_price_changes(tickers,batch_size=10):
    results={}; unique=list(set(tickers))
    for i in range(0,len(unique),batch_size):
        for ticker in unique[i:i+batch_size]:
            try:
                t=yf.Ticker(ticker); hist=t.history(period="5d")
                if len(hist)>=2:
                    cp=float(hist["Close"].iloc[-1]); pc=float(hist["Close"].iloc[-2])
                    chg=((cp-pc)/pc*100) if pc>0 else 0.0
                    results[ticker]={"curr_price":cp,"prev_close":pc,"change_pct":chg}
                elif len(hist)==1:
                    cp=float(hist["Close"].iloc[-1])
                    results[ticker]={"curr_price":cp,"prev_close":cp,"change_pct":0.0}
            except: pass
        if i+batch_size<len(unique): time.sleep(0.3)
    return results
