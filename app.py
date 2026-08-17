"""
MF Return Estimator - Streamlit App
Two modes:
  1. Search MF - search by fund name, view holdings and estimated return
  2. Load from Sheet - load multiple MFs from a Google Sheet, see summary table
"""

import streamlit as st
import pandas as pd
import requests
import re
import io
import plotly.express as px
import plotly.graph_objects as go
from collections import defaultdict

from mf_data import search_funds, fetch_holdings, get_fund_nav, get_fund_meta
from stock_data import resolve_ticker, fetch_price_changes
from mf_helpers import compute_fund_return, render_fund_detail


st.set_page_config(
    page_title="MF Return Estimator",
    page_icon="chart_with_upwards_trend",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- Theme detection: use Streamlit's built-in Light/Dark switcher ---
# (the three-dot menu top right). This JS snippet detects the active theme
# and writes it to the URL query param so Plotly charts can adapt.
import streamlit.components.v1 as components

components.html("""
<script>
    function detectTheme() {
        try {
            var el = window.parent.document.querySelector('[data-testid="stAppViewContainer"]')
                  || window.parent.document.querySelector('.stApp');
            if (!el) return 'light';
            var bg = window.getComputedStyle(el).backgroundColor;
            var m = bg.match(/\d+/g);
            if (m && parseInt(m[0]) < 50) return 'dark';
            return 'light';
        } catch(e) { return 'light'; }
    }
    var theme = detectTheme();
    try {
        var url = new URL(window.parent.location.href);
        if (url.searchParams.get('st_theme') !== theme) {
            url.searchParams.set('st_theme', theme);
            window.parent.history.replaceState({}, '', url);
        }
    } catch(e) {}
</script>
""", height=0, width=0)

# --- Google Analytics 4 Integration (Measurement ID: G-WGVCPVK4H6) ---
# Loads gtag.js directly inside this iframe - no window.parent access needed
# Uses components.html (not st.markdown) because st.markdown strips script tags
_lt = chr(60)
ga_script = (
    _lt + "script async src='https://www.googletagmanager.com/gtag/js?id=G-WGVCPVK4H6'" + _lt + "/script" + chr(62)
    + _lt + "script" + chr(62)
    + "window.dataLayer=window.dataLayer||[];"
    + "function gtag(){dataLayer.push(arguments);}"
    + "gtag('js',new Date());"
    + "gtag('config','G-WGVCPVK4H6',{page_title:'MF Return Estimator',page_location:window.location.href});"
    + _lt + "/script" + chr(62)
)
components.html(ga_script, height=0, width=0)

# Read detected theme for Plotly chart templates
_detected_theme = st.query_params.get("st_theme", "light")
st.session_state["theme_mode"] = "Dark" if _detected_theme == "dark" else "Light"

# Show app title in Streamlit's own header bar, left side, stays while scrolling
# Also hide Fork/GitHub button and Streamlit footer/profile links
# IMPORTANT: Keep the three-dot menu (stMainMenu) visible - it has theme selector
_lt = chr(60)
st.markdown(_lt + "style" + chr(62) +
    # Title in header bar - gradient blue/purple for attractiveness
    '[data-testid="stHeader"]::before {'
    ' content: "MF Return Estimator";'
    ' font-size: 1.15rem;'
    ' font-weight: 800;'
    ' margin-left: 1rem;'
    ' margin-right: auto;'
    ' white-space: nowrap;'
    ' background: linear-gradient(135deg, #00b4d8, #7209b7);'
    ' -webkit-background-clip: text;'
    ' -webkit-text-fill-color: transparent;'
    ' background-clip: text;'
    ' }'
    # Hide Fork button + GitHub repo link in header (keep three-dot menu!)
    ' [data-testid="stHeaderContent"] a[href*="github"], '
    ' [data-testid="stHeaderContent"] a[href*="fork"], '
    ' [data-testid="stHeader"] a[target="_blank"], '
    ' .stGithubFork, '
    ' [data-testid="stGitFork"], '
    ' [data-testid="stGithubFork"] {'
    ' display: none !important;'
    ' }'
    # Hide Streamlit profile button + hosted-by text at bottom right
    ' [data-testid="stProfileLink"], '
    ' .stProfileLink, [data-testid="stStatusWidget"], '
    ' footer [data-testid="stMarkdownContainer"], '
    ' .stDeployButton, [data-testid="stDeployButton"] {'
    ' display: none !important;'
    ' }'
    # Hide the streamlit footer entirely
    ' footer, .stFooter, [data-testid="stFooter"], '
    ' [data-testid="stBottom"] {'
    ' display: none !important;'
    ' }'
    + _lt + "/style" + chr(62),
    unsafe_allow_html=True)

# Also use JS to remove Fork/GitHub link and footer (CSS alone may not catch all)
components.html("""
<script>
function cleanup() {
    try {
        var doc = window.parent.document;
        // Remove Fork button and GitHub repo link from header
        var headerLinks = doc.querySelectorAll('[data-testid="stHeader"] a, [data-testid="stHeaderContent"] a');
        headerLinks.forEach(function(a) {
            var href = (a.href || '').toLowerCase();
            var text = (a.textContent || '').toLowerCase();
            if (href.indexOf('github') >= 0 || text.indexOf('fork') >= 0) {
                a.style.display = 'none';
            }
        });
        // Remove footer / profile / deploy buttons
        var footer = doc.querySelector('footer');
        if (footer) footer.style.display = 'none';
        var profile = doc.querySelector('[data-testid="stProfileLink"]');
        if (profile) profile.style.display = 'none';
        var status = doc.querySelector('[data-testid="stStatusWidget"]');
        if (status) status.style.display = 'none';
        var bottom = doc.querySelector('[data-testid="stBottom"]');
        if (bottom) bottom.style.display = 'none';
    } catch(e) {}
}
cleanup();
setInterval(cleanup, 1000);
</script>
""", height=0, width=0)

tab_search, tab_sheet = st.tabs(["Search MF", "Load from Sheet"])



# =======================================================================
# TAB 1: Search MF (original flow)
# =======================================================================

with tab_search:
    st.info(
        "How it works: Enter a fund name, the app fetches its holdings, "
        "resolves each stock to an NSE ticker, fetches today's price changes, "
        "and computes the weighted estimated return."
    )

    if "search_results" not in st.session_state:
        st.session_state.search_results = []
    if "selected_fund" not in st.session_state:
        st.session_state.selected_fund = None
    if "holdings_data" not in st.session_state:
        st.session_state.holdings_data = None
    if "holdings_source" not in st.session_state:
        st.session_state.holdings_source = None
    if "holdings_date" not in st.session_state:
        st.session_state.holdings_date = None
    if "price_data" not in st.session_state:
        st.session_state.price_data = None
    if "computed_results" not in st.session_state:
        st.session_state.computed_results = None

    st.markdown("---")

    col_search, col_btn = st.columns([4, 1])
    with col_search:
        search_query = st.text_input("Search Mutual Fund", placeholder="Type a fund name... e.g. ICICI Prudential FlexiCap", label_visibility="collapsed")
    with col_btn:
        search_btn = st.button("Search", type="primary", use_container_width=True)

    if search_btn and search_query:
        with st.spinner("Searching funds..."):
            results = search_funds(search_query, limit=15)
            st.session_state.search_results = results
            st.session_state.selected_fund = None
            st.session_state.holdings_data = None
            st.session_state.price_data = None
            st.session_state.computed_results = None
        if not results:
            st.warning("No funds found. Try a different search term.")

    if not st.session_state.search_results and not st.session_state.selected_fund:
        st.markdown("**Try these popular funds:**")
        suggestion_cols = st.columns(6)
        suggestions = ["ICICI Prudential FlexiCap", "Parag Parikh Flexi Cap", "HDFC Mid Cap", "SBI Small Cap", "Axis Bluechip", "Mirae Asset Large Cap"]
        for i, suggestion in enumerate(suggestions):
            col = suggestion_cols[i % 6]
            if col.button(suggestion, key=f"sugg_{i}"):
                with st.spinner("Searching..."):
                    results = search_funds(suggestion, limit=15)
                    st.session_state.search_results = results
                    st.session_state.selected_fund = None
                    st.session_state.holdings_data = None
                    st.session_state.computed_results = None
                st.rerun()

    if st.session_state.search_results and not st.session_state.selected_fund:
        st.markdown(f"#### Found {len(st.session_state.search_results)} matching funds")
        st.caption("Click a fund below to analyze it")
        fund_options = [(r["scheme_name"], r["scheme_code"]) for r in st.session_state.search_results]
        for idx, (label, code) in enumerate(fund_options):
            col_name, col_btn2 = st.columns([5, 1])
            with col_name:
                st.markdown(f"**{idx + 1}.** {label}")
            with col_btn2:
                if st.button("Select", key=f"select_{idx}", use_container_width=True):
                    st.session_state.selected_fund = {"name": label, "code": code}
                    st.session_state.holdings_data = None
                    st.session_state.price_data = None
                    st.session_state.computed_results = None
                    st.rerun()
        st.markdown("---")

    if st.session_state.selected_fund:
        fund = st.session_state.selected_fund
        fund_name = fund["name"]
        fund_code = fund["code"]
        if st.button("Search a different fund"):
            st.session_state.selected_fund = None
            st.session_state.holdings_data = None
            st.session_state.computed_results = None
            st.rerun()

        col1, col2, col3 = st.columns(3)
        with col1:
            with st.spinner("Fetching NAV..."):
                nav_val, nav_date = get_fund_nav(fund_code)
        with col2:
            meta = get_fund_meta(fund_code)
            fund_house = meta.get("fund_house", "N/A")
        with col3:
            scheme_type = meta.get("scheme_type", "N/A")

        if st.session_state.holdings_data is None:
            with st.spinner("Fetching portfolio holdings..."):
                holdings, source, holdings_date = fetch_holdings(fund_name, fund_code)
            if holdings:
                st.session_state.holdings_data = holdings
                st.session_state.holdings_source = source
                st.session_state.holdings_date = holdings_date
                date_info = f" (as of {holdings_date})" if holdings_date else ""
                st.success(f"Found {len(holdings)} holdings (Source: {source}{date_info})")
            else:
                st.error("Could not fetch holdings.")
                with st.expander("Technical details (click to expand)", expanded=False):
                    st.code(source, language="text")

        if st.session_state.holdings_data:
            holdings = st.session_state.holdings_data
            holdings_date = st.session_state.get("holdings_date")
            equity_holdings = [h for h in holdings if h.get("instrument", "").lower() in ("equity", "stock", "foreign equity")]

            st.markdown("---")
            st.markdown("### Estimate Today's Return")

            if st.button("Fetch Live Prices & Estimate Return", type="primary"):
                with st.spinner("Resolving stock tickers..."):
                    ticker_map = {}
                    unresolved = []
                    for h in equity_holdings:
                        ticker = resolve_ticker(h["name"])
                        if ticker:
                            ticker_map[h["name"]] = ticker
                        else:
                            unresolved.append(h["name"])
                if unresolved:
                    st.warning(f"Could not resolve tickers for {len(unresolved)} holdings: {', '.join(unresolved[:5])}{'...' if len(unresolved) > 5 else ''}")
                resolved_holdings = [h for h in equity_holdings if h["name"] in ticker_map]
                if resolved_holdings:
                    all_tickers = list(set(ticker_map.values()))
                    with st.spinner(f"Fetching today's prices for {len(all_tickers)} stocks..."):
                        price_data = fetch_price_changes(all_tickers)
                    st.session_state.price_data = price_data
                    results = []
                    total_weight_used = 0
                    total_weight_unresolved = 0
                    for h in equity_holdings:
                        name = h["name"]
                        weight = h["weight"]
                        ticker = ticker_map.get(name)
                        if ticker and ticker in price_data:
                            pd_data = price_data[ticker]
                            change_pct = pd_data["change_pct"]
                            contribution = (weight / 100) * change_pct
                            total_weight_used += weight
                            results.append({"name": name, "ticker": ticker, "weight": weight, "change_pct": change_pct, "contribution": contribution, "prev_close": pd_data["prev_close"], "curr_price": pd_data["curr_price"]})
                        else:
                            total_weight_unresolved += weight
                    if results:
                        total_estimated_return = sum(r["contribution"] for r in results)
                        coverage = total_weight_used / (total_weight_used + total_weight_unresolved) * 100 if (total_weight_used + total_weight_unresolved) > 0 else 0
                        if total_estimated_return >= 0:
                            st.success(f"Estimated Today's Return: +{total_estimated_return:.4f}%")
                        else:
                            st.error(f"Estimated Today's Return: {total_estimated_return:.4f}%")
                        st.caption(f"Based on {len(results)} resolved holdings covering {coverage:.1f}% of portfolio weight.")

                        col_pos, col_neg = st.columns(2)
                        with col_pos:
                            st.markdown("#### Top Positive Contributors")
                            pos = sorted([(r["name"], r["contribution"]) for r in results if r["contribution"] > 0], key=lambda x: x[1], reverse=True)
                            for name, contrib in pos[:5]:
                                st.markdown(f"**{name}**: +{contrib:.4f}%")
                        with col_neg:
                            st.markdown("#### Top Negative Contributors")
                            neg = sorted([(r["name"], r["contribution"]) for r in results if r["contribution"] < 0], key=lambda x: x[1])
                            for name, contrib in neg[:5]:
                                st.markdown(f"**{name}**: {contrib:.4f}%")

                        results_df = pd.DataFrame(results)
                        results_df = results_df[["name", "ticker", "weight", "prev_close", "curr_price", "change_pct", "contribution"]].rename(columns={
                            "name": "Company", "ticker": "Ticker", "weight": "Weight (%)",
                            "prev_close": "Prev Close", "curr_price": "Current Price",
                            "change_pct": "Change (%)", "contribution": "Contribution",
                        })
                        results_df = results_df.sort_values("Contribution", ascending=False)
                        st.markdown("#### Detailed Breakdown")
                        st.dataframe(results_df, use_container_width=True, hide_index=True, column_config={
                            "Weight (%)": st.column_config.NumberColumn(format="%.2f%%"),
                            "Change (%)": st.column_config.NumberColumn(format="%.2f%%"),
                            "Contribution": st.column_config.NumberColumn(format="%.4f%%"),
                        })
                        top15 = results_df.head(15)
                        fig_water = go.Figure(go.Waterfall(
                            x=top15["Company"], y=top15["Contribution"], orientation="v",
                            connector={"line": {"color": "#ccc"}},
                            increasing={"marker": {"color": "#10b981"}},
                            decreasing={"marker": {"color": "#ef4444"}},
                        ))
                        _tmpl = "plotly_dark" if st.session_state.get("theme_mode") == "Dark" else "plotly_white"
                        fig_water.update_layout(title="Contribution Waterfall (Top 15 by Impact)", yaxis_title="Contribution (%)", height=400, margin=dict(l=20, r=20, t=40, b=80), template=_tmpl)
                        fig_water.update_xaxes(tickangle=45)
                        st.plotly_chart(fig_water, use_container_width=True)

            st.markdown("---")
            nav_float = None
            try:
                nav_float = float(nav_val) if nav_val else None
            except (ValueError, TypeError):
                pass
            render_fund_detail(fund_name, fund_code, holdings, st.session_state.holdings_source, holdings_date, nav_float, None, None)

    if not st.session_state.search_results and not st.session_state.selected_fund:
        st.markdown(
            """
            ### Get Started

            Type a fund name in the search box above, or click one of the suggestion buttons.

            ---

            ### How the return is calculated

            **Estimated Return = Sum (Holding Weight x Stock's Daily Change %)**

            For example, if TVS Motor (9.29% weight) is down -0.81% today, its contribution to the fund's return is:

            `9.29% x (-0.81%) = -0.0752%`

            Summing all such contributions gives the estimated fund return for the day.

            ### Limitations

            - Holdings are disclosed **monthly** by AMCs. The fund may have traded since the last disclosure.
            - **Debt, cash, and repo holdings** are excluded from the calculation (only equity is used).
            - Some stocks may not be in the ticker database.
            - This is an **estimate**, not the actual NAV return.
            """
        )


# =======================================================================
# TAB 2: Load from Sheet
# =======================================================================

with tab_sheet:
    if "sheet_mf_list" not in st.session_state:
        st.session_state.sheet_mf_list = []
    if "sheet_mf_results" not in st.session_state:
        st.session_state.sheet_mf_results = None
    if "sheet_detail_idx" not in st.session_state:
        st.session_state.sheet_detail_idx = None

    if st.session_state.sheet_detail_idx is not None and st.session_state.sheet_mf_results:
        idx = st.session_state.sheet_detail_idx
        results = st.session_state.sheet_mf_results
        if idx >= len(results):
            st.session_state.sheet_detail_idx = None
            st.rerun()

        result = results[idx]
        if st.button("Back to Summary", type="secondary"):
            st.session_state.sheet_detail_idx = None
            st.rerun()

        render_fund_detail(
            result["name"], result.get("code", ""),
            result.get("holdings", []), None,
            result.get("holdings_date"), result.get("nav"),
            result.get("day_change"), result.get("return_details"),
        )
        if result.get("error"):
            st.warning(f"Note: {result['error']}")

    else:
        st.markdown("### Load MFs from Google Sheet")
        st.caption(
            "Enter the URL of a public Google Sheet (anyone with link can view) "
            "that has a tab named 'mf' with your fund list."
        )

        col_url, col_load = st.columns([5, 1])
        with col_url:
            sheet_url_input = st.text_input(
                "Google Sheet URL",
                placeholder="https://docs.google.com/spreadsheets/d/...",
                key="sheet_url_field",
                label_visibility="collapsed",
            )
        with col_load:
            load_btn = st.button("Load", type="primary", use_container_width=True)

        if load_btn and sheet_url_input:
            with st.spinner("Loading MFs from Google Sheet..."):
                match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url_input)
                if not match:
                    st.error("Could not extract Sheet ID from URL.")
                else:
                    sheet_id = match.group(1)
                    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=mf"
                    try:
                        resp = requests.get(csv_url, timeout=30)
                        resp.raise_for_status()
                        df = pd.read_csv(io.StringIO(resp.text))
                        if df.empty:
                            st.error("No data found in the 'mf' tab.")
                        else:
                            name_col = None
                            code_col = None
                            for col in df.columns:
                                cl = col.lower().strip()
                                if cl in ("scheme_name", "scheme name", "name", "fund_name", "fund name", "mf name", "mf_name"):
                                    name_col = col
                                if cl in ("scheme_code", "scheme code", "code", "amfi_code", "amfi code", "amfi"):
                                    code_col = col
                            if not name_col:
                                name_col = df.columns[0]
                            mf_list = []
                            for _, row in df.iterrows():
                                name = str(row[name_col]).strip()
                                code = ""
                                if code_col:
                                    raw_code = str(row[code_col]).strip()
                                    if raw_code and raw_code.lower() not in ("nan", "none", ""):
                                        code = raw_code
                                if name and name.lower() not in ("nan", "none", ""):
                                    mf_list.append({"name": name, "code": code})
                            st.session_state.sheet_mf_list = mf_list
                            st.session_state.sheet_mf_results = None
                            st.session_state.sheet_detail_idx = None
                            st.success(f"Loaded {len(mf_list)} MFs from sheet.")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Failed to load sheet: {str(e)[:100]}")

        if st.session_state.sheet_mf_list:
            st.markdown("---")
            st.markdown("### Fetch Returns for All MFs")

            col_fetch, col_refresh, col_count = st.columns([2, 2, 2])
            with col_fetch:
                fetch_btn = st.button("Fetch All Returns", type="primary", key="sheet_fetch_btn")
            with col_refresh:
                refresh_btn = st.button("Refresh (Re-fetch)", type="secondary", key="sheet_refresh_btn")
            with col_count:
                st.metric("MFs Loaded", len(st.session_state.sheet_mf_list))

            if fetch_btn or refresh_btn:
                mf_list = st.session_state.sheet_mf_list
                results = []
                progress = st.progress(0, "Starting...")

                for i, mf in enumerate(mf_list):
                    pct = (i + 1) / len(mf_list)
                    progress.progress(pct, text=f"Processing {i + 1}/{len(mf_list)}: {mf['name'][:50]}...")

                    result = {
                        "name": mf["name"], "code": mf["code"],
                        "nav": None, "day_change": None,
                        "holdings_count": 0, "holdings": [],
                        "holdings_date": None, "return_details": [],
                        "error": None,
                    }

                    scheme_code = mf["code"]
                    if not scheme_code:
                        sr = search_funds(mf["name"], limit=5)
                        if sr:
                            best = max(sr, key=lambda x: x.get("score", 0))
                            scheme_code = str(best["scheme_code"])
                            result["code"] = scheme_code

                    if not scheme_code:
                        result["error"] = "Could not find scheme code"
                        results.append(result)
                        continue

                    nav_val, nav_date = get_fund_nav(scheme_code)
                    if nav_val:
                        try:
                            result["nav"] = float(nav_val)
                        except (ValueError, TypeError):
                            pass

                    try:
                        holdings, source, holdings_date = fetch_holdings(mf["name"], scheme_code)
                        if holdings:
                            result["holdings"] = holdings
                            result["holdings_count"] = len(holdings)
                            result["holdings_date"] = holdings_date
                            day_change, return_details = compute_fund_return(holdings)
                            result["day_change"] = day_change
                            result["return_details"] = return_details
                        else:
                            result["error"] = source or "No holdings found"
                    except Exception as e:
                        result["error"] = str(e)[:100]

                    results.append(result)

                progress.progress(1.0, "Done!")
                st.session_state.sheet_mf_results = results
                st.rerun()

            if st.session_state.sheet_mf_results:
                results = st.session_state.sheet_mf_results
                st.markdown("---")
                st.markdown("### Summary - All MF Returns")

                summary_rows = []
                for i, r in enumerate(results):
                    change = r.get("day_change")
                    nav = r.get("nav")
                    summary_rows.append({
                        "#": i + 1,
                        "MF Name": r["name"],
                        "Holdings": r.get("holdings_count", 0),
                        "Day Change (%)": round(change, 4) if change is not None else None,
                        "Current NAV": round(nav, 4) if nav else None,
                        "Holdings As Of": r.get("holdings_date") or "Unknown",
                        "Status": "OK" if not r.get("error") else f"Error: {r['error'][:40]}",
                    })
                summary_df = pd.DataFrame(summary_rows)

                st.dataframe(
                    summary_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Day Change (%)": st.column_config.NumberColumn(
                            format="%.4f%%",
                            help="Estimated return based on underlying stock holdings",
                        ),
                        "Current NAV": st.column_config.NumberColumn(format="Rs. %.4f"),
                        "Holdings": st.column_config.NumberColumn(help="Click View Holdings below to see detail"),
                    },
                )

                st.markdown("---")
                st.markdown("### View Holdings Detail")
                st.caption("Select an MF and click the button to view its full holdings breakdown.")

                fund_names = [f"{i + 1}. {r['name'][:60]}" for i, r in enumerate(results)]
                selected_idx = st.selectbox(
                    "Select an MF to view its holdings",
                    range(len(results)),
                    format_func=lambda i: fund_names[i],
                    key="sheet_detail_selectbox",
                )

                col_view, col_back = st.columns([1, 3])
                with col_view:
                    if st.button("View Holdings", type="primary", use_container_width=True, key="sheet_view_btn"):
                        st.session_state.sheet_detail_idx = selected_idx
                        st.rerun()

                st.markdown("---")
                col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                with col_s1:
                    total_mfs = len(results)
                    ok_count = sum(1 for r in results if not r.get("error"))
                    st.metric("MFs Loaded", f"{ok_count}/{total_mfs}")
                with col_s2:
                    avg_vals = [r["day_change"] for r in results if r.get("day_change") is not None]
                    avg_change = sum(avg_vals) / len(avg_vals) if avg_vals else 0
                    st.metric("Avg Day Change", f"{avg_change:+.4f}%")
                with col_s3:
                    gainers = sum(1 for v in avg_vals if v > 0)
                    st.metric("Gainers", gainers)
                with col_s4:
                    losers = sum(1 for v in avg_vals if v < 0)
                    st.metric("Losers", losers)
            else:
                st.info("Click 'Fetch All Returns' to load holdings, NAV, and estimated returns for all MFs in your sheet.")

        else:
            st.info(
                "Enter a Google Sheet URL above to get started. "
                "The sheet should have a tab named 'mf' with your fund list."
            )
