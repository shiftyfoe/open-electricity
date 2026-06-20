"""Report generation: daily diff, weekly brief, monthly analytics, quarterly prediction.

All functions follow the same contract as exporter.py:
- Accept explicit raw_dir: Path, out_dir: Path
- Read parquet/JSON from raw_dir/
- Write JSON to out_dir/
- Return a result dict with at least {"status": ...}
- Handle insufficient data gracefully (never crash on empty input)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from math import sqrt
from pathlib import Path

import pandas as pd

from .storage import _parse_stem

# ── helpers ────────────────────────────────────────────────────────────────────


def _effective_price(row: dict | pd.Series) -> float | None:
    """Compute the effective price for a retail plan row."""
    price = row.get("price_cents_kwh")
    disc = row.get("discounted_price_cents_kwh")
    tariff = row.get("regulated_tariff_cents_kwh")
    otype = row.get("offer_type", "")
    if otype == "DRT" and disc is not None and tariff is not None:
        return float(tariff) - float(disc)
    if price is not None:
        return float(price)
    return None


def _plan_key(row: dict | pd.Series) -> str:
    """Stable composite key for a retail plan."""
    retailer = str(row.get("retailer", "")).strip()
    name = str(row.get("offer_name", "")).strip()
    ctype = str(row.get("offer_type", ""))
    contract = str(row.get("contract_months", ""))
    return f"{retailer}||{name}||{ctype}||{contract}"


def _read_parquet_dates(raw_dir: Path, source: str) -> list[tuple[date, Path]]:
    """Return sorted (date, path) pairs for all parquet files in a source dir."""
    src = raw_dir / source
    if not src.exists():
        return []
    pairs = []
    for f in src.glob("*.parquet"):
        try:
            pairs.append((_parse_stem(f.stem), f))
        except ValueError:
            continue
    return sorted(pairs, key=lambda x: x[0])


def _read_json_dates(raw_dir: Path, source: str) -> list[tuple[date, Path]]:
    """Return sorted (date, path) pairs for all JSON files in a source dir."""
    src = raw_dir / source
    if not src.exists():
        return []
    pairs = []
    for f in src.glob("*.json"):
        try:
            pairs.append((_parse_stem(f.stem), f))
        except ValueError:
            continue
    return sorted(pairs, key=lambda x: x[0])


def _load_emc_in_range(raw_dir: Path, start: date, end: date) -> pd.DataFrame:
    """Load and concatenate all EMC parquet files in a date range."""
    pairs = _read_parquet_dates(raw_dir, "emc")
    frames = []
    for d, path in pairs:
        if start <= d <= end:
            frames.append(pd.read_parquet(path))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _load_retail_in_range(raw_dir: Path, start: date, end: date) -> pd.DataFrame:
    """Load and concatenate all retail parquet files in a date range."""
    pairs = _read_parquet_dates(raw_dir, "retail")
    frames = []
    for d, path in pairs:
        if start <= d <= end:
            frames.append(pd.read_parquet(path))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _load_live_in_range(raw_dir: Path, start: date, end: date) -> list[dict]:
    """Load live JSON snapshots in a date range."""
    pairs = _read_json_dates(raw_dir, "live")
    records = []
    for d, path in pairs:
        if start <= d <= end:
            records.append(json.loads(path.read_text()))
    return records


def _direction(values: list[float]) -> str:
    """Classify a numeric series as 'rising', 'falling', or 'flat'."""
    if len(values) < 2:
        return "flat"
    # Simple linear slope using first-last comparison
    first_half = sum(values[: len(values) // 2]) / max(len(values) // 2, 1)
    second_half = sum(values[len(values) // 2 :]) / max(len(values) - len(values) // 2, 1)
    if first_half == 0:
        return "flat"
    pct = (second_half - first_half) / abs(first_half) * 100
    if pct > 2:
        return "rising"
    if pct < -2:
        return "falling"
    return "flat"


def _pearson(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient."""
    n = len(x)
    if n < 3:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    sx = sqrt(sum((v - mx) ** 2 for v in x) / (n - 1))
    sy = sqrt(sum((v - my) ** 2 for v in y) / (n - 1))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x[i] - mx) * (y[i] - my) for i in range(n)) / ((n - 1) * sx * sy)


