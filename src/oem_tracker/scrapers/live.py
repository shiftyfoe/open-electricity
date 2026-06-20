"""Unofficial real-time NEMS API (nems.sn.sg) — current USEP, demand, VCP.

No authentication. Cross-origin enabled. Updated every half-hour.
Response: {"updated": <unix_ts_sst>, "usep": <$/MWh>, "demand": <MW>, "vcp": <$/MWh>}
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..config import NEMS_LIVE_URL


def fetch_snapshot() -> dict:
    with httpx.Client(timeout=15) as client:
        resp = client.get(NEMS_LIVE_URL)
        resp.raise_for_status()
    data = resp.json()
    # Convert SST unix timestamp to ISO string
    ts = datetime.fromtimestamp(data["updated"], tz=timezone.utc)
    return {
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        "updated_at": ts.isoformat(),
        "usep": data.get("usep"),
        "demand_mw": data.get("demand"),
        "vcp": data.get("vcp"),
    }
