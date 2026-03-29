"""
components/country_table.py — Interconnected country comparison tables.

Two public functions:
  render_today_country_table()    — today's snapshot: latest price per zone vs CCGT SRMC
  render_tomorrow_country_table() — tomorrow's DA: avg price + period signal counts per zone

Today table:
  Uses the most recent available price per zone (GB = latest MID, EU = latest DA hour).
  Shows a single signal per zone based on that snapshot price.
  EU prices from Energy Charts (today's DA hours published up to now).

Tomorrow table:
  Uses all published tomorrow periods per zone (GB: up to 48 half-hours, EU: up to 24 hours).
  Shows average price + how many of those periods fall within the CCGT SRMC ±10% zone.
  Shows "⏳ Not yet published" if auction hasn't cleared yet (~12:00 UTC).

Notes:
  - Ireland (I-SEM) excluded — not in Energy Charts freely licensed tier.
  - All prices converted to GBP for comparison.
  - GB SRMC includes Carbon Price Support (£18/tCO₂); EU SRMC does not.
"""

import streamlit as st
import pandas as pd
from typing import Optional
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ENTSOE_ZONES
from calc.srmc import (
    calc_srmc_band_gbp,
    calc_srmc_band_eur,
    assess_gas_setting,
    SIGNAL_LABELS,
)


def _srmc_bands_for_zone(
    zone_key: str,
    gas_p_therm: Optional[float],
    uk_ets_gbp: Optional[float],
    ttf_eur_mwh: Optional[float],
    eu_ets_eur: Optional[float],
    eur_to_gbp: float,
) -> Optional[dict]:
    """Return CCGT SRMC band in GBP for a zone, or None if inputs missing."""
    gb_ok = gas_p_therm is not None and uk_ets_gbp is not None
    eu_ok = ttf_eur_mwh is not None and eu_ets_eur is not None

    if zone_key == "GB" and gb_ok:
        return calc_srmc_band_gbp(gas_p_therm, uk_ets_gbp, "CCGT", include_cps=True)
    elif zone_key != "GB" and eu_ok:
        band_eur = calc_srmc_band_eur(ttf_eur_mwh, eu_ets_eur, "CCGT")
        return {
            **band_eur,
            "srmc_low":  band_eur["srmc_low"]  * eur_to_gbp,
            "srmc_mid":  band_eur["srmc_mid"]  * eur_to_gbp,
            "srmc_high": band_eur["srmc_high"] * eur_to_gbp,
        }
    return None


# ── Today's snapshot table ───────────────────────────────────────────────────

def render_today_country_table(
    da_latest:   dict[str, Optional[float]],
    gas_p_therm: Optional[float],
    uk_ets_gbp:  Optional[float],
    ttf_eur_mwh: Optional[float],
    eu_ets_eur:  Optional[float],
    eur_to_gbp:  float = 0.845,
) -> None:
    """
    Today's snapshot: one current price per zone vs CCGT SRMC mid.

    Args:
        da_latest:   Dict of zone_key -> latest price in native currency
                     (GBP for GB, EUR for EU zones). None if unavailable.
        gas_p_therm: NBP gas price (p/therm GCV) for GB SRMC
        uk_ets_gbp:  UK ETS (£/tCO2) for GB SRMC
        ttf_eur_mwh: TTF gas (EUR/MWh GCV) for EU SRMC
        eu_ets_eur:  EU ETS (EUR/tCO2) for EU SRMC
        eur_to_gbp:  EUR to GBP conversion rate
    """
    rows = []
    for zone_key, zone_info in ENTSOE_ZONES.items():
        name      = zone_info["name"]
        currency  = zone_info["currency"]
        da_native = da_latest.get(zone_key)

        # Convert to GBP
        if da_native is None:
            da_gbp = None
        elif currency == "EUR":
            da_gbp = da_native * eur_to_gbp
        else:
            da_gbp = da_native

        ccgt_band = _srmc_bands_for_zone(
            zone_key, gas_p_therm, uk_ets_gbp, ttf_eur_mwh, eu_ets_eur, eur_to_gbp
        )
        srmc_mid = ccgt_band["srmc_mid"] if ccgt_band else None

        if da_gbp is not None and ccgt_band is not None:
            signal  = assess_gas_setting(da_gbp, ccgt_band)
            label, emoji, _ = SIGNAL_LABELS[signal]
            signal_str = f"{emoji} {label}"
        else:
            signal_str = "No data"

        rows.append({
            "Country":           name,
            "Price (£/MWh)":     f"£{da_gbp:.1f}"   if da_gbp  is not None else "—",
            "CCGT SRMC (£/MWh)": f"£{srmc_mid:.1f}" if srmc_mid is not None else "—",
            "Spread (£/MWh)":    (
                f"£{(da_gbp - srmc_mid):+.1f}"
                if da_gbp is not None and srmc_mid is not None else "—"
            ),
            "Signal":            signal_str,
        })

    if not rows:
        st.info("No country data available.")
        return

    df = pd.DataFrame(rows).set_index("Country")
    st.subheader("🌍 Today — Country Comparison")
    st.caption(
        "Latest available price per zone vs CCGT SRMC mid. "
        "GB = current MID (intraday). EU = most recent DA hour from Energy Charts. "
        "All prices in GBP. EU SRMC uses TTF + EU ETS (no CPS)."
    )
    st.dataframe(df, use_container_width=True, height=310)
    missing = [r["Country"] for r in rows if r["Price (£/MWh)"] == "—"]
    if missing:
        st.caption(f"No price data for: {', '.join(missing)}")


