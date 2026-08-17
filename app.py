# --- Imports -----------------------------------------------------------------
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import json
import requests
from datetime import datetime, date
import time
from streamlit.components.v1 import components
from streamlit.web.server.server import Server
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

# Force wide layout and configure the page once (must be before any other st call)
st.set_page_config(
    page_title="MF Return Estimator",
    page_icon=":bar_chart:",
    layout="wide",
    menu_items={
        'Get Help': 'https://github.com/SachZoho/mf-return-estimator',
        'Report a bug': 'https://github.com/SachZoho/mf-return-estimator/issues',
        'About': "MF Return Estimator - Analyze and estimate returns on Indian Mutual Fund SIPs and Lumpsum investments."
    }
)

# --- Theme Detection (light/dark) -------------------------------------------
# Inject JS into parent document that detects the active Streamlit theme and
# stores it as a query param so Python can pick it up to style Plotly charts.
components.html("""
<script>
    function detectTheme() {
        try {
            var theme = 'light';
            try {
                var root = window.parent.document.documentElement;
                if (root.classList.contains('st-emotion-layout') &&
                    (root.getAttribute('data-teststate') === 'dark' ||
                     window.parent.getComputedStyle(root).getPropertyValue('--background-color').trim() !== '')) {
                    var bg = window.parent.getComputedStyle(root).getPropertyValue('background-color');
                    if (bg) {
                        var rgb = bg.match(/\d+/g);
                        if (rgb && rgb.length >= 3) {
                            var luminance = 0.299*parseInt(rgb[0]) + 0.587*parseInt(rgb[1]) + 0.114*parseInt(rgb[2]);
                            theme = luminance < 128 ? 'dark' : 'light';
                        }
                    }
                }
            } catch(e) {}
            try {
                var header = window.parent.document.querySelector('[data-testid="stHeader"]');
                if (header) {
                    var bg = window.parent.getComputedStyle(header).getPropertyValue('background-color');
                    if (bg) {
                        var rgb = bg.match(/\d+/g);
                        if (rgb && rgb.length >= 3) {
                            var luminance = 0.299*parseInt(rgb[0]) + 0.587*parseInt(rgb[1]) + 0.114*parseInt(rgb[2]);
                            theme = luminance < 128 ? 'dark' : 'light';
                        }
                    }
                }
            } catch(e) {}
            var url = new URL(window.parent.location.href);
            if (url.searchParams.get('st_theme') !== theme) {
                url.searchParams.set('st_theme', theme);
                window.parent.history.replaceState({}, '', url);
            }
        } catch(e) {}
</script>
""", height=0, width=0)

# --- Google Analytics 4 Integration (Measurement ID: G-WGVCPVK4H6) ---
# Injects gtag.js into the PARENT document (same approach as theme detection JS)
components.html("""
<script>
    var d = window.parent.document;
    if (!d.querySelector('script[src*="gtag/js"]')) {
        var s = d.createElement('script');
        s.async = true;
        s.src = 'https://www.googletagmanager.com/gtag/js?id=G-WGVCPVK4H6';
        d.head.appendChild(s);
        window.parent.dataLayer = window.parent.dataLayer || [];
        window.parent.gtag = function(){ window.parent.dataLayer.push(arguments); };
        window.parent.gtag('js', new Date());
        window.parent.gtag('config', 'G-WGVCPVK4H6', {
            page_title: 'MF Return Estimator',
            page_location: window.parent.location.href
        });
    }
</script>
""", height=0, width=0)

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
    ' font-weight: 700;'
    ' margin-left: 16px;'
    ' background: linear-gradient(90deg, #4A90E2, #9B51E0);'
    ' -webkit-background-clip: text;'
    ' background-clip: text;'
    ' -webkit-text-fill-color: transparent;'
    '}'
    # Hide Fork/GitHub button
    '[data-testid="stHeaderContent"] [data-testid="stLogo"] {display: none;}'
    # Hide Streamlit footer "Made with Streamlit"
    '[data-testid="stFooter"] {display: none;}'
    # Hide viewer profile/avatar links
    '[data-testid="stHeader"] [data-testid="stHeaderUserMenu"] {display: none;}'
    + _lt + "/style" + chr(62), unsafe_allow_html=True)


# --- Configuration -----------------------------------------------------------
# MF_API base URL for fetching scheme master data
MF_API_BASE = "https://api.mfapi.in"

