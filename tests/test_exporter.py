"""Tests for oem_tracker.exporter."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from oem_tracker.exporter import (
    build_all,
    export_emc,
    export_emc_daily_summary,
    export_live,
    export_retail,
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


# ── export_emc ────────────────────────────────────────────────────────────────

class TestExportEmc:
    def test_single_date(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_emc_parquet(raw, "2026-06-13", [
            {"period": "00:00-00:30", "usep": 175.0, "demand_mw": 6000.0, "solar_mw": 0.0},
            {"period": "00:30-01:00", "usep": 176.0, "demand_mw": 6100.0, "solar_mw": 0.0},
        ])
        dates = export_emc(raw, out)
        assert dates == ["2026-06-13"]
        data = json.loads((out / "emc" / "2026-06-13.json").read_text())
        assert len(data) == 2
        assert data[0]["usep"] == 175.0

    def test_web_json_uses_iso_date(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_emc_parquet(raw, "2026-06-13", [
            {"period": "00:00-00:30", "usep": 100.0, "demand_mw": 5000.0, "solar_mw": 0.0},
        ])
        export_emc(raw, out)
        assert (out / "emc" / "2026-06-13.json").exists()
        assert not (out / "emc" / "20260613.json").exists()

    def test_multiple_dates_sorted(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_emc_parquet(raw, "2026-06-10", [{"period": "00:00-00:30", "usep": 100.0, "demand_mw": 5000.0, "solar_mw": 0.0}])
        _write_emc_parquet(raw, "2026-06-13", [{"period": "00:00-00:30", "usep": 200.0, "demand_mw": 6000.0, "solar_mw": 0.0}])
        assert export_emc(raw, out) == ["2026-06-10", "2026-06-13"]

    def test_no_files(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        assert export_emc(raw, out) == []


# ── export_emc_daily_summary ─────────────────────────────────────────────────

class TestExportEmcDailySummary:
    def test_single_date(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_emc_parquet(raw, "2026-06-13", [
            {"period": "00:00-00:30", "usep": 100.0, "demand_mw": 5000.0, "solar_mw": 0.0},
            {"period": "00:30-01:00", "usep": 200.0, "demand_mw": 6000.0, "solar_mw": 50.0},
        ])
        rows = export_emc_daily_summary(raw, out)
        assert len(rows) == 1
        r = rows[0]
        assert r["date"] == "2026-06-13"
        assert r["usep_avg"] == 150.0
        assert r["usep_min"] == 100.0
        assert r["usep_max"] == 200.0
        assert r["demand_peak"] == 6000.0
        assert r["solar_peak"] == 50.0

    def test_multiple_dates(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_emc_parquet(raw, "2026-06-10", [
            {"period": "00:00-00:30", "usep": 100.0, "demand_mw": 5000.0, "solar_mw": 0.0},
        ])
        _write_emc_parquet(raw, "2026-06-11", [
            {"period": "00:00-00:30", "usep": 200.0, "demand_mw": 6000.0, "solar_mw": 100.0},
        ])
        rows = export_emc_daily_summary(raw, out)
        assert len(rows) == 2
        assert rows[0]["date"] == "2026-06-10"
        assert rows[1]["date"] == "2026-06-11"

    def test_no_files(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        assert export_emc_daily_summary(raw, out) == []


# ── export_live ───────────────────────────────────────────────────────────────

class TestExportLive:
    def test_aggregates_all_snapshots(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_live_json(raw, "2026-06-10", {"usep": 100.0, "fetched_at": "t1"})
        _write_live_json(raw, "2026-06-11", {"usep": 200.0, "fetched_at": "t2"})
        assert export_live(raw, out) == 2
        data = json.loads((out / "live.json").read_text())
        assert len(data) == 2
        assert data[0]["usep"] == 100.0

    def test_no_files_writes_empty(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        assert export_live(raw, out) == 0
        data = json.loads((out / "live.json").read_text())
        assert data == []


# ── export_retail ─────────────────────────────────────────────────────────────

class TestExportRetail:
    def test_latest_and_history(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_retail_parquet(raw, "2026-06-10", [
            {"scraped_date": "2026-06-10", "retailer": "A", "offer_name": "Plan A",
             "offer_type": "FR", "price_cents_kwh": 28.5, "discounted_price_cents_kwh": None,
             "estimated_monthly_sgd": 100.0, "contract_months": 24, "regulated_tariff_cents_kwh": 30.0},
            {"scraped_date": "2026-06-10", "retailer": "B", "offer_name": "Plan B",
             "offer_type": "DRT", "price_cents_kwh": None, "discounted_price_cents_kwh": 2.0,
             "estimated_monthly_sgd": 95.0, "contract_months": 12, "regulated_tariff_cents_kwh": 30.0},
        ])
        info = export_retail(raw, out)
        assert info["plan_count"] == 2
        assert info["latest_date"] == "2026-06-10"

        latest = json.loads((out / "retail_latest.json").read_text())
        assert len(latest) == 2

        history = json.loads((out / "retail_history.json").read_text())
        assert len(history) == 1
        h = history[0]
        assert h["date"] == "2026-06-10"
        assert h["cheapest_fr"] == 28.5
        assert h["cheapest_drt"] == 28.0  # 30.0 tariff - 2.0 discount

    def test_no_files(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        info = export_retail(raw, out)
        assert info["plan_count"] == 0
        assert info["latest_date"] is None
        assert json.loads((out / "retail_latest.json").read_text()) == []

    def test_history_multiple_dates(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_retail_parquet(raw, "2026-06-10", [
            {"scraped_date": "2026-06-10", "retailer": "A", "offer_name": "P1",
             "offer_type": "FR", "price_cents_kwh": 28.0, "discounted_price_cents_kwh": None,
             "estimated_monthly_sgd": 100.0, "contract_months": 24, "regulated_tariff_cents_kwh": 30.0},
        ])
        _write_retail_parquet(raw, "2026-06-11", [
            {"scraped_date": "2026-06-11", "retailer": "A", "offer_name": "P1",
             "offer_type": "FR", "price_cents_kwh": 27.0, "discounted_price_cents_kwh": None,
             "estimated_monthly_sgd": 99.0, "contract_months": 24, "regulated_tariff_cents_kwh": 29.5},
        ])
        info = export_retail(raw, out)
        assert info["history_dates"] == 2
        assert info["latest_date"] == "2026-06-11"

        history = json.loads((out / "retail_history.json").read_text())
        assert history[0]["cheapest_fr"] == 28.0
        assert history[1]["cheapest_fr"] == 27.0
        assert history[1]["regulated_tariff"] == 29.5


# ── build_all ─────────────────────────────────────────────────────────────────

class TestBuildAll:
    def test_creates_manifest(self, tmp_path: Path):
        raw, out = _diri(tmp_path / "raw"), _diri(tmp_path / "out")
        _write_emc_parquet(raw, "2026-06-13", [
            {"period": "00:00-00:30", "usep": 100.0, "demand_mw": 5000.0, "solar_mw": 0.0},
        ])
        _write_live_json(raw, "2026-06-13", {"usep": 100.0, "fetched_at": "t1"})

        manifest = build_all(raw, out)
        assert manifest["emc"]["dates"] == ["2026-06-13"]
        assert manifest["live"]["count"] == 1
        assert "retail" in manifest
        assert (out / "manifest.json").exists()
