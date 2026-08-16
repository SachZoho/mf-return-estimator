"""
MF Return Estimator — Streamlit App
Estimates today's mutual fund return based on underlying holdings' price changes.

How it works:
1. User searches for any Indian mutual fund by name
2. App fetches the fund's portfolio holdings (from FinAPI/mfdata.in/Groww)
3. Resolves each stock to an NSE ticker
4. Fetches current-day price changes via Yahoo Finance
5. Computes weighted return = sum(holding_weight * stock_change_pct)

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


st.set_page_config(page_title="MF Return Estimator", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    .main-header { font-size: 2.2rem; font-weight: 700; color: #1f4e79; margin-bottom: 0.2rem; }
    .sub-header { font-size: 1rem; color: #666; margin-bottom: 1.5rem; }
    .info-banner { background: #eff6ff; border-left: 4px solid #3b82f6; padding: 10px 15px; border-radius: 5px; margin: 10px 0; font-size: 0.9rem; color: #1e40af; }
    .warning-banner { background: #fffbeb; border-left: 4px solid #f59e0b; padding: 10px 15px; border-radius: 5px; margin: 10px 0; font-size: 0.9rem; color: #92400e; }
</style>
""", unsafe_allow_html=True)

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

st.markdown("---")

col_search, col_btn = st.columns([4, 1])
with col_search:
    search_query = st.text_input("🔎 Search Mutual Fund", placeholder="Type a fund name... e.g. ICICI Prudential FlexiCap", label_visibility="collapsed")
with col_btn:
    search_btn = st.button("🔍 Search", type="primary", use_container_width=True)

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
    st.markdown("**💡 Try these popular funds:**")
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
    st.caption("Click a fund below to analyze it 👇")
    fund_options = [(r["scheme_name"], r["scheme_code"]) for r in st.session_state.search_results]
    for idx, (label, code) in enumerate(fund_options):
        col_name, col_btn2 = st.columns([5, 1])
        with col_name:
            st.markdown(f"**{idx + 1}.** {label}")
        with col_btn2:
            if st.button("📊 Select", key=f"select_{idx}", use_container_width=True):
                st.session_state.selected_fund = {"name": label, "code": code}
                st.session_state.holdings_data = None
                st.session_state.price_data = None
                st.session_state.computed_results = None
                st.rerun()
    st.markdown("---")

with st.sidebar:
    st.markdown("### 🔎 Quick Search")
    sidebar_query = st.text_input("Search another fund", placeholder="Type fund name...", key="sidebar_search", label_visibility="collapsed")
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
        st.markdown("**Current Fund:**")
        st.caption(st.session_state.selected_fund["name"])

