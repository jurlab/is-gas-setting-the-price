"""
config.py — Central configuration for the GB Gas Price Setter dashboard.

All physical constants, plant parameters, API codes, and display settings
are defined here so they can be reviewed and adjusted without touching logic.
"""

from typing import Dict

# ── Thermodynamic constants ─────────────────────────────────────────────────
# OilPriceAPI quotes NBP gas in p/therm on a GCV (gross calorific value) basis.
# Plant efficiency benchmarks are on an LHV/NCV (net calorific value) basis.
# These must be reconciled in the SRMC formula.
THERM_TO_KWH_GCV: float = 29.3071       # kWh energy content per therm (GCV)
GCV_TO_NCV_FACTOR: float = 1.1054       # ratio GCV/NCV for natural gas

# TTF European gas is quoted in €/MWh already on an energy (GCV) basis —
# divide by GCV_TO_NCV_FACTOR to get NCV basis before applying efficiency.

# ── Gas emission factor ─────────────────────────────────────────────────────
# Source: DESNZ/BEIS Greenhouse Gas Conversion Factors (published annually)
# Natural gas combustion: tCO₂ per MWh thermal on NCV basis.
# Emission intensity of electricity = GAS_EMISSION_FACTOR_NCV / plant_efficiency_LHV
GAS_EMISSION_FACTOR_NCV: float = 0.18329  # tCO₂/MWh_th (NCV)

# ── UK Carbon Price Support (CPS) ───────────────────────────────────────────
# A UK-specific top-up carbon tax applied to fossil fuel generators in GB.
# Frozen at £18/tCO₂ since April 2016 by HMRC.
# Applied on top of UK ETS price for GB generators only — NOT for IE/FR/BE/NL/DK1/NO2.
CARBON_PRICE_SUPPORT_GBP: float = 18.0  # £/tCO₂

# ── Plant parameters (LHV efficiency range) ─────────────────────────────────
# Sources:
#   CCGT: IEA-ETSAP Technology Brief E02; range reflects GB fleet mix including
#         older plant and part-load cycling operation (Juraj's adjustment)
#   OCGT: IEA-ETSAP; large peaking turbines in GB
#   Recip: BEIS/DESNZ Generation Costs Report; large lean-burn gas engines
#
# Higher efficiency → lower SRMC. Bands are therefore:
#   srmc_low  ← eff_high (best plant)
#   srmc_high ← eff_low  (worst plant)
PLANT_PARAMS: Dict[str, dict] = {
    "CCGT": {
        "eff_low": 0.50, "eff_high": 0.58,
        "label": "CCGT",
        "color": "#1E88E5",
        "color_band": "rgba(30,136,229,0.12)",
    },
    "OCGT": {
        "eff_low": 0.35, "eff_high": 0.40,
        "label": "OCGT",
        "color": "#FB8C00",
        "color_band": "rgba(251,140,0,0.12)",
    },
    "Recip": {
        "eff_low": 0.36, "eff_high": 0.45,
        "label": "Recip. engine",
        "color": "#8E24AA",
        "color_band": "rgba(142,36,170,0.12)",
    },
}

# ── Electricity price data sources ──────────────────────────────────────────
# GB prices: Elexon Insights API (data.elexon.co.uk) — public, no key required
# EU zone prices: Energy Charts API (api.energy-charts.info, Fraunhofer ISE)
#                 — public, no key required
#
# IE (Ireland I-SEM) is NOT in Energy Charts' freely licensed zones; it is
# displayed with a data-unavailable flag and the row is greyed out in the UI.
# Source for zone codes: api.energy-charts.info/openapi.json
ELEXON_BASE_URL: str = "https://data.elexon.co.uk/bmrs/api/v1"
ENERGY_CHARTS_BASE_URL: str = "https://api.energy-charts.info"

EU_ZONES: Dict[str, dict] = {
    "FR":  {"bzn": "FR",  "name": "France",        "currency": "EUR", "use_cps": False, "licensed": True},
    "BE":  {"bzn": "BE",  "name": "Belgium",       "currency": "EUR", "use_cps": False, "licensed": True},
    "NL":  {"bzn": "NL",  "name": "Netherlands",   "currency": "EUR", "use_cps": False, "licensed": True},
    "NO2": {"bzn": "NO2", "name": "Norway NO2",    "currency": "EUR", "use_cps": False, "licensed": True},
    "DK1": {"bzn": "DK1", "name": "Denmark DK1",   "currency": "EUR", "use_cps": False, "licensed": True},
    "IE":  {"bzn": "IE",  "name": "Ireland I-SEM", "currency": "EUR", "use_cps": False, "licensed": False},
}