# ── report generators ──────────────────────────────────────────────────────────


def build_daily_diff(raw_dir: Path, out_dir: Path) -> dict:
    """Compare today's retail plans against the previous scrape. Detect changes >1%.

    Writes daily_diff.json.
    """
    pairs = _read_parquet_dates(raw_dir, "retail")
    if len(pairs) < 2:
        result = {
            "latest_date": pairs[-1][0].isoformat() if pairs else None,
            "previous_date": None,
            "status": "insufficient_data",
            "summary": {"total_plans": 0, "new_count": 0, "removed_count": 0, "changed_count": 0, "returned_count": 0, "unchanged_count": 0, "regulated_tariff_change": None},
            "alerts": [],
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "daily_diff.json").write_text(json.dumps(result))
        return result

    prev_date, prev_path = pairs[-2]
    latest_date, latest_path = pairs[-1]

    prev_df = pd.read_parquet(prev_path)
    latest_df = pd.read_parquet(latest_path)

    prev_keys = {_plan_key(r): r for _, r in prev_df.iterrows()}
    latest_keys = {_plan_key(r): r for _, r in latest_df.iterrows()}

    # Also collect all keys from older files for "returned" detection
    older_keys: set[str] = set()
    for _d, path in pairs[:-2]:
        odf = pd.read_parquet(path)
        older_keys |= {_plan_key(r) for _, r in odf.iterrows()}

    alerts: list[dict] = []
    new_count = removed_count = changed_count = returned_count = unchanged_count = 0

    # Plans in latest but NOT in previous
    for key, row in latest_keys.items():
        if key not in prev_keys:
            if key in older_keys:
                returned_count += 1
                alerts.append(_make_alert(row, "returned", None, _effective_price(row)))
            else:
                new_count += 1
                alerts.append(_make_alert(row, "new", None, _effective_price(row)))

    # Plans in previous but NOT in latest
    for key, row in prev_keys.items():
        if key not in latest_keys:
            removed_count += 1
            alerts.append(_make_alert(row, "removed", _effective_price(row), None))

    # Plans in both — check for price change
    for key, row in latest_keys.items():
        if key not in prev_keys:
            continue
        prev_eff = _effective_price(prev_keys[key])
        latest_eff = _effective_price(row)
        if prev_eff is not None and latest_eff is not None and prev_eff != 0:
            pct = abs(latest_eff - prev_eff) / prev_eff * 100
            if pct > 1.0:
                changed_count += 1
                direction = "up" if latest_eff > prev_eff else "down"
                alerts.append(_make_alert(row, "changed", prev_eff, latest_eff, direction, round(pct, 2)))
            else:
                unchanged_count += 1
        else:
            unchanged_count += 1

    # Regulated tariff change
    prev_tariff = prev_df["regulated_tariff_cents_kwh"].iloc[0] if "regulated_tariff_cents_kwh" in prev_df.columns else None
    latest_tariff = latest_df["regulated_tariff_cents_kwh"].iloc[0] if "regulated_tariff_cents_kwh" in latest_df.columns else None
    tariff_change = None
    if prev_tariff is not None and latest_tariff is not None and prev_tariff != 0:
        pct = round((latest_tariff - prev_tariff) / prev_tariff * 100, 2)
        if abs(pct) > 0.01:
            tariff_change = {"from": round(float(prev_tariff), 2), "to": round(float(latest_tariff), 2), "pct": pct}

    result = {
        "latest_date": latest_date.isoformat(),
        "previous_date": prev_date.isoformat(),
        "status": "ok",
        "summary": {
            "total_plans": len(latest_df),
            "new_count": new_count,
            "removed_count": removed_count,
            "changed_count": changed_count,
            "returned_count": returned_count,
            "unchanged_count": unchanged_count,
            "regulated_tariff_change": tariff_change,
        },
        "alerts": sorted(alerts, key=lambda a: {"changed": 0, "new": 1, "returned": 2, "removed": 3}[a["status"]]),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "daily_diff.json").write_text(json.dumps(result))
    return result