# Cache TTLs (seconds)
CACHE_TTL_SCHEME_LIST = 24 * 60 * 60  # 1 day
CACHE_TTL_NAV_HISTORY = 6 * 60 * 60   # 6 hours

# SIP calculation constants
SIP_DEFAULT_RATE = 0.10  # 10% expected annual return
SIP_DEFAULT_YEARS = 10
SIP_DEFAULT_MONTHLY = 5000  # ₹5,000/month

# Risk-adjusted return estimates (annualized, based on category)
# These are conservative midpoints used for projections when no history exists
CATEGORY_RETURN_ESTIMATES = {
    "Equity - Large Cap": 0.12,
    "Equity - Large & Mid Cap": 0.13,
    "Equity - Mid Cap": 0.15,
    "Equity - Small Cap": 0.17,
    "Equity - Multi Cap": 0.14,
    "Equity - Flexi Cap": 0.14,
    "Equity - Sectoral": 0.15,
    "Equity - ELSS": 0.12,
    "Equity - Dividend Yield": 0.10,
    "Equity - Focused": 0.14,
    "Equity - Value": 0.13,
    "Hybrid - Balanced Advantage": 0.10,
    "Hybrid - Aggressive": 0.11,
    "Hybrid - Conservative": 0.08,
    "Hybrid - Arbitrage": 0.06,
    "Hybrid - Multi Asset": 0.10,
    "Debt - Short Duration": 0.07,
    "Debt - Medium Duration": 0.08,
    "Debt - Long Duration": 0.09,
    "Debt - Corporate Bond": 0.08,
    "Debt - Banking & PSU": 0.07,
    "Debt - Gilt": 0.07,
    "Debt - Liquid": 0.06,
    "Debt - Ultra Short": 0.06,
    "Debt - Money Market": 0.06,
    "Debt - Low Duration": 0.07,
    "Debt - Credit Risk": 0.09,
    "Index Funds": 0.11,
    "ETF": 0.11,
    "Solution Oriented - Retirement": 0.10,
    "Solution Oriented - Children": 0.10,
    "Other": 0.10,
}

# Default return when category is unknown
DEFAULT_RETURN_ESTIMATE = 0.10

# Mapping for normalized category names (to handle API variations)
CATEGORY_ALIASES = {
    "Equity Scheme - Large Cap Fund": "Equity - Large Cap",
    "Equity Scheme - Large & Mid Cap Fund": "Equity - Large & Mid Cap",
    "Equity Scheme - Mid Cap Fund": "Equity - Mid Cap",
    "Equity Scheme - Small Cap Fund": "Equity - Small Cap",
    "Equity Scheme - Multi Cap Fund": "Equity - Multi Cap",
    "Equity Scheme - Flexi Cap Fund": "Equity - Flexi Cap",
    "Equity Scheme - Sectoral/Thematic": "Equity - Sectoral",
    "Equity Scheme - ELSS": "Equity - ELSS",
    "Equity Scheme - Dividend Yield Fund": "Equity - Dividend Yield",
    "Equity Scheme - Focused Fund": "Equity - Focused",
    "Equity Scheme - Value Fund": "Equity - Value",
    "Hybrid Scheme - Balanced Advantage Fund": "Hybrid - Balanced Advantage",
    "Hybrid Scheme - Aggressive Hybrid Fund": "Hybrid - Aggressive",
    "Hybrid Scheme - Conservative Hybrid Fund": "Hybrid - Conservative",
    "Hybrid Scheme - Arbitrage Fund": "Hybrid - Arbitrage",
    "Hybrid Scheme - Multi Asset Allocation Fund": "Hybrid - Multi Asset",
    "Debt Scheme - Short Duration Fund": "Debt - Short Duration",
    "Debt Scheme - Medium Duration Fund": "Debt - Medium Duration",
    "Debt Scheme - Long Duration Fund": "Debt - Long Duration",
    "Debt Scheme - Corporate Bond Fund": "Debt - Corporate Bond",
    "Debt Scheme - Banking and PSU Fund": "Debt - Banking & PSU",
    "Debt Scheme - Gilt Fund": "Debt - Gilt",
    "Debt Scheme - Liquid Fund": "Debt - Liquid",
    "Debt Scheme - Ultra Short Duration Fund": "Debt - Ultra Short",
    "Debt Scheme - Money Market Fund": "Debt - Money Market",
    "Debt Scheme - Low Duration Fund": "Debt - Low Duration",
    "Debt Scheme - Credit Risk Fund": "Debt - Credit Risk",
    "Index Fund Scheme": "Index Funds",
    "Exchange Traded Fund": "ETF",
    "Solution Oriented Scheme - Retirement Fund": "Solution Oriented - Retirement",
    "Solution Oriented Scheme - Children Fund": "Solution Oriented - Children",
}


