"""
components/kpi_cards.py — Header KPI strips.

render_kpi_cards()          — today's intraday (MID) prices
render_tomorrow_kpi_cards() — tomorrow's day-ahead auction prices
"""

import streamlit as st
from typing import Optional
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from calc.srmc import SIGNAL_LABELS


def render_kpi_cards(
    da_price_gbp:      Optional[float],
    ccgt_srmc_mid:     Optional[float],
    ccgt_srmc_low:     Optional[float],
    ccgt_srmc_high:    Optional[float],
    gas_signal:        Optional[str],
    gas_p_therm:       Optional[float],
    uk_ets_gbp:        Optional[float],
    last_updated:      Optional[str] = None,
    gas_price_label:   str = "NBP Gas (yesterday DA)",
) -> None:
    """
    Today's intraday KPI row.
    gas_p_therm should be yesterday's NBP price — the gas bought yesterday
    for delivery and dispatch today.
    """
    if gas_signal and gas_signal in SIGNAL_LABELS:
        label, emoji, color = SIGNAL_LABELS[gas_signal]
    else:
        label, emoji, color = SIGNAL_LABELS["unknown"]

    spread = None
    spread_delta = None
    if da_price_gbp is not None and ccgt_srmc_mid is not None:
        spread = da_price_gbp - ccgt_srmc_mid
        spread_delta = f"{'above' if spread >= 0 else 'below'} CCGT SRMC mid"

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        st.metric(
            label="⚡ GB MID Price",
            value=f"£{da_price_gbp:.1f}/MWh" if da_price_gbp is not None else "—",
            help=(
                "Current GB Market Index Data (MID): volume-weighted average of "
                "intraday continuous market trades for this settlement period. "
                "Source: Elexon BMRS (APXMIDP)."
            ),
        )

    with col2:
        band_str = (f"£{ccgt_srmc_low:.0f}–{ccgt_srmc_high:.0f}/MWh"
                    if ccgt_srmc_low is not None and ccgt_srmc_high is not None else "")
        st.metric(
            label="🔥 CCGT SRMC (mid)",
            value=f"£{ccgt_srmc_mid:.1f}/MWh" if ccgt_srmc_mid is not None else "—",
            help=f"CCGT short-run marginal cost mid (50–58% LHV). Band: {band_str}. Uses yesterday's gas price.",
        )

    with col3:
        st.metric(
            label="📊 Difference vs gas SRMC",
            value=f"£{spread:+.1f}/MWh" if spread is not None else "—",
            delta=spread_delta,
            delta_color="off",
            help="MID price minus CCGT SRMC mid. Positive = electricity price above gas cost.",
        )

    with col4:
        signal_html = (
            f'<div style="font-size:0.75rem;color:#666;margin-bottom:4px">🎯 Gas at margin?</div>'
            f'<div style="font-size:1.4rem;font-weight:700;color:{color}">{emoji} {label}</div>'
        )
        st.markdown(signal_html, unsafe_allow_html=True)

    with col5:
        st.metric(
            label=f"⛽ {gas_price_label}",
            value=f"{gas_p_therm:.1f} p/th" if gas_p_therm is not None else "—",
            help=(
                "Yesterday's NBP day-ahead gas price (p/therm, GCV basis). "
                "Generators running today bought this gas yesterday on the D+1 market "
                "for delivery on today's gas day (06:00–06:00). "
                "Source: OilPriceAPI history (NATURAL_GAS_GBP)."
            ),
        )

    with col6:
        st.metric(
            label="🌿 UK ETS",
            value=f"£{uk_ets_gbp:.2f}/tCO₂" if uk_ets_gbp is not None else "—",
            help="UK ETS allowance price. CPS (£18/tCO₂) added on top in SRMC. Source: OilPriceAPI.",
        )

    if last_updated:
        st.caption(
            f"Data fetched: {last_updated} UTC · "
            f"GB price: Elexon MID (intraday) · "
            f"SRMC uses yesterday's NBP DA gas price"
        )


