"""
MF Return Estimator — Streamlit App
Estimates today's mutual fund return based on underlying holdings' price changes.

How it works:
1. User searches for any Indian mutual fund by name
2. App fetches the fund's portfolio holdings (from Groww)
3. Resolves each stock to an NSE ticker
4. Fetches current-day price changes via Yahoo Finance
5. Computes weighted return = sum(holding_weight × stock_change_pct)

Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
from datetime import datetime

from mf_data import search_funds, fetch_holdings, get_fund_nav, get_fund_meta
from stock_data import resolve_ticker, fetch_price_changes


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="MF Return Estimator",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1f4e79;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1rem;
        color: #666;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background: white;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        text-align: center;
    }
    .positive {
        color: #16a34a;
        font-weight: 700;
    }
    .negative {
        color: #dc2626;
        font-weight: 700;
    }
    .neutral {
        color: #666;
        font-weight: 600;
    }
    .stDataFrame {
        width: 100%;
    }
    .info-banner {
        background: #eff6ff;
        border-left: 4px solid #3b82f6;
        padding: 10px 15px;
        border-radius: 5px;
        margin: 10px 0;
        font-size: 0.9rem;
        color: #1e40af;
    }
    .warning-banner {
        background: #fffbeb;
        border-left: 4px solid #f59e0b;
        padding: 10px 15px;
        border-radius: 5px;
        margin: 10px 0;
        font-size: 0.9rem;
        color: #92400e;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown('<div class="main-header">📈 MF Return Estimator</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Estimate today\'s mutual fund return from underlying stock holdings</div>', unsafe_allow_html=True)

st.markdown("""
<div class="info-banner">
    🔍 <b>How it works:</b> Enter a fund name → App fetches its holdings → Resolves each stock to an NSE ticker → 
    Fetches today's price changes → Computes the weighted estimated return.
    <br>⚠️ This is an <b>estimate</b> based on the latest disclosed holdings (monthly). Actual MF NAV may differ due to 
    cash positions, recent trades, and debt holdings.
</div>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Initialize session state
# ---------------------------------------------------------------------------

if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "selected_fund" not in st.session_state:
    st.session_state.selected_fund = None
if "holdings_data" not in st.session_state:
    st.session_state.holdings_data = None
if "holdings_source" not in st.session_state:
    st.session_state.holdings_source = None
if "price_data" not in st.session_state:
    st.session_state.price_data = None
if "computed_results" not in st.session_state:
    st.session_state.computed_results = None


# ---------------------------------------------------------------------------
# Sidebar: Fund Search
# ---------------------------------------------------------------------------

st.sidebar.markdown("### 🔎 Search Mutual Fund")

search_query = st.sidebar.text_input(
    "Enter fund name",
    placeholder="e.g. ICICI Prudential FlexiCap",
    help="Type the fund name and click Search. Try to include the AMC name for better results."
)

search_btn = st.sidebar.button("🔍 Search Funds", type="primary", use_container_width=True)

if search_btn and search_query:
    with st.sidebar.spinner("Searching funds..."):
        results = search_funds(search_query, limit=15)
        st.session_state.search_results = results
    if not results:
        st.sidebar.warning("No funds found. Try a different search term.")

# Display search results
if st.session_state.search_results:
    st.sidebar.markdown(f"**Found {len(st.session_state.search_results)} funds**")
    
    fund_options = []
    for r in st.session_state.search_results:
        label = r["scheme_name"]
        fund_options.append((label, r["scheme_code"]))
    
    selected_label = st.sidebar.selectbox(
        "Select a fund",
        options=range(len(fund_options)),
        format_func=lambda i: fund_options[i][0],
    )
    
    if st.sidebar.button("📊 Analyze Fund", type="primary", use_container_width=True):
        st.session_state.selected_fund = {
            "name": fund_options[selected_label][0],
            "code": fund_options[selected_label][1],
        }
        # Reset previous results
        st.session_state.holdings_data = None
        st.session_state.price_data = None
        st.session_state.computed_results = None


# ---------------------------------------------------------------------------
# Main content: Fund Analysis
# ---------------------------------------------------------------------------