# --- Data fetching helpers ---------------------------------------------------
@st.cache_data(ttl=CACHE_TTL_SCHEME_LIST, show_spinner=False)
def fetch_scheme_list():
    """Fetch the full list of mutual fund schemes from mfapi.in."""
    try:
        resp = requests.get(f"{MF_API_BASE}/mf", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Build a DataFrame for easier filtering
        df = pd.DataFrame(data)
        # Expected columns: schemeCode, schemeName
        if df.empty:
            return pd.DataFrame(columns=["schemeCode", "schemeName"])
        # Ensure schemeName is string
        df["schemeName"] = df["schemeName"].astype(str)
        # Sort alphabetically
        df = df.sort_values("schemeName").reset_index(drop=True)
        return df
    except Exception as e:
        st.error(f"Failed to fetch scheme list: {e}")
        return pd.DataFrame(columns=["schemeCode", "schemeName"])


@st.cache_data(ttl=CACHE_TTL_NAV_HISTORY, show_spinner=False)
def fetch_nav_history(scheme_code, scheme_name):
    """Fetch NAV history for a given scheme code."""
    try:
        resp = requests.get(f"{MF_API_BASE}/mf/{scheme_code}", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Expected structure: { "status": "SUCCESS", "data": [ {date, nav, ...}, ... ], "meta": {...} }
        if data.get("status") != "SUCCESS" or "data" not in data:
            return pd.DataFrame(), {}
        nav_data = data["data"]
        if not nav_data:
            return pd.DataFrame(), {}
        df = pd.DataFrame(nav_data)
        # Keep date and nav columns; parse
        if "date" not in df.columns or "nav" not in df.columns:
            return pd.DataFrame(), {}
        df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y", errors="coerce")
        df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
        df = df.dropna(subset=["date", "nav"])
        # Sort ascending by date
        df = df.sort_values("date").reset_index(drop=True)
        # Meta info (scheme category, fund house, etc.)
        meta = data.get("meta", {})
        return df, meta
    except Exception as e:
        st.error(f"Failed to fetch NAV history for {scheme_name}: {e}")
        return pd.DataFrame(), {}


def normalize_category(category_str):
    """Normalize a category string to our internal mapping."""
    if not category_str:
        return "Other"
    # Direct match
    if category_str in CATEGORY_RETURN_ESTIMATES:
        return category_str
    # Alias match
    if category_str in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[category_str]
    # Try case-insensitive substring matching
    cat_lower = category_str.lower()
    for key, val in CATEGORY_ALIASES.items():
        if key.lower() in cat_lower or cat_lower in key.lower():
            return val
    # Heuristic: keyword-based
    if "large" in cat_lower and "cap" in cat_lower:
        return "Equity - Large Cap"
    if "mid" in cat_lower and "cap" in cat_lower:
        return "Equity - Mid Cap"
    if "small" in cat_lower and "cap" in cat_lower:
        return "Equity - Small Cap"
    if "debt" in cat_lower or "bond" in cat_lower or "gilt" in cat_lower:
        if "short" in cat_lower:
            return "Debt - Short Duration"
        if "medium" in cat_lower:
            return "Debt - Medium Duration"
        if "long" in cat_lower:
            return "Debt - Long Duration"
        return "Debt - Corporate Bond"
    if "hybrid" in cat_lower or "balanced" in cat_lower:
        return "Hybrid - Balanced Advantage"
    if "liquid" in cat_lower:
        return "Debt - Liquid"
    if "index" in cat_lower:
        return "Index Funds"
    if "etf" in cat_lower:
        return "ETF"
    if "elss" in cat_lower or "tax" in cat_lower:
        return "Equity - ELSS"
    return "Other"


def get_category_return_estimate(category):
    """Get the expected annualized return for a category."""
    return CATEGORY_RETURN_ESTIMATES.get(category, DEFAULT_RETURN_ESTIMATE)


# --- Return calculation helpers ----------------------------------------------
def calculate_sip_future_value(monthly_investment, annual_rate, years):
    """Calculate the future value of a SIP using the standard formula.
    FV = P * [((1 + i)^n - 1) / i] * (1 + i)
    where i = monthly rate, n = number of months, P = monthly investment.
    """
    if annual_rate <= 0 or years <= 0 or monthly_investment <= 0:
        return 0.0
    i = annual_rate / 12  # monthly rate
    n = years * 12        # number of months
    fv = monthly_investment * (((1 + i) ** n - 1) / i) * (1 + i)
    return fv


def calculate_lumpsum_future_value(principal, annual_rate, years):
    """Calculate the future value of a lumpsum investment.
    FV = P * (1 + r)^n
    """
    if annual_rate <= 0 or years <= 0 or principal <= 0:
        return 0.0
    fv = principal * ((1 + annual_rate) ** years)
    return fv


def calculate_cagr(start_value, end_value, years):
    """Calculate Compound Annual Growth Rate."""
    if start_value <= 0 or end_value <= 0 or years <= 0:
        return 0.0
    return (end_value / start_value) ** (1 / years) - 1


def calculate_returns_from_nav(nav_df, periods_years):
    """Calculate realized returns from NAV history over specified periods.
    Returns a dict of {period: annualized_return}.
    """
    if nav_df.empty or len(nav_df) < 2:
        return {}
    results = {}
    latest = nav_df.iloc[-1]
    latest_nav = latest["nav"]
    latest_date = latest["date"]
    for yrs in periods_years:
        if yrs <= 0:
            continue
        target_date = latest_date - pd.DateOffset(years=yrs)
        # Find the nav closest to (but not after) the target date
        mask = nav_df["date"] <= target_date
        if not mask.any():
            # Use the earliest available
            start_row = nav_df.iloc[0]
        else:
            start_row = nav_df.loc[mask].iloc[-1]
        start_nav = start_row["nav"]
        start_date = start_row["date"]
        # Actual years between the two dates
        actual_years = (latest_date - start_date).days / 365.25
        if actual_years <= 0 or start_nav <= 0:
            results[yrs] = np.nan
            continue
        cagr = calculate_cagr(start_nav, latest_nav, actual_years)
        results[yrs] = cagr
    return results


def build_nav_chart(nav_df, theme_mode="light"):
    """Build a Plotly chart of NAV history with theme-aware styling."""
    if nav_df.empty:
        return None
    # Sample if too many points to keep the chart responsive
    plot_df = nav_df
    if len(plot_df) > 1500:
        step = max(1, len(plot_df) // 1500)
        plot_df = plot_df.iloc[::step].copy()
    if theme_mode == "dark":
        paper_bg = "rgba(0,0,0,0)"
        plot_bg = "rgba(0,0,0,0)"
        text_color = "#fafafa"
        grid_color = "rgba(255,255,255,0.08)"
        line_color = "#4A90E2"
    else:
        paper_bg = "rgba(0,0,0,0)"
        plot_bg = "rgba(0,0,0,0)"
        text_color = "#2c2c2c"
        grid_color = "rgba(0,0,0,0.08)"
        line_color = "#1f77b4"
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=plot_df["date"], y=plot_df["nav"],
        mode="lines",
        name="NAV",
        line=dict(color=line_color, width=1.8),
        hovertemplate="<b>%{x|%d %b %Y}</b><br>NAV: ₹%{y:.4f}<extra></extra>",
    ))
    fig.update_layout(
        title="NAV History",
        title_x=0.5,
        title_font=dict(size=14),
        paper_bgcolor=paper_bg,
        plot_bgcolor=plot_bg,
        font=dict(color=text_color, size=11),
        margin=dict(l=8, r=8, t=40, b=8),
        xaxis=dict(showgrid=True, gridcolor=grid_color),
        yaxis=dict(showgrid=True, gridcolor=grid_color, tickprefix="₹"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=380,
    )
    fig.update_xaxes(tickformat="%b %Y")
    return fig


def build_projection_chart(monthly_investment, annual_rate, years, theme_mode="light"):
    """Build a cumulative-investment vs projected-value chart for a SIP."""
    if monthly_investment <= 0 or annual_rate <= 0 or years <= 0:
        return None
    i = annual_rate / 12
    n_total = int(years * 12)
    months = np.arange(1, n_total + 1)
    # Cumulative invested
    invested = monthly_investment * months
    # Future value at each month
    fv = monthly_investment * (((1 + i) ** months - 1) / i) * (1 + i)
    if theme_mode == "dark":
        text_color = "#fafafa"
        grid_color = "rgba(255,255,255,0.08)"
        inv_color = "#9B51E0"
        val_color = "#4A90E2"
    else:
        text_color = "#2c2c2c"
        grid_color = "rgba(0,0,0,0.08)"
        inv_color = "#7B3FCB"
        val_color = "#1f77b4"
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=months, y=invested, mode="lines", name="Invested",
        line=dict(color=inv_color, width=2, dash="dot"),
        hovertemplate="Month %{x}<br>Invested: ₹%{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=months, y=fv, mode="lines", name="Projected Value",
        line=dict(color=val_color, width=2),
        hovertemplate="Month %{x}<br>Value: ₹%{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title="SIP Projection: Invested vs Projected Value",
        title_x=0.5,
        title_font=dict(size=14),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=text_color, size=11),
        margin=dict(l=8, r=8, t=40, b=8),
        xaxis=dict(title="Month", showgrid=True, gridcolor=grid_color),
        yaxis=dict(title="Amount (₹)", showgrid=True, gridcolor=grid_color, tickprefix="₹"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=380,
    )
    return fig


# --- Main UI -----------------------------------------------------------------
def main():
    st.title("MF Return Estimator")
    st.caption("Analyze Indian mutual fund SIPs and lumpsum investments with real NAV history.")

    # Sidebar - scheme search
    with st.sidebar:
        st.header("Fund Lookup")
        scheme_list_df = fetch_scheme_list()
        if scheme_list_df.empty:
            st.error("Could not load the fund list. Please refresh.")
            st.stop()
        search_term = st.text_input(
            "Search fund by name",
            value="",
            placeholder="e.g. Parag Parikh, Axis Bluechip, HDFC Mid",
            help="Type a fund name or keyword. Matches are case-insensitive.",
        )
        # Filter schemes
        if search_term.strip():
            mask = scheme_list_df["schemeName"].str.contains(search_term, case=False, na=False)
            filtered = scheme_list_df.loc[mask].head(50)
        else:
            # Show some popular schemes as default
            popular_keywords = ["Parag Parikh Flexi", "Axis Bluechip", "HDFC Mid-Cap",
                                "Mirae Asset Large Cap", "SBI Small Cap", "ICICI Pru Bluechip"]
            mask = scheme_list_df["schemeName"].str.contains("|".join(popular_keywords), case=False, na=False, regex=True)
            filtered = scheme_list_df.loc[mask].head(50)
        if filtered.empty:
            st.info("No funds match your search. Try another keyword.")
            st.stop()
        options = filtered["schemeName"].tolist()
        selected_name = st.selectbox(
            f"Matching funds ({len(options)} shown)",
            options=options,
            index=0,
        )
        selected_row = filtered.loc[filtered["schemeName"] == selected_name].iloc[0]
        scheme_code = str(selected_row["schemeCode"])
        st.session_state["selected_scheme_code"] = scheme_code
        st.session_state["selected_scheme_name"] = selected_name

    # Fetch NAV history for the selected scheme
    scheme_code = st.session_state.get("selected_scheme_code")
    scheme_name = st.session_state.get("selected_scheme_name")
    if not scheme_code:
        st.warning("Please select a fund from the sidebar.")
        st.stop()
    with st.spinner(f"Loading NAV history for {scheme_name}..."):
        nav_df, meta = fetch_nav_history(scheme_code, scheme_name)

    if nav_df.empty:
        st.error("No NAV history available for this scheme.")
        st.stop()

    # Display scheme metadata
    category_raw = meta.get("scheme_category", "")
    fund_house = meta.get("mutual_fund_family", meta.get("fund_house", ""))
    scheme_type = meta.get("scheme_type", "")
    normalized_cat = normalize_category(category_raw)
    return_estimate = get_category_return_estimate(normalized_cat)

    # Header with fund details
    st.subheader(scheme_name)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Fund House", fund_house or "-")
    col2.metric("Category", normalized_cat)
    col3.metric("Scheme Type", scheme_type or "-")
    # Latest NAV
    latest_nav = nav_df.iloc[-1]["nav"]
    latest_nav_date = nav_df.iloc[-1]["date"].strftime("%d %b %Y")
    col4.metric("Latest NAV", f"₹{latest_nav:.4f}", f"as on {latest_nav_date}")

    # NAV chart
    st.write("### NAV History")
    theme_mode = st.session_state.get("theme_mode", "Light")
    nav_fig = build_nav_chart(nav_df, theme_mode)
    if nav_fig:
        st.plotly_chart(nav_fig, use_container_width=True)
    # Data range note
    st.caption(f"Showing {len(nav_df)} NAV data points from {nav_df.iloc[0]['date'].strftime('%d %b %Y')} to {latest_nav_date}.")

    # Realized returns section
    st.write("### Realized Returns (from NAV history)")
    periods = [1, 3, 5, 7, 10, 15]
    available_periods = [p for p in periods if (nav_df.iloc[-1]["date"] - nav_df.iloc[0]["date"]).days >= p * 365]
    if not available_periods:
        st.info("This fund does not have enough history to compute realized returns for standard periods.")
    else:
        realized = calculate_returns_from_nav(nav_df, available_periods)
        realized_clean = {p: r for p, r in realized.items() if not np.isnan(r)}
        if realized_clean:
            rcols = st.columns(len(realized_clean))
            for col, (p, r) in zip(rcols, realized_clean.items()):
                col.metric(f"{p}Y CAGR", f"{r*100:.2f}%")
        else:
            st.info("Could not compute realized returns for this fund.")

    # Projection section
    st.write("### Projected Returns")
    st.write("Estimate the future value of SIP or lumpsum investments in this fund.")
    proj_tabs = st.tabs(["SIP", "Lumpsum"])
    with proj_tabs[0]:
        st.write("#### SIP Calculator")
        sc1, sc2, sc3 = st.columns(3)
        monthly = sc1.number_input("Monthly Investment (₹)", min_value=500, value=SIP_DEFAULT_MONTHLY, step=500, key="sip_monthly")
        sip_years = sc2.number_input("Duration (years)", min_value=1, max_value=40, value=SIP_DEFAULT_YEARS, key="sip_years")
        sip_rate = sc3.number_input("Expected Annual Return (%)", min_value=1.0, max_value=30.0, value=round(return_estimate*100, 2), step=0.5, key="sip_rate") / 100.0
        sip_fv = calculate_sip_future_value(monthly, sip_rate, sip_years)
        total_invested = monthly * sip_years * 12
        gains = sip_fv - total_invested
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Total Invested", f"₹{total_invested:,.0f}")
        mc2.metric("Projected Value", f"₹{sip_fv:,.0f}")
        mc3.metric("Estimated Gains", f"₹{gains:,.0f}", f"{(gains/total_invested*100) if total_invested else 0:.1f}%")
        st.write("##### Projection Chart")
        proj_fig = build_projection_chart(monthly, sip_rate, sip_years, theme_mode)
        if proj_fig:
            st.plotly_chart(proj_fig, use_container_width=True)
        st.caption("Note: Projections are based on the assumed return rate and do not guarantee future performance. Mutual fund investments are subject to market risks.")
    with proj_tabs[1]:
        st.write("#### Lumpsum Calculator")
        lc1, lc2, lc3 = st.columns(3)
        principal = lc1.number_input("Investment Amount (₹)", min_value=1000, value=100000, step=5000, key="lump_principal")
        lump_years = lc2.number_input("Duration (years)", min_value=1, max_value=40, value=10, key="lump_years")
        lump_rate = lc3.number_input("Expected Annual Return (%)", min_value=1.0, max_value=30.0, value=round(return_estimate*100, 2), step=0.5, key="lump_rate") / 100.0
        lump_fv = calculate_lumpsum_future_value(principal, lump_rate, lump_years)
        lump_gains = lump_fv - principal
        lc1m, lc2m, lc3m = st.columns(3)
        lc1m.metric("Invested", f"₹{principal:,.0f}")
        lc2m.metric("Projected Value", f"₹{lump_fv:,.0f}")
        lc3m.metric("Estimated Gains", f"₹{lump_gains:,.0f}", f"{(lump_gains/principal*100) if principal else 0:.1f}%")
        st.caption("Note: Projections are based on the assumed return rate and do not guarantee future performance. Mutual fund investments are subject to market risks.")

    # Footer / disclaimer
    st.divider()
    st.caption("Data source: mfapi.in. This tool is for informational purposes only and is not investment advice.")


if __name__ == "__main__":
    main()
