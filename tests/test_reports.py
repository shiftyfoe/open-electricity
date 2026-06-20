"""Tests for oem_tracker.reports."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from oem_tracker.reports import (
    build_all_reports,
    build_daily_diff,
    build_monthly_analytics,
    build_quarterly_prediction,
    build_weekly_brief,
)


def _diri(path: Path) -> Path:
    """Ensure path exists as a directory and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_emc_parquet(raw: Path, datestr: str, rows: list[dict]) -> None:
    src = _diri(raw / "emc")
    stem = datestr.replace("-", "")
    pd.DataFrame(rows).to_parquet(src / f"{stem}.parquet", index=False)


def _write_retail_parquet(raw: Path, datestr: str, rows: list[dict]) -> None:
    src = _diri(raw / "retail")
    stem = datestr.replace("-", "")
    pd.DataFrame(rows).to_parquet(src / f"{stem}.parquet", index=False)


def _write_live_json(raw: Path, datestr: str, record: dict) -> None:
    src = _diri(raw / "live")
    stem = datestr.replace("-", "")
    (src / f"{stem}.json").write_text(json.dumps(record))


def _retail_row(retailer="A", offer_name="Plan1", offer_type="FR",
                price_cents_kwh=28.0, discounted_price_cents_kwh=None,
                estimated_monthly_sgd=100.0, contract_months=24,
                regulated_tariff_cents_kwh=30.0) -> dict:
    return {
        "scraped_date": None,  # will be set per-file
        "retailer": retailer,
        "offer_name": offer_name,
        "offer_type": offer_type,
        "price_cents_kwh": price_cents_kwh,
        "discounted_price_cents_kwh": discounted_price_cents_kwh,
        "estimated_monthly_sgd": estimated_monthly_sgd,
        "contract_months": contract_months,
        "regulated_tariff_cents_kwh": regulated_tariff_cents_kwh,
    }


def _emc_row(period="00:00-00:30", usep=170.0, demand_mw=6000.0,
              solar_mw=0.0, date_val="2026-06-13") -> dict:
    return {"period": period, "date": date_val,
            "usep": usep, "demand_mw": demand_mw, "solar_mw": solar_mw}


# ── build_daily_diff ────────────────────────────────────────────────────────────