if st.session_state.selected_fund:
    fund = st.session_state.selected_fund
    fund_name = fund["name"]
    fund_code = fund["code"]
    
    st.markdown(f"### 📋 {fund_name}")
    
    # Fetch fund metadata
    col1, col2, col3 = st.columns(3)
    
    with col1:
        with st.spinner("Fetching NAV..."):
            nav_val, nav_date = get_fund_nav(fund_code)
        if nav_val:
            st.metric("Latest NAV", f"₹{float(nav_val):.4f}", delta=f"as on {nav_date}")
        else:
            st.metric("Latest NAV", "N/A")
    
    with col2:
        meta = get_fund_meta(fund_code)
        fund_house = meta.get("fund_house", "N/A")
        st.metric("Fund House", fund_house[:25])
    
    with col3:
        scheme_type = meta.get("scheme_type", "N/A")
        st.metric("Scheme Type", scheme_type[:25])
    
    st.divider()
    
    # --- Step 1: Fetch holdings ---
    if st.session_state.holdings_data is None:
        with st.spinner("Fetching portfolio holdings..."):
            holdings, source = fetch_holdings(fund_name, fund_code)
        
        if holdings:
            st.session_state.holdings_data = holdings
            st.session_state.holdings_source = source
            st.success(f"✅ Found {len(holdings)} holdings (Source: {source})")
        else:
            st.error(f"❌ Could not fetch holdings: {source}")
            st.markdown("""
            <div class="warning-banner">
                Try searching with a slightly different fund name, or check if the fund is very new.
                You can also try the fund's exact name from <a href="https://groww.in/mutual-funds">Groww</a>.
            </div>
            """, unsafe_allow_html=True)
    
    # --- Step 2: Resolve tickers and fetch prices ---
    if st.session_state.holdings_data:
        holdings = st.session_state.holdings_data
        
        # Show holdings summary
        st.markdown(f"#### Portfolio Holdings ({len(holdings)} instruments)")
        
        # Filter to equity holdings only (price changes are meaningful for stocks)
        equity_holdings = [h for h in holdings if h.get("instrument", "").lower() in ["equity", "stock"]]
        non_equity = [h for h in holdings if h.get("instrument", "").lower() not in ["equity", "stock"]]
        
        if non_equity:
            st.caption(f"ℹ️ {len(equity_holdings)} equity holdings + {len(non_equity)} non-equity (debt/cash/repo) — only equity is used for return estimation.")
        
        if st.button("🚀 Fetch Live Prices & Estimate Return", type="primary"):
            # Resolve tickers
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
                st.warning(f"⚠️ Could not resolve tickers for {len(unresolved)} holdings: {', '.join(unresolved[:5])}{'...' if len(unresolved) > 5 else ''}")
            
            resolved_holdings = [h for h in equity_holdings if h["name"] in ticker_map]
            
            if not resolved_holdings:
                st.error("❌ No holdings could be resolved to NSE tickers. The fund may hold stocks not in our database.")
            else:
                # Fetch prices
                all_tickers = list(set(ticker_map.values()))
                with st.spinner(f"Fetching today's prices for {len(all_tickers)} stocks..."):
                    price_data = fetch_price_changes(all_tickers)
                
                st.session_state.price_data = price_data
                
                # Compute weighted return
                results = []
                total_weight_used = 0
                total_weight_unresolved = 0
                positive_contributors = []
                negative_contributors = []
                
                for h in equity_holdings:
                    name = h["name"]
                    weight = h["weight"]
                    ticker = ticker_map.get(name)
                    
                    if ticker and ticker in price_data:
                        pd_data = price_data[ticker]
                        change_pct = pd_data["change_pct"]
                        contribution = (weight / 100) * change_pct
                        total_weight_used += weight
                        
                        if change_pct > 0:
                            positive_contributors.append((name, change_pct, weight, contribution, ticker, pd_data["curr_price"]))
                        elif change_pct < 0:
                            negative_contributors.append((name, change_pct, weight, contribution, ticker, pd_data["curr_price"]))
                        
                        results.append({
                            "Company": name,
                            "Ticker": ticker,
                            "Sector": h.get("sector", "N/A"),
                            "Weight %": weight,
                            "Prev Close (₹)": round(pd_data["prev_close"], 2),
                            "Current (₹)": round(pd_data["curr_price"], 2),
                            "Change %": round(change_pct, 2),
                            "Contribution %": round(contribution, 4),
                        })
                    else:
                        total_weight_unresolved += weight
                        results.append({
                            "Company": name,
                            "Ticker": "N/A" if not ticker else ticker,
                            "Sector": h.get("sector", "N/A"),
                            "Weight %": weight,
                            "Prev Close (₹)": "N/A",
                            "Current (₹)": "N/A",
                            "Change %": "N/A",
                            "Contribution %": "N/A",
                        })
                
                # Sort results by weight descending
                results.sort(key=lambda x: x["Weight %"], reverse=True)
                st.session_state.computed_results = {
                    "results": results,
                    "total_weight_used": total_weight_used,
                    "total_weight_unresolved": total_weight_unresolved,
                    "positive_contributors": positive_contributors,
                    "negative_contributors": negative_contributors,
                }
        
        # Display results
        if st.session_state.computed_results:
            comp = st.session_state.computed_results
            results = comp["results"]
            total_weight_used = comp["total_weight_used"]
            total_weight_unresolved = comp["total_weight_unresolved"]
            pos = comp["positive_contributors"]
            neg = comp["negative_contributors"]
            
            # --- Estimated return ---
            estimated_return = sum(r["Contribution %"] for r in results if isinstance(r["Contribution %"], (int, float)))
            coverage = total_weight_used / (total_weight_used + total_weight_unresolved) * 100 if (total_weight_used + total_weight_unresolved) > 0 else 0
            
            st.divider()
            st.markdown("### 📊 Estimated Today's Return")
            
            # Big metric
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                if estimated_return > 0:
                    st.metric("Estimated Return", f"+{estimated_return:.3f}%", delta="Positive 📈", delta_color="normal")
                elif estimated_return < 0:
                    st.metric("Estimated Return", f"{estimated_return:.3f}%", delta="Negative 📉", delta_color="inverse")
                else:
                    st.metric("Estimated Return", f"{estimated_return:.3f}%", delta="Neutral", delta_color="off")
            
            with col2:
                st.metric("Portfolio Coverage", f"{coverage:.1f}%")
            
            with col3:
                st.metric("Gainers", f"{len(pos)} stocks", delta=f"+{sum(p[1] for p in pos):.2f}%" if pos else "0")
            
            with col4:
                st.metric("Losers", f"{len(neg)} stocks", delta=f"{sum(n[1] for n in neg):.2f}%" if neg else "0", delta_color="inverse" if neg else "off")
            
            if coverage < 90:
                st.markdown(f"""
                <div class="warning-banner">
                    ⚠️ Only {coverage:.1f}% of the portfolio could be resolved to stock tickers. 
                    The estimate may not be fully accurate. Unresolved holdings ({100 - coverage:.1f}% of portfolio) are excluded.
                </div>
                """, unsafe_allow_html=True)
            
            # --- Detailed table ---
            st.markdown("### 📋 Holdings with Price Changes")
            
            df = pd.DataFrame(results)
            
            # Color-code the Change % and Contribution % columns
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Change %": st.column_config.NumberColumn(
                        format="%.2f%%",
                        help="Today's price change for this stock"
                    ),
                    "Contribution %": st.column_config.NumberColumn(
                        format="%.4f%%",
                        help="This stock's contribution to the fund's return = weight × change%"
                    ),
                    "Weight %": st.column_config.NumberColumn(format="%.2f%%"),
                },
            )
            
            # --- Top contributors ---
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 🟢 Top Positive Contributors")
                if pos:
                    pos.sort(key=lambda x: x[3], reverse=True)
                    pos_df = pd.DataFrame(pos[:10], columns=["Company", "Change %", "Weight %", "Contribution %", "Ticker", "Price (₹)"])
                    pos_df["Change %"] = pos_df["Change %"].round(2)
                    pos_df["Weight %"] = pos_df["Weight %"].round(2)
                    pos_df["Contribution %"] = pos_df["Contribution %"].round(4)
                    pos_df["Price (₹)"] = pos_df["Price (₹)"].round(2)
                    st.dataframe(pos_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No positive contributors today.")
            
            with col2:
                st.markdown("#### 🔴 Top Negative Contributors")
                if neg:
                    neg.sort(key=lambda x: x[3])
                    neg_df = pd.DataFrame(neg[:10], columns=["Company", "Change %", "Weight %", "Contribution %", "Ticker", "Price (₹)"])
                    neg_df["Change %"] = neg_df["Change %"].round(2)
                    neg_df["Weight %"] = neg_df["Weight %"].round(2)
                    neg_df["Contribution %"] = neg_df["Contribution %"].round(4)
                    neg_df["Price (₹)"] = neg_df["Price (₹)"].round(2)
                    st.dataframe(neg_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No negative contributors today.")
            
            # --- Download as CSV ---
            st.divider()
            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Download Holdings & Returns as CSV",
                data=csv,
                file_name=f"mf_returns_{fund_name.replace(' ', '_').lower()}.csv",
                mime="text/csv",
                use_container_width=True,
            )

else:
    # No fund selected — show instructions
    st.markdown("""
    ### 👈 Get Started
    
    1. **Search for a mutual fund** using the sidebar on the left
    2. **Select a fund** from the search results
    3. **Click "Analyze Fund"** to fetch its holdings
    4. **Click "Fetch Live Prices & Estimate Return"** to see today's estimated return
    
    ---
    
    ### 💡 Example searches
    - `ICICI Prudential FlexiCap`
    - `HDFC Mid Cap`
    - `SBI Small Cap`
    - `Axis Bluechip`
    - `Parag Parikh Flexi Cap`
    - `Mirae Asset Large Cap`
    
    ### 📐 How the return is calculated
    
    The estimated return is computed as:
    
    **Estimated Return = Σ (Holding Weight × Stock's Daily Change %)**
    
    For example, if TVS Motor (9.29% weight) is down -0.81% today, its contribution to the fund's return is:
    
    `9.29% × (-0.81%) = -0.0752%`
    
    Summing all such contributions gives the estimated fund return for the day.
    
    ### ⚠️ Limitations
    
    - Holdings are disclosed **monthly** by AMCs. The fund may have traded since the last disclosure.
    - **Debt, cash, and repo holdings** are excluded from the calculation (only equity is used).
    - Some stocks (especially recently listed ones) may not be in the ticker database.
    - This is an **estimate**, not the actual NAV return. Use it as a directional indicator.
    """)

st.divider()
st.caption("📊 MF Return Estimator | Data: mfapi.in, Groww, Yahoo Finance | Built with Streamlit")
