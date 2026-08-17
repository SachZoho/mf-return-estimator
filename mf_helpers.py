"""
MF Helpers - shared functions for MF Return Estimator.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import defaultdict

from mf_data import search_funds, fetch_holdings, get_fund_nav, get_fund_meta
from stock_data import resolve_ticker, fetch_price_changes


def _chart_template():
    """Return Plotly template name based on current theme."""
    if getattr(st, "session_state", None) and st.session_state.get("theme_mode") == "Dark":
        return "plotly_dark"
    return "plotly_white"


def compute_fund_return(holdings):
    """Given holdings list, resolve tickers, fetch prices, return (day_change, details)."""
    equity = [
        h for h in holdings
        if h.get("instrument", "").lower() in ("equity", "stock", "foreign equity")
    ]
    ticker_map = {}
    for h in equity:
        ticker = resolve_ticker(h["name"])
        if ticker:
            ticker_map[h["name"]] = ticker
    if not ticker_map:
        return None, []
    all_tickers = list(set(ticker_map.values()))
    price_data = fetch_price_changes(all_tickers)
    total_return = 0.0
    details = []
    for h in equity:
        name = h["name"]
        weight = h["weight"]
        ticker = ticker_map.get(name)
        if ticker and ticker in price_data:
            change_pct = price_data[ticker]["change_pct"]
            contribution = (weight / 100) * change_pct
            total_return += contribution
            details.append({
                "name": name, "ticker": ticker, "weight": weight,
                "change_pct": change_pct, "contribution": contribution,
                "prev_close": price_data[ticker].get("prev_close"),
                "curr_price": price_data[ticker].get("curr_price"),
            })
    return total_return, details


def render_fund_detail(fund_name, fund_code, holdings, source, holdings_date, nav_val, day_change, return_details):
    """Render the holdings detail view for a single fund."""
    st.markdown(f"### {fund_name}")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Latest NAV", f"Rs.{nav_val:.4f}" if nav_val else "N/A")
    with col2:
        if day_change is not None:
            st.metric("Est. Day Change", f"{day_change:+.4f}%", delta=f"{day_change:+.4f}%")
        else:
            st.metric("Est. Day Change", "N/A")
    with col3:
        st.metric("Total Holdings", len(holdings) if holdings else 0)
    with col4:
        eq = [h for h in (holdings or []) if h.get("instrument", "").lower() in ("equity", "stock", "foreign equity")]
        ew = sum(h["weight"] for h in eq)
        st.metric("Equity Exposure", f"{ew:.1f}%")
    with col5:
        st.metric("Holdings As Of", holdings_date or "Unknown")

    if not holdings:
        st.warning("No holdings data available for this fund.")
        return

    equity = [h for h in holdings if h.get("instrument", "").lower() in ("equity", "stock", "foreign equity")]
    non_equity = [h for h in holdings if h.get("instrument", "").lower() not in ("equity", "stock", "foreign equity")]

    # Top 10 bar chart
    st.markdown("#### Top 10 Holdings by Weight")
    top10 = sorted(holdings, key=lambda x: x["weight"], reverse=True)[:10]
    top10_df = pd.DataFrame(top10)
    fig_top = px.bar(
        top10_df, x="weight", y="name", orientation="h",
        color="weight", color_continuous_scale="Blues",
        labels={"weight": "Portfolio Weight (%)", "name": ""},
    )
    fig_top.update_layout(
        height=400, yaxis={"categoryorder": "total ascending"},
        showlegend=False, margin=dict(l=0, r=20, t=0, b=0),
        coloraxis_showscale=False, template=_chart_template(),
    )
    fig_top.update_traces(texttemplate="%{x:.2f}%", textposition="outside")
    st.plotly_chart(fig_top, use_container_width=True)

    # Sector allocation
    st.markdown("#### Sector Allocation")
    sector_totals = defaultdict(lambda: {"weight": 0, "count": 0})
    for h in holdings:
        sector = h.get("sector", "Unknown") or "Unknown"
        if sector in ("N/A", ""):
            sector = "Unknown"
        sector_totals[sector]["weight"] += h["weight"]
        sector_totals[sector]["count"] += 1
    sector_df = pd.DataFrame([
        {"Sector": s, "Weight (%)": d["weight"], "Holdings": d["count"]}
        for s, d in sector_totals.items()
    ]).sort_values("Weight (%)", ascending=False)
    col_pie, col_table = st.columns([1.2, 1])
    with col_pie:
        fig_pie = px.pie(
            sector_df, values="Weight (%)", names="Sector", hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Set3,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label", textfont_size=11)
        fig_pie.update_layout(height=400, showlegend=False, margin=dict(l=10, r=10, t=10, b=10), template=_chart_template())
        st.plotly_chart(fig_pie, use_container_width=True)
    with col_table:
        st.markdown("**Sector Breakdown**")
        st.dataframe(sector_df, use_container_width=True, hide_index=True)

    # All holdings
    with st.expander("View All Holdings (Full List)", expanded=False):
        all_df = pd.DataFrame(holdings)
        all_df = all_df.rename(columns={
            "name": "Company / Instrument", "sector": "Sector",
            "instrument": "Type", "weight": "Weight (%)",
        })
        all_df = all_df.sort_values("Weight (%)", ascending=False)
        st.dataframe(all_df, use_container_width=True, hide_index=True)

    # Return breakdown
    if return_details:
        st.markdown("---")
        st.markdown("#### Return Breakdown (Live Prices)")
        details_df = pd.DataFrame(return_details)
        details_df = details_df[["name", "ticker", "weight", "prev_close", "curr_price", "change_pct", "contribution"]]
        details_df = details_df.rename(columns={
            "name": "Company", "ticker": "Ticker", "weight": "Weight (%)",
            "prev_close": "Prev Close", "curr_price": "Current Price",
            "change_pct": "Change (%)", "contribution": "Contribution",
        })
        details_df = details_df.sort_values("Contribution", ascending=False)
        st.dataframe(
            details_df, use_container_width=True, hide_index=True,
            column_config={
                "Weight (%)": st.column_config.NumberColumn(format="%.2f%%"),
                "Change (%)": st.column_config.NumberColumn(format="%.2f%%"),
                "Contribution": st.column_config.NumberColumn(format="%.4f%%"),
            },
        )
        top15 = details_df.head(15)
        fig_water = go.Figure(go.Waterfall(
            x=top15["Company"], y=top15["Contribution"], orientation="v",
            connector={"line": {"color": "#ccc"}},
            increasing={"marker": {"color": "#10b981"}},
            decreasing={"marker": {"color": "#ef4444"}},
        ))
        fig_water.update_layout(
            title="Contribution Waterfall (Top 15 by Impact)",
            yaxis_title="Contribution (%)", height=400,
            margin=dict(l=20, r=20, t=40, b=80), template=_chart_template(),
        )
        fig_water.update_xaxes(tickangle=45)
        st.plotly_chart(fig_water, use_container_width=True)
