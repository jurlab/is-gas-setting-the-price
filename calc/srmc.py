"""
calc/srmc.py — Short-Run Marginal Cost (SRMC) engine for gas power plants.

The SRMC is the minimum price at which a generator will offer energy into the
market to cover its variable costs. For a gas plant:

    SRMC (£/MWh_e) = fuel_cost + carbon_cost

    fuel_cost   = gas_price_ncv (£/MWh_th) / efficiency_lhv
    carbon_cost = (carbon_price + cps) × emission_factor
    emission_factor (tCO₂/MWh_e) = GAS_EMISSION_FACTOR_NCV / efficiency_lhv

Key unit conventions:
    - Gas price input (NBP):  p/therm GCV  → must convert to £/MWh NCV
    - Gas price input (TTF):  €/MWh GCV   → must convert to €/MWh NCV
    - Efficiency:             LHV fraction  (e.g. 0.52)
    - Carbon:                 £/tCO₂ or €/tCO₂ (caller converts if needed)
"""

from dataclasses import dataclass
from typing import Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    THERM_TO_KWH_GCV,
    GCV_TO_NCV_FACTOR,
    GAS_EMISSION_FACTOR_NCV,
    CARBON_PRICE_SUPPORT_GBP,
    PLANT_PARAMS,
    GAS_SETTING_UPPER_THRESHOLD,
    GAS_SETTING_LOWER_THRESHOLD,
)


# ── Unit conversion helpers ─────────────────────────────────────────────────

def nbp_to_gbp_per_mwh_ncv(p_per_therm_gcv: float) -> float:
    """
    Convert NBP gas price from p/therm (GCV) to £/MWh (NCV).

    NBP convention: prices in pence per therm on a gross calorific value basis.
    Plant efficiency benchmarks are on NCV (net) basis, so we divide by GCV/NCV.

    1 therm (GCV) = 29.3071 kWh (GCV)
    1 kWh (GCV)   = 1/1.1054 kWh (NCV) for natural gas
    """
    kwh_ncv_per_therm = THERM_TO_KWH_GCV / GCV_TO_NCV_FACTOR  # ≈ 26.51 kWh NCV/therm
    gbp_per_kwh_ncv = (p_per_therm_gcv / 100.0) / kwh_ncv_per_therm
    return gbp_per_kwh_ncv * 1000.0  # → £/MWh NCV


def ttf_to_eur_per_mwh_ncv(eur_per_mwh_gcv: float) -> float:
    """
    Convert TTF gas price from €/MWh (GCV) to €/MWh (NCV).
    TTF prices are quoted on an energy basis (MWh), not per therm.
    """
    return eur_per_mwh_gcv / GCV_TO_NCV_FACTOR


# ── Core SRMC calculation ───────────────────────────────────────────────────

@dataclass
class SRMCResult:
    """Full SRMC breakdown for a single plant at a single efficiency."""
    plant_type: str
    efficiency_lhv: float
    fuel_cost: float       # £/MWh_e (or €/MWh_e for EU)
    carbon_cost: float     # £/MWh_e
    srmc: float            # £/MWh_e
    emission_factor: float # tCO₂/MWh_e


def calc_srmc_gbp(
    gas_p_per_therm_gcv: float,
    carbon_gbp_per_tco2: float,
    efficiency_lhv: float,
    include_cps: bool = True,
    plant_type: str = "custom",
) -> SRMCResult:
    """
    SRMC for a GB gas plant. Gas price in p/therm GCV, carbon in £/tCO₂.

    Args:
        gas_p_per_therm_gcv:  NBP gas price (p/therm, GCV basis)
        carbon_gbp_per_tco2:  UK ETS carbon price (£/tCO₂)
        efficiency_lhv:       Plant electrical efficiency (LHV, 0–1)
        include_cps:          Add UK Carbon Price Support (True for GB generators)
        plant_type:           Label for result (e.g. 'CCGT')
    """
    if not 0 < efficiency_lhv <= 1:
        raise ValueError(f"efficiency_lhv must be in (0,1]; got {efficiency_lhv}")

    gas_gbp_mwh_ncv = nbp_to_gbp_per_mwh_ncv(gas_p_per_therm_gcv)
    fuel_cost = gas_gbp_mwh_ncv / efficiency_lhv

    emission_factor = GAS_EMISSION_FACTOR_NCV / efficiency_lhv
    effective_carbon = carbon_gbp_per_tco2 + (CARBON_PRICE_SUPPORT_GBP if include_cps else 0.0)
    carbon_cost = effective_carbon * emission_factor

    return SRMCResult(
        plant_type=plant_type,
        efficiency_lhv=efficiency_lhv,
        fuel_cost=round(fuel_cost, 2),
        carbon_cost=round(carbon_cost, 2),
        srmc=round(fuel_cost + carbon_cost, 2),
        emission_factor=round(emission_factor, 4),
    )


def calc_srmc_eur(
    ttf_eur_per_mwh_gcv: float,
    eu_ets_eur_per_tco2: float,
    efficiency_lhv: float,
    plant_type: str = "custom",
) -> SRMCResult:
    """
    SRMC for a European gas plant. Gas price in €/MWh GCV, carbon in €/tCO₂.
    No CPS for non-GB countries.
    Returns result in €/MWh_e.
    """
    if not 0 < efficiency_lhv <= 1:
        raise ValueError(f"efficiency_lhv must be in (0,1]; got {efficiency_lhv}")

    gas_eur_mwh_ncv = ttf_to_eur_per_mwh_ncv(ttf_eur_per_mwh_gcv)
    fuel_cost = gas_eur_mwh_ncv / efficiency_lhv

    emission_factor = GAS_EMISSION_FACTOR_NCV / efficiency_lhv
    carbon_cost = eu_ets_eur_per_tco2 * emission_factor

    return SRMCResult(
        plant_type=plant_type,
        efficiency_lhv=efficiency_lhv,
        fuel_cost=round(fuel_cost, 2),
        carbon_cost=round(carbon_cost, 2),
        srmc=round(fuel_cost + carbon_cost, 2),
        emission_factor=round(emission_factor, 4),
    )