class TestDailyDiff:
    def test_two_dates_detects_changes(self, tmp_path: Path):
        """Plan price changed >1% between two scrapes."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_retail_parquet(raw, "2026-06-19", [
            _retail_row(price_cents_kwh=28.00, offer_name="Plan A"),
        ])
        _write_retail_parquet(raw, "2026-06-20", [
            _retail_row(price_cents_kwh=28.50, offer_name="Plan A"),
        ])
        result = build_daily_diff(raw, out)
        assert result["status"] == "ok"
        assert result["summary"]["changed_count"] == 1
        assert result["alerts"][0]["status"] == "changed"
        assert result["alerts"][0]["change_pct"] >= 1.0

    def test_single_date_insufficient(self, tmp_path: Path):
        """Only one retail file — not enough for diff."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_retail_parquet(raw, "2026-06-20", [_retail_row()])
        result = build_daily_diff(raw, out)
        assert result["status"] == "insufficient_data"
        assert result["alerts"] == []

    def test_new_and_removed_plans(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_retail_parquet(raw, "2026-06-19", [
            _retail_row(offer_name="Plan A"),
        ])
        _write_retail_parquet(raw, "2026-06-20", [
            _retail_row(offer_name="Plan B"),
        ])
        result = build_daily_diff(raw, out)
        assert result["summary"]["new_count"] == 1
        assert result["summary"]["removed_count"] == 1
        alerts = {(a["status"], a["offer_name"]) for a in result["alerts"]}
        assert ("new", "Plan B") in alerts
        assert ("removed", "Plan A") in alerts

    def test_returned_plan(self, tmp_path: Path):
        """Plan appears, disappears, then reappears."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_retail_parquet(raw, "2026-06-17", [_retail_row(offer_name="Plan A")])
        _write_retail_parquet(raw, "2026-06-18", [_retail_row(offer_name="Plan B")])
        _write_retail_parquet(raw, "2026-06-19", [_retail_row(offer_name="Plan A")])
        result = build_daily_diff(raw, out)
        assert result["summary"]["returned_count"] == 1
        assert result["summary"]["removed_count"] == 1  # Plan B removed
        returned = [a for a in result["alerts"] if a["status"] == "returned"]
        assert len(returned) == 1
        assert returned[0]["offer_name"] == "Plan A"

    def test_unchanged_plans(self, tmp_path: Path):
        """Same price in both dates — no alert."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_retail_parquet(raw, "2026-06-19", [_retail_row(price_cents_kwh=28.30)])
        _write_retail_parquet(raw, "2026-06-20", [_retail_row(price_cents_kwh=28.30)])
        result = build_daily_diff(raw, out)
        assert result["summary"]["changed_count"] == 0
        assert result["summary"]["unchanged_count"] == 1

    def test_no_files(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        result = build_daily_diff(raw, out)
        assert result["status"] == "insufficient_data"
        assert result["latest_date"] is None

    def test_drt_effective_price_change_detected(self, tmp_path: Path):
        """DRT plans compare effective (tariff - discount) prices."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        # Day 1: DRT with 1.50 discount off 30.0 = 28.50 effective
        _write_retail_parquet(raw, "2026-06-19", [
            _retail_row(offer_type="DRT", price_cents_kwh=None,
                        discounted_price_cents_kwh=1.50, regulated_tariff_cents_kwh=30.00),
        ])
        # Day 2: DRT with 1.00 discount off 30.0 = 29.00 effective (>1% change)
        _write_retail_parquet(raw, "2026-06-20", [
            _retail_row(offer_type="DRT", price_cents_kwh=None,
                        discounted_price_cents_kwh=1.00, regulated_tariff_cents_kwh=30.00),
        ])
        result = build_daily_diff(raw, out)
        assert result["summary"]["changed_count"] == 1
        assert result["alerts"][0]["direction"] == "up"  # effective price went up

    def test_tariff_change_detected(self, tmp_path: Path):
        """Regulated tariff changed between scrapes."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_retail_parquet(raw, "2026-06-19", [
            _retail_row(regulated_tariff_cents_kwh=30.00),
        ])
        _write_retail_parquet(raw, "2026-06-20", [
            _retail_row(regulated_tariff_cents_kwh=31.00),
        ])
        result = build_daily_diff(raw, out)
        tc = result["summary"]["regulated_tariff_change"]
        assert tc is not None
        assert tc["from"] == 30.00
        assert tc["to"] == 31.00

    def test_output_file_written(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_retail_parquet(raw, "2026-06-19", [_retail_row()])
        _write_retail_parquet(raw, "2026-06-20", [_retail_row()])
        build_daily_diff(raw, out)
        data = json.loads((out / "daily_diff.json").read_text())
        assert data["status"] == "ok"


# ── build_weekly_brief ──────────────────────────────────────────────────────────


class TestWeeklyBrief:
    def test_full_week_data(self, tmp_path: Path):
        """7 days of EMC, live, and retail data."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        today = date.today()
        for i in range(8, 1, -1):
            d = (today - timedelta(days=i)).isoformat()
            _write_emc_parquet(raw, d, [_emc_row(date_val=d, usep=160.0 + i * 5.0)])
            _write_live_json(raw, d, {"usep": 160.0 + i * 5.0, "vcp": 185.0, "demand_mw": 7000.0, "fetched_at": d})
            _write_retail_parquet(raw, d, [_retail_row(price_cents_kwh=28.0, regulated_tariff_cents_kwh=30.0)])
        result = build_weekly_brief(raw, out)
        assert result["status"] == "ok"
        assert result["data_days"] >= 1
        assert result["usep"]["7day_trend"] in ("rising", "falling", "flat")
        assert result["vcp_usep_spread"]["trend"] in ("widening", "narrowing", "flat")
        assert "recommendation" in result

    def test_insufficient_days(self, tmp_path: Path):
        """Only 2 days of data — still produces a report."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        today = date.today()
        _write_emc_parquet(raw, (today - timedelta(days=2)).isoformat(),
                           [_emc_row(date_val=(today - timedelta(days=2)).isoformat())])
        result = build_weekly_brief(raw, out)
        assert result["status"] == "ok"  # still ok — just flagged with low data_days
        assert result["data_days"] <= 2

    def test_no_data(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        result = build_weekly_brief(raw, out)
        assert result["status"] == "insufficient_data"

    def test_falling_usep_trend(self, tmp_path: Path):
        """USEP that clearly falls across 7 days."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        today = date.today()
        for i in range(8, 1, -1):
            d = (today - timedelta(days=i)).isoformat()
            usep = 100.0 + i * 12.0  # i=8→196(oldest), i=2→124(newest) = falling
            _write_emc_parquet(raw, d, [_emc_row(date_val=d, usep=usep)])
        result = build_weekly_brief(raw, out)
        assert result["usep"]["7day_trend"] == "falling"

    def test_output_file_written(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        today = date.today()
        _write_emc_parquet(raw, (today - timedelta(days=2)).isoformat(),
                           [_emc_row(date_val=(today - timedelta(days=2)).isoformat())])
        build_weekly_brief(raw, out)
        data = json.loads((out / "weekly_brief.json").read_text())
        assert "period" in data
        assert "recommendation" in data


# ── build_monthly_analytics ─────────────────────────────────────────────────────


class TestMonthlyAnalytics:
    def test_single_day_data(self, tmp_path: Path):
        """Single day in a month — reports 'insufficient_data' (needs 48+ periods)."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_emc_parquet(raw, "2026-06-13", [
            _emc_row(period="00:00-00:30", usep=170.0),
            _emc_row(period="00:30-01:00", usep=175.0),
        ])
        result = build_monthly_analytics(raw, out)
        assert result["month"] == "2026-06"
        assert result["status"] == "insufficient_data"

    def test_full_month_of_data(self, tmp_path: Path):
        """Enough data (48+ periods) in one month."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        # Generate 48 half-hour periods for one day (enough for 1 full day)
        rows = []
        for h in range(24):
            for m in (0, 30):
                period = f"{h:02d}:{m:02d}-{h:02d}:{m+30:02d}" if m == 0 else f"{h:02d}:30-{(h+1)%24:02d}:00"
                # Simulate solar: 0 at night, peaks at 13:00
                solar = max(0, 1000 - abs(h - 13) * 150)
                usep = 180.0 - solar * 0.03  # solar depresses USEP
                rows.append(_emc_row(period=period, usep=usep, solar_mw=float(solar),
                                     date_val="2026-06-13"))
        _write_emc_parquet(raw, "2026-06-13", rows)
        _write_retail_parquet(raw, "2026-06-13", [_retail_row()])
        result = build_monthly_analytics(raw, out)
        assert result["status"] == "ok"
        assert result["data_days"] == 1
        assert result["usep"]["monthly_avg"] > 0
        assert result["solar_price_correlation"] < 0  # negative: more solar → lower USEP
        assert "night" in result["intraday"]
        assert "evening" in result["intraday"]

    def test_no_files(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        result = build_monthly_analytics(raw, out)
        assert result["status"] == "insufficient_data"

    def test_output_file_written(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_emc_parquet(raw, "2026-06-13", [
            _emc_row(period=f"{h:02d}:00-{h:02d}:30", usep=170.0)
            for h in range(24)
        ] + [
            _emc_row(period=f"{h:02d}:30-{(h+1)%24:02d}:00", usep=170.0)
            for h in range(24)
        ])
        build_monthly_analytics(raw, out)
        data = json.loads((out / "monthly_analytics.json").read_text())
        assert data["month"] == "2026-06"


# ── build_quarterly_prediction ──────────────────────────────────────────────────


class TestQuarterlyPrediction:
    def test_with_data_predicts_direction(self, tmp_path: Path):
        """With EMC data, should produce a directional prediction."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        today = date.today()
        # Write retail data for current tariff
        _write_retail_parquet(raw, today.isoformat(),
                              [_retail_row(regulated_tariff_cents_kwh=29.72)])
        # Write some EMC data in current quarter
        q_start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
        for i in range(5):
            d = (q_start + timedelta(days=i * 7))
            if d < today:
                _write_emc_parquet(raw, d.isoformat(),
                                   [_emc_row(date_val=d.isoformat(), usep=170.0 + i * 5.0)])
        result = build_quarterly_prediction(raw, out)
        assert result["status"] == "ok"
        assert "current_tariff" in result
        assert result["prediction"]["direction"] in ("increase", "decrease", "flat")
        assert "factors" in result
        assert len(result["factors"]) >= 2  # at least USEP trend + carbon tax

    def test_no_data_still_works(self, tmp_path: Path):
        """Even with zero data, prediction returns a framework with factors."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        result = build_quarterly_prediction(raw, out)
        assert result["status"] == "insufficient_data"
        assert "factors" in result
        assert len(result["factors"]) >= 2
        assert "prediction" in result
        assert "recommendation" in result
        assert "disclaimer" in result

    def test_factors_include_carbon_tax(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        result = build_quarterly_prediction(raw, out)
        carbon = [f for f in result["factors"] if "carbon" in f["name"].lower()]
        assert len(carbon) == 1

    def test_output_file_written(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        build_quarterly_prediction(raw, out)
        data = json.loads((out / "quarterly_prediction.json").read_text())
        assert "current_quarter" in data
        assert "next_quarter" in data

    def test_quarter_label_correct(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        result = build_quarterly_prediction(raw, out)
        today = date.today()
        expected_q = (today.month - 1) // 3 + 1
        assert result["current_quarter"] == f"{today.year}-Q{expected_q}"


# ── build_all_reports ────────────────────────────────────────────────────────────


class TestBuildAllReports:
    def test_all_reports_generated(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        # Add minimum data: 2 retail files for diff, 1 EMC for others
        _write_retail_parquet(raw, "2026-06-19", [_retail_row(price_cents_kwh=28.0)])
        _write_retail_parquet(raw, "2026-06-20", [_retail_row(price_cents_kwh=28.0)])
        _write_emc_parquet(raw, "2026-06-13", [
            _emc_row(period=f"{h:02d}:00-{h:02d}:30", usep=170.0)
            for h in range(24)
        ] + [
            _emc_row(period=f"{h:02d}:30-{(h+1)%24:02d}:00", usep=170.0)
            for h in range(24)
        ])
        _write_live_json(raw, "2026-06-13", {"usep": 170.0, "vcp": 195.0, "demand_mw": 7000.0, "fetched_at": "test"})

        statuses = build_all_reports(raw, out)
        assert "daily_diff" in statuses
        assert "weekly_brief" in statuses
        assert "monthly_analytics" in statuses
        assert "quarterly_prediction" in statuses
        # All should be "ok" since we have sufficient data
        assert all(v == "ok" for v in statuses.values())

    def test_result_dict_keys(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        statuses = build_all_reports(raw, out)
        assert set(statuses.keys()) == {"daily_diff", "weekly_brief", "monthly_analytics", "quarterly_prediction"}

    def test_all_json_files_written(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_retail_parquet(raw, "2026-06-19", [_retail_row()])
        _write_retail_parquet(raw, "2026-06-20", [_retail_row()])
        _write_emc_parquet(raw, "2026-06-13", [
            _emc_row(period=f"{h:02d}:00-{h:02d}:30") for h in range(24)
        ] + [
            _emc_row(period=f"{h:02d}:30-{(h+1)%24:02d}:00") for h in range(24)
        ])
        build_all_reports(raw, out)
        for name in ("daily_diff", "weekly_brief", "monthly_analytics", "quarterly_prediction"):
            assert (out / f"{name}.json").exists(), f"Missing {name}.json"

    def test_one_failure_doesnt_block_others(self, tmp_path: Path, monkeypatch):
        """If one report raises, the others still succeed."""
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_retail_parquet(raw, "2026-06-19", [_retail_row()])
        _write_retail_parquet(raw, "2026-06-20", [_retail_row()])
        _write_emc_parquet(raw, "2026-06-13", [
            _emc_row(period=f"{h:02d}:00-{h:02d}:30") for h in range(24)
        ] + [
            _emc_row(period=f"{h:02d}:30-{(h+1)%24:02d}:00") for h in range(24)
        ])

        # Make daily_diff crash by corrupting one file
        import oem_tracker.reports as rpt
        original = rpt.build_daily_diff

        def crash(*args, **kwargs):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(rpt, "build_daily_diff", crash)
        statuses = build_all_reports(raw, out)
        assert "error" in statuses["daily_diff"]
        assert statuses["weekly_brief"] == "ok"
        assert statuses["monthly_analytics"] == "ok"
        assert statuses["quarterly_prediction"] == "ok"
