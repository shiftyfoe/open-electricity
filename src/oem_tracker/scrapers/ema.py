"""EMA (Energy Market Authority) data scrapers.

Sources:
  1. Monthly average USEP (XLSX) — updated monthly, long-term trend
  2. Half-hourly system demand (XLSX) — filter by year/month via page form
"""

from __future__ import annotations

import io
import re

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from ..config import EMA_BASE, EMA_MONTHLY_USEP_PAGE

HEADERS = {
    "User-Agent": "oem-tracker/0.1 (data research; espsluar@gmail.com)",
}


def _get_xlsx_link(page_url: str, pattern: str) -> str | None:
    """Scrape a page and return the first href matching a regex pattern."""
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(page_url, headers=HEADERS)
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(pattern, href, re.IGNORECASE):
            return href if href.startswith("http") else EMA_BASE + href
    return None


def fetch_monthly_usep() -> pd.DataFrame:
    """Download EMA's monthly average USEP Excel file.

    Discovers the current download link by scraping the statistics page,
    since EMA embeds the update date in the filename.
    """
    link = _get_xlsx_link(EMA_MONTHLY_USEP_PAGE, r"Average.*USEP.*\.xlsx")
    if not link:
        raise RuntimeError("Could not find monthly USEP download link on EMA page")
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        resp = client.get(link, headers=HEADERS)
        resp.raise_for_status()
    df = pd.read_excel(io.BytesIO(resp.content), engine="openpyxl")
    return _clean_monthly_usep(df)


def _clean_monthly_usep(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip() for c in df.columns]
    # EMA workbooks vary in layout; find the year and USEP columns heuristically
    df = df.dropna(how="all").reset_index(drop=True)
    # Try to find a 'Year' or date-like column and a $/MWh column
    date_col = next((c for c in df.columns if "year" in c.lower() or "month" in c.lower() or "period" in c.lower()), None)
    usep_col = next((c for c in df.columns if "usep" in c.lower() or "price" in c.lower() or "$/mwh" in c.lower()), None)
    if date_col and usep_col:
        out = df[[date_col, usep_col]].copy()
        out.columns = ["period", "usep_avg"]
        out["usep_avg"] = pd.to_numeric(out["usep_avg"], errors="coerce")
        return out.dropna(subset=["usep_avg"])
    # Fallback: return raw with normalised column names
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    return df
