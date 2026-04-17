import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import requests
from pathlib import Path
from calc_engine import calculate_metrics

st.set_page_config(page_title="Multifamily Market Analytics", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] label {
    color: white !important;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# PASSWORD GATE
# ---------------------------------------------------------
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")
FRED_KEY = st.secrets.get("FRED_API_KEY", "30a709ea0e7f3eb954d3b60d096f925f")
CENSUS_KEY = st.secrets.get("CENSUS_API_KEY", "c6039957fbd8a5a0445cc17afdff0df926fc70a1")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "pw_error" not in st.session_state:
    st.session_state.pw_error = False

if not st.session_state.authenticated:
    st.title("🏢 RealEstate-Analytics.ai")
    st.markdown("#### Multifamily & Market Intelligence")
    if st.session_state.pw_error:
        st.error("❌ Incorrect password. Please try again.")
        st.session_state.pw_error = False
    password = st.text_input("🔒 Please enter access password", type="password")
    if st.button("Unlock"):
        if password == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.session_state.pw_error = True
            st.rerun()
    st.stop()

# ---------------------------------------------------------
# FRED DATA FUNCTIONS
# ---------------------------------------------------------
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

@st.cache_data(show_spinner="Fetching 10-Year Treasury from FRED...")
def get_treasury_rate(fred_key):
    try:
        url = f"{FRED_BASE}?series_id=DGS10&api_key={fred_key}&file_type=json&limit=10&sort_order=desc"
        r = requests.get(url, timeout=10)
        data = r.json()
        if "observations" not in data:
            return 4.29, "2026-04-15"
        obs = [o for o in data["observations"] if o["value"] != "."]
        if obs:
            return float(obs[0]["value"]), obs[0]["date"]
        return 4.29, "2026-04-15"
    except Exception:
        return 4.29, "2026-04-15"

@st.cache_data(show_spinner="Fetching multifamily vacancy rate from FRED...")
def get_multifamily_vacancy(fred_key):
    try:
        url = f"{FRED_BASE}?series_id=RRVRUSQ156N&api_key={fred_key}&file_type=json&limit=20&sort_order=desc"
        r = requests.get(url, timeout=10)
        data = r.json()
        if "observations" not in data:
            return 7.2, "2025-10-01"
        obs = [o for o in data["observations"] if o["value"] != "."]
        if obs:
            return float(obs[0]["value"]), obs[0]["date"]
        return 7.2, "2025-10-01"
    except Exception:
        return 7.2, "2025-10-01"

@st.cache_data(show_spinner="Fetching rent index from FRED...")
def get_rent_index_history(fred_key):
    try:
        url = f"{FRED_BASE}?series_id=CUSR0000SEHA&api_key={fred_key}&file_type=json&sort_order=asc"
        r = requests.get(url, timeout=15)
        data = r.json()
        if "observations" not in data:
            raise ValueError("No observations")
        obs = [o for o in data["observations"] if o["value"] != "."]
        dates = pd.to_datetime([o["date"] for o in obs])
        values = [float(o["value"]) for o in obs]
        return pd.Series(values, index=dates)
    except Exception:
        # Synthetic fallback — approximate CPI rent index 2019-2026
        dates = pd.date_range(start="2019-01-01", end="2026-04-01", freq="MS")
        base = 300.0
        values = [base * (1.005 ** i) for i in range(len(dates))]
        return pd.Series(values, index=dates)

@st.cache_data(show_spinner="Fetching mortgage rate history from FRED...")
def get_mortgage_rate_history(fred_key):
    try:
        url = f"{FRED_BASE}?series_id=MORTGAGE30US&api_key={fred_key}&file_type=json&sort_order=asc"
        r = requests.get(url, timeout=15)
        data = r.json()
        if "observations" not in data:
            raise ValueError("No observations")
        obs = [o for o in data["observations"] if o["value"] != "."]
        dates = pd.to_datetime([o["date"] for o in obs])
        values = [float(o["value"]) for o in obs]
        return pd.Series(values, index=dates)
    except Exception:
        # Synthetic fallback — approximate 30yr mortgage rate 2019-2026
        dates = pd.date_range(start="2019-01-01", end="2026-04-01", freq="W")
        values = ([3.5]*52 + [3.0]*52 + [3.1]*52 + [5.5]*52 + [6.8]*52 + [7.0]*52 + [6.9]*26)
        values = values[:len(dates)]
        return pd.Series(values, index=dates)

@st.cache_data(show_spinner="Fetching Census rental data...")
def get_census_data(zip_code, census_key):
    url = (
        f"https://api.census.gov/data/2022/acs/acs5"
        f"?get=B25064_001E,B25002_001E,B25002_003E,B25003_001E,B25003_003E"
        f"&for=zip%20code%20tabulation%20area:{zip_code}"
        f"&key={census_key}"
    )
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if len(data) < 2:
            return None
        row = data[1]
        median_rent = int(row[0]) if row[0] and row[0] != "-666666666" else None
        total_units = int(row[1]) if row[1] else None
        vacant_units = int(row[2]) if row[2] else None
        total_occupied = int(row[3]) if row[3] else None
        renter_occupied = int(row[4]) if row[4] else None
        vacancy_rate = (vacant_units / total_units * 100) if total_units and vacant_units else None
        renter_pct = (renter_occupied / total_occupied * 100) if total_occupied and renter_occupied else None
        return {
            "median_rent": median_rent,
            "vacancy_rate": vacancy_rate,
            "renter_pct": renter_pct,
            "total_units": total_units
        }
    except:
        return None

# ---------------------------------------------------------
# CAP RATE ESTIMATOR
# ---------------------------------------------------------
def estimate_cap_rate_range(treasury_rate, property_type):
    spreads = {
        "Multifamily 2-4 units": (150, 250),
        "Multifamily 5+ units": (175, 275),
    }
    low_spread, high_spread = spreads.get(property_type, (175, 275))
    cap_low = treasury_rate + (low_spread / 100)
    cap_high = treasury_rate + (high_spread / 100)
    return round(cap_low, 2), round(cap_high, 2)

def market_signal_multi(vacancy_rate, yoy_rent_change):
    if vacancy_rate is None:
        return "Insufficient data for market signal", "#666666"
    if vacancy_rate < 4 and yoy_rent_change > 3:
        label, color = "strong landlord's market — low vacancy, rising rents", "#0F6E56"
    elif vacancy_rate < 6 and yoy_rent_change > 0:
        label, color = "stable landlord's market — healthy fundamentals", "#185FA5"
    elif vacancy_rate < 8:
        label, color = "balanced market — monitor rent trends", "#854F0B"
    else:
        label, color = "tenant's market — elevated vacancy, rent pressure", "#A32D2D"
    return label, color

# ---------------------------------------------------------
# GRADE COLOR HELPER
# ---------------------------------------------------------
def grade_color(grade):
    return {"A": "#0F6E56", "B": "#1D9E75", "C": "#EF9F27", "D": "#E05C2A", "F": "#A32D2D"}.get(grade, "#666")

# ---------------------------------------------------------
# DEAL ANALYSIS DISPLAY (reusable for single + dual)
# ---------------------------------------------------------
def display_deal_analysis(label, address, results, acq_price, monthly_rent, num_units,
                          down_pct, mortgage_rate, mortgage_term, vacancy_rate,
                          cap_low, cap_high, treasury_rate, time_horizon):

    your_cap = results["Cap Rate (%)"]
    coc = results["Cash-on-Cash Return (%)"]
    irr_total = results["IRR (Total incl. Sale) (%)"]
    irr_op = results["IRR (Operational) (%)"]
    eq_mult = results["equity_multiple"]
    monthly_mortgage = results["Monthly Mortgage ($)"]
    grade = results["Grade"]
    first_yr_cf = results["First Year Cash Flow ($)"]
    cash_flows = results["Multi-Year Cash Flow"]
    rents = results["Annual Rents $ (by year)"]
    noi_list = results["NOI by year"]
    prop_value = results["Current Property Value ($)"]
    remaining_bal = results["Remaining Loan Balance ($)"]

    cap_signal = "✅ Above market — attractive yield" if your_cap > cap_high else \
                 "⚠️ At market range" if your_cap >= cap_low else \
                 "🔴 Below market cap rate — priced rich"

    treasury_spread_deal = your_cap - treasury_rate if treasury_rate else None
    spread_signal = ""
    if treasury_spread_deal is not None:
        if treasury_spread_deal > 2.0:
            spread_signal = "✅ Healthy spread over Treasury"
        elif treasury_spread_deal > 1.0:
            spread_signal = "⚠️ Thin but acceptable spread"
        else:
            spread_signal = "🔴 Compressed spread — limited risk premium"

    if address:
        st.markdown(f"**📍 {address}**")

    # Grade badge
    st.markdown(
        f"<span style='background:{grade_color(grade)};color:white;padding:4px 14px;"
        f"border-radius:20px;font-size:18px;font-weight:bold;'>Grade: {grade}</span>",
        unsafe_allow_html=True
    )
    st.markdown("")

    # Key metrics row 1
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cap Rate", f"{your_cap:.2f}%", cap_signal)
    c2.metric("Cash-on-Cash", f"{coc:.2f}%")
    c3.metric("IRR (Total)", f"{irr_total:.2f}%")
    c4.metric("IRR (Operational)", f"{irr_op:.2f}%")
    c5.metric("Equity Multiple", f"{eq_mult:.2f}x")

    # Key metrics row 2
    c6, c7, c8, c9, c10 = st.columns(5)
    c6.metric("Monthly Mortgage", f"${monthly_mortgage:,.0f}")
    c7.metric("Yr-1 Cash Flow", f"${first_yr_cf:,.0f}")
    c8.metric("Price / Unit", f"${acq_price / num_units:,.0f}")
    c9.metric("Rent / Unit/Mo", f"${monthly_rent / num_units:,.0f}")
    c10.metric("GRM", f"{acq_price / (monthly_rent * 12):.1f}x")

    # Treasury spread banner
    if treasury_spread_deal is not None:
        st.markdown(f"""
<div style="background:#1D9E7522; border-left:4px solid #1D9E75;
padding:10px 16px; border-radius:6px; margin: 0.5rem 0; font-size:14px;">
<strong>Treasury Spread:</strong> {treasury_spread_deal:.2f}% ({treasury_spread_deal*100:.0f} bps) — {spread_signal}
</div>""", unsafe_allow_html=True)

    st.markdown("")

    # Cash flow chart
    years = list(range(1, len(cash_flows) + 1))
    fig_cf = go.Figure()
    fig_cf.add_trace(go.Bar(
        x=years, y=cash_flows,
        marker_color=["#1D9E75" if v >= 0 else "#A32D2D" for v in cash_flows],
        name="Annual Cash Flow"
    ))
    fig_cf.add_trace(go.Scatter(
        x=years, y=noi_list,
        mode="lines+markers", line=dict(color="#378ADD", width=2),
        name="NOI"
    ))
    fig_cf.update_layout(
        title="Annual Cash Flow vs NOI",
        height=280, margin=dict(t=40, b=40),
        yaxis_tickprefix="$", yaxis_tickformat=",",
        legend=dict(orientation="h", y=1.1),
        hovermode="x unified"
    )
    st.plotly_chart(fig_cf, use_container_width=True)

    # Equity build table
    down_amt = acq_price * (down_pct / 100)
    equity_now = prop_value - remaining_bal
    st.markdown(f"""
<div style="background:#37474F22; border-left:4px solid #378ADD;
padding:10px 16px; border-radius:6px; font-size:14px; margin-bottom:0.5rem;">
<strong>Equity Position at Yr {time_horizon}:</strong>
Property Value: <strong>${prop_value:,.0f}</strong> &nbsp;|&nbsp;
Remaining Loan: <strong>${remaining_bal:,.0f}</strong> &nbsp;|&nbsp;
Estimated Equity: <strong>${equity_now:,.0f}</strong>
</div>""", unsafe_allow_html=True)

    # Multi-year table
    with st.expander("📋 Full Multi-Year Projection"):
        df = pd.DataFrame({
            "Year": years,
            "Gross Annual Rent ($)": rents,
            "NOI ($)": noi_list,
            "Cash Flow ($)": cash_flows,
        })
        df = df.set_index("Year")
        st.dataframe(df.style.format("${:,.0f}"), use_container_width=True)


# ---------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------
st.sidebar.header("🏢 Multifamily Market Explorer")
zip_input = st.sidebar.text_input("Enter ZIP Code", value="94526", max_chars=5)
property_type = st.sidebar.selectbox(
    "Property Type",
    ["Multifamily 2-4 units", "Multifamily 5+ units"]
)

st.sidebar.markdown("---")
st.sidebar.header("🏠 Multifamily Property Analyzer")
st.sidebar.caption("Enter deal parameters for full analysis")

address_a = st.sidebar.text_input("Street Address", placeholder="e.g. 616 Aleta Pl, Pleasant Hill, CA 94523")

acq_price_a = st.sidebar.number_input("Acquisition Price ($)", value=1500000, step=50000, key="acq_a")
gross_rent_a = st.sidebar.number_input("Gross Monthly Rent ($)", value=8000, step=500, key="rent_a")
num_units_a = st.sidebar.number_input("Number of Units", value=6, step=1, min_value=1, key="units_a")
down_pct_a = st.sidebar.number_input("Down Payment (%)", value=25.0, step=1.0, key="down_a")
int_rate_a = st.sidebar.number_input("Interest Rate (%)", value=7.0, step=0.1, key="rate_a")
loan_term_a = st.sidebar.number_input("Loan Term (years)", value=30, step=5, key="term_a")
expenses_a = st.sidebar.number_input("Monthly Expenses ($)", value=2000, step=100, key="exp_a")
vacancy_a = st.sidebar.number_input("Vacancy Rate (%)", value=5.0, step=0.5, key="vac_a")
rent_growth_a = st.sidebar.number_input("Rent Growth Rate (%/yr)", value=3.0, step=0.5, key="rg_a")
appr_rate_a = st.sidebar.number_input("Appreciation Rate (%/yr)", value=4.0, step=0.5, key="ap_a")
time_horizon_a = st.sidebar.number_input("Time Horizon (years)", value=10, step=1, min_value=1, max_value=30, key="th_a")

# ---------------------------------------------------------
# FETCH ALL DATA
# ---------------------------------------------------------
treasury_rate, treasury_date = get_treasury_rate(FRED_KEY)
vacancy_national, vacancy_date = get_multifamily_vacancy(FRED_KEY)
rent_index = get_rent_index_history(FRED_KEY)
mortgage_history = get_mortgage_rate_history(FRED_KEY)
census_data = get_census_data(zip_input.strip(), CENSUS_KEY)

if treasury_rate:
    cap_low, cap_high = estimate_cap_rate_range(treasury_rate, property_type)
else:
    cap_low, cap_high = 5.0, 6.5

try:
    recent_rent = rent_index.iloc[-1]
    year_ago_rent = rent_index[rent_index.index <= rent_index.index[-1] - pd.DateOffset(years=1)].iloc[-1]
    yoy_rent_pct = ((recent_rent - year_ago_rent) / year_ago_rent) * 100
except:
    yoy_rent_pct = 0.0

vac_for_signal = census_data["vacancy_rate"] if census_data else vacancy_national
signal_text, sig_color = market_signal_multi(vac_for_signal, yoy_rent_pct)

# ---------------------------------------------------------
# THREE TABS
# ---------------------------------------------------------
tab1, tab2, tab3 = st.tabs(["📊 Market Intelligence", "🏠 Single Multifamily", "⚖️ Dual Multifamily Comp"])

# =========================================================
# TAB 1 — MARKET INTELLIGENCE (unchanged from original)
# =========================================================
with tab1:
    st.title(f"🏢 Multifamily Market Intelligence — ZIP {zip_input}")
    st.caption(f"Sources: FRED (Federal Reserve) · U.S. Census ACS · HUD FMR | Property Type: {property_type}")

    st.markdown(f"""
<div style="background:{sig_color}22; border-left:4px solid {sig_color};
padding:12px 16px; border-radius:6px; margin-bottom:1rem; font-size:15px;">
<strong>ZIP {zip_input} — {property_type}</strong> — {signal_text}
</div>""", unsafe_allow_html=True)

    st.subheader("📊 Market Benchmarks")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("10-Yr Treasury", f"{treasury_rate:.2f}%" if treasury_rate else "N/A",
                help="Current 10-year US Treasury yield from FRED")
    col2.metric("Est. Cap Rate Range", f"{cap_low:.1f}% – {cap_high:.1f}%",
                help=f"Estimated market cap rate = Treasury + typical {property_type} spread")
    col3.metric("Treasury Spread", f"{(cap_low + cap_high)/2 - treasury_rate:.0f} bps" if treasury_rate else "N/A",
                help="Cap rate premium over risk-free 10-yr Treasury")
    col4.metric("National Rental Vacancy", f"{vacancy_national:.1f}%" if vacancy_national else "N/A",
                help=f"As of {vacancy_date}")
    col5.metric("Rent Index YoY", f"{yoy_rent_pct:+.1f}%",
                help="CPI Rent of Primary Residence — year-over-year change")

    st.markdown("---")

    if census_data:
        st.subheader(f"📍 ZIP {zip_input} — Local Rental Market (Census ACS)")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Median Gross Rent", f"${census_data['median_rent']:,}/mo" if census_data['median_rent'] else "N/A")
        c2.metric("Local Vacancy Rate", f"{census_data['vacancy_rate']:.1f}%" if census_data['vacancy_rate'] else "N/A")
        c3.metric("Renter Occupancy", f"{census_data['renter_pct']:.1f}%" if census_data['renter_pct'] else "N/A")
        c4.metric("Total Housing Units", f"{census_data['total_units']:,}" if census_data['total_units'] else "N/A")
    else:
        st.info(f"Census data not available for ZIP {zip_input}. Showing national benchmarks.")

    st.markdown("---")

    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader("📈 National Rent Index Trend")
        rent_5yr = rent_index[rent_index.index >= rent_index.index[-1] - pd.DateOffset(years=5)]
        fig_rent = go.Figure()
        fig_rent.add_trace(go.Scatter(
            x=rent_5yr.index, y=rent_5yr.values,
            mode="lines", line=dict(color="#1D9E75", width=2),
            fill="tozeroy", fillcolor="rgba(29,158,117,0.1)"
        ))
        fig_rent.update_layout(height=300, margin=dict(t=20, b=40),
                               yaxis_title="CPI Rent Index", hovermode="x unified")
        st.plotly_chart(fig_rent, use_container_width=True)

    with col_right:
        st.subheader("📉 30-Year Mortgage Rate Trend")
        mort_5yr = mortgage_history[mortgage_history.index >= mortgage_history.index[-1] - pd.DateOffset(years=5)]
        fig_mort = go.Figure()
        fig_mort.add_trace(go.Scatter(
            x=mort_5yr.index, y=mort_5yr.values,
            mode="lines", line=dict(color="#378ADD", width=2),
            fill="tozeroy", fillcolor="rgba(55,138,221,0.1)"
        ))
        fig_mort.update_layout(height=300, margin=dict(t=20, b=40),
                               yaxis_title="Rate (%)", yaxis_ticksuffix="%", hovermode="x unified")
        st.plotly_chart(fig_mort, use_container_width=True)

    st.markdown("---")
    st.subheader("🎯 Cap Rate Spread Visualizer")

    annual_rent_quick = gross_rent_a * 12
    noi_quick = annual_rent_quick * 0.60
    your_cap_quick = (noi_quick / acq_price_a) * 100 if acq_price_a > 0 else 0

    categories = ["10-Yr Treasury", "Est. Cap Rate Low", "Est. Cap Rate High", "Your Cap Rate"]
    values = [treasury_rate if treasury_rate else 0, cap_low, cap_high, your_cap_quick]
    colors = ["#378ADD", "#1D9E75", "#0F6E56", "#EF9F27"]
    fig_spread = go.Figure(go.Bar(
        x=categories, y=values, marker_color=colors,
        text=[f"{v:.2f}%" for v in values], textposition="outside"
    ))
    fig_spread.update_layout(height=320, margin=dict(t=20, b=40),
                              yaxis=dict(ticksuffix="%", range=[0, max(values) * 1.3]))
    st.plotly_chart(fig_spread, use_container_width=True)

    st.markdown("---")
    with st.expander("📋 View Raw Market Data"):
        st.write("**FRED Data Points:**")
        st.json({
            "10_yr_treasury_rate": treasury_rate,
            "treasury_date": treasury_date,
            "national_rental_vacancy_pct": vacancy_national,
            "vacancy_date": vacancy_date,
            "rent_index_yoy_change_pct": round(yoy_rent_pct, 2)
        })
        if census_data:
            st.write("**Census ACS Data:**")
            st.json(census_data)

    st.caption(f"RealEstate-Analytics.ai | Multifamily Market Intelligence | ZIP {zip_input} | {property_type} | v2.0")

# =========================================================
# TAB 2 — SINGLE MULTIFAMILY ANALYZER
# =========================================================
with tab2:
    st.title("🏠 Multifamily Property Analyzer")
    st.caption("Full CCIM-level deal analysis — enter parameters in the left sidebar")

    st.markdown(f"""
<div style="background:{sig_color}22; border-left:4px solid {sig_color};
padding:12px 16px; border-radius:6px; margin-bottom:1rem; font-size:15px;">
<strong>Market Context — ZIP {zip_input}:</strong> {signal_text} &nbsp;|&nbsp;
Est. Market Cap Rate: <strong>{cap_low:.1f}% – {cap_high:.1f}%</strong> &nbsp;|&nbsp;
10-Yr Treasury: <strong>{treasury_rate:.2f}%</strong>
</div>""", unsafe_allow_html=True)

    results_a = calculate_metrics(
        purchase_price=acq_price_a,
        monthly_rent=gross_rent_a,
        down_payment_pct=down_pct_a,
        mortgage_rate=int_rate_a,
        mortgage_term=loan_term_a,
        monthly_expenses=expenses_a,
        vacancy_rate=vacancy_a,
        appreciation_rate=appr_rate_a,
        rent_growth_rate=rent_growth_a,
        time_horizon=int(time_horizon_a)
    )

    display_deal_analysis(
        label="Property A",
        address=address_a,
        results=results_a,
        acq_price=acq_price_a,
        monthly_rent=gross_rent_a,
        num_units=num_units_a,
        down_pct=down_pct_a,
        mortgage_rate=int_rate_a,
        mortgage_term=loan_term_a,
        vacancy_rate=vacancy_a,
        cap_low=cap_low,
        cap_high=cap_high,
        treasury_rate=treasury_rate if treasury_rate else 4.29,
        time_horizon=int(time_horizon_a)
    )

# =========================================================
# TAB 3 — DUAL MULTIFAMILY COMP
# =========================================================
with tab3:
    st.title("⚖️ Dual Multifamily Comparison")
    st.caption("Compare two properties side by side — Property A uses sidebar inputs")

    # Property B inputs inline (not sidebar — keeps sidebar clean)
    st.markdown("### 🅱️ Property B — Enter Second Deal")
    b1, b2, b3 = st.columns(3)
    with b1:
        address_b = st.text_input("Street Address (B)", placeholder="e.g. 44778 Challenge Common, Fremont, CA", key="addr_b")
        acq_price_b = st.number_input("Acquisition Price ($)", value=1200000, step=50000, key="acq_b")
        gross_rent_b = st.number_input("Gross Monthly Rent ($)", value=7000, step=500, key="rent_b")
        num_units_b = st.number_input("Number of Units", value=4, step=1, min_value=1, key="units_b")
    with b2:
        down_pct_b = st.number_input("Down Payment (%)", value=25.0, step=1.0, key="down_b")
        int_rate_b = st.number_input("Interest Rate (%)", value=7.0, step=0.1, key="rate_b")
        loan_term_b = st.number_input("Loan Term (years)", value=30, step=5, key="term_b")
        expenses_b = st.number_input("Monthly Expenses ($)", value=1800, step=100, key="exp_b")
    with b3:
        vacancy_b = st.number_input("Vacancy Rate (%)", value=5.0, step=0.5, key="vac_b")
        rent_growth_b = st.number_input("Rent Growth Rate (%/yr)", value=3.0, step=0.5, key="rg_b")
        appr_rate_b = st.number_input("Appreciation Rate (%/yr)", value=4.0, step=0.5, key="ap_b")
        time_horizon_b = st.number_input("Time Horizon (years)", value=10, step=1, min_value=1, max_value=30, key="th_b")

    st.markdown("---")

    results_b = calculate_metrics(
        purchase_price=acq_price_b,
        monthly_rent=gross_rent_b,
        down_payment_pct=down_pct_b,
        mortgage_rate=int_rate_b,
        mortgage_term=loan_term_b,
        monthly_expenses=expenses_b,
        vacancy_rate=vacancy_b,
        appreciation_rate=appr_rate_b,
        rent_growth_rate=rent_growth_b,
        time_horizon=int(time_horizon_b)
    )

    # Side by side summary comparison
    st.subheader("📊 Head-to-Head Summary")

    metrics_compare = {
        "Cap Rate (%)": (results_a["Cap Rate (%)"], results_b["Cap Rate (%)"]),
        "Cash-on-Cash (%)": (results_a["Cash-on-Cash Return (%)"], results_b["Cash-on-Cash Return (%)"]),
        "IRR Total (%)": (results_a["IRR (Total incl. Sale) (%)"], results_b["IRR (Total incl. Sale) (%)"]),
        "IRR Operational (%)": (results_a["IRR (Operational) (%)"], results_b["IRR (Operational) (%)"]),
        "Equity Multiple": (results_a["equity_multiple"], results_b["equity_multiple"]),
        "Yr-1 Cash Flow ($)": (results_a["First Year Cash Flow ($)"], results_b["First Year Cash Flow ($)"]),
        "Monthly Mortgage ($)": (results_a["Monthly Mortgage ($)"], results_b["Monthly Mortgage ($)"]),
        "Price / Unit ($)": (acq_price_a / num_units_a, acq_price_b / num_units_b),
        "Rent / Unit/Mo ($)": (gross_rent_a / num_units_a, gross_rent_b / num_units_b),
        "GRM": (acq_price_a / (gross_rent_a * 12), acq_price_b / (gross_rent_b * 12)),
    }

    label_a = address_a if address_a else "Property A"
    label_b = address_b if address_b else "Property B"

    # Build comparison table with winner highlights
    rows = []
    higher_is_better = {"Cap Rate (%)": True, "Cash-on-Cash (%)": True, "IRR Total (%)": True,
                         "IRR Operational (%)": True, "Equity Multiple": True, "Yr-1 Cash Flow ($)": True,
                         "Rent / Unit/Mo ($)": True}
    lower_is_better = {"Monthly Mortgage ($)": True, "Price / Unit ($)": True, "GRM": True}

    for metric, (val_a, val_b) in metrics_compare.items():
        if metric in higher_is_better:
            winner = "A" if val_a > val_b else "B" if val_b > val_a else "Tie"
        elif metric in lower_is_better:
            winner = "A" if val_a < val_b else "B" if val_b < val_a else "Tie"
        else:
            winner = "—"

        if "$" in metric:
            fmt_a = f"${val_a:,.0f}"
            fmt_b = f"${val_b:,.0f}"
        elif "%" in metric:
            fmt_a = f"{val_a:.2f}%"
            fmt_b = f"{val_b:.2f}%"
        else:
            fmt_a = f"{val_a:.2f}x"
            fmt_b = f"{val_b:.2f}x"

        rows.append({"Metric": metric, label_a: fmt_a, label_b: fmt_b, "Winner": f"🏆 {winner}" if winner not in ["Tie", "—"] else winner})

    df_compare = pd.DataFrame(rows).set_index("Metric")
    st.dataframe(df_compare, use_container_width=True)

    st.markdown("---")

    # Grade comparison
    grade_a = results_a["Grade"]
    grade_b = results_b["Grade"]
    gc1, gc2 = st.columns(2)
    with gc1:
        st.markdown(f"**{label_a}**")
        st.markdown(
            f"<span style='background:{grade_color(grade_a)};color:white;padding:4px 14px;"
            f"border-radius:20px;font-size:18px;font-weight:bold;'>Grade: {grade_a}</span>",
            unsafe_allow_html=True
        )
    with gc2:
        st.markdown(f"**{label_b}**")
        st.markdown(
            f"<span style='background:{grade_color(grade_b)};color:white;padding:4px 14px;"
            f"border-radius:20px;font-size:18px;font-weight:bold;'>Grade: {grade_b}</span>",
            unsafe_allow_html=True
        )

    st.markdown("---")

    # Side by side cash flow charts
    st.subheader("📈 Cash Flow Comparison")
    cf_col1, cf_col2 = st.columns(2)

    def cf_chart(results, label, color):
        cash_flows = results["Multi-Year Cash Flow"]
        noi_list = results["NOI by year"]
        years = list(range(1, len(cash_flows) + 1))
        fig = go.Figure()
        fig.add_trace(go.Bar(x=years, y=cash_flows,
                             marker_color=["#1D9E75" if v >= 0 else "#A32D2D" for v in cash_flows],
                             name="Cash Flow"))
        fig.add_trace(go.Scatter(x=years, y=noi_list,
                                 mode="lines+markers", line=dict(color=color, width=2), name="NOI"))
        fig.update_layout(title=label, height=280, margin=dict(t=40, b=40),
                          yaxis_tickprefix="$", yaxis_tickformat=",",
                          legend=dict(orientation="h", y=1.1), hovermode="x unified")
        return fig

    with cf_col1:
        st.plotly_chart(cf_chart(results_a, label_a, "#378ADD"), use_container_width=True)
    with cf_col2:
        st.plotly_chart(cf_chart(results_b, label_b, "#EF9F27"), use_container_width=True)

    st.caption(f"RealEstate-Analytics.ai | Dual Multifamily Comp | v2.0")