if st.session_state.selected_fund:
    fund = st.session_state.selected_fund
    fund_name = fund["name"]
    fund_code = fund["code"]
    st.markdown(f"### 📋 {fund_name}")
    if st.button("🔄 Search a different fund"):
        st.session_state.selected_fund = None
        st.session_state.holdings_data = None
        st.session_state.computed_results = None
        st.rerun()
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

    if st.session_state.holdings_data is None:
        with st.spinner("Fetching portfolio holdings..."):
            holdings, source = fetch_holdings(fund_name, fund_code)
        if holdings:
            st.session_state.holdings_data = holdings
            st.session_state.holdings_source = source
            st.success(f"✅ Found {len(holdings)} holdings (Source: {source})")
        else:
            st.error("❌ Could not fetch holdings.")
            with st.expander("📋 Technical details (click to expand)", expanded=False):
                st.code(source, language="text")
            st.markdown('''
            <div class="warning-banner">
                The app tried multiple data sources (FinAPI, mfdata.in, Groww) but none returned holdings.
                This could be a temporary network issue. Please try again in a moment, or try a different fund.
            </div>
            ''', unsafe_allow_html=True)

    if st.session_state.holdings_data:
        holdings = st.session_state.holdings_data
        equity_holdings = [h for h in holdings if h.get("instrument", "").lower() in ["equity", "stock", "foreign equity"]]
        non_equity = [h for h in holdings if h.get("instrument", "").lower() not in ["equity", "stock", "foreign equity"]]

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

        st.markdown("#### 🏆 Top 10 Holdings by Weight")
        top10 = sorted(holdings, key=lambda x: x["weight"], reverse=True)[:10]
        top10_df = pd.DataFrame(top10)
        fig_top = px.bar(top10_df, x="weight", y="name", orientation="h", color="weight", color_continuous_scale="Blues", labels={"weight": "Portfolio Weight (%)", "name": ""}, title="")
        fig_top.update_layout(height=400, yaxis={"categoryorder": "total ascending"}, showlegend=False, margin=dict(l=0, r=20, t=0, b=0), coloraxis_showscale=False)
        fig_top.update_traces(texttemplate="%{x:.2f}%", textposition="outside")
        st.plotly_chart(fig_top, use_container_width=True)

        st.markdown("#### 🥧 Sector Allocation")
        sector_totals = defaultdict(lambda: {"weight": 0, "count": 0})
        for h in holdings:
            sector = h.get("sector", "Unknown") or "Unknown"
            if sector == "N/A" or sector == "":
                sector = "Unknown"
            sector_totals[sector]["weight"] += h["weight"]
            sector_totals[sector]["count"] += 1
        sector_df = pd.DataFrame([{"Sector": s, "Weight (%)": d["weight"], "Holdings": d["count"]} for s, d in sector_totals.items()]).sort_values("Weight (%)", ascending=False)
        col_pie, col_sector_table = st.columns([1.2, 1])
        with col_pie:
            fig_pie = px.pie(sector_df, values="Weight (%)", names="Sector", hole=0.4, color_discrete_sequence=px.colors.qualitative.Set3)
            fig_pie.update_traces(textposition="inside", textinfo="percent+label", textfont_size=11)
            fig_pie.update_layout(height=400, showlegend=False, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_pie, use_container_width=True)
        with col_sector_table:
            st.markdown("**Sector Breakdown**")
            st.dataframe(sector_df, use_container_width=True, hide_index=True, column_config={"Weight (%)": st.column_config.ProgressColumn(format="%.2f%%", min_value=0, max_value=max(sector_df["Weight (%)"].max(), 1))})

        if non_equity:
            st.markdown("#### 💰 Non-Equity Holdings (Debt / Cash / Repo)")
            non_equity_df = pd.DataFrame(non_equity)
            non_equity_df = non_equity_df[["name", "sector", "instrument", "weight"]].rename(columns={"name": "Instrument", "sector": "Category", "instrument": "Type", "weight": "Weight (%)"})
            non_equity_df = non_equity_df.sort_values("Weight (%)", ascending=False)
            st.dataframe(non_equity_df, use_container_width=True, hide_index=True, column_config={"Weight (%)": st.column_config.NumberColumn(format="%.2f%%")})

        with st.expander("📋 View All Holdings (Full List)", expanded=False):
            all_holdings_df = pd.DataFrame(holdings)
            all_holdings_df = all_holdings_df.rename(columns={"name": "Company / Instrument", "sector": "Sector", "instrument": "Type", "weight": "Weight (%)"})
            all_holdings_df = all_holdings_df.sort_values("Weight (%)", ascending=False)
            st.dataframe(all_holdings_df, use_container_width=True, hide_index=True, column_config={"Weight (%)": st.column_config.NumberColumn(format="%.2f%%")})

        st.divider()
        st.markdown("### 🚀 Estimate Today's Return")
        if non_equity:
            st.caption(f"ℹ️ {len(equity_holdings)} equity holdings will be used for return estimation. {len(non_equity)} non-equity holdings (debt/cash/repo) are excluded.")

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
                st.warning(f"⚠️ Could not resolve tickers for {len(unresolved)} holdings: {', '.join(unresolved[:5])}{'...' if len(unresolved) > 5 else ''}")
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
                        results.append({"name": name, "ticker": ticker, "weight": weight, "change_pct": change_pct, "contribution": contribution, "prev_close": pd_data["prev_close"], "curr_price": pd_data["curr_price"]})
                        if contribution > 0:
                            positive_contributors.append((name, contribution))
                        elif contribution < 0:
                            negative_contributors.append((name, contribution))
                    else:
                        total_weight_unresolved += weight
                if results:
                    total_estimated_return = sum(r["contribution"] for r in results)
                    coverage = total_weight_used / (total_weight_used + total_weight_unresolved) * 100 if (total_weight_used + total_weight_unresolved) > 0 else 0
                    if total_estimated_return >= 0:
                        st.markdown(f'<div style="background: linear-gradient(135deg, #d1fae5, #a7f3d0); border: 2px solid #10b981; border-radius: 12px; padding: 20px; text-align: center; margin: 15px 0;"><span style="font-size: 1.2rem; color: #065f46;">📊 Estimated Today\'s Return</span><br><span style="font-size: 2.5rem; font-weight: 800; color: #047857;">+{total_estimated_return:.4f}%</span></div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div style="background: linear-gradient(135deg, #fee2e2, #fecaca); border: 2px solid #ef4444; border-radius: 12px; padding: 20px; text-align: center; margin: 15px 0;"><span style="font-size: 1.2rem; color: #991b1b;">📊 Estimated Today\'s Return</span><br><span style="font-size: 2.5rem; font-weight: 800; color: #dc2626;">{total_estimated_return:.4f}%</span></div>', unsafe_allow_html=True)
                    st.caption(f"Based on {len(results)} resolved holdings covering {coverage:.1f}% of portfolio weight. {len(unresolved)} holdings could not be resolved.")
                    col_pos, col_neg = st.columns(2)
                    with col_pos:
                        st.markdown("#### 🟢 Top Positive Contributors")
                        positive_contributors.sort(key=lambda x: x[1], reverse=True)
                        for name, contrib in positive_contributors[:5]:
                            st.markdown(f"**{name}**: +{contrib:.4f}%")
                    with col_neg:
                        st.markdown("#### 🔴 Top Negative Contributors")
                        negative_contributors.sort(key=lambda x: x[1])
                        for name, contrib in negative_contributors[:5]:
                            st.markdown(f"**{name}**: {contrib:.4f}%")
                    results_df = pd.DataFrame(results)
                    results_df = results_df[["name", "ticker", "weight", "prev_close", "curr_price", "change_pct", "contribution"]].rename(columns={"name": "Company", "ticker": "Ticker", "weight": "Weight (%)", "prev_close": "Prev Close", "curr_price": "Current Price", "change_pct": "Change (%)", "contribution": "Contribution"})
                    results_df = results_df.sort_values("Contribution", ascending=False)
                    st.markdown("#### 📊 Detailed Breakdown")
                    st.dataframe(results_df, use_container_width=True, hide_index=True, column_config={"Weight (%)": st.column_config.NumberColumn(format="%.2f%%"), "Change (%)": st.column_config.NumberColumn(format="%.2f%%"), "Contribution": st.column_config.NumberColumn(format="%.4f%%")})
                    top15 = results_df.head(15)
                    fig_water = go.Figure(go.Waterfall(x=top15["Company"], y=top15["Contribution"], orientation="v", connector={"line": {"color": "#ccc"}}, increasing={"marker": {"color": "#10b981"}}, decreasing={"marker": {"color": "#ef4444"}}}))
                    fig_water.update_layout(title="Contribution Waterfall (Top 15 by Impact)", yaxis_title="Contribution (%)", height=400, margin=dict(l=20, r=20, t=40, b=80))
                    fig_water.update_xaxes(tickangle=45)
                    st.plotly_chart(fig_water, use_container_width=True)

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

