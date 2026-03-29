"""
components/price_chart.py — Today's GB DA price chart with SRMC bands and signal tolerance zone.

Shows today's GB half-hourly day-ahead prices (00:00–23:30 UTC) against the SRMC
ranges for CCGT, OCGT, and reciprocating engines.

For CCGT only, a ±10% tolerance band is drawn around the efficiency band.  This
represents the "gas at margin" decision zone shown in the signal: if the DA price
sits inside the outer dashed lines, gas is classified as likely marginal.  If it
sits outside these lines — above or below — it is classified as above/below SRMC.

Assumptions made explicit on the chart:
  - Efficiency band (shaded):   50–58% LHV — reflects the GB fleet mix
  - Tolerance zone (dashed):    ±10% either side of the band — covers SRMC model
                                uncertainty (gas quote lag, heat-rate variance,
                                carbon intraday moves) and modest scarcity premium
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from typing import Optional
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import PLANT_PARAMS, GAS_SETTING_UPPER_THRESHOLD, GAS_SETTING_LOWER_THRESHOLD


def render_price_chart(
    da_series: pd.Series,
    srmc_bands: dict[str, dict],
    title: str = "Today's GB Day-Ahead Price vs Gas SRMC Ranges",
) -> None:
    """
    Render the today-only intraday price chart.

    Filters da_series to the current UTC calendar date before plotting, so the
    chart always shows a clean 00:00–23:30 window regardless of how much data
    was fetched by the caller.

    Args:
        da_series:   pd.Series with UTC DatetimeIndex and DA price values (£/MWh)
        srmc_bands:  Dict from calc.srmc.calc_srmc_band_gbp for each plant type
                     Keys: 'CCGT', 'OCGT', 'Recip'
        title:       Chart title string
    """

    if da_series.empty:
        st.warning("No day-ahead price data available. Check Elexon API connection.")
        return

    # ── Filter to today (UTC) ────────────────────────────────────────────────
    today_start = pd.Timestamp.now(tz="UTC").normalize()          # today 00:00 UTC
    today_end   = today_start + pd.Timedelta(days=1)              # tomorrow 00:00 UTC
    today_series = da_series[(da_series.index >= today_start) & (da_series.index < today_end)]

    if today_series.empty:
        st.warning(
            f"No data for today ({today_start.strftime('%d %b %Y')}) in the fetched series. "
            "Try refreshing — Elexon may have a brief lag."
        )
        return

    timestamps = today_series.index.tolist()

    fig = go.Figure()

    # ── CCGT tolerance zone (drawn first, behind everything) ─────────────────
    # Shows the ±10% bounds used for the "gas at margin" signal.
    # Only drawn for CCGT since that is the band assessed in the signal logic.
    if "CCGT" in srmc_bands:
        ccgt = srmc_bands["CCGT"]
        tol_upper = ccgt["srmc_high"] * (1.0 + GAS_SETTING_UPPER_THRESHOLD)
        tol_lower = ccgt["srmc_low"]  * (1.0 - GAS_SETTING_LOWER_THRESHOLD)

        # Upper dashed boundary
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=[tol_upper] * len(timestamps),
            mode="lines",
            line=dict(color="#1E88E5", width=1, dash="dash"),
            name=f"CCGT tolerance +{int(GAS_SETTING_UPPER_THRESHOLD*100)}%",
            legendgroup="ccgt_tol",
            showlegend=True,
            hovertemplate=(
                f"<b>CCGT tolerance upper:</b> £{tol_upper:.1f}/MWh "
                f"(SRMC high +{int(GAS_SETTING_UPPER_THRESHOLD*100)}%)<extra></extra>"
            ),
        ))
        # Fill from lower bound to upper bound (tolerance fill)
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=[tol_lower] * len(timestamps),
            mode="lines",
            line=dict(color="#1E88E5", width=1, dash="dash"),
            fill="tonexty",
            fillcolor="rgba(30,136,229,0.04)",   # very faint blue fill
            name=f"CCGT tolerance −{int(GAS_SETTING_LOWER_THRESHOLD*100)}%",
            legendgroup="ccgt_tol",
            showlegend=True,
            hovertemplate=(
                f"<b>CCGT tolerance lower:</b> £{tol_lower:.1f}/MWh "
                f"(SRMC low −{int(GAS_SETTING_LOWER_THRESHOLD*100)}%)<extra></extra>"
            ),
        ))

    # ── SRMC efficiency bands ────────────────────────────────────────────────
    for plant_type, band in srmc_bands.items():
        params     = PLANT_PARAMS[plant_type]
        color_band = params["color_band"]
        color_line = params["color"]
        label      = band["label"]

        fig.add_trace(go.Scatter(
            x=timestamps,
            y=[band["srmc_high"]] * len(timestamps),
            mode="lines",
            line=dict(width=0),
            name=f"{label} SRMC high",
            showlegend=False,
            hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=[band["srmc_low"]] * len(timestamps),
            mode="lines",
            line=dict(width=0),
            fill="tonexty",
            fillcolor=color_band,
            name=f"{label} SRMC range (efficiency band)",
            showlegend=True,
            legendgroup=plant_type,
            hovertemplate=(
                f"<b>{label} SRMC efficiency band</b><br>"
                f"Low (58% eff): £{band['srmc_low']:.1f}/MWh<br>"
                f"Mid (54% eff): £{band['srmc_mid']:.1f}/MWh<br>"
                f"High (50% eff): £{band['srmc_high']:.1f}/MWh<br>"
                "<extra></extra>"
            ),
        ))
        # Midpoint line
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=[band["srmc_mid"]] * len(timestamps),
            mode="lines",
            line=dict(color=color_line, width=1.5, dash="dot"),
            name=f"{label} SRMC mid",
            legendgroup=plant_type,
            showlegend=True,
            hovertemplate=(
                f"<b>{label} SRMC mid:</b> £{band['srmc_mid']:.1f}/MWh<extra></extra>"
            ),
        ))

    # ── DA electricity price line ────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=today_series.index.tolist(),
        y=today_series.values.tolist(),
        mode="lines",
        name="GB DA Price (today)",
        line=dict(color="#212121", width=2.5),
        hovertemplate="<b>DA Price:</b> £%{y:.1f}/MWh<br>%{x|%H:%M} UTC<extra></extra>",
    ))

    # ── "Now" vertical line ──────────────────────────────────────────────────
    now = pd.Timestamp.now(tz="UTC")
    if today_series.index[0] <= now <= today_series.index[-1]:
        fig.add_vline(
            x=now,
            line=dict(color="#B0BEC5", width=1, dash="dash"),
            annotation_text="Now",
            annotation_position="top right",
            annotation_font_color="#B0BEC5",
        )

    # ── Layout ───────────────────────────────────────────────────────────────
    date_label = today_start.strftime("%d %b %Y")
    fig.update_layout(
        title=dict(text=f"{title} — {date_label}", font=dict(size=15)),
        xaxis=dict(
            title="Time (UTC)",
            tickformat="%H:%M",
            gridcolor="#F0F0F0",
            range=[today_start, today_end],
        ),
        yaxis=dict(
            title="£/MWh",
            gridcolor="#F0F0F0",
            zeroline=False,
        ),
        showlegend=False,
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(t=60, b=50, l=60, r=20),
        height=400,
    )

    st.plotly_chart(fig, use_container_width=True)

    # ── Methodology footnote ─────────────────────────────────────────────────
    with st.expander("ℹ️ Chart assumptions and methodology", expanded=False):
        st.markdown(f"""
        **SRMC formula:** `SRMC = (Gas price NCV ÷ efficiency) + (Carbon price + CPS) × emission factor`

        **Efficiency band (shaded region):**
        - CCGT: 50–58% LHV — GB fleet mix, including part-load cycling.  The band spans from the best
          plant's variable cost (high efficiency → cheap) to the worst (low efficiency → expensive).
        - OCGT: 35–40% LHV.  OCGT band is shown for reference only; the "gas at margin" signal uses CCGT.
        - Recip: 36–45% LHV (source: BEIS Generation Costs Report).

        **Tolerance zone (outer dashed lines, CCGT only):**
        - ±{int(GAS_SETTING_UPPER_THRESHOLD*100)}% symmetric band around the CCGT efficiency band.
        - This is the zone used for the "Gas at margin?" signal in the KPI header.
        - Assumption: covers SRMC model uncertainty (gas quote lag ~1 day, heat-rate variance across
          GB fleet, carbon intraday moves — estimated ±3–5%) plus a buffer for modest scarcity
          conditions when a CCGT is still the marginal unit but its bid price exceeds pure variable cost.
        - If the DA price is inside the outer dashed lines → **Gas at margin**.
        - Above the upper dashed line → **Above SRMC** (scarcity / imports / network constraint).
        - Below the lower dashed line → **Below SRMC** (wind, nuclear, hydro, or imports at margin).

        **Gas and carbon prices:** NBP day-ahead (OilPriceAPI) and UK ETS (Yahoo Finance UKA=F).
        Carbon Price Support (CPS) of £18/tCO₂ is added on top of UK ETS for GB generators.

        *This is a first-order indicative signal.  Actual merit order depends on plant-specific bids,
        balancing mechanism actions, and network constraints.*
        """)


def render_da_chart(
    tomorrow_series: pd.Series,
    srmc_bands: dict[str, dict],
    title: str = "Tomorrow's Day-Ahead Price vs Gas SRMC Ranges",
) -> None:
    """
    Render tomorrow's day-ahead price chart against SRMC bands.

    tomorrow_series: pd.Series with UTC DatetimeIndex and £/MWh prices for
                     tomorrow's 48 half-hourly settlement periods.
    srmc_bands:      Same structure as render_price_chart — uses today's gas price.
    """
    if tomorrow_series.empty:
        st.info(
            "Tomorrow's day-ahead prices not yet published. "
            "The N2EX/APXMIDP auction clears at ~11:00 UTC, results available from ~11:45."
        )
        return

    tomorrow_start = tomorrow_series.index.min().normalize()
    tomorrow_end   = tomorrow_start + pd.Timedelta(days=1)
    timestamps     = tomorrow_series.index.tolist()

    fig = go.Figure()

    # ── CCGT tolerance zone ──────────────────────────────────────────────────
    if "CCGT" in srmc_bands:
        ccgt      = srmc_bands["CCGT"]
        tol_upper = ccgt["srmc_high"] * (1.0 + GAS_SETTING_UPPER_THRESHOLD)
        tol_lower = ccgt["srmc_low"]  * (1.0 - GAS_SETTING_LOWER_THRESHOLD)

        fig.add_trace(go.Scatter(
            x=timestamps, y=[tol_upper] * len(timestamps),
            mode="lines", line=dict(color="#1E88E5", width=1, dash="dash"),
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=timestamps, y=[tol_lower] * len(timestamps),
            mode="lines", line=dict(color="#1E88E5", width=1, dash="dash"),
            fill="tonexty", fillcolor="rgba(30,136,229,0.04)",
            showlegend=False,
            hovertemplate=(
                f"<b>CCGT tolerance zone:</b> £{tol_lower:.1f}–£{tol_upper:.1f}/MWh "
                f"(±{int(GAS_SETTING_UPPER_THRESHOLD*100)}%)<extra></extra>"
            ),
        ))

    # ── SRMC efficiency bands ────────────────────────────────────────────────
    for plant_type, band in srmc_bands.items():
        params     = PLANT_PARAMS[plant_type]
        color_band = params["color_band"]
        color_line = params["color"]
        label      = band["label"]

        fig.add_trace(go.Scatter(
            x=timestamps, y=[band["srmc_high"]] * len(timestamps),
            mode="lines", line=dict(width=0),
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=timestamps, y=[band["srmc_low"]] * len(timestamps),
            mode="lines", line=dict(width=0),
            fill="tonexty", fillcolor=color_band,
            showlegend=False,
            hovertemplate=(
                f"<b>{label} SRMC band</b><br>"
                f"Low: £{band['srmc_low']:.1f}/MWh<br>"
                f"Mid: £{band['srmc_mid']:.1f}/MWh<br>"
                f"High: £{band['srmc_high']:.1f}/MWh<extra></extra>"
            ),
        ))
        fig.add_trace(go.Scatter(
            x=timestamps, y=[band["srmc_mid"]] * len(timestamps),
            mode="lines", line=dict(color=color_line, width=1.5, dash="dot"),
            showlegend=False,
            hovertemplate=f"<b>{label} SRMC mid:</b> £{band['srmc_mid']:.1f}/MWh<extra></extra>",
        ))

    # ── DA price line ────────────────────────────────────────────────────────
    n   = len(tomorrow_series)
    avg = tomorrow_series.mean()
    fig.add_trace(go.Scatter(
        x=timestamps, y=tomorrow_series.values.tolist(),
        mode="lines", name="Tomorrow DA",
        line=dict(color="#212121", width=2.5),
        showlegend=False,
        hovertemplate="<b>DA:</b> £%{y:.1f}/MWh<br>%{x|%H:%M} UTC<extra></extra>",
    ))

    date_label = tomorrow_start.strftime("%d %b %Y")
    fig.update_layout(
        title=dict(
            text=f"{title} — {date_label}  ({n}/48 periods · avg £{avg:.1f}/MWh)",
            font=dict(size=15),
        ),
        xaxis=dict(
            title="Time (UTC)",
            tickformat="%H:%M",
            gridcolor="#F0F0F0",
            range=[tomorrow_start, tomorrow_end],
        ),
        yaxis=dict(title="£/MWh", gridcolor="#F0F0F0", zeroline=False),
        showlegend=False,
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(t=60, b=50, l=60, r=20),
        height=400,
    )

    st.plotly_chart(fig, use_container_width=True)
