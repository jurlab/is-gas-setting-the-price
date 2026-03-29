"""
data/carbon_client.py — Carbon allowance price fetcher.

UK ETS (UKA):
    Fetched via OilPriceAPI code UK_CARBON_GBP (£/tCO₂).
    Confirmed available on OilPriceAPI as of March 2026.
    This replaces the previous Yahoo Finance UKA=F approach — that ticker
    was delisted from Yahoo Finance in early 2026.
    History is fetched via /prices/past with the same code.
    Falls back to FALLBACK_UK_ETS_GBP if the API call fails.

EU ETS (EUA):
    Fetched via OilPriceAPI code EU_CARBON_EUR (€/tCO₂).
    Falls back to /futures/eua-carbon front-month if spot fails.
"""

import os
import requests
import pandas as pd
from typing import Optional
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OIL_API_BASE_URL, OIL_API_CODES, FALLBACK_UK_ETS_GBP


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Token {api_key}", "Content-Type": "application/json"}


def _get_key(api_key: Optional[str] = None) -> str:
    key = api_key or os.getenv("OIL_PRICE_API_KEY", "")
    if not key:
        raise EnvironmentError("OIL_PRICE_API_KEY not set — register at oilpriceapi.com")
    return key


# ── UK ETS ──────────────────────────────────────────────────────────────────

def fetch_uk_ets_gbp(
    fallback: float = FALLBACK_UK_ETS_GBP,
    api_key: Optional[str] = None,
) -> tuple[float, str]:
    """
    Fetch the latest UK ETS allowance price (£/tCO₂) via OilPriceAPI.

    Returns (price, source_label).
    Falls back to hardcoded value on failure — shown with ⚠️ in the UI.
    """
    try:
        key = _get_key(api_key)
        resp = requests.get(
            f"{OIL_API_BASE_URL}/prices/latest",
            headers=_headers(key),
            params={"by_code": OIL_API_CODES["uk_ets"]},
            timeout=10,
        )
        resp.raise_for_status()
        price = float(resp.json()["data"]["price"])
        if price <= 0:
            raise ValueError(f"Implausible UK ETS price: {price}")
        return round(price, 2), "OilPriceAPI (UK_CARBON_GBP)"

    except Exception as e:
        print(f"UK ETS fetch error: {e} — using fallback £{fallback}/tCO₂")
        return fallback, f"Fallback (£{fallback} hardcoded — live data unavailable)"


def fetch_uk_ets_history_gbp(
    days: int = 30,
    api_key: Optional[str] = None,
) -> pd.Series:
    """
    Fetch UK ETS daily prices for the last N days (£/tCO₂) via OilPriceAPI.
    Returns pd.Series with UTC DatetimeIndex.
    """
    try:
        key = _get_key(api_key)
        resp = requests.get(
            f"{OIL_API_BASE_URL}/prices/past",
            headers=_headers(key),
            params={"by_code": OIL_API_CODES["uk_ets"]},
            timeout=15,
        )
        resp.raise_for_status()
        records = []
        for entry in resp.json().get("data", []):
            try:
                records.append((
                    pd.to_datetime(entry["created_at"], utc=True),
                    float(entry["price"]),
                ))
            except (KeyError, ValueError):
                continue

        if not records:
            return pd.Series(dtype=float)

        series = (
            pd.DataFrame(records, columns=["ts", "price"])
            .drop_duplicates("ts")
            .set_index("ts")["price"]
            .sort_index()
        )
        # Trim to requested window
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
        return series[series.index >= cutoff]

    except Exception as e:
        print(f"UK ETS history fetch error: {e}")
        return pd.Series(dtype=float)


# ── EU ETS ──────────────────────────────────────────────────────────────────

def fetch_eu_ets_eur(api_key: Optional[str] = None) -> Optional[float]:
    """
    Fetch latest EU ETS allowance price (€/tCO₂) via OilPriceAPI.
    First tries /prices/latest, falls back to /futures/eua-carbon front-month.
    """
    key = _get_key(api_key)

    try:
        resp = requests.get(
            f"{OIL_API_BASE_URL}/prices/latest",
            headers=_headers(key),
            params={"by_code": OIL_API_CODES["eu_ets"]},
            timeout=10,
        )
        resp.raise_for_status()
        price = float(resp.json()["data"]["price"])
        if price > 0:
            return round(price, 2)
    except Exception as e:
        print(f"EU ETS /prices/latest failed: {e} — trying futures endpoint")

    try:
        resp = requests.get(
            f"{OIL_API_BASE_URL}/futures/eua-carbon",
            headers=_headers(key),
            timeout=10,
        )
        resp.raise_for_status()
        contracts = resp.json().get("contracts", [])
        for c in contracts:
            if c.get("is_front_month"):
                price = c.get("last_price") or c.get("close")
                if price:
                    return round(float(price), 2)
        if contracts:
            price = contracts[0].get("last_price") or contracts[0].get("close")
            if price:
                return round(float(price), 2)
    except Exception as e:
        print(f"EU ETS /futures/eua-carbon failed: {e}")

    return None


def fetch_eu_ets_history_eur(api_key: Optional[str] = None) -> pd.Series:
    """Fetch EU ETS daily close prices for the last 30 days (€/tCO₂)."""
    try:
        key = _get_key(api_key)
        resp = requests.get(
            f"{OIL_API_BASE_URL}/futures/eua-carbon/historical",
            headers=_headers(key),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        records = []
        for contract_data in data.get("contracts", []):
            if contract_data.get("contract_status") == "front_month" or \
               contract_data.get("is_front_month"):
                for day in contract_data.get("daily_data", []):
                    try:
                        ts    = pd.to_datetime(day["trading_date"], utc=True)
                        price = float(day.get("close") or day.get("settlement") or 0)
                        if price > 0:
                            records.append((ts, price))
                    except (KeyError, ValueError):
                        continue
                break

        if not records:
            return pd.Series(dtype=float)

        return (
            pd.DataFrame(records, columns=["ts", "price"])
            .drop_duplicates("ts")
            .set_index("ts")["price"]
            .sort_index()
        )

    except Exception as e:
        print(f"EU ETS history fetch error: {e}")
        return pd.Series(dtype=float)
