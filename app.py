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
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from collections import defaultdict

from mf_data import search_funds, fetch_holdings, get_fund_nav, get_fund_meta
from stock_data import resolve_ticker, fetch_price_changes


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="MF Return Estimator",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
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
# Search bar — FRONT AND CENTER in the main content area
# ---------------------------------------------------------------------------

st.markdown("---")

# Search box in main content
col_search, col_btn = st.columns([4, 1])

with col_search:
    search_query = st.text_input(
        "🔎 Search Mutual Fund",
        placeholder="Type a fund name... e.g. ICICI Prudential FlexiCap",
        label_visibility="collapsed",
    )

with col_btn:
    search_btn = st.button("🔍 Search", type="primary", use_container_width=True)

# Handle search
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

# Quick suggestion chips
if not st.session_state.search_results and not st.session_state.selected_fund:
    st.markdown("**💡 Try these popular funds:**")
    suggestion_cols = st.columns(6)
    suggestions = [
        "ICICI Prudential FlexiCap",
        "Parag Parikh Flexi Cap",
        "HDFC Mid Cap",
        "SBI Small Cap",
        "Axis Bluechip",
        "Mirae Asset Large Cap",
    ]
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


# ---------------------------------------------------------------------------
# Display search results — inline in main content
# ---------------------------------------------------------------------------

if st.session_state.search_results and not st.session_state.selected_fund:
    st.markdown(f"#### Found {len(st.session_state.search_results)} matching funds")
    st.caption("Click a fund below to analyze it 👇")

    fund_options = []
    for r in st.session_state.search_results:
        label = r["scheme_name"]
        fund_options.append((label, r["scheme_code"]))

    # Render each fund as a clickable card
    for idx, (label, code) in enumerate(fund_options):
        col_name, col_btn2 = st.columns([5, 1])
        with col_name:
            st.markdown(f"**{idx + 1}.** {label}")
        with col_btn2:
            if st.button("📊 Select", key=f"select_{idx}", use_container_width=True):
                st.session_state.selected_fund = {
                    "name": label,
                    "code": code,
                }
                st.session_state.holdings_data = None
                st.session_state.price_data = None
                st.session_state.computed_results = None
                st.rerun()

    st.markdown("---")


# ---------------------------------------------------------------------------
# Sidebar: Quick search (kept for convenience when a fund is already loaded)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 🔎 Quick Search")
    sidebar_query = st.text_input(
        "Search another fund",
        placeholder="Type fund name...",
        key="sidebar_search",
        label_visibility="collapsed",
    )
    if st.button("🔍 Search", key="sidebar_search_btn", use_container_width=True):
        if sidebar_query:
            results = search_funds(sidebar_query, limit=15)
            st.session_state.search_results = results
            st.session_state.selected_fund = None
            st.session_state.holdings_data = None
            st.session_state.computed_results = None
            st.rerun()

    if st.session_state.selected_fund:
        st.markdown("---")
        st.markdown(f"**Current Fund:**")
        st.caption(st.session_state.selected_fund["name"])


# ---------------------------------------------------------------------------
# Main content: Fund Analysis
# ---------------------------------------------------------------------------