# ---------------------------------------------------------------------------
# Alert Setup — email notification for negative returns
# ---------------------------------------------------------------------------

st.markdown("### 🔔 Set Up Negative Return Alert")

st.markdown("""
Get an email alert every 5 minutes when your tracked fund's estimated return goes negative.
No login needed — just enter your email and pick a fund.
""")

alert_col1, alert_col2 = st.columns([3, 2])

with alert_col1:
    alert_email = st.text_input(
        "📧 Your email address",
        placeholder="you@example.com",
        key="alert_email_input",
    )

with alert_col2:
    fund_choices = []
    if st.session_state.search_results:
        for r in st.session_state.search_results:
            fund_choices.append((r["scheme_name"], r["scheme_code"]))
    elif st.session_state.selected_fund:
        fund_choices.append((
            st.session_state.selected_fund["name"],
            st.session_state.selected_fund["code"],
        ))

    if fund_choices:
        selected_idx = st.selectbox(
            "📊 Fund to track",
            range(len(fund_choices)),
            format_func=lambda i: fund_choices[i][0][:60],
            key="alert_fund_select",
        )
        alert_fund_name, alert_fund_code = fund_choices[selected_idx]
    else:
        st.markdown("*Search and select a fund first, then come back here to set up an alert.*")
        alert_fund_name, alert_fund_code = None, None

