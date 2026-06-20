"""EMC NEMS public download API — half-hourly USEP, demand, ancillary prices.

Endpoint: GET https://www.nems.emcsg.com/api/sitecore/DataSync/DataDownload
  value=10  → USEP + Demand (fields: Date, Period, Demand(MW), Solar(MW), TCL(MW),
               USEP($/MWh), EHEUR($/MWh), LCP($/MWh), RUSEP($/MWh), MAP($/MWh),
               MAPT($/MWh), TPC Applied, Last Updated)
Max window: 31 days. Rolling availability: 5 years. Release lag: D+6 for USEP/Demand.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import httpx
import pandas as pd

from ..config import EMC_DOWNLOAD_URL, EMC_DATASETS

HEADERS = {
    "Referer": "https://www.nems.emcsg.com/nems-prices",
}


def _fetch_csv(value: int, tpc_value: int, from_date: date, to_date: date) -> pd.DataFrame:
    params = {
        "value": value,
        "tpcValue": tpc_value,
        "fromDate": from_date.isoformat(),
        "toDate": to_date.isoformat(),
    }
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        resp = client.get(EMC_DOWNLOAD_URL, params=params, headers=HEADERS)
        resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text))


def _clean_usep_demand(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip() for c in df.columns]
    # Normalise column names to snake_case
    rename = {
        "Date": "date",
        "Period": "period",
        "Demand (MW)": "demand_mw",
        "Solar (MW)": "solar_mw",
        "TCL (MW)": "tcl_mw",
        "USEP ($/MWh)": "usep",
        "EHEUR ($/MWh)": "eheur",
        "LCP ($/MWh)": "lcp",
        "RUSEP ($/MWh)": "rusep",
        "MAP ($/MWh)": "map",
        "MAPT ($/MWh)": "mapt",
        "TPC Applied": "tpc_applied",
        "Last Updated": "last_updated",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce").dt.date
    for col in ["usep", "demand_mw", "solar_mw", "tcl_mw", "eheur", "lcp", "rusep"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["date", "usep"])


def fetch_usep_demand(from_date: date, to_date: date) -> pd.DataFrame:
    """Download half-hourly USEP + demand for a date range (max 31 days)."""
    window = (to_date - from_date).days
    if window > 31:
        raise ValueError(f"Date window {window} days exceeds 31-day API limit")
    cfg = EMC_DATASETS["usep_demand"]
    raw = _fetch_csv(cfg["value"], cfg["tpcValue"], from_date, to_date)
    return _clean_usep_demand(raw)


def fetch_yesterday() -> pd.DataFrame:
    """Convenience: fetch the most recently available day (D+6 lag → fetch D-6)."""
    today = date.today()
    # EMC releases data with a D+6 lag; fetch a safe window ending 7 days ago
    to_date = today - timedelta(days=7)
    from_date = to_date  # single day
    return fetch_usep_demand(from_date, to_date)
