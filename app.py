"""
MF Return Estimator - Streamlit App
Loads MF list from a Google Sheet (tab: 'mf'), fetches holdings and NAV,
computes estimated day change for each fund, and displays a summary table.
Click on a fund to view its holdings detail page.
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


st.set_page_config(
    page_title="MF Return Estimator",
    page_icon="chart_with_upwards_trend",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("MF Return Estimator")
st.caption("Load mutual funds from a Google Sheet and see today's estimated returns")

# ------------------------------------------------------------------------
# Session state
# -----------------------------------------------------------------------
if "sheet_url" not in st.session_state:
    st.session_state.sheet_url = ""
if "mf_list" not in st.session_state:
    st.session_state.mf_list = []
if "mf_results" not in st.session_state:
    st.session_state.mf_results = None
if "detail_fund_idx" not in st.session_state:
    st.session_state.detail_fund_idx = None


# ------------------------------------------------------------------------
# Helper: compute estimated return for one fund
# -----------------------------------------------------------------------
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
                "name": name,
                "ticker": ticker,
                "weight": weight,
                "change_pct": change_pct,
                "contribution": contribution,
                "prev_close": price_data[ticker].get("prev_close"),
                "curr_price": price_data[ticker].get("curr_price"),
            })
    return total_return, details


# ------------------------------------------------------------------------
# Helper: load MFs from Google Sheet
# ------------------------------------------------------------------------
def load_mfs_from_sheet(url):
    """Extract sheet ID, read 'mf' tab, return list of {name, code}."""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not match:
        return None, "Could not extract Sheet ID from URL."
    sheet_id = match.group(1)
    csv_url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet=mf"
    )
    resp = requests.get(csv_url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    if df.empty:
        return None, "No data found in the 'mf' tab."

    # Auto-detect name and code columns
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

    return mf_list, None


# -----------------------------------------------------------------------
# DETAIL VIEW
# ----------------------------------------------------------------------
if st.session_state.detail_fund_idx is not None and st.session_state.mf_results:
    idx = st.session_state.detail_fund_idx
    results = st.session_state.mf_results
    if idx >= len(results):
        st.session_state.detail_fund_idx = None
        st.rerun()

    result = results[idx]
    fund_name = result["name"]

    if st.button("Back to Summary", type="secondary"):
        st.session_state.detail_fund_idx = None
        st.rerun()

    st.markdown(f"### {fund_name}")

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        nav = result.get("nav")
        st.metric("Current NAV", f"Rs.{nav:.4f}" if nav else "N/A")
    with col2:
        change = result.get("day_change")
        if change is not None:
            st.metric("Est. Day Change", f"{change:+.4f}%", delta=f"{change:+.4f}%")
        else:
            st.metric("Est. Day Change", "N/A")
    with col3:
        st.metric("Holdings", result.get("holdings_count", "N/A"))
    with col4:
        st.metric("Holdings As Of", result.get("holdings_date") or "Unknown")

    if result.get("error"):
        st.warning(f"Note: {result['error']}")

    holdings = result.get("holdings", [])
    if not holdings:
        st.warning("No holdings data available for this fund.")
    else:
        equity = [
            h for h in holdings
            if h.get("instrument", "").lower() in ("equity", "stock", "foreign equity")
        ]
        non_equity = [
            h for h in holdings
            if h.get("instrument", "").lower() not in ("equity", "stock", "foreign equity")
        ]

        # Top 10 holdings bar chart
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
            coloraxis_showscale=False,
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
            fig_pie.update_layout(height=400, showlegdend=False, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_pie, use_container_width=True)
        with col_table:
            st.markdown("**Sector Breakdown**")
            st.dataframe(sector_df, use_container_width=True, hide_index=True)

        # All holdings table
        with st.expander("View All Holdings (Full List)", expanded=False):
            all_df = pd.DataFrame(holdings)
            all_df = all_df.rename(columns={
                "name": "Company / Instrument", "sector": "Sector",
                "instrument": "Type", "weight": "Weight (%)",
            })
            all_df = all_df.sort_values("Weight (%)", ascending=False)
            st.dataframe(all_df, use_container_width=True, hide_index=True)

        # Return breakdown
        if result.get("return_details"):
            st.markdown("---")
            st.markdown("#### Return Breakdown (Live Prices)")
            details = result["return_details"]
            details_df = pd.DataFrame(details)
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

            # Contribution waterfall
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
                margin=dict(l=20, r=20, t=40, b=80),
            )
            fig_water.update_xapes(tickangle=45)
            st.plotly_chart(fig_water, use_container_width=True)

    st.divider()
    st.caption("MF Return Estimator | Data: Google Sheets, mfapi.in, FinAPI, AMFI Portal, Yahoo Finance")


# ------------------------------------------------------------------------
# SUMMARY VIEW
# --------------------------------------------------------------------------
else:

    # --- Step 1: Load MFs from Google Sheet ---
    st.markdown("### 1. Load MFs from Google Sheet")
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
            mf_list, err = load_mfs_from_sheet(sheet_url_input)
            if err:
                st.error(err)
            else:
                st.session_state.mf_list = mf_list
                st.session_state.mf_results = None
                st.session_state.detail_fund_idx = None
                st.success(f"Loaded {len(mf_list)} MFs from sheet.")
                st.rerun()

    # --- Step 2: Fetch returns ---
    if st.session_state.mf_list:
        st.markdown("---")
        st.markdown("### 2. Fetch Returns for All MFs")

        col_fetch, col_refresh, col_count = st.columns([2, 2, 2])
        with col_fetch:
            fetch_btn = st.button("Fetch All Returns", type="primary")
        with col_refresh:
            refresh_btn = st.button("Refresh (Re-fetch)", type="secondary")
        with col_count:
            st.metric("MFs Loaded", len(st.session_state.mf_list))

        if fetch_btn or refresh_btn:
            mf_list = st.session_state.mf_list
            results = []
            progress = st.progress(0, "Starting...")

            for i, mf in enumerate(mf_list):
                pct = (i + 1) / len(mf_list)
                progress.progress(
                    pct,
                    text=f"Processing {i + 1}/{len(mf_list)}: {mf['name'][:50]}...",
                )

                result = {
                    "name": mf["name"], "code": mf["code"],
                    "nav": None, "day_change": None,
                    "holdings_count": 0, "holdings": [],
                    "holdings_date": None, "return_details": [],
                    "error": None,
                }

                # Resolve scheme code if not provided
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

                # Fetch NAV
                nav_val, nav_date = get_fund_nav(scheme_code)
                if nav_val:
                    try:
                        result["nav"] = float(nav_val)
                    except (ValueError, TypeError):
                        pass

                # Fetch holdings
                try:
                    holdings, source, holdings_date = fetch_holdings(mf["name"], scheme_code)
                    if holdings:
                        result["holdings"] = holdings
                        result["holdings_count"] = len$holdings)
                        result["holdings_date"] = holdings_date

                        # Compute estimated return
                        day_change, return_details = compute_fund_return(holdings)
                        result["day_change"] = day_change
                        result["return_details"] = return_details
                    else:
                        result["error"] = source or "No holdings found"
                except Exception as e:
                    result["error"] = str(e)[:100]

                results.append(result)

            progress.progress(1.0, "Done!")
            st.session_state.mf_results = results
            st.rerun()

        # --- Step 3: Summary table ---
        if st.session_state.mf_results:
            results = st.session_state.mf_results

            st.markdown("---")
            st.markdown("### 3. Summary - All MF Returns")

            # Build summary table
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

            # Color-code Day Change column
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

            # Navigation to detail view
            st.markdown("---")
            st.markdown("### View Holdings Detail")
            st.caption("Select an MF and click the button to view its full holdings breakdown.")

            fund_names = [
                f"{i + 1}. {r['name'][:60]}" for i, r in enumerate(results)
            ]
            selected_idx = st.selectbox(
                "Select an MF to view its holdings",
                range(len(results)),
                format_func=lambda i: fund_names[i],
                key="detail_selectbox",
            )

            col_view, col_back = st.columns([1, 3])
            with col_view:
                if st.button("View Holdings", type="primary", use_container_width=True):
                    st.session_state.detail_fund_idx = selected_idx
                    st.rerun()

            # Quick stats
            st.markdown("---")
            col_s1, col_s2, col_s3, col_s4 = st.columns(4)
            with col_s1:
                total_mfs = len(results)
                ok_count = sum(1 for r in results if not r.get("error"))
                st.metric("MFs Loaded", f"{ok_count}/{total_mfs}")
            with col_s2:
                avg_change_vals = [r["day_change"] for r in results if r.get("day_change") is not None]
                avg_change = sum(avg_change_vals) / len(avg_change_vals) if avg_change_vals else 0
                st.metric("Avg Day Change", f"{avg_change:+-4f}%")
            with col_s3:
                gainers = sum(1 for v in avg_change_vals if v > 0)
                st.metric("Gainers", gainers)
            with col_s4:
                losers = sum(1 for v in avg_change_vals if v < 0)
                st.metric("Losers", losers)

        else:
            st.info(
                "Click 'Fetch All Returns' to load holdings, NAV, and estimated returns "
                "for all MFs in your sheet."
            )

    else:
        # No sheet loaded yet
        st.info(
            "Enter a Google Sheet URL above to get started. "
            "The sheet should have a tab named 'mf' with your fund list."
        )

    st.divider()
    st.caption(
        "MF Return Estimator | Data: Google Sheets, mfapi.in, FinAPI, AMFI Portal, Yahoo Finance "
        "| Built with Streamlit"
    )