def _make_alert(row, status: str, prev_price: float | None, latest_price: float | None,
                direction: str = "", change_pct: float = 0.0) -> dict:
    alert: dict = {
        "retailer": str(row.get("retailer", "")).strip(),
        "offer_name": str(row.get("offer_name", "")).strip(),
        "offer_type": str(row.get("offer_type", "")),
        "contract_months": row.get("contract_months"),
        "status": status,
    }
    if prev_price is not None:
        alert["previous_price"] = round(prev_price, 2)
    if latest_price is not None:
        alert["latest_price"] = round(latest_price, 2)
    if direction:
        alert["direction"] = direction
    if change_pct:
        alert["change_pct"] = change_pct
    return alert


def build_weekly_brief(raw_dir: Path, out_dir: Path) -> dict:
    """Generate a Monday-morning weekly summary of the past 7 days.

    Writes weekly_brief.json.
    """
    today = date.today()
    week_start = today - timedelta(days=7)
    week_end = today - timedelta(days=1)

    # USEP 7-day trend
    emc_df = _load_emc_in_range(raw_dir, week_start, week_end)
    usep_daily: list[float] = []
    usep_min_day = usep_max_day = None
    if not emc_df.empty and "usep" in emc_df.columns:
        by_date = emc_df.groupby("date")["usep"].mean()
        usep_daily = [float(v) for v in by_date.values]
        if usep_daily:
            usep_min_day = {"date": str(by_date.idxmin()), "value": round(float(by_date.min()), 2)}
            usep_max_day = {"date": str(by_date.idxmax()), "value": round(float(by_date.max()), 2)}
    usep_7day_avg = round(sum(usep_daily) / len(usep_daily), 2) if usep_daily else None
    usep_trend = _direction(usep_daily) if len(usep_daily) >= 2 else "flat"

    # VCP-USEP spread from live snapshots
    live_records = _load_live_in_range(raw_dir, week_start, week_end)
    spreads: list[float] = []
    for r in live_records:
        if r.get("usep") is not None and r.get("vcp") is not None:
            spreads.append(float(r["vcp"]) - float(r["usep"]))
    spread_avg = round(sum(spreads) / len(spreads), 2) if spreads else None
    raw_trend = _direction(spreads) if len(spreads) >= 2 else "flat"
    spread_trend = {"rising": "narrowing", "falling": "widening", "flat": "flat"}[raw_trend]

    # Retail data
    retail_df = _load_retail_in_range(raw_dir, week_start, week_end)
    tariff = None
    cheapest_fr = cheapest_drt = None
    price_changes = 0
    if not retail_df.empty:
        if "regulated_tariff_cents_kwh" in retail_df.columns:
            tariff = round(float(retail_df["regulated_tariff_cents_kwh"].iloc[-1]), 2)
        fr = retail_df[retail_df["offer_type"] == "FR"]
        drt = retail_df[retail_df["offer_type"] == "DRT"]
        if not fr.empty and "price_cents_kwh" in fr.columns:
            best_fr = fr.loc[fr["price_cents_kwh"].idxmin()]
            cheapest_fr = {
                "retailer": str(best_fr["retailer"]).strip(),
                "plan": str(best_fr["offer_name"]).strip(),
                "price": round(float(best_fr["price_cents_kwh"]), 2),
                "contract_months": int(best_fr["contract_months"]) if best_fr.get("contract_months") is not None else None,
            }
        if not drt.empty:
            drt_eff = []
            for _, r in drt.iterrows():
                eff = _effective_price(r)
                if eff is not None:
                    drt_eff.append((eff, r))
            if drt_eff:
                drt_eff.sort()
                best = drt_eff[0][1]
                cheapest_drt = {
                    "retailer": str(best["retailer"]).strip(),
                    "plan": str(best["offer_name"]).strip(),
                    "effective_price": round(drt_eff[0][0], 2),
                    "discount": round(float(best["discounted_price_cents_kwh"]), 2) if best.get("discounted_price_cents_kwh") is not None else None,
                    "contract_months": int(best["contract_months"]) if best.get("contract_months") is not None else None,
                }

    # Recommendation heuristic
    recommendation = _weekly_recommendation(cheapest_fr, cheapest_drt, tariff, usep_trend)

    data_days = len(usep_daily)
    status = "ok" if data_days >= 1 else "insufficient_data"

    result = {
        "generated_at": datetime.now().isoformat(),
        "period": {"from": week_start.isoformat(), "to": week_end.isoformat()},
        "status": status,
        "data_days": data_days,
        "usep": {
            "7day_avg": usep_7day_avg,
            "7day_trend": usep_trend,
            "min_day": usep_min_day,
            "max_day": usep_max_day,
        },
        "vcp_usep_spread": {
            "7day_avg": spread_avg,
            "trend": spread_trend,
        },
        "retail": {
            "regulated_tariff": tariff,
            "cheapest_fr": cheapest_fr,
            "cheapest_drt": cheapest_drt,
            "price_changes_this_week": price_changes,
        },
        "recommendation": recommendation,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "weekly_brief.json").write_text(json.dumps(result))
    return result


