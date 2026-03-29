"""
data/fx_client.py — EUR/GBP exchange rate via ECB SDMX free API.

No API key required. Rate updates once daily (working days).
Used to convert EU zone prices and EU SRMC values to GBP for display.
"""

import os
import requests
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ECB_FX_URL

# Fallback rate if ECB API is unavailable
_FALLBACK_EUR_TO_GBP = 0.845


def fetch_eur_to_gbp(fallback: float = _FALLBACK_EUR_TO_GBP) -> float:
    """
    Fetch the latest EUR/GBP exchange rate from the ECB SDMX API.

    ECB endpoint returns daily rates with 1 working day lag.
    Falls back to a hardcoded rate on failure (displayed with warning in UI).

    Returns:
        EUR→GBP conversion rate (multiply EUR amount by this to get GBP).
    """
    # ECB SDMX API returns XML. We request JSON format instead.
    url = ECB_FX_URL
    headers = {"Accept": "application/json"}
    params = {
        "lastNObservations": 1,
        "format": "jsondata",
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=8)
        resp.raise_for_status()
        data = resp.json()

        # Navigate the SDMX-JSON structure to find the observation value
        # Path: dataSets[0].series["0:0:0:0:0"].observations["0"][0]
        datasets = data.get("dataSets", [])
        if not datasets:
            raise ValueError("Empty dataSets in ECB response")

        series = datasets[0].get("series", {})
        if not series:
            raise ValueError("No series in ECB response")

        # There should be exactly one series key
        obs_dict = next(iter(series.values())).get("observations", {})
        if not obs_dict:
            raise ValueError("No observations in ECB response")

        # Most recent observation — sorted descending
        latest_obs = sorted(obs_dict.values())[-1]
        rate = float(latest_obs[0])

        if rate <= 0 or rate > 2:
            raise ValueError(f"Implausible EUR/GBP rate: {rate}")

        return rate

    except Exception as e:
        print(f"ECB FX fetch error: {e} — using fallback rate {fallback}")
        return fallback


def eur_to_gbp(eur_amount: float, rate: Optional[float] = None) -> float:
    """Convert EUR amount to GBP. Fetches rate if not provided."""
    if rate is None:
        rate = fetch_eur_to_gbp()
    return eur_amount * rate
