"""
data/energy_charts_client.py — EU zone day-ahead prices via Energy Charts API.
(Fraunhofer Institute for Solar Energy Systems ISE)

Endpoint: https://api.energy-charts.info/price?bzn={BZN}&start={ISO}&end={ISO}
No API key required. CC BY 4.0 licensed for: FR, BE, NL, NO2, DK1 (and others).
IE (Ireland I-SEM) is NOT in the freely licensed tier — excluded from fetches.

Response JSON shape:
{
  "license_info": "...",
  "unix_seconds": [1742860800, 1742864400, ...],
  "price": [82.54, 85.10, ...],       # EUR/MWh, hourly resolution
  "unit": "EUR/MWh",
  "deprecated": false
}

Attribution required: Energy-Charts.info
"""

import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Optional
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ENERGY_CHARTS_BASE_URL, EU_ZONES

_PRICE_ENDPOINT = f"{ENERGY_CHARTS_BASE_URL}/price"


def fetch_zone_prices(
    bzn: str,
    hours_back: int = 48,
) -> pd.Series:
    """
    Fetch hourly day-ahead prices for a single EU bidding zone.

    Args:
        bzn:        Bidding zone code (e.g. 'FR', 'BE', 'NL', 'NO2', 'DK1')
        hours_back: Hours of history to retrieve

    Returns:
        pd.Series with UTC DatetimeIndex and float prices in EUR/MWh.
        Empty Series on failure or unlicensed zone.
    """
    # Check zone is in the freely licensed set
    zone_info = next((v for v in EU_ZONES.values() if v["bzn"] == bzn), None)
    if zone_info and not zone_info.get("licensed", True):
        print(f"Energy Charts: zone {bzn} not in freely licensed tier — skipping.")
        return pd.Series(dtype=float)

    now_utc  = datetime.now(timezone.utc)
    start_dt = now_utc - timedelta(hours=hours_back)
    # Add 24h forward to capture next-day DA prices
    end_dt   = now_utc + timedelta(hours=24)

    params = {
        "bzn":   bzn,
        "start": start_dt.strftime("%Y-%m-%dT%H:%MZ"),
        "end":   end_dt.strftime("%Y-%m-%dT%H:%MZ"),
    }

    try:
        resp = requests.get(_PRICE_ENDPOINT, params=params, timeout=12,
                            headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()

        unix_seconds = data.get("unix_seconds", [])
        prices       = data.get("price", [])

        if not unix_seconds or not prices or len(unix_seconds) != len(prices):
            print(f"Energy Charts: unexpected response structure for {bzn}")
            return pd.Series(dtype=float)

        idx = pd.to_datetime(unix_seconds, unit="s", utc=True)
        series = pd.Series(prices, index=idx, dtype=float)
        # Drop any null values (Energy Charts uses null for missing data)
        return series.dropna().sort_index()

    except requests.exceptions.HTTPError as e:
        print(f"Energy Charts HTTP error [{bzn}]: {e}")
        return pd.Series(dtype=float)
    except Exception as e:
        print(f"Energy Charts fetch error [{bzn}]: {e}")
        return pd.Series(dtype=float)


def fetch_all_eu_zones(hours_back: int = 48) -> dict[str, pd.Series]:
    """
    Fetch day-ahead prices for all configured EU zones.

    Returns dict mapping zone_key → pd.Series (EUR/MWh).
    Skips unlicensed zones (IE) with an empty Series.
    """
    results = {}
    for zone_key, zone_info in EU_ZONES.items():
        if not zone_info.get("licensed", True):
            results[zone_key] = pd.Series(dtype=float)
            continue
        results[zone_key] = fetch_zone_prices(zone_info["bzn"], hours_back)
    return results


def fetch_all_eu_zones_tomorrow() -> dict[str, pd.Series]:
    """
    Fetch tomorrow's day-ahead prices for all configured EU zones.

    EU DA prices are published by ~13:00 CET (12:00 UTC) for the next calendar
    day.  Fetches strictly from tomorrow 00:00 UTC to tomorrow 23:59 UTC so the
    caller always gets a clean 24-hour window with no prior-day contamination.

    Returns dict mapping zone_key → pd.Series (EUR/MWh).
    Returns empty Series for each zone if prices are not yet available or the
    zone is not in the freely licensed tier (Ireland/IE).
    """
    tomorrow    = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    from_dt     = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, tzinfo=timezone.utc)
    to_dt       = from_dt + timedelta(hours=24)

    results = {}
    for zone_key, zone_info in EU_ZONES.items():
        if not zone_info.get("licensed", True):
            results[zone_key] = pd.Series(dtype=float)
            continue

        bzn = zone_info["bzn"]
        params = {
            "bzn":   bzn,
            "start": from_dt.strftime("%Y-%m-%dT%H:%MZ"),
            "end":   to_dt.strftime("%Y-%m-%dT%H:%MZ"),
        }
        try:
            resp = requests.get(_PRICE_ENDPOINT, params=params, timeout=12,
                                headers={"Accept": "application/json"})
            resp.raise_for_status()
            data         = resp.json()
            unix_seconds = data.get("unix_seconds", [])
            prices       = data.get("price", [])

            if not unix_seconds or not prices or len(unix_seconds) != len(prices):
                results[zone_key] = pd.Series(dtype=float)
                continue

            idx    = pd.to_datetime(unix_seconds, unit="s", utc=True)
            series = pd.Series(prices, index=idx, dtype=float).dropna().sort_index()
            # Defensive: keep only tomorrow's timestamps
            series = series[series.index.date == tomorrow]
            results[zone_key] = series

        except Exception as e:
            print(f"Energy Charts tomorrow fetch error [{bzn}]: {e}")
            results[zone_key] = pd.Series(dtype=float)

    return results


def get_latest_price(series: pd.Series) -> Optional[float]:
    """Return the most recent price from the series."""
    if series.empty:
        return None
    now_utc = pd.Timestamp.now(tz="UTC")
    past = series[series.index <= now_utc]
    if past.empty:
        return float(series.iloc[0])
    return float(past.iloc[-1])