# ── Band calculation (low / mid / high for a plant type) ───────────────────

def calc_srmc_band_gbp(
    gas_p_per_therm_gcv: float,
    carbon_gbp_per_tco2: float,
    plant_type: str,
    include_cps: bool = True,
) -> dict:
    """
    SRMC band (low/mid/high) for a named plant type from PLANT_PARAMS.

    Note: higher efficiency → lower SRMC, so:
        srmc_low  corresponds to eff_high (best plant)
        srmc_high corresponds to eff_low  (worst plant)

    Returns a dict with band values plus display metadata.
    """
    params = PLANT_PARAMS[plant_type]
    eff_low = params["eff_low"]
    eff_high = params["eff_high"]
    eff_mid = (eff_low + eff_high) / 2.0

    r_low  = calc_srmc_gbp(gas_p_per_therm_gcv, carbon_gbp_per_tco2, eff_low,  include_cps, plant_type)
    r_mid  = calc_srmc_gbp(gas_p_per_therm_gcv, carbon_gbp_per_tco2, eff_mid,  include_cps, plant_type)
    r_high = calc_srmc_gbp(gas_p_per_therm_gcv, carbon_gbp_per_tco2, eff_high, include_cps, plant_type)

    return {
        "plant_type":        plant_type,
        "label":             params["label"],
        "srmc_low":          r_high.srmc,        # best efficiency → cheapest
        "srmc_mid":          r_mid.srmc,
        "srmc_high":         r_low.srmc,         # worst efficiency → most expensive
        "fuel_cost_mid":     r_mid.fuel_cost,
        "carbon_cost_mid":   r_mid.carbon_cost,
        "emission_factor_mid": r_mid.emission_factor,
        "color":             params["color"],
        "color_band":        params["color_band"],
    }


def calc_srmc_band_eur(
    ttf_eur_per_mwh_gcv: float,
    eu_ets_eur_per_tco2: float,
    plant_type: str,
) -> dict:
    """SRMC band in €/MWh_e for a European country."""
    params = PLANT_PARAMS[plant_type]
    eff_low = params["eff_low"]
    eff_high = params["eff_high"]
    eff_mid = (eff_low + eff_high) / 2.0

    r_low  = calc_srmc_eur(ttf_eur_per_mwh_gcv, eu_ets_eur_per_tco2, eff_low,  plant_type)
    r_mid  = calc_srmc_eur(ttf_eur_per_mwh_gcv, eu_ets_eur_per_tco2, eff_mid,  plant_type)
    r_high = calc_srmc_eur(ttf_eur_per_mwh_gcv, eu_ets_eur_per_tco2, eff_high, plant_type)

    return {
        "plant_type":  plant_type,
        "label":       params["label"],
        "srmc_low":    r_high.srmc,
        "srmc_mid":    r_mid.srmc,
        "srmc_high":   r_low.srmc,
        "color":       params["color"],
        "color_band":  params["color_band"],
    }


# ── Price signal assessment ─────────────────────────────────────────────────

SIGNAL_LABELS = {
    "gas_marginal": ("Gas at margin",   "🔴", "#E53935"),
    "above_srmc":   ("Above SRMC",      "🟠", "#FB8C00"),
    "below_srmc":   ("Below SRMC",      "🟢", "#43A047"),
    "unknown":      ("Unknown",         "⚪", "#9E9E9E"),
}


def assess_gas_setting(
    da_price: float,
    ccgt_band: dict,
    upper_threshold: float = GAS_SETTING_UPPER_THRESHOLD,
    lower_threshold: float = GAS_SETTING_LOWER_THRESHOLD,
) -> str:
    """
    Compare current DA electricity price to CCGT SRMC band.

    Uses asymmetric tolerances:
      - upper_threshold (default 15%): DA can be this far *above* srmc_high and
        still be classified as 'gas_marginal'. Scarcity events and network
        constraints routinely push prices above SRMC without changing the
        marginal unit.
      - lower_threshold (default 5%): DA can only be this far *below* srmc_low
        before being classified as 'below_srmc'. A price materially below the
        cheapest CCGT's variable cost is a reliable signal of clean generation
        at the margin. 5% covers SRMC parameter uncertainty only.

    Returns:
        'gas_marginal' — DA price sits within or close to the CCGT SRMC band
        'above_srmc'   — DA price significantly above band (scarcity / import constraint)
        'below_srmc'   — DA price significantly below band (clean generation at margin)
    """
    srmc_low  = ccgt_band["srmc_low"]
    srmc_high = ccgt_band["srmc_high"]

    lower_bound = srmc_low  * (1.0 - lower_threshold)   # tight: 5% below cheapest CCGT
    upper_bound = srmc_high * (1.0 + upper_threshold)   # loose: 15% above dearest CCGT

    if lower_bound <= da_price <= upper_bound:
        return "gas_marginal"
    elif da_price > upper_bound:
        return "above_srmc"
    else:
        return "below_srmc"
