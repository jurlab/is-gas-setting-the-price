"""
app.py — GB Gas Price Setter Dashboard

Data sources (all require no registration except OilPriceAPI):
  GB electricity prices  -> Elexon Insights API (data.elexon.co.uk, public)
  EU electricity prices  -> Energy Charts API (api.energy-charts.info, public)
  NBP gas / TTF gas      -> OilPriceAPI (7-day free trial)
  EU ETS carbon          -> OilPriceAPI /futures/eua-carbon
  UK ETS carbon          -> OilPriceAPI UK_CARBON_GBP
  EUR/GBP FX             -> ECB SDMX API (public, no key)

Layout:
  KPI header (signal, prices, SRMC)
  Today: [Chart: GB MID vs SRMC bands] [Table: today snapshot, all zones]
  Footer

Run: streamlit run app.py
"""

import os
import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

from data.elexon_client import (
    fetch_gb_da_prices,
    get_latest_price as elexon_latest,
)
from data.energy_charts_client import (
    fetch_all_eu_zones,
    get_latest_price as ec_latest,
)
from data.oilprice_client import GasPrices
from data.carbon_client import fetch_uk_ets_gbp, fetch_eu_ets_eur
from data.fx_client import fetch_eur_to_gbp
from calc.srmc import calc_srmc_band_gbp, assess_gas_setting
from components.kpi_cards import render_kpi_cards
from components.price_chart import render_price_chart
from components.country_table import render_today_country_table
from config import PLANT_PARAMS, INTRADAY_HOURS, CACHE_TTL_SECONDS

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Is gas setting GB electricity price?",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; padding-bottom: 1rem; }
    .stMetric { background: #FAFAFA; border-radius: 8px; padding: 0.5rem; }
    div[data-testid="stMetricValue"] { font-size: 1.2rem; }
</style>
""", unsafe_allow_html=True)


# ── Cached data loaders ───────────────────────────────────────────────────────
@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_gb_prices(hours_back: int = INTRADAY_HOURS) -> pd.Series:
    return fetch_gb_da_prices(hours_back=hours_back)

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_eu_prices(hours_back: int = INTRADAY_HOURS) -> dict:
    return fetch_all_eu_zones(hours_back=hours_back)

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_gas_prices() -> GasPrices:
    return GasPrices().load(include_history=False)

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_uk_ets() -> tuple:
    return fetch_uk_ets_gbp()

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_eu_ets() -> float | None:
    return fetch_eu_ets_eur()

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_fx() -> float:
    return fetch_eur_to_gbp()


# ── Header ────────────────────────────────────────────────────────────────────
st.title("🔥 GB Gas Price Setter")
st.markdown(
    "Real-time signal: is natural gas currently setting the GB electricity price? "
    "Compares intraday MID prices against the short-run marginal cost of gas generation."
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    if st.button("🔄 Refresh data", type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("**Data sources**")
    st.markdown("- GB prices: [Elexon Insights API](https://data.elexon.co.uk) *(no key)*")
    st.markdown("- EU prices: [Energy Charts / Fraunhofer ISE](https://api.energy-charts.info) *(no key)*")
    st.markdown("- Gas & carbon: [OilPriceAPI](https://oilpriceapi.com) *(key required)*")
    st.markdown("- FX: [ECB SDMX](https://data-api.ecb.europa.eu) *(no key)*")

    st.markdown("---")
    st.markdown("**Methodology**")
    st.markdown(
        "SRMC = fuel cost + carbon cost  \n"
        "Fuel cost = NBP NCV ÷ efficiency  \n"
        "Carbon = (UK ETS + CPS £18) × emission factor  \n"
        "Emission factor = 0.18329 tCO₂/MWh_th NCV ÷ efficiency (LHV)  \n"
        "Source: DESNZ/BEIS GHG Conversion Factors"
    )

    st.markdown("---")
    st.markdown("**Efficiency ranges (LHV)**")
    for pt, params in PLANT_PARAMS.items():
        st.markdown(f"- {params['label']}: {int(params['eff_low']*100)}–{int(params['eff_high']*100)}%")

    st.markdown("---")
    st.caption("Prices refresh every hour. Data is indicative only.")


# ── Fetch all data ────────────────────────────────────────────────────────────
with st.spinner("Fetching market data…"):
    gb_series             = load_gb_prices()
    eu_series             = load_eu_prices()
    gas                   = load_gas_prices()
    uk_ets, uk_ets_source = load_uk_ets()
    eu_ets                = load_eu_ets()
    eur_to_gbp            = load_fx()

# ── Data availability checks ──────────────────────────────────────────────────
gb_data_ok = not gb_series.empty
gas_ok     = gas.gas_gbp is not None

if not gb_data_ok:
    st.error("⚠️ No GB electricity price data from Elexon. Check network connection.")
if not gas_ok:
    st.error("⚠️ No NBP gas price from OilPriceAPI. Check OIL_PRICE_API_KEY in .env")
if "Fallback" in uk_ets_source:
    st.warning(f"⚠️ UK ETS live price unavailable — {uk_ets_source}")

# ── Compute SRMC bands ────────────────────────────────────────────────────────
srmc_bands: dict = {}
if gas_ok and uk_ets is not None:
    for plant_type in PLANT_PARAMS:
        srmc_bands[plant_type] = calc_srmc_band_gbp(
            gas_p_per_therm_gcv=gas.gas_gbp,
            carbon_gbp_per_tco2=uk_ets,
            plant_type=plant_type,
            include_cps=True,
        )

ccgt_band      = srmc_bands.get("CCGT")
current_da_gbp = elexon_latest(gb_series) if gb_data_ok else None
gas_signal     = (
    assess_gas_setting(current_da_gbp, ccgt_band)
    if current_da_gbp is not None and ccgt_band is not None else None
)
last_updated = (
    gas.fetched_at.strftime("%d %b %Y %H:%M") if gas.fetched_at else "—"
)

# ── Latest EU prices (for today country table) ────────────────────────────────
now_utc = pd.Timestamp.now(tz="UTC")
da_latest_today: dict = {"GB": current_da_gbp}
for zone_key, series in eu_series.items():
    if series.empty:
        da_latest_today[zone_key] = None
    else:
        idx  = series.index if series.index.tz is not None else series.index.tz_localize("UTC")
        past = series[idx <= now_utc]
        da_latest_today[zone_key] = ec_latest(past) if not past.empty else None


# ════════════════════════════════════════════════════════════════════════════
# SECTION 1: KPI header
# ════════════════════════════════════════════════════════════════════════════
render_kpi_cards(
    da_price_gbp   = current_da_gbp,
    ccgt_srmc_mid  = ccgt_band["srmc_mid"]  if ccgt_band else None,
    ccgt_srmc_low  = ccgt_band["srmc_low"]  if ccgt_band else None,
    ccgt_srmc_high = ccgt_band["srmc_high"] if ccgt_band else None,
    gas_signal     = gas_signal,
    gas_p_therm    = gas.gas_gbp,
    uk_ets_gbp     = uk_ets,
    last_updated   = last_updated,
)

st.markdown("---")

# ════════════════════════════════════════════════════════════════════════════
# SECTION 2: Today — intraday chart + country snapshot table
# ════════════════════════════════════════════════════════════════════════════
st.subheader("📍 Today — Intraday Market (MID)")

col_chart, col_table = st.columns([3, 2])

with col_chart:
    render_price_chart(da_series=gb_series, srmc_bands=srmc_bands)

with col_table:
    render_today_country_table(
        da_latest   = da_latest_today,
        gas_p_therm = gas.gas_gbp,
        uk_ets_gbp  = uk_ets,
        ttf_eur_mwh = gas.ttf,
        eu_ets_eur  = eu_ets,
        eur_to_gbp  = eur_to_gbp,
    )
    st.caption(
        "⚠️ Ireland (I-SEM) unavailable — outside Energy Charts freely licensed tier."
    )

st.markdown("---")

# ════════════════════════════════════════════════════════════════════════════
# Footer
# ════════════════════════════════════════════════════════════════════════════
st.caption(
    "**Disclaimer:** Indicative first-order signal only. Not financial or trading advice.  \n"
    "**GB electricity prices:** Elexon Insights API (Market Index Data, APXMIDP) · "
    "**EU prices:** Energy Charts / Fraunhofer ISE (CC BY 4.0) · "
    "**Gas & carbon:** OilPriceAPI (NBP DA, UK_CARBON_GBP, EU ETS futures) · "
    "**FX:** ECB SDMX · "
    "**SRMC:** DESNZ/BEIS GHG Conversion Factors, BEIS Generation Costs Report · "
    "**Signal tolerance:** ±10% symmetric band around CCGT SRMC range"
)