def _weekly_recommendation(cheapest_fr, cheapest_drt, tariff, usep_trend: str) -> str:
    """Simple rules-based weekly recommendation."""
    parts: list[str] = []
    if cheapest_drt and cheapest_fr and tariff:
        if cheapest_drt["effective_price"] < cheapest_fr["price"]:
            parts.append("Discount (DRT) plans currently offer the lowest effective rate.")
        else:
            parts.append("Fixed rate plans currently offer the best value below the regulated tariff.")
        if cheapest_fr["price"] < tariff * 0.98:
            parts.append("Retail plans are significantly cheaper than the regulated tariff — consider switching.")
    if usep_trend == "rising":
        parts.append("Wholesale USEP is trending upward — lock in a fixed plan before retail rates adjust.")
    elif usep_trend == "falling":
        parts.append("Wholesale USEP is trending downward — retail rates may fall further. Consider a short-term or DRT plan.")
    if not parts:
        parts.append("Monitor the market. Compare fixed and discount plans against the regulated tariff.")
    return " ".join(parts)


def build_monthly_analytics(raw_dir: Path, out_dir: Path) -> dict:
    """Deep monthly analysis: USEP averages, intraday curve, solar correlation, retail stats.

    Writes monthly_analytics.json.
    """
    today = date.today()
    # Use the most recent complete calendar month (or current month if we're past mid-month)
    if today.day < 15:
        # Use previous month
        if today.month == 1:
            month_start = date(today.year - 1, 12, 1)
            month_end = date(today.year - 1, 12, 31)
        else:
            month_start = date(today.year, today.month - 1, 1)
            month_end = date(today.year, today.month, 1) - timedelta(days=1)
    else:
        month_start = date(today.year, today.month, 1)
        month_end = today - timedelta(days=1)

    month_label = month_start.strftime("%Y-%m")

    emc_df = _load_emc_in_range(raw_dir, month_start, month_end)
    if emc_df.empty or "usep" not in emc_df.columns or len(emc_df) < 48:  # need at least 1 full day
        result = {
            "month": month_label,
            "status": "insufficient_data",
            "data_days": len(emc_df["date"].unique()) if not emc_df.empty else 0,
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "monthly_analytics.json").write_text(json.dumps(result))
        return result

    data_days = len(emc_df["date"].unique())

    # USEP stats
    usep_vals = [float(v) for v in emc_df["usep"].dropna()]
    usep_stats = {
        "monthly_avg": round(sum(usep_vals) / len(usep_vals), 2),
        "monthly_min": round(float(emc_df["usep"].min()), 2),
        "monthly_max": round(float(emc_df["usep"].max()), 2),
        "monthly_stdev": round(float(emc_df["usep"].std()), 2),
    }

    # Intraday curve (4 blocks)
    emc = emc_df.copy()
    emc["hour"] = emc["period"].apply(lambda p: int(str(p).split(":")[0]))
    intraday = {}
    for label, (lo, hi) in [("night", (0, 6)), ("morning", (6, 12)), ("afternoon", (12, 18)), ("evening", (18, 24))]:
        mask = emc["hour"].between(lo, hi - 1)
        intraday[label] = round(float(emc.loc[mask, "usep"].mean()), 2) if mask.any() else None

    # Solar correlation
    solar_corr = 0.0
    if "solar_mw" in emc_df.columns and len(emc_df) >= 10:
        s = [float(v) for v in emc_df["solar_mw"].dropna()]
        u = [float(v) for v in emc_df.loc[emc_df["solar_mw"].notna(), "usep"]]
        if len(s) == len(u) and len(s) >= 10:
            solar_corr = round(_pearson(s, u), 2)

    # Demand stats
    demand_stats = {}
    if "demand_mw" in emc_df.columns:
        demand_stats = {
            "average_peak": round(float(emc_df.groupby("date")["demand_mw"].max().mean()), 1),
            "average_trough": round(float(emc_df.groupby("date")["demand_mw"].min().mean()), 1),
        }

    # Retail stats for the month
    retail_df = _load_retail_in_range(raw_dir, month_start, month_end)
    retail_stats = {}
    if not retail_df.empty:
        tariff = round(float(retail_df["regulated_tariff_cents_kwh"].iloc[-1]), 2) if "regulated_tariff_cents_kwh" in retail_df.columns else None
        retail_stats["regulated_tariff"] = tariff
        retail_stats["avg_daily_plans"] = round(len(retail_df) / max(data_days, 1), 1)

        # Cheapest FR/DRT range
        fr = retail_df[retail_df["offer_type"] == "FR"]
        drt = retail_df[retail_df["offer_type"] == "DRT"]
        if not fr.empty and "price_cents_kwh" in fr.columns:
            retail_stats["cheapest_fr_range"] = {"min": round(float(fr["price_cents_kwh"].min()), 2), "max": round(float(fr["price_cents_kwh"].max()), 2)}
        if not drt.empty:
            drt_prices = []
            for _, r in drt.iterrows():
                eff = _effective_price(r)
                if eff is not None:
                    drt_prices.append(eff)
            if drt_prices:
                retail_stats["cheapest_drt_range"] = {"min": round(min(drt_prices), 2), "max": round(max(drt_prices), 2)}

        # Wholesale-retail spread
        if "cheapest_fr_range" in retail_stats:
            spread = retail_stats["cheapest_fr_range"]["min"] - (usep_stats["monthly_avg"] / 10)
            retail_stats["wholesale_retail_spread"] = round(spread, 2)

    result = {
        "month": month_label,
        "status": "ok",
        "data_days": data_days,
        "usep": usep_stats,
        "intraday": intraday,
        "solar_price_correlation": solar_corr,
        "demand": demand_stats,
        "retail": retail_stats,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "monthly_analytics.json").write_text(json.dumps(result))
    return result