if st.session_state.selected_fund:
    fund = st.session_state.selected_fund
    fund_name = fund["name"]
    fund_code = fund["code"]

    st.markdown(f"### 📋 {fund_name}")

    # Option to search again
    if st.button("🔄 Search a different fund"):
        st.session_state.selected_fund = None
        st.session_state.holdings_data = None
        st.session_state.computed_results = None
        st.rerun()

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

    # --- Show holdings overview (immediately after fetch) ---
    if st.session_state.holdings_data:
        holdings = st.session_state.holdings_data

        equity_holdings = [h for h in holdings if h.get("instrument", "").lower() in ["equity", "stock"]]
        non_equity = [h for h in holdings if h.get("instrument", "").lower() not in ["equity", "stock"]]

        # --- Summary cards ---
        col_a, col_b, col_c, col_d = st.columns(4)

        with col_a:
            st.metric("Total Holdings", len(holdings))
        with col_b:
            st.metric("Equity Holdings", len(equity_holdings))
        with col_c:
            st.metric("Non-Equity (Debt/Cash)", len(non_equity))
        with col_d:
            total_equity_weight = sum(h["weight"] for h in equity_holdings)
            st.metric("Equity Exposure", f"{total_equity_weight:.1f}%")

        # --- Top 10 Holdings bar chart ---
        st.markdown("#### 🏆 Top 10 Holdings by Weight")

        top10 = sorted(holdings, key=lambda x: x["weight"], reverse=True)[:10]
        top10_df = pd.DataFrame(top10)

        fig_top = px.bar(
            top10_df,
            x="weight",
            y="name",
            orientation="h",
            color="weight",
            color_continuous_scale="Blues",
            labels={"weight": "Portfolio Weight (%)", "name": ""},
            title="",
        )
        fig_top.update_layout(
            height=400,
            yaxis={"categoryorder": "total ascending"},
            showlegend=False,
            margin=dict(l=0, r=20, t=0, b=0),
            coloraxis_showscale=False,
        )
        fig_top.update_traces(
            texttemplate="%{x:.2f}%",
            textposition="outside",
        )
        st.plotly_chart(fig_top, use_container_width=True)

        # --- Sector allocation pie chart ---
        st.markdown("#### 🥧 Sector Allocation")

        sector_totals = defaultdict(lambda: {"weight": 0, "count": 0})
        for h in holdings:
            sector = h.get("sector", "Unknown") or "Unknown"
            if sector == "N/A" or sector == "":
                sector = "Unknown"
            sector_totals[sector]["weight"] += h["weight"]
            sector_totals[sector]["count"] += 1

        sector_df = pd.DataFrame(
            [{"Sector": s, "Weight (%)": d["weight"], "Holdings": d["count"]}
             for s, d in sector_totals.items()]
        ).sort_values("Weight (%)", ascending=False)

        col_pie, col_sector_table = st.columns([1.2, 1])

        with col_pie:
            fig_pie = px.pie(
                sector_df,
                values="Weight (%)",
                names="Sector",
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Set3,
            )
            fig_pie.update_traces(
                textposition="inside",
                textinfo="percent+label",
                textfont_size=11,
            )
            fig_pie.update_layout(
                height=400,
                showlegend=False,
                margin=dict(l=10, r=10, t=10, b=10),
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        with col_sector_table:
            st.markdown("**Sector Breakdown**")
            st.dataframe(
                sector_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Weight (%)": st.column_config.ProgressColumn(
                        format="%.2f%%",
                        min_value=0,
                        max_value=max(sector_df["Weight (%)"].max(), 1),
                    ),
                },
            )

        # --- Non-equity holdings ---
        if non_equity:
            st.markdown("#### 💰 Non-Equity Holdings (Debt / Cash / Repo)")
            non_equity_df = pd.DataFrame(non_equity)
            non_equity_df = non_equity_df[["name", "sector", "instrument", "weight"]].rename(columns={
                "name": "Instrument",
                "sector": "Category",
                "instrument": "Type",
                "weight": "Weight (%)",
            })
            non_equity_df = non_equity_df.sort_values("Weight (%)", ascending=False)
            st.dataframe(
                non_equity_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Weight (%)": st.column_config.NumberColumn(format="%.2f%%"),
                },
            )

        # --- Full holdings table (expandable) ---
        with st.expander("📋 View All Holdings (Full List)", expanded=False):
            all_holdings_df = pd.DataFrame(holdings)
            all_holdings_df = all_holdings_df.rename(columns={
                "name": "Company / Instrument",
                "sector": "Sector",
                "instrument": "Type",
                "weight": "Weight (%)",
            })
            all_holdings_df = all_holdings_df.sort_values("Weight (%)", ascending=False)
            st.dataframe(
                all_holdings_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Weight (%)": st.column_config.NumberColumn(format="%.2f%%"),
                },
            )

        st.divider()

        # --- Step 2: Fetch live prices and estimate return ---
        st.markdown("### 🚀 Estimate Today's Return")

        if non_equity:
            st.caption(f"ℹ️ {len(equity_holdings)} equity holdings will be used for return estimation. "
                       f"{len(non_equity)} non-equity holdings (debt/cash/repo) are excluded.")

        if st.button("🚀 Fetch Live Prices & Estimate Return", type="primary"):
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
                st.warning(f"⚠️ Could not resolve tickers for {len(unresolved)} holdings: "
                          f"{', '.join(unresolved[:5])}{'...' if len(unresolved) > 5 else ''}")

            resolved_holdings = [h for h in equity_holdings if h["name"] in ticker_map]

            if not resolved_holdings:
                st.error("❌ No holdings could be resolved to NSE tickers. The fund may hold stocks not in our database.")
            else:
                all_tickers = list(set(ticker_map.values()))
                with st.spinner(f"Fetching today's prices for {len(all_tickers)} stocks..."):
                    price_data = fetch_price_changes(all_tickers)

                st.session_state.price_data = price_data

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

            estimated_return = sum(r["Contribution %"] for r in results if isinstance(r["Contribution %"], (int, float)))
            coverage = total_weight_used / (total_weight_used + total_weight_unresolved) * 100 if (total_weight_used + total_weight_unresolved) > 0 else 0

            st.divider()
            st.markdown("### 📊 Estimated Today's Return")

            # Big return banner
            if estimated_return > 0:
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, #dcfce7, #bbf7d0); border-radius: 12px; padding: 24px; text-align: center; margin: 10px 0;">
                    <div style="font-size: 0.9rem; color: #166534; margin-bottom: 4px;">Estimated Return</div>
                    <div style="font-size: 2.5rem; font-weight: 800; color: #15803d;">+{estimated_return:.3f}%</div>
                    <div style="font-size: 0.85rem; color: #166534; margin-top: 4px;">📈 Positive — {len(pos)} gainers, {len(neg)} losers</div>
                </div>
                """, unsafe_allow_html=True)
            elif estimated_return < 0:
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, #fee2e2, #fecaca); border-radius: 12px; padding: 24px; text-align: center; margin: 10px 0;">
                    <div style="font-size: 0.9rem; color: #991b1b; margin-bottom: 4px;">Estimated Return</div>
                    <div style="font-size: 2.5rem; font-weight: 800; color: #dc2626;">{estimated_return:.3f}%</div>
                    <div style="font-size: 0.85rem; color: #991b1b; margin-top: 4px;">📉 Negative — {len(pos)} gainers, {len(neg)} losers</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.metric("Estimated Return", f"{estimated_return:.3f}%", delta="Neutral")

            # Metrics row
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Portfolio Coverage", f"{coverage:.1f}%")
            with col2:
                st.metric("Gainers", f"{len(pos)} stocks", delta=f"+{sum(p[1] for p in pos):.2f}%" if pos else "0")
            with col3:
                st.metric("Losers", f"{len(neg)} stocks", delta=f"{sum(n[1] for n in neg):.2f}%" if neg else "0", delta_color="inverse" if neg else "off")

            if coverage < 90:
                st.markdown(f"""
                <div class="warning-banner">
                    ⚠️ Only {coverage:.1f}% of the portfolio could be resolved to stock tickers.
                    The estimate may not be fully accurate. Unresolved holdings ({100 - coverage:.1f}% of portfolio) are excluded.
                </div>
                """, unsafe_allow_html=True)

            # --- Contribution waterfall chart ---
            st.markdown("#### 📊 Contribution to Today's Return")

            chart_data = []
            for r in results:
                if isinstance(r["Contribution %"], (int, float)):
                    chart_data.append({
                        "Company": r["Company"][:20],
                        "Contribution": r["Contribution %"],
                        "Change": r["Change %"] if isinstance(r["Change %"], (int, float)) else 0,
                        "Weight": r["Weight %"],
                    })

            if chart_data:
                chart_df = pd.DataFrame(chart_data)
                chart_df["abs_contrib"] = chart_df["Contribution"].abs()
                chart_df = chart_df.sort_values("abs_contrib", ascending=False).head(15)
                chart_df = chart_df.sort_values("Contribution", ascending=True)

                colors = ["#dc2626" if v < 0 else "#16a34a" for v in chart_df["Contribution"]]

                fig_contrib = go.Figure(data=[
                    go.Bar(
                        x=chart_df["Contribution"],
                        y=chart_df["Company"],
                        orientation="h",
                        marker_color=colors,
                        text=[f"{'+' if v >= 0 else ''}{v:.4f}%" for v in chart_df["Contribution"]],
                        textposition="outside",
                    )
                ])
                fig_contrib.update_layout(
                    height=450,
                    xaxis_title="Contribution to Fund Return (%)",
                    yaxis_title="",
                    showlegend=False,
                    margin=dict(l=0, r=60, t=0, b=40),
                    xaxis=dict(zeroline=True, zerolinecolor="#333", zerolinewidth=1),
                )
                st.plotly_chart(fig_contrib, use_container_width=True)

            # --- Detailed holdings table with prices ---
            st.markdown("### 📋 Holdings with Price Changes")

            df = pd.DataFrame(results)

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
                    "Prev Close (₹)": st.column_config.NumberColumn(format="₹%.2f"),
                    "Current (₹)": st.column_config.NumberColumn(format="₹%.2f"),
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
    if not st.session_state.search_results:
        st.markdown("""
        ### 👆 Get Started

        Type a fund name in the search box above, or click one of the suggestion buttons.

        ---

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
