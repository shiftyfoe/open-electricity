"""Export raw data to web-friendly JSON files for the static dashboard.

All functions accept explicit raw_dir / out_dir so they're testable
without filesystem hacks.  scripts/build_site.py is a thin wrapper.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

# Raw data files use compact YYYYMMDD (no dashes).
# Web-facing JSON files use YYYY-MM-DD for readability.
_DATE_FMT = "%Y%m%d"

EMC_COLS = ["period", "usep", "demand_mw", "solar_mw", "tcl_mw", "eheur", "lcp", "rusep", "map", "mapt"]

RETAIL_COLS = ["scraped_date", "retailer", "offer_name", "offer_type",
               "price_cents_kwh", "discounted_price_cents_kwh",
               "estimated_monthly_sgd", "contract_months", "regulated_tariff_cents_kwh"]


def _parse_stem(stem: str) -> datetime:
    return datetime.strptime(stem, _DATE_FMT)


# ── public API ────────────────────────────────────────────────────────────────

def export_emc(raw_dir: Path, out_dir: Path) -> list[str]:
    src = raw_dir / "emc"
    dst = out_dir / "emc"
    dst.mkdir(parents=True, exist_ok=True)
    dates: list[str] = []
    for f in sorted(src.glob("*.parquet")):
        df = pd.read_parquet(f)
        cols = [c for c in EMC_COLS if c in df.columns]
        iso_date = _parse_stem(f.stem).strftime("%Y-%m-%d")
        out = dst / f"{iso_date}.json"
        out.write_text(df[cols].to_json(orient="records"))
        dates.append(iso_date)
    return dates


def export_emc_daily_summary(raw_dir: Path, out_dir: Path) -> list[dict]:
    """Generate daily aggregates across all EMC dates for trend charts."""
    src = raw_dir / "emc"
    rows: list[dict] = []
    for f in sorted(src.glob("*.parquet")):
        df = pd.read_parquet(f)
        row: dict = {"date": _parse_stem(f.stem).strftime("%Y-%m-%d")}
        if "usep" in df.columns:
            row["usep_avg"] = round(float(df["usep"].mean()), 2)
            row["usep_min"] = round(float(df["usep"].min()), 2)
            row["usep_max"] = round(float(df["usep"].max()), 2)
        if "demand_mw" in df.columns:
            row["demand_peak"] = round(float(df["demand_mw"].max()), 1)
            row["demand_avg"] = round(float(df["demand_mw"].mean()), 1)
        if "solar_mw" in df.columns:
            row["solar_peak"] = round(float(df["solar_mw"].max()), 1)
        rows.append(row)
    (out_dir / "emc_daily_summary.json").write_text(json.dumps(rows))
    return rows


def export_live(raw_dir: Path, out_dir: Path) -> int:
    src = raw_dir / "live"
    records = []
    for f in sorted(src.glob("*.json")):
        records.append(json.loads(f.read_text()))
    (out_dir / "live.json").write_text(json.dumps(records))
    return len(records)


def export_retail(raw_dir: Path, out_dir: Path) -> dict:
    src = raw_dir / "retail"
    files = sorted(src.glob("*.parquet")) if src.exists() else []
    if not files:
        (out_dir / "retail_latest.json").write_text("[]")
        (out_dir / "retail_history.json").write_text("[]")
        return {"latest_date": None, "plan_count": 0, "history_dates": 0}

    # Latest snapshot → retail_latest.json
    latest_df = pd.read_parquet(files[-1])
    cols = [c for c in RETAIL_COLS if c in latest_df.columns]
    (out_dir / "retail_latest.json").write_text(latest_df[cols].to_json(orient="records"))

    # Daily cheapest per type → retail_history.json
    history = []
    for f in files:
        df = pd.read_parquet(f)
        row: dict = {"date": _parse_stem(f.stem).strftime("%Y-%m-%d")}
        if "regulated_tariff_cents_kwh" in df.columns:
            row["regulated_tariff"] = df["regulated_tariff_cents_kwh"].iloc[0]
        for otype in ("FR", "DRT"):
            sub = df[df["offer_type"] == otype]
            if sub.empty:
                continue
            if otype == "FR":
                price_col = "price_cents_kwh"
                if price_col in sub.columns:
                    valid = sub[price_col].dropna()
                    if not valid.empty:
                        row[f"cheapest_{otype.lower()}"] = round(float(valid.min()), 4)
            else:  # DRT — effective price = tariff - discount
                disc_col = "discounted_price_cents_kwh"
                if disc_col in sub.columns and "regulated_tariff_cents_kwh" in sub.columns:
                    # Compute effective price per row, then take the minimum
                    sub = sub.copy()
                    sub["_effective_drt"] = sub["regulated_tariff_cents_kwh"] - sub[disc_col]
                    valid = sub["_effective_drt"].dropna()
                    if not valid.empty:
                        row[f"cheapest_{otype.lower()}"] = round(float(valid.min()), 4)
        history.append(row)
    (out_dir / "retail_history.json").write_text(json.dumps(history))

    return {"latest_date": _parse_stem(files[-1].stem).strftime("%Y-%m-%d"),
            "plan_count": len(latest_df), "history_dates": len(files)}


def build_all(raw_dir: Path, out_dir: Path) -> dict:
    """Run all exports and return a manifest dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    emc_dates = export_emc(raw_dir, out_dir)
    export_emc_daily_summary(raw_dir, out_dir)
    live_count = export_live(raw_dir, out_dir)
    retail_info = export_retail(raw_dir, out_dir)
    manifest = {
        "emc": {"dates": emc_dates},
        "live": {"count": live_count},
        "retail": retail_info,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