def build_quarterly_prediction(raw_dir: Path, out_dir: Path) -> dict:
    """Predict next quarter's regulated tariff direction based on USEP trends.

    Always produces output, even with zero data. Uses structural knowledge
    about Singapore's electricity market.

    Writes quarterly_prediction.json.
    """
    today = date.today()
    # Determine current quarter
    q = (today.month - 1) // 3 + 1  # 1=Q1, 2=Q2, 3=Q3, 4=Q4
    current_q = f"{today.year}-Q{q}"
    q_start = date(today.year, (q - 1) * 3 + 1, 1)
    # Next quarter
    if q == 4:
        next_q = f"{today.year + 1}-Q1"
    else:
        next_q = f"{today.year}-Q{q + 1}"

    # Load current tariff (from latest retail data, or any available source)
    current_tariff = None
    retail_pairs = _read_parquet_dates(raw_dir, "retail")
    if retail_pairs:
        try:
            latest_retail = pd.read_parquet(retail_pairs[-1][1])
            if "regulated_tariff_cents_kwh" in latest_retail.columns:
                current_tariff = round(float(latest_retail["regulated_tariff_cents_kwh"].iloc[0]), 2)
        except Exception:
            pass

    # Load USEP data for the current quarter
    emc_df = _load_emc_in_range(raw_dir, q_start, today - timedelta(days=1))
    usep_daily: list[float] = []
    if not emc_df.empty and "usep" in emc_df.columns:
        usep_daily = [float(v) for v in emc_df.groupby("date")["usep"].mean().values]

    quarterly_avg = round(sum(usep_daily) / len(usep_daily), 2) if usep_daily else None
    usep_trend = _direction(usep_daily)

    # Build factor analysis
    factors = _build_factors(usep_daily, usep_trend, today)

    # Generate prediction
    prediction = _build_prediction(usep_daily, current_tariff, factors)

    result = {
        "generated_at": datetime.now().isoformat(),
        "current_quarter": current_q,
        "next_quarter": next_q,
        "status": "ok" if len(usep_daily) >= 1 else "insufficient_data",
        "current_tariff": current_tariff,
        "usep_trend": {
            "direction": usep_trend,
            "quarterly_avg": quarterly_avg,
            "data_points": len(usep_daily),
        },
        "factors": factors,
        "prediction": prediction,
        "recommendation": _quarterly_recommendation(prediction),
        "disclaimer": "This is a directional estimate based on public wholesale electricity price patterns. "
                       "The actual regulated tariff is set quarterly by SP Group under EMA guidelines "
                       "and depends on natural gas prices, carbon tax, and grid costs.",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "quarterly_prediction.json").write_text(json.dumps(result))
    return result