def render_tomorrow_kpi_cards(
    tomorrow_avg_gbp:  Optional[float],
    tomorrow_min_gbp:  Optional[float],
    tomorrow_max_gbp:  Optional[float],
    ccgt_srmc_mid:     Optional[float],
    ccgt_srmc_low:     Optional[float],
    ccgt_srmc_high:    Optional[float],
    gas_signal:        Optional[str],
    gas_p_therm:       Optional[float],
    uk_ets_gbp:        Optional[float],
    n_periods:         int = 0,
) -> None:
    """
    Tomorrow's day-ahead KPI row.
    gas_p_therm should be today's NBP price — the gas bought today for delivery tomorrow.
    """
    if gas_signal and gas_signal in SIGNAL_LABELS:
        label, emoji, color = SIGNAL_LABELS[gas_signal]
    else:
        label, emoji, color = SIGNAL_LABELS["unknown"]

    spread = None
    spread_delta = None
    if tomorrow_avg_gbp is not None and ccgt_srmc_mid is not None:
        spread = tomorrow_avg_gbp - ccgt_srmc_mid
        spread_delta = f"{'above' if spread >= 0 else 'below'} CCGT SRMC mid"

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        price_range = (f" · £{tomorrow_min_gbp:.0f}–£{tomorrow_max_gbp:.0f} range"
                       if tomorrow_min_gbp is not None else "")
        st.metric(
            label="⚡ Tomorrow DA (avg)",
            value=f"£{tomorrow_avg_gbp:.1f}/MWh" if tomorrow_avg_gbp is not None else "—",
            help=(
                f"Average of {n_periods} day-ahead half-hourly auction prices for tomorrow. "
                f"Source: N2EX/APXMIDP DA auction published ~11:45 today.{price_range}"
            ),
        )

    with col2:
        band_str = (f"£{ccgt_srmc_low:.0f}–{ccgt_srmc_high:.0f}/MWh"
                    if ccgt_srmc_low is not None and ccgt_srmc_high is not None else "")
        st.metric(
            label="🔥 CCGT SRMC (mid)",
            value=f"£{ccgt_srmc_mid:.1f}/MWh" if ccgt_srmc_mid is not None else "—",
            help=f"CCGT SRMC using today's NBP DA gas price. Band: {band_str}.",
        )

    with col3:
        st.metric(
            label="📊 Spread vs SRMC",
            value=f"£{spread:+.1f}/MWh" if spread is not None else "—",
            delta=spread_delta,
            delta_color="off",
        )

    with col4:
        signal_html = (
            f'<div style="font-size:0.75rem;color:#666;margin-bottom:4px">🎯 Gas at margin?</div>'
            f'<div style="font-size:1.4rem;font-weight:700;color:{color}">{emoji} {label}</div>'
        )
        st.markdown(signal_html, unsafe_allow_html=True)

    with col5:
        st.metric(
            label="⛽ NBP Gas (today DA)",
            value=f"{gas_p_therm:.1f} p/th" if gas_p_therm is not None else "—",
            help=(
                "Today's NBP day-ahead gas price. Generators bidding into tomorrow's "
                "DA auction buy gas today for delivery tomorrow. "
                "Source: OilPriceAPI (NATURAL_GAS_GBP)."
            ),
        )

    with col6:
        st.metric(
            label="🌿 UK ETS",
            value=f"£{uk_ets_gbp:.2f}/tCO₂" if uk_ets_gbp is not None else "—",
        )

    if n_periods > 0:
        periods_note = f"{n_periods}/48 half-hour periods published"
    else:
        periods_note = "DA prices not yet published — N2EX auction runs at 11:00 daily"
    st.caption(
        f"Tomorrow's prices: N2EX day-ahead auction · {periods_note} · "
        f"SRMC uses today's NBP DA gas price (bought today, delivered tomorrow)"
    )
