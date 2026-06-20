"""Tests for oem_tracker.analytics — price, demand, trend summaries."""

from __future__ import annotations

import pandas as pd
import pytest

from oem_tracker.analytics import (
    demand_summary,
    monthly_trend,
    price_summary,
    vcp_vs_usep,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def emc_df() -> pd.DataFrame:
    """Two days of half-hourly EMC data."""
    return pd.DataFrame({
        "date": ["2026-06-10"] * 4 + ["2026-06-11"] * 4,
        "period": [
            "00:00-00:30", "00:30-01:00", "01:00-01:30", "01:30-02:00",
            "00:00-00:30", "00:30-01:00", "01:00-01:30", "01:30-02:00",
        ],
        "usep": [100, 110, 105, 95, 120, 130, 125, 115],
        "demand_mw": [6000, 6100, 6050, 5950, 6200, 6300, 6250, 6150],
        "solar_mw": [0, 0, 0, 0, 50, 60, 55, 45],
    })


# ── price_summary ─────────────────────────────────────────────────────────────

class TestPriceSummary:
    def test_basic_stats(self, emc_df: pd.DataFrame):
        result = price_summary(emc_df)
        assert len(result) == 2
        assert list(result.columns) == ["date", "mean", "p5", "p95", "min", "max", "std"]

        # Day 1
        row0 = result[result["date"] == "2026-06-10"].iloc[0]
        assert row0["min"] == 95.0
        assert row0["max"] == 110.0
        assert 100 < row0["mean"] < 105

        # Day 2
        row1 = result[result["date"] == "2026-06-11"].iloc[0]
        assert row1["min"] == 115.0
        assert row1["max"] == 130.0

    def test_empty_df_returns_empty(self):
        result = price_summary(pd.DataFrame())
        assert result.empty

    def test_no_usep_column_returns_empty(self):
        df = pd.DataFrame({"date": ["2026-06-10"], "other": [1]})
        result = price_summary(df)
        assert result.empty


# ── demand_summary ────────────────────────────────────────────────────────────

class TestDemandSummary:
    def test_basic_stats(self, emc_df: pd.DataFrame):
        result = demand_summary(emc_df)
        assert len(result) == 2
        assert list(result.columns) == ["date", "mean", "peak", "trough"]

        row0 = result[result["date"] == "2026-06-10"].iloc[0]
        assert row0["trough"] == 5950.0
        assert row0["peak"] == 6100.0

    def test_empty_df_returns_empty(self):
        result = demand_summary(pd.DataFrame())
        assert result.empty

    def test_no_demand_column_returns_empty(self):
        df = pd.DataFrame({"date": ["2026-06-10"], "other": [1]})
        result = demand_summary(df)
        assert result.empty


# ── monthly_trend ─────────────────────────────────────────────────────────────

class TestMonthlyTrend:
    def test_basic(self, emc_df: pd.DataFrame):
        result = monthly_trend(emc_df)
        assert len(result) == 1  # one month
        assert list(result.columns) == ["month", "usep_avg", "demand_peak", "solar_avg"]
        assert result["demand_peak"].iloc[0] == 6300.0

    def test_multiple_months(self):
        df = pd.DataFrame({
            "date": ["2026-05-15"] * 2 + ["2026-06-15"] * 2,
            "period": ["00:00-00:30", "00:30-01:00"] * 2,
            "usep": [100, 200, 300, 400],
            "demand_mw": [5000, 6000, 7000, 8000],
            "solar_mw": [0, 0, 100, 200],
        })
        result = monthly_trend(df)
        assert len(result) == 2
        assert set(result["month"]) == {"2026-05", "2026-06"}

    def test_empty_returns_empty(self):
        result = monthly_trend(pd.DataFrame())
        assert result.empty


# ── vcp_vs_usep ───────────────────────────────────────────────────────────────

class TestVcpVsUsep:
    def test_basic(self):
        snaps = [
            {"fetched_at": "2026-06-10T10:00:00Z", "usep": 175.0, "vcp": 190.0, "demand_mw": 6000},
            {"fetched_at": "2026-06-10T11:00:00Z", "usep": 180.0, "vcp": 195.0, "demand_mw": 6100},
        ]
        result = vcp_vs_usep(snaps)
        assert len(result) == 2
        assert "fetched_at" in result.columns
        assert "usep" in result.columns
        assert "vcp" in result.columns
        assert result["usep"].iloc[0] == 175.0

    def test_empty_returns_empty(self):
        result = vcp_vs_usep([])
        assert result.empty
