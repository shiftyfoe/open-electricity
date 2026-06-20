#!/usr/bin/env python3
"""Export raw data to web-friendly JSON files for the static dashboard.

Outputs:
  docs/data/manifest.json        — available dates per source
  docs/data/emc/<date>.json      — 48 half-hour rows per EMC date
  docs/data/live.json            — all live snapshots as an array
  docs/data/retail_latest.json   — current retail plans (latest scraped date)
  docs/data/retail_history.json  — daily cheapest FR/DRT prices over time
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "docs" / "data"

EMC_COLS = ["period", "usep", "demand_mw", "solar_mw", "tcl_mw", "eheur", "lcp", "rusep", "map", "mapt"]

RETAIL_COLS = ["scraped_date", "retailer", "offer_name", "offer_type",
               "price_cents_kwh", "discounted_price_cents_kwh",
               "estimated_monthly_sgd", "contract_months", "regulated_tariff_cents_kwh"]


def export_emc() -> list[str]:
    src = RAW / "emc"
    dst = OUT / "emc"
    dst.mkdir(parents=True, exist_ok=True)
    dates: list[str] = []
    for f in sorted(src.glob("*.parquet")):
        df = pd.read_parquet(f)
        cols = [c for c in EMC_COLS if c in df.columns]
        out = dst / f"{f.stem}.json"
        out.write_text(df[cols].to_json(orient="records"))
        dates.append(f.stem)
    return dates


def export_live() -> int:
    src = RAW / "live"
    records = []
    for f in sorted(src.glob("*.json")):
        records.append(json.loads(f.read_text()))
    (OUT / "live.json").write_text(json.dumps(records))
    return len(records)


def export_retail() -> dict:
    src = RAW / "retail"
    files = sorted(src.glob("*.parquet")) if src.exists() else []
    if not files:
        (OUT / "retail_latest.json").write_text("[]")
        (OUT / "retail_history.json").write_text("[]")
        return {"latest_date": None, "plan_count": 0, "history_dates": 0}

    # Latest snapshot → retail_latest.json
    latest_df = pd.read_parquet(files[-1])
    cols = [c for c in RETAIL_COLS if c in latest_df.columns]
    (OUT / "retail_latest.json").write_text(latest_df[cols].to_json(orient="records"))

    # Daily cheapest per type → retail_history.json
    history = []
    for f in files:
        df = pd.read_parquet(f)
        row: dict = {"date": f.stem}
        if "regulated_tariff_cents_kwh" in df.columns:
            row["regulated_tariff"] = df["regulated_tariff_cents_kwh"].iloc[0]
        for otype in ("FR", "DRT"):
            sub = df[df["offer_type"] == otype]
            price_col = "price_cents_kwh" if otype == "FR" else "discounted_price_cents_kwh"
            if not sub.empty and price_col in sub.columns:
                valid = sub[price_col].dropna()
                if not valid.empty:
                    row[f"cheapest_{otype.lower()}"] = round(float(valid.min()), 4)
        history.append(row)
    (OUT / "retail_history.json").write_text(json.dumps(history))

    return {"latest_date": files[-1].stem, "plan_count": len(latest_df), "history_dates": len(files)}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    emc_dates = export_emc()
    live_count = export_live()
    retail_info = export_retail()
    manifest = {
        "emc": {"dates": emc_dates},
        "live": {"count": live_count},
        "retail": retail_info,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Built: {len(emc_dates)} EMC dates, {live_count} live, "
          f"{retail_info['plan_count']} retail plans → {OUT}")


if __name__ == "__main__":
    main()
