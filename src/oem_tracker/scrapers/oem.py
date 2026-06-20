"""Open Electricity Market (OEM) statistics scraper.

Scrapes market share by purchase option from openelectricitymarket.sg/about/statistics.
Data: % of accounts on Regulated Tariff / Retail Price Plan / Wholesale Electricity Plan,
split by Residential and Business segments.
"""

from __future__ import annotations

import re
from datetime import date

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from ..config import OEM_STATS_URL

HEADERS = {
    "User-Agent": "oem-tracker/0.1 (data research; espsluar@gmail.com)",
    "Referer": "https://www.openelectricitymarket.sg",
}


def fetch_market_share() -> pd.DataFrame:
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(OEM_STATS_URL, headers=HEADERS)
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract as-of date from the page (typically "As of <Month> <Year>")
    as_of = None
    for tag in soup.find_all(string=re.compile(r"as of", re.I)):
        as_of = tag.strip()
        break

    rows = []
    # Find percentage values with their context labels
    # The page has two sections: Residential and Business accounts
    for segment in ["residential", "business"]:
        section = soup.find(string=re.compile(segment, re.I))
        if not section:
            continue
        parent = section.find_parent()
        # Walk siblings to find the three plan percentages
        text = parent.get_text(" ", strip=True) if parent else ""
        pct_matches = re.findall(r"([\w\s]+?)\s*\(?([\d.]+)%\)?", text)
        for label, pct in pct_matches:
            label = label.strip()
            if any(kw in label.lower() for kw in ["regulated", "retail", "wholesale"]):
                rows.append({"segment": segment, "plan": label, "pct": float(pct), "as_of": as_of, "scraped_date": date.today().isoformat()})

    if not rows:
        # Fallback: extract all percentages from the full page
        for match in re.finditer(r"([\w\s]+?):\s*([\d.]+)%", soup.get_text()):
            label, pct = match.group(1).strip(), float(match.group(2))
            rows.append({"segment": "unknown", "plan": label, "pct": pct, "as_of": as_of, "scraped_date": date.today().isoformat()})

    return pd.DataFrame(rows)