# ── Tomorrow's DA table ──────────────────────────────────────────────────────

def _count_signal_periods(
    series: pd.Series,
    ccgt_band: dict,
    eur_to_gbp: float = 1.0,
    is_eur: bool = False,
) -> tuple[str, int, int]:
    """Returns (dominant_signal, gas_marginal_count, total_count)."""
    if series.empty or ccgt_band is None:
        return ("unknown", 0, 0)

    prices_gbp = series * eur_to_gbp if is_eur else series
    total  = len(prices_gbp)
    counts = {"gas_marginal": 0, "above_srmc": 0, "below_srmc": 0}
    for price in prices_gbp:
        counts[assess_gas_setting(float(price), ccgt_band)] += 1

    dominant = assess_gas_setting(float(prices_gbp.mean()), ccgt_band)
    return (dominant, counts["gas_marginal"], total)


def render_tomorrow_country_table(
    da_tomorrow: dict[str, pd.Series],
    gas_p_therm: Optional[float],
    uk_ets_gbp:  Optional[float],
    ttf_eur_mwh: Optional[float],
    eu_ets_eur:  Optional[float],
    eur_to_gbp:  float = 0.845,
) -> None:
    """
    Tomorrow's DA: avg price + period count signal per zone.

    Args:
        da_tomorrow: Dict of zone_key -> pd.Series of tomorrow's DA prices
                     (GBP for GB, EUR for EU zones). Empty Series = not yet published.
        Others:      Same as render_today_country_table.
    """
    rows = []
    for zone_key, zone_info in ENTSOE_ZONES.items():
        name     = zone_info["name"]
        currency = zone_info["currency"]
        series   = da_tomorrow.get(zone_key, pd.Series(dtype=float))
        is_eur   = (currency == "EUR")

        ccgt_band = _srmc_bands_for_zone(
            zone_key, gas_p_therm, uk_ets_gbp, ttf_eur_mwh, eu_ets_eur, eur_to_gbp
        )
        srmc_mid = ccgt_band["srmc_mid"] if ccgt_band else None

        dominant, gas_count, total = _count_signal_periods(
            series, ccgt_band, eur_to_gbp=eur_to_gbp, is_eur=is_eur
        )

        if series.empty:
            avg_gbp    = None
            signal_str = "Not yet published"
        else:
            avg_native = float(series.mean())
            avg_gbp    = avg_native * eur_to_gbp if is_eur else avg_native
            label, emoji, _ = SIGNAL_LABELS.get(dominant, SIGNAL_LABELS["unknown"])
            signal_str = f"{emoji} {label}  ({gas_count}/{total} periods)"

        rows.append({
            "Country":              name,
            "Avg DA (£/MWh)":       f"£{avg_gbp:.1f}"   if avg_gbp  is not None else "—",
            "CCGT SRMC (£/MWh)":    f"£{srmc_mid:.1f}"  if srmc_mid is not None else "—",
            "Spread (£/MWh)":       (
                f"£{(avg_gbp - srmc_mid):+.1f}"
                if avg_gbp is not None and srmc_mid is not None else "—"
            ),
            "Signal (all periods)": signal_str,
        })

    if not rows:
        st.info("No country data available.")
        return

    df = pd.DataFrame(rows).set_index("Country")
    st.subheader("🌍 Tomorrow — Country Comparison")
    st.caption(
        "Average of all published tomorrow periods. EU prices in GBP. "
        "EU SRMC uses TTF + EU ETS (no CPS). "
        "Signal counts periods within CCGT SRMC ±10% zone. "
        "Not yet published = auction clears ~12:00 UTC."
    )
    st.dataframe(df, use_container_width=True, height=310)
    missing = [r["Country"] for r in rows if r["Avg DA (£/MWh)"] == "—"]
    if missing:
        st.caption(f"No tomorrow price data: {', '.join(missing)}")
