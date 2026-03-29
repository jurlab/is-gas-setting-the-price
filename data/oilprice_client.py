"""
data/oilprice_client.py — Gas price fetcher via OilPriceAPI.

Handles:
    - NBP natural gas price (p/therm GCV)   — code: NATURAL_GAS_GBP
    - TTF natural gas price (€/MWh GCV)     — code: DUTCH_TTF_EUR

Carbon prices are handled separately in data/carbon_client.py:
    - UK ETS → Yahoo Finance (UKA=F)         OilPriceAPI does NOT carry UK ETS
    - EU ETS → OilPriceAPI futures endpoint  /futures/eua-carbon

Codes verified against docs.oilpriceapi.com, March 2026.
Free trial: 10,000 requests / 7 days at oilpriceapi.com.
"""

import os
import requests
import pandas as pd
from datetime import datetime, timezone
from typing import Optional
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OIL_API_BASE_URL, OIL_API_CODES


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Token {api_key}", "Content-Type": "application/json"}


def _get_key(api_key: Optional[str] = None) -> str:
    key = api_key or os.getenv("OIL_PRICE_API_KEY", "")
    if not key:
        raise EnvironmentError("OIL_PRICE_API_KEY not set")
    return key


def fetch_latest_price(commodity_key: str, api_key: Optional[str] = None) -> Optional[float]:
    key  = _get_key(api_key)
    code = OIL_API_CODES.get(commodity_key)
    if not code:
        raise ValueError(f"Unknown commodity key: {commodity_key}")
    try:
        resp = requests.get(
            f"{OIL_API_BASE_URL}/prices/latest",
            headers=_headers(key),
            params={"by_code": code},
            timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json()["data"]["price"])
    except Exception as e:
        print(f"OilPriceAPI error [{commodity_key}/{code}]: {e}")
        return None


def fetch_price_history(commodity_key: str, api_key: Optional[str] = None) -> pd.Series:
    key  = _get_key(api_key)
    code = OIL_API_CODES.get(commodity_key)
    if not code:
        raise ValueError(f"Unknown commodity key: {commodity_key}")
    try:
        resp = requests.get(
            f"{OIL_API_BASE_URL}/prices/past",
            headers=_headers(key),
            params={"by_code": code},
            timeout=15,
        )
        resp.raise_for_status()
        records = []
        for entry in resp.json().get("data", []):
            try:
                records.append((pd.to_datetime(entry["created_at"], utc=True), float(entry["price"])))
            except (KeyError, ValueError):
                continue
        if not records:
            return pd.Series(dtype=float)
        return (
            pd.DataFrame(records, columns=["ts", "price"])
            .drop_duplicates("ts").set_index("ts")["price"].sort_index()
        )
    except Exception as e:
        print(f"OilPriceAPI history error [{commodity_key}]: {e}")
        return pd.Series(dtype=float)


def _patch_history_with_live(
    hist: pd.Series,
    live_price: Optional[float],
    fetched_at: datetime,
) -> pd.Series:
    """
    Splice the live (latest) price into a history series when the API has a
    trailing lag.

    OilPriceAPI /prices/past typically stops publishing 1–2 days before today.
    We already have today's price from /prices/latest, so if that timestamp is
    more than 20 hours newer than the last entry in hist, we insert it so that
    any downstream consumer (e.g. a future trend chart) has an unbroken series.

    The entry is keyed to midnight UTC of the fetch date so it aligns cleanly
    with resample("1D") operations.
    """
    if live_price is None:
        return hist

    today_midnight = pd.Timestamp(fetched_at.date(), tz="UTC")

    # Determine the most recent date already covered
    if not hist.empty:
        last_ts = hist.index[-1]
        gap = today_midnight - last_ts.normalize()
        if gap <= pd.Timedelta(hours=20):
            # History is already up to date — nothing to patch
            return hist

    # Insert live price at today's midnight; this will overwrite if somehow
    # the same key exists (idempotent).
    new_entry = pd.Series({today_midnight: live_price})
    patched   = pd.concat([hist, new_entry]).sort_index()
    patched    = patched[~patched.index.duplicated(keep="last")]
    return patched


class GasPrices:
    """Gas prices only (NBP + TTF). Carbon handled by carbon_client.py."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key    = api_key or os.getenv("OIL_PRICE_API_KEY", "")
        self.gas_gbp:    Optional[float] = None
        self.ttf:        Optional[float] = None
        self.fetched_at: Optional[datetime] = None
        self.gas_gbp_hist: pd.Series = pd.Series(dtype=float)
        self.ttf_hist:     pd.Series = pd.Series(dtype=float)

    def load(self, include_history: bool = True) -> "GasPrices":
        self.gas_gbp    = fetch_latest_price("gas_gbp", self._api_key)
        self.ttf        = fetch_latest_price("ttf",     self._api_key)
        self.fetched_at = datetime.now(timezone.utc)
        if include_history:
            self.gas_gbp_hist = fetch_price_history("gas_gbp", self._api_key)
            self.ttf_hist     = fetch_price_history("ttf",     self._api_key)
            # OilPriceAPI /prices/past has a publication lag of ~1 day.
            # If the live price is newer than the latest history entry, splice it in
            # so that today (and any missing trailing day) is represented in the
            # trend chart and SRMC history calculations.
            self.gas_gbp_hist = _patch_history_with_live(
                self.gas_gbp_hist, self.gas_gbp, self.fetched_at
            )
            self.ttf_hist = _patch_history_with_live(
                self.ttf_hist, self.ttf, self.fetched_at
            )
        return self

    @property
    def gb_available(self) -> bool:
        return self.gas_gbp is not None

    @property
    def eu_available(self) -> bool:
        return self.ttf is not None