# ── OilPriceAPI commodity codes ─────────────────────────────────────────────
# Verified against docs.oilpriceapi.com (March 2026).
#
# UK ETS is NOT available on OilPriceAPI — they only carry EU ETS (EUA).
# UK ETS is fetched separately via Yahoo Finance's unofficial JSON API (UKA=F).
# See data/carbon_client.py for implementation.
OIL_API_BASE_URL: str = "https://api.oilpriceapi.com/v1"
OIL_API_CODES: Dict[str, str] = {
    "gas_gbp": "NATURAL_GAS_GBP",  # NBP day-ahead, p/therm (GCV). Confirmed in docs.
    "uk_ets":  "UK_CARBON_GBP",    # UK ETS allowance price (£/tCO₂). Used by carbon_client.py.
    "eu_ets":  "EU_CARBON_EUR",     # EU ETS spot via /prices/latest. Live-tested on oilpriceapi.com/live/eu-carbon-price
    "ttf":     "DUTCH_TTF_EUR",     # TTF European gas, €/MWh (GCV). Confirmed in docs.
}

# UK ETS: fetched from Yahoo Finance (UKA=F futures) — no API key required.
# Falls back to FALLBACK_UK_ETS_GBP if the fetch fails.
YAHOO_UKA_URL: str = "https://query1.finance.yahoo.com/v8/finance/chart/UKA=F"
FALLBACK_UK_ETS_GBP: float = 36.0   # £/tCO₂ — update manually if scrape fails

# ── FX (ECB free API) ────────────────────────────────────────────────────────
ECB_FX_URL: str = "https://data-api.ecb.europa.eu/service/data/EXR/D.GBP.EUR.SP00.A"

# ── Compatibility alias used by country_table.py ─────────────────────────────
# Maps every zone key to a flat dict with name/currency/use_cps for display.
ENTSOE_ZONES: Dict[str, dict] = {
    "GB":  {"name": "Great Britain",    "currency": "GBP", "use_cps": True},
    **{k: {"name": v["name"], "currency": v["currency"], "use_cps": v["use_cps"]}
       for k, v in EU_ZONES.items()}
}

# ── "Is gas setting the price?" decision logic ───────────────────────────────
# The CCGT SRMC band (srmc_low → srmc_high) is derived from the plant efficiency
# range (50–58% LHV) applied to today's NBP gas and UK ETS prices.
#
# A symmetric ±10% tolerance is applied around that band before classifying
# the DA price signal.  This reflects two explicit assumptions:
#
#   UPPER +10%: Scarcity events, network constraints, and capacity payments can
#               push DA prices above CCGT variable cost without changing the
#               marginal unit.  The 10% upper buffer avoids false "above SRMC"
#               flags during tight system conditions.
#
#   LOWER −10%: SRMC model uncertainty — gas quote lag (~1 day), heat-rate
#               variance across the GB CCGT fleet, and carbon price intraday
#               moves — is estimated at ±3–5%.  The lower buffer is deliberately
#               wider (10%) to be conservative: we only call "gas NOT at margin"
#               when the price is clearly below even the most-efficient CCGT's
#               variable cost.
#
# Both bounds are shown explicitly on the intraday price chart so the reader
# can see how much headroom the DA price has relative to the tolerance zone.
# These values can be adjusted here; the chart and signal will update together.
GAS_SETTING_THRESHOLD: float = 0.10         # kept as a single symmetric alias
GAS_SETTING_UPPER_THRESHOLD: float = 0.10   # fraction above srmc_high → still "gas marginal"
GAS_SETTING_LOWER_THRESHOLD: float = 0.10   # fraction below srmc_low  → still "gas marginal"

# ── Dashboard time windows ───────────────────────────────────────────────────
HISTORY_DAYS: int = 7    # trend chart lookback in days
INTRADAY_HOURS: int = 48  # intraday chart lookback in hours
CACHE_TTL_SECONDS: int = 3600  # API cache TTL (1 hour)
