"""Retail electricity plan price scraper.

Source: compare.openelectricitymarket.sg / public.api.spdigital.sg/retailer
No auth required. startIndex is 1-based (0 returns a 400).
"""

from __future__ import annotations

from datetime import date

import httpx
import pandas as pd

from ..config import RETAIL_API_BASE, RETAIL_COMPARE_ORIGIN

HEADERS = {
    "User-Agent": "oem-tracker/0.1 (data research; espsluar@gmail.com)",
    "Origin": RETAIL_COMPARE_ORIGIN,
    "Referer": RETAIL_COMPARE_ORIGIN + "/",
}

# Representative reference flat for price estimation context.
# Price (¢/kWh) is the same regardless of housing type; only estimatedCharges differs.
_REF_HOUSING = "HDB 4-Room"
_REF_KWH = "364.7242"


def fetch_regulated_tariff() -> float:
    """Return current SP Group regulated tariff in ¢/kWh."""
    with httpx.Client(timeout=30, headers=HEADERS) as client:
        r = client.get(f"{RETAIL_API_BASE}/namcPremiseInfo/getNamcValues")
        r.raise_for_status()
    return float(r.json()["regulatedTariff"])


def fetch_retail_plans() -> pd.DataFrame:
    """Return all current residential retail plans as a DataFrame."""
    regulated = fetch_regulated_tariff()

    payload = {
        "estimationFlag": True,
        "housingType": _REF_HOUSING,
        "monthlyConsumption": _REF_KWH,
        "sortBy": "estimatedChargesAsc",
        "searchCriteriaOr": "customerType:RES,customerType:BTH",
        "searchCriteriaOfferOr": "offerType:FR,offerType:DRT",
        "startIndex": 1,  # API is 1-indexed; 0 returns 400
    }

    with httpx.Client(timeout=30, headers=HEADERS) as client:
        r = client.post(
            f"{RETAIL_API_BASE}/priceplan/filterEstimatedSavingsAndCharges",
            json=payload,
        )
        r.raise_for_status()

    plans = r.json().get("consumerViewPlanDTOs", [])
    rows = []
    for p in plans:
        rows.append({
            "scraped_date": date.today().isoformat(),
            "retailer": p.get("retailerName", ""),
            "retailer_code": p.get("retailerCode", ""),
            "offer_id": p.get("offerId", ""),
            "offer_name": p.get("offerName", ""),
            "offer_type": p.get("offerType", ""),
            "price_cents_kwh": _f(p.get("price")),
            "discounted_price_cents_kwh": _f(p.get("discountedPrice")),
            "estimated_monthly_sgd": _f(p.get("estimatedCharges")),
            "contract_months": p.get("contractDuration"),
            "regulated_tariff_cents_kwh": regulated,
            "ref_housing_type": _REF_HOUSING,
        })

    return pd.DataFrame(rows)


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None