st.markdown("---")
st.markdown("#### 🔑 GitHub Configuration (for saving alerts)")
st.caption("""
Alerts are stored in a CSV file in your GitHub repo. To save alerts from this app,
you need a GitHub Personal Access Token with 'repo' scope.
Create one at: https://github.com/settings/tokens/new?scopes=repo
""")

gh_col1, gh_col2, gh_col3 = st.columns(3)
with gh_col1:
    gh_token = st.text_input("GitHub Token", type="password", placeholder="ghp_...", key="gh_token_input")
with gh_col2:
    gh_owner = st.text_input("Repo Owner", value="SachZoho", key="gh_owner_input")
with gh_col3:
    gh_repo = st.text_input("Repo Name", value="mf-return-estimator", key="gh_repo_input")

if st.button("🔔 Set Up Alert", type="primary", disabled=(not alert_email or not alert_fund_code or not gh_token)):
    with st.spinner("Saving alert to GitHub..."):
        from alerts import save_alert_github
        success, msg = save_alert_github(
            gh_token, gh_owner, gh_repo, alert_email, alert_fund_code, alert_fund_name
        )
    if success:
        st.success(f"✅ {msg} You'll receive an email at **{alert_email}** whenever **{alert_fund_name[:50]}** has a negative estimated return.")
        st.info("""
        **What happens next:**
        - A GitHub Actions job runs every 5 minutes, checking your fund's estimated return.
        - If the return is negative, you'll get an email alert.
        - If the return is positive, no email is sent.
        - Make sure you've set up the GitHub repo secrets: `SENDER_EMAIL` and `SENDER_PASSWORD`.
        """)
    else:
        st.error(f"❌ {msg}")

if gh_token:
    st.markdown("---")
    st.markdown("#### 📋 Your Existing Alerts")
    if st.button("🔄 Refresh alerts list"):
        st.rerun()
    try:
        from alerts import read_alerts_github
        existing_alerts, _ = read_alerts_github(gh_token, gh_owner, gh_repo)
        if existing_alerts:
            alerts_df = pd.DataFrame(existing_alerts)
            st.dataframe(alerts_df, use_container_width=True, hide_index=True)

            st.markdown("**Remove an alert:**")
            remove_idx = st.selectbox(
                "Select alert to remove",
                range(len(existing_alerts)),
                format_func=lambda i: f"{existing_alerts[i].get('email', '')} -> {existing_alerts[i].get('scheme_name', '')[:40]}",
                key="remove_alert_select",
            )
            if st.button("🗑️ Remove Selected Alert"):
                from alerts import remove_alert_github
                sel = existing_alerts[remove_idx]
                success, msg = remove_alert_github(
                    gh_token, gh_owner, gh_repo,
                    sel.get("email", ""), sel.get("scheme_code", "")
                )
                if success:
                    st.success(f"✅ {msg}")
                    st.rerun()
                else:
                    st.error(f"❌ {msg}")
        else:
            st.info("No alerts configured yet.")
    except Exception as e:
        st.warning(f"Could not read alerts: {str(e)[:80]}")

st.divider()
st.caption("📊 MF Return Estimator | Data: mfapi.in, FinAPI, Yahoo Finance | Alerts via GitHub Actions + Gmail | Built with Streamlit")