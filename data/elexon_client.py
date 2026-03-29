"""
data/elexon_client.py — GB electricity prices via Elexon Insights API.

The same MID endpoint returns two kinds of records:
  Past/current periods  → Market Index Data (MID): volume-weighted average
                          of intraday continuous market trades.
  Future periods        → APXMIDP populates future settlement periods with
                          the DA auction clearing prices published ~11:45.

GB trading day runs 23:00 UTC → 23:00 UTC the following day.
We split on the 23:00 UTC boundary, NOT on now_utc, so that at 23:01 the
just-started trading day is correctly classified as "tomorrow's DA".

Fetch window: past 48h + next 48h, to ensure full coverage at all times.

Provider notes (confirmed March 2026):
  APXMIDP: real prices for both intraday and DA future periods.
  N2EXMIDP: returns records but all price=0.0 since Nord Pool acquired N2EX.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta, timezone, date
from typing import Optional
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ELEXON_BASE_URL

_MID_ENDPOINT  = f"{ELEXON_BASE_URL}/balancing/pricing/market-index"
_PREF_PROVIDER = "APXMIDP"


def _parse_records(payload: dict, skip_zero: bool = True) -> list[tuple]:
    records = []
    for item in payload.get("data", []):
        try:
            price = float(item["price"])
            if skip_zero and price == 0.0:
                continue
            ts = pd.to_datetime(item["startTime"], utc=True)
            records.append((ts, price))
        except (KeyError, TypeError, ValueError):
            continue
    return records


def _build_series(records: list[tuple]) -> pd.Series:
    if not records:
        return pd.Series(dtype=float)
    df = (
        pd.DataFrame(records, columns=["timestamp", "price"])
        .drop_duplicates("timestamp")
        .sort_values("timestamp")
        .set_index("timestamp")
    )
    return df["price"]


def _trading_day_boundary(now_utc: pd.Timestamp) -> pd.Timestamp:
    """
    Return the 23:00 UTC timestamp that marks the start of the current
    GB trading day.

    If now >= 23:00 UTC today → boundary is today at 23:00 (we are already
    in the new trading day that started minutes/seconds ago).
    If now < 23:00 UTC today  → boundary is yesterday at 23:00 (today's
    trading day started last night).
    """
    today_2300 = now_utc.normalize() + pd.Timedelta(hours=23)
    if now_utc >= today_2300:
        return today_2300          # boundary was a few minutes/hours ago
    else:
        return today_2300 - pd.Timedelta(days=1)  # boundary was last night


def fetch_gb_da_prices(hours_back: int = 48) -> pd.Series:
    """
    Fetch GB MID + DA prices. Returns a combined series.
    Fetches hours_back into the past and 48h forward (full next trading day).
    """
    now_utc = datetime.now(timezone.utc)
    from_dt = now_utc - timedelta(hours=hours_back)
    to_dt   = now_utc + timedelta(hours=48)   # 48h forward to cover full next trading day

    base_params = {
        "from": from_dt.strftime("%Y-%m-%dT%H:%MZ"),
        "to":   to_dt.strftime("%Y-%m-%dT%H:%MZ"),
    }

    for extra, label in [
        ({"dataProviders": _PREF_PROVIDER}, "APXMIDP"),
        ({},                                "all providers"),
    ]:
        try:
            resp = requests.get(
                _MID_ENDPOINT, params={**base_params, **extra},
                timeout=15, headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            records = _parse_records(resp.json(), skip_zero=True)
            if records:
                print(f"Elexon: {len(records)} records ({label})")
                return _build_series(records)
            else:
                print(f"Elexon: no non-zero records ({label}), "
                      f"{'retrying…' if extra else 'giving up.'}")
        except requests.exceptions.HTTPError as e:
            print(f"Elexon HTTP {e.response.status_code} ({label}): {e.response.text[:200]}")
        except Exception as e:
            print(f"Elexon error ({label}): {e}")

    return pd.Series(dtype=float)


def fetch_gb_tomorrow_da() -> pd.Series:
    """
    Fetch GB day-ahead prices for tomorrow only, using APXMIDP.

    N2EX/APXMIDP publishes tomorrow's 48 half-hourly prices at ~11:45 UTC today.
    Returns an empty Series (not an error) if the auction hasn't published yet.

    Uses the same APXMIDP provider and zero-price filtering as fetch_gb_da_prices.
    """
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    from_dt  = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, tzinfo=timezone.utc)
    to_dt    = from_dt + timedelta(hours=24)

    params = {
        "from": from_dt.strftime("%Y-%m-%dT%H:%MZ"),
        "to":   to_dt.strftime("%Y-%m-%dT%H:%MZ"),
        "dataProviders": _PREF_PROVIDER,
    }

    try:
        resp = requests.get(
            _MID_ENDPOINT, params=params,
            timeout=15, headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        records = _parse_records(resp.json(), skip_zero=True)
        # Defensive: keep only tomorrow's timestamps
        records = [(ts, p) for ts, p in records if ts.date() == tomorrow]
        if not records:
            print(f"Elexon tomorrow: no data yet for {tomorrow} (auction publishes ~11:45 UTC)")
            return pd.Series(dtype=float)
        print(f"Elexon tomorrow: {len(records)} periods for {tomorrow}")
        return _build_series(records)
    except requests.exceptions.HTTPError as e:
        print(f"Elexon HTTP error (tomorrow): {e.response.status_code}")
        return pd.Series(dtype=float)
    except Exception as e:
        print(f"Elexon error (tomorrow): {e}")
        return pd.Series(dtype=float)


def split_intraday_and_tomorrow(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """
    Split a combined series into today's intraday MID and tomorrow's DA.

    Splits on the 23:00 UTC trading day boundary:
      intraday  — startTime < current trading day boundary (i.e. current day's MID)
      tomorrow  — startTime >= current trading day boundary (the next trading day's DA)

    This correctly handles the post-23:00 case: at 23:01, the new trading day
    has just started, so all periods from 23:00 onwards are "tomorrow's DA".
    """
    if series.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    now_utc   = pd.Timestamp.now(tz="UTC")
    boundary  = _trading_day_boundary(now_utc)

    intraday = series[series.index < boundary]
    tomorrow = series[series.index >= boundary]

    return intraday, tomorrow


def get_latest_price(series: pd.Series) -> Optional[float]:
    """Return the most recent past price (closest to now, before now)."""
    if series.empty:
        return None
    now_utc = pd.Timestamp.now(tz="UTC")
    past = series[series.index <= now_utc]
    if past.empty:
        return float(series.iloc[0])
    return float(past.iloc[-1])


def get_tomorrow_avg_price(series: pd.Series) -> Optional[float]:
    """Return the average price from a series (intended for tomorrow's DA series)."""
    if series.empty:
        return None
    return round(float(series.mean()), 2)