def _build_factors(usep_daily: list[float], usep_trend: str, today: date) -> list[dict]:
    """Assemble known structural factors affecting the tariff."""
    factors: list[dict] = []

    # USEP trend factor
    if usep_daily:
        if usep_trend == "rising":
            factors.append({"name": "USEP wholesale trend", "impact": "upward", "weight": "high",
                            "note": f"USEP has been trending upward over {len(usep_daily)} observed days, suggesting higher fuel costs will feed into the tariff."})
        elif usep_trend == "falling":
            factors.append({"name": "USEP wholesale trend", "impact": "downward", "weight": "high",
                            "note": f"USEP has been trending downward over {len(usep_daily)} observed days, suggesting fuel cost relief."})
        else:
            factors.append({"name": "USEP wholesale trend", "impact": "neutral", "weight": "medium",
                            "note": f"USEP has been relatively flat over {len(usep_daily)} observed days."})
    else:
        factors.append({"name": "USEP wholesale trend", "impact": "unknown", "weight": "high",
                        "note": "Insufficient USEP data collected. This tracker needs more EMC data to establish a trend."})

    # Carbon tax factor
    year = today.year
    if year >= 2026:
        carbon_note = "Carbon tax at S$45/tCO2e (2026-2027). Already priced into current tariff — no additional impact this quarter."
    elif year >= 2024:
        carbon_note = "Carbon tax at S$25/tCO2e (2024-2025)."
    else:
        carbon_note = "Carbon tax at S$5/tCO2e."
    factors.append({"name": "Carbon tax", "impact": "neutral", "weight": "medium", "note": carbon_note})

    # Strait of Hormuz / geopolitical context (2026 specific)
    if today.year == 2026 and today.month >= 3:
        factors.append({"name": "Geopolitical: Hormuz blockade", "impact": "upward", "weight": "high",
                        "note": "The Strait of Hormuz blockade (from Feb 2026) has pushed up global LNG and oil prices. "
                               "Fuel costs rose sharply in March-May 2026, which will feed into the Q3 tariff review."})

    # Tariff lag mechanics
    factors.append({"name": "Fuel cost pass-through lag", "impact": "neutral", "weight": "low",
                    "note": "The energy cost component uses a ~2.5-month lagged fuel price window. "
                           "Recent fuel price moves take 1-2 quarters to fully reflect in the tariff."})

    return factors


