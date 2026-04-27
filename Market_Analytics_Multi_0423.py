import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import requests
import re
from pathlib import Path

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
# PASSWORD + PIN GATE
# ---------------------------------------------------------
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")
try:
    VALID_PINS = dict(st.secrets["pins"])
except Exception:
    VALID_PINS = {}

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "pw_error" not in st.session_state:
    st.session_state.pw_error = False

if not st.session_state.authenticated:
    st.title("🏢 RealEstate-Analytics.ai")
    st.markdown("#### Multifamily & Market Intelligence")
    if st.session_state.pw_error:
        st.error("❌ Incorrect password or PIN. Please try again.")
        st.session_state.pw_error = False
    password = st.text_input("🔒 Access Password", type="password")
    pin = st.text_input("🔑 Your Access PIN", type="password")
    if st.button("Unlock"):
        pin_values = list(VALID_PINS.values()) if isinstance(VALID_PINS, dict) else []
        if password == APP_PASSWORD and pin in pin_values:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.session_state.pw_error = True
            st.rerun()
    st.stop()

# ---------------------------------------------------------
# FRED API
# ---------------------------------------------------------
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

@st.cache_data(show_spinner="Fetching 10-Year Treasury from FRED...")
def get_treasury_rate(fred_key):
    try:
        url = f"{FRED_BASE}?series_id=DGS10&api_key={fred_key}&file_type=json&limit=10&sort_order=desc"
        r = requests.get(url, timeout=8)
        data = r.json()
        obs = [o for o in data["observations"] if o["value"] != "."]
        if obs:
            return float(obs[0]["value"]), obs[0]["date"]
    except:
        pass
    return 4.35, "fallback — FRED unavailable"

@st.cache_data(show_spinner="Fetching vacancy rate from FRED...")
def get_multifamily_vacancy(fred_key):
    try:
        url = f"{FRED_BASE}?series_id=RRVRUSQ156N&api_key={fred_key}&file_type=json&limit=20&sort_order=desc"
        r = requests.get(url, timeout=8)
        data = r.json()
        obs = [o for o in data["observations"] if o["value"] != "."]
        if obs:
            return float(obs[0]["value"]), obs[0]["date"]
    except:
        pass
    return 6.1, "fallback — FRED unavailable"

@st.cache_data(show_spinner="Fetching rent index from FRED...")
def get_rent_index_history(fred_key):
    try:
        url = f"{FRED_BASE}?series_id=CUSR0000SEHA&api_key={fred_key}&file_type=json&sort_order=asc"
        r = requests.get(url, timeout=8)
        data = r.json()
        obs = [o for o in data["observations"] if o["value"] != "."]
        dates = pd.to_datetime([o["date"] for o in obs])
        values = [float(o["value"]) for o in obs]
        return pd.Series(values, index=dates)
    except:
        pass
    dates = pd.date_range(start="2020-01-01", end="2026-01-01", freq="MS")
    values = [300 * (1.005 ** i) for i in range(len(dates))]
    return pd.Series(values, index=dates)

@st.cache_data(show_spinner="Fetching mortgage rate from FRED...")
def get_mortgage_rate_history(fred_key):
    try:
        url = f"{FRED_BASE}?series_id=MORTGAGE30US&api_key={fred_key}&file_type=json&sort_order=asc"
        r = requests.get(url, timeout=8)
        data = r.json()
        obs = [o for o in data["observations"] if o["value"] != "."]
        dates = pd.to_datetime([o["date"] for o in obs])
        values = [float(o["value"]) for o in obs]
        return pd.Series(values, index=dates)
    except:
        pass
    from datetime import date
    end_date = date.today().strftime("%Y-%m-%d")
    dates = pd.date_range(start="2020-01-01", end=end_date, freq="MS")
    n = len(dates)
    base = [3.5, 3.2, 2.9, 3.1, 3.5, 4.2, 5.0, 6.5, 7.0, 7.2, 7.1, 6.9,
            6.8, 6.7, 6.6, 6.5, 6.4, 6.8, 7.1, 7.2, 7.0, 6.9, 6.7, 6.5,
            6.4, 6.3, 6.2, 6.4, 6.6, 6.8, 6.9, 7.0, 6.8, 6.7, 6.5, 6.4,
            6.3, 6.2, 6.1, 6.0, 5.9, 5.8, 5.7, 5.6, 5.5, 5.4, 5.3, 5.2,
            5.1, 5.0, 4.9, 4.8, 4.7, 4.6, 4.5, 4.4, 4.35, 4.3, 4.35, 4.4,
            4.35, 4.3, 4.35, 4.4, 4.35, 4.3, 4.35, 4.4, 4.35, 4.3, 4.35, 4.4]
    values = (base * 10)[:n]
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
# PROPERTY WEB LOOKUP — SerpAPI fallback
# ---------------------------------------------------------
@st.cache_data(show_spinner="Looking up property details from public listings...")
def lookup_property_web(address: str, serp_api_key: str, google_cse_id: str):
    """
    Searches via SerpAPI for property-level data when
    address is provided but unit count / rent is unknown.
    Returns dict with suggested units and rent range, or None if unavailable.
    """
    if not serp_api_key or not address.strip():
        return None

    query = f"{address} apartments units rent"
    url = "https://serpapi.com/search"
    params = {
        "api_key": serp_api_key,
        "engine": "google",
        "q": query,
        "num": 5
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 429:
            return {"error": "Daily search limit reached (100 free calls/day). Enter values manually."}
        if r.status_code != 200:
            return None

        data = r.json()
        # SerpAPI returns organic_results
        items = data.get("organic_results", [])
        if not items:
            return None

        # Combine all snippet text for parsing
        combined = " ".join([
            item.get("snippet", "") + " " + item.get("title", "")
            for item in items
        ])

        result = {}

        # Extract unit count — look for patterns like "96 units", "96-unit"
        unit_patterns = [
            r'(\d+)\s*[-–]?\s*unit',
            r'(\d+)\s+units',
            r'(\d+)\s+apartment',
        ]
        for pattern in unit_patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                units_found = int(match.group(1))
                if 2 <= units_found <= 5000:  # sanity range
                    result["suggested_units"] = units_found
                    break

        # Extract rent range — look for patterns like "$1,029", "$1,029 - $1,449"
        rent_matches = re.findall(r'\$(\d{1,2},?\d{3})', combined)
        rent_values = []
        for m in rent_matches:
            val = int(m.replace(",", ""))
            if 400 <= val <= 15000:  # sanity range for monthly rent
                rent_values.append(val)

        if rent_values:
            result["rent_low"] = min(rent_values)
            result["rent_high"] = max(rent_values)
            result["rent_midpoint"] = int(np.mean(rent_values))

        # Extract property name if available
        if items:
            result["source_title"] = items[0].get("title", "")[:80]

        return result if result else None

    except Exception as e:
        return None


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
# KEYS
# ---------------------------------------------------------
FRED_KEY = st.secrets.get("FRED_API_KEY", "")
CENSUS_KEY = st.secrets.get("CENSUS_API_KEY", "")
SERP_API_KEY = st.secrets.get("SERP_API_KEY", "")
GOOGLE_CSE_ID = st.secrets.get("GOOGLE_CSE_ID", "")

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
st.sidebar.header("🏠 Property Address Lookup")
street_address = st.sidebar.text_input(
    "Street Address (optional)",
    placeholder="e.g. 1818 S 7th St, Waco, TX 76706",
    help="Enter address to auto-suggest unit count and rent range from public listings"
)

# Run property lookup if address entered and Google keys available
property_lookup = None
if street_address.strip():
    if SERP_API_KEY:
        property_lookup = lookup_property_web(street_address.strip(), SERP_API_KEY, GOOGLE_CSE_ID)
    else:
        st.sidebar.caption("⚠️ Add SERP_API_KEY to secrets to enable address lookup.")

# Show lookup results as suggestions in sidebar
if property_lookup:
    if "error" in property_lookup:
        st.sidebar.warning(f"🔍 {property_lookup['error']}")
    else:
        st.sidebar.markdown("**🔍 Public Listing Suggestions** *(verify before using)*")
        if "suggested_units" in property_lookup:
            st.sidebar.info(f"Units found: **{property_lookup['suggested_units']}**")
        if "rent_low" in property_lookup:
            st.sidebar.info(
                f"Rent range: **${property_lookup['rent_low']:,} – ${property_lookup['rent_high']:,}/unit/mo**\n\n"
                f"Midpoint: **${property_lookup['rent_midpoint']:,}/unit/mo**"
            )
        if "source_title" in property_lookup:
            st.sidebar.caption(f"Source: {property_lookup['source_title']}")

st.sidebar.markdown("---")
st.sidebar.header("💰 Deal Parameters")
st.sidebar.caption("Enter to benchmark your deal against market")

# Pre-fill defaults from lookup if available, otherwise use original defaults
default_units = property_lookup.get("suggested_units", 6) if property_lookup and "error" not in property_lookup else 6
default_rent = property_lookup.get("rent_midpoint", 8000) if property_lookup and "rent_midpoint" in property_lookup else 8000

acquisition_price = st.sidebar.number_input("Acquisition Price ($)", value=1500000, step=50000)
gross_rent_monthly = st.sidebar.number_input("Gross Monthly Rent ($)", value=default_rent, step=500)
num_units = st.sidebar.number_input("Number of Units", value=default_units, step=1, min_value=1)

# Show rent-per-unit hint if units > 1
if num_units > 1:
    st.sidebar.caption(f"= ${gross_rent_monthly / num_units:,.0f}/unit/mo across {num_units} units")

# ---------------------------------------------------------
# FETCH MARKET DATA
# ---------------------------------------------------------
treasury_rate, treasury_date = get_treasury_rate(FRED_KEY)
vacancy_national, vacancy_date = get_multifamily_vacancy(FRED_KEY)
rent_index = get_rent_index_history(FRED_KEY)
mortgage_history = get_mortgage_rate_history(FRED_KEY)
census_data = get_census_data(zip_input.strip(), CENSUS_KEY)

# ---------------------------------------------------------
# MAIN DASHBOARD
# ---------------------------------------------------------
st.title(f"🏢 Multifamily Market Intelligence — ZIP {zip_input}")
st.caption(f"Sources: FRED (Federal Reserve) · U.S. Census ACS · HUD FMR | Property Type: {property_type}")

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

st.markdown(f"""
<div style="background:{sig_color}22; border-left:4px solid {sig_color};
padding:12px 16px; border-radius:6px; margin-bottom:1rem; font-size:15px;">
<strong>ZIP {zip_input} — {property_type}</strong> — {signal_text}
</div>""", unsafe_allow_html=True)

# Show property lookup banner on main page if results found
if property_lookup and "error" not in property_lookup and any(
    k in property_lookup for k in ["suggested_units", "rent_low"]
):
    lookup_parts = []
    if "suggested_units" in property_lookup:
        lookup_parts.append(f"**{property_lookup['suggested_units']} units** found")
    if "rent_low" in property_lookup:
        lookup_parts.append(
            f"rent range **${property_lookup['rent_low']:,}–${property_lookup['rent_high']:,}/unit/mo**"
        )
    st.info(
        f"🔍 Public listing lookup for *{street_address}*: {', '.join(lookup_parts)}. "
        f"Values pre-filled below — verify independently before finalizing analysis."
    )

st.subheader("📊 Market Benchmarks")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("10-Yr Treasury", f"{treasury_rate:.2f}%" if treasury_rate else "N/A")
col2.metric("Est. Cap Rate Range", f"{cap_low:.1f}% – {cap_high:.1f}%")
col3.metric("Treasury Spread", f"{(cap_low + cap_high)/2 - treasury_rate:.0f} bps" if treasury_rate else "N/A")
col4.metric("National Rental Vacancy", f"{vacancy_national:.1f}%" if vacancy_national else "N/A")
col5.metric("Rent Index YoY", f"{yoy_rent_pct:+.1f}%")

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

st.subheader("🧮 Your Deal vs Market Benchmarks")
annual_rent = gross_rent_monthly * 12
expense_ratio = 0.40
noi = annual_rent * (1 - expense_ratio)
your_cap_rate = (noi / acquisition_price) * 100 if acquisition_price > 0 else 0
price_per_unit = acquisition_price / num_units if num_units > 0 else 0
gross_rent_multiplier = acquisition_price / annual_rent if annual_rent > 0 else 0
rent_per_unit = gross_rent_monthly / num_units if num_units > 0 else 0

cap_signal = "✅ Above market — potentially attractive" if your_cap_rate > cap_high else \
             "⚠️ At market range" if your_cap_rate >= cap_low else \
             "🔴 Below market cap rate — priced rich"

treasury_spread_deal = your_cap_rate - treasury_rate if treasury_rate else None
spread_signal = ""
if treasury_spread_deal is not None:
    if treasury_spread_deal > 2.0:
        spread_signal = "✅ Healthy spread over Treasury"
    elif treasury_spread_deal > 1.0:
        spread_signal = "⚠️ Thin but acceptable spread"
    else:
        spread_signal = "🔴 Compressed spread — limited risk premium"

d1, d2, d3, d4 = st.columns(4)
d1.metric("Your Cap Rate", f"{your_cap_rate:.2f}%", cap_signal)
d2.metric("Price Per Unit", f"${price_per_unit:,.0f}")
d3.metric("Gross Rent Multiplier", f"{gross_rent_multiplier:.1f}x")
d4.metric("Rent Per Unit/Mo", f"${rent_per_unit:,.0f}")

if treasury_spread_deal is not None:
    st.markdown(f"""
<div style="background:#1D9E7522; border-left:4px solid #1D9E75;
padding:10px 16px; border-radius:6px; margin:0.5rem 0; font-size:14px;">
<strong>Treasury Spread on Your Deal:</strong> {treasury_spread_deal:.2f}% ({treasury_spread_deal*100:.0f} bps) — {spread_signal}
</div>""", unsafe_allow_html=True)

st.markdown("---")

col_left, col_right = st.columns(2)
with col_left:
    st.subheader("📈 National Rent Index Trend")
    rent_5yr = rent_index[rent_index.index >= rent_index.index[-1] - pd.DateOffset(years=5)]
    fig_rent = go.Figure()
    fig_rent.add_trace(go.Scatter(x=rent_5yr.index, y=rent_5yr.values, mode="lines",
        line=dict(color="#1D9E75", width=2), fill="tozeroy", fillcolor="rgba(29,158,117,0.1)"))
    fig_rent.update_layout(height=300, margin=dict(t=20, b=40), yaxis_title="CPI Rent Index", hovermode="x unified")
    st.plotly_chart(fig_rent, use_container_width=True)

with col_right:
    st.subheader("📉 30-Year Mortgage Rate Trend")
    mort_5yr = mortgage_history[mortgage_history.index >= mortgage_history.index[-1] - pd.DateOffset(years=5)]
    fig_mort = go.Figure()
    fig_mort.add_trace(go.Scatter(x=mort_5yr.index, y=mort_5yr.values, mode="lines",
        line=dict(color="#378ADD", width=2), fill="tozeroy", fillcolor="rgba(55,138,221,0.1)"))
    fig_mort.update_layout(height=300, margin=dict(t=20, b=40), yaxis_ticksuffix="%", hovermode="x unified")
    st.plotly_chart(fig_mort, use_container_width=True)

st.markdown("---")
st.subheader("🎯 Cap Rate Spread Visualizer")
categories = ["10-Yr Treasury", "Est. Cap Rate Low", "Est. Cap Rate High", "Your Cap Rate"]
values = [treasury_rate if treasury_rate else 0, cap_low, cap_high, your_cap_rate]
colors = ["#378ADD", "#1D9E75", "#0F6E56", "#EF9F27"]
fig_spread = go.Figure(go.Bar(x=categories, y=values, marker_color=colors,
    text=[f"{v:.2f}%" for v in values], textposition="outside"))
fig_spread.update_layout(height=320, margin=dict(t=20, b=40),
    yaxis=dict(ticksuffix="%", range=[0, max(values) * 1.3]))
st.plotly_chart(fig_spread, use_container_width=True)

st.markdown("---")
with st.expander("📋 View Raw Market Data"):
    st.json({
        "10_yr_treasury_rate": treasury_rate,
        "treasury_date": treasury_date,
        "national_rental_vacancy_pct": vacancy_national,
        "rent_index_yoy_change_pct": round(yoy_rent_pct, 2)
    })
    if census_data:
        st.json(census_data)
    if property_lookup and "error" not in property_lookup:
        st.json({"property_lookup_suggestions": property_lookup})

st.caption(f"RealEstate-Analytics.ai | Multifamily Market Intelligence | ZIP {zip_input} | {property_type} | v1.2")