def _build_prediction(usep_daily: list[float], current_tariff: float | None,
                      factors: list[dict]) -> dict:
    """Generate a directional prediction with a price range."""
    # Count factor impacts
    upward = sum(1 for f in factors if f["impact"] == "upward" and f["weight"] == "high")
    downward = sum(1 for f in factors if f["impact"] == "downward" and f["weight"] == "high")

    if upward > downward:
        direction = "increase"
        confidence = "medium" if usep_daily else "low"
    elif downward > upward:
        direction = "decrease"
        confidence = "medium" if usep_daily else "low"
    else:
        direction = "flat"
        confidence = "low"

    # Estimate range
    if current_tariff and direction != "flat":
        if direction == "increase":
            low = round(current_tariff * 1.01, 2)
            high = round(current_tariff * 1.06, 2)
        else:
            low = round(current_tariff * 0.96, 2)
            high = round(current_tariff * 0.99, 2)
        reasoning = _prediction_reasoning(direction, factors)
    elif current_tariff:
        low = round(current_tariff * 0.99, 2)
        high = round(current_tariff * 1.01, 2)
        reasoning = "Insufficient directional signals. Expect the tariff to stay within ~1% of current levels."
    else:
        low = high = None
        reasoning = "No current tariff data available for estimation."

    return {"direction": direction, "range": {"low": low, "high": high}, "confidence": confidence, "reasoning": reasoning}


def _prediction_reasoning(direction: str, factors: list[dict]) -> str:
    """Generate human-readable reasoning from factor analysis."""
    high_factors = [f for f in factors if f["weight"] == "high" and f["impact"] in ("upward", "downward")]
    names = [f["name"] for f in high_factors]
    if direction == "increase":
        return f"Upward pressure from: {', '.join(names)}. The tariff is likely to rise."
    else:
        return f"Downward pressure from: {', '.join(names)}. The tariff is likely to decrease."


def _quarterly_recommendation(prediction: dict) -> str:
    """Generate a consumer recommendation based on the prediction."""
    direction = prediction["direction"]
    if direction == "increase":
        return "Lock in a fixed-rate plan now before the tariff and retail prices rise. " \
               "Current FR plans are already below the regulated tariff — this advantage will shrink."
    elif direction == "decrease":
        return "Consider waiting or using a discount-off-tariff (DRT) plan. " \
               "If tariffs fall, your DRT rate falls with them. Fixed-rate plans may also become cheaper."
    else:
        return "No strong directional signal. Compare fixed-rate and DRT plans against the regulated tariff. " \
               "Either is reasonable — focus on the absolute rate and contract terms."


def build_all_reports(raw_dir: Path, out_dir: Path) -> dict:
    """Run all report generators. Each is wrapped so one failure doesn't block others.

    Mirrors exporter.build_all() pattern.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    statuses: dict[str, str] = {}

    for name, fn in [("daily_diff", build_daily_diff), ("weekly_brief", build_weekly_brief),
                     ("monthly_analytics", build_monthly_analytics), ("quarterly_prediction", build_quarterly_prediction)]:
        try:
            result = fn(raw_dir, out_dir)
            statuses[name] = result.get("status", "unknown")
        except Exception as e:
            statuses[name] = f"error: {e}"

    return statuses
