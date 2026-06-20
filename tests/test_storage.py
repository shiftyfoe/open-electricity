"""Tests for oem_tracker.storage — save, load, inventory with YYYYMMDD filenames."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from oem_tracker.storage import (
    _DATE_FMT,
    _format_date,
    _parse_stem,
    inventory,
    load_json_series,
    load_parquet,
    save_json,
    save_parquet,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect RAW_DIR to a temp directory."""
    raw = tmp_path / "raw"
    import oem_tracker.storage as mod
    monkeypatch.setattr(mod, "RAW_DIR", raw)
    return raw


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "period": ["00:00-00:30", "00:30-01:00"],
        "usep": [175.89, 176.37],
        "demand_mw": [6483.1, 6368.4],
    })


# ── date helpers ──────────────────────────────────────────────────────────────

class TestDateFormat:
    def test_format_date(self):
        assert _format_date(date(2026, 6, 20)) == "20260620"
        assert _format_date(date(2025, 1, 1)) == "20250101"

    def test_parse_stem(self):
        assert _parse_stem("20260620") == date(2026, 6, 20)
        assert _parse_stem("20250101") == date(2025, 1, 1)

    def test_roundtrip(self):
        d = date(2026, 12, 31)
        assert _parse_stem(_format_date(d)) == d

    def test_fmt_no_dashes(self):
        """Ensure no ISO dashes leak in."""
        assert "-" not in _format_date(date(2026, 6, 20))
        assert _DATE_FMT == "%Y%m%d"


# ── parquet save / load ───────────────────────────────────────────────────────

class TestParquet:
    def test_save_creates_file(self, tmp_raw: Path, sample_df: pd.DataFrame):
        path = save_parquet(sample_df, "emc", date(2026, 6, 20))
        assert path.exists()
        assert path.suffix == ".parquet"
        assert path.parent == tmp_raw / "emc"

    def test_save_uses_yyyymmdd_name(self, tmp_raw: Path, sample_df: pd.DataFrame):
        path = save_parquet(sample_df, "emc", date(2026, 6, 20))
        assert path.stem == "20260620"

    def test_load_returns_same_data(self, tmp_raw: Path, sample_df: pd.DataFrame):
        save_parquet(sample_df, "emc", date(2026, 6, 20))
        loaded = load_parquet("emc", date(2026, 6, 1), date(2026, 6, 30))
        pd.testing.assert_frame_equal(loaded, sample_df)

    def test_load_filters_by_date_range(self, tmp_raw: Path, sample_df: pd.DataFrame):
        save_parquet(sample_df, "emc", date(2026, 6, 10))
        save_parquet(sample_df, "emc", date(2026, 6, 20))
        loaded = load_parquet("emc", date(2026, 6, 15), date(2026, 6, 25))
        # Only data from 2026-06-20 should be in range
        assert len(loaded) == 2  # 2 rows in sample_df

    def test_load_missing_source_returns_empty(self, tmp_raw: Path):
        df = load_parquet("nonexistent", date(2026, 1, 1), date(2026, 12, 31))
        assert df.empty

    def test_load_no_files_in_range(self, tmp_raw: Path, sample_df: pd.DataFrame):
        save_parquet(sample_df, "emc", date(2026, 6, 1))
        df = load_parquet("emc", date(2026, 7, 1), date(2026, 7, 31))
        assert df.empty


# ── JSON save / load ──────────────────────────────────────────────────────────

class TestJson:
    def test_save_creates_file(self, tmp_raw: Path):
        record = {"usep": 175.0, "demand_mw": 6000}
        path = save_json(record, "live", date(2026, 6, 20))
        assert path.exists()
        assert path.suffix == ".json"
        assert path.stem == "20260620"

    def test_save_preserves_data(self, tmp_raw: Path):
        record = {"usep": 175.0, "fetched_at": "2026-06-20T10:00:00Z"}
        save_json(record, "live", date(2026, 6, 20))
        loaded = json.loads((tmp_raw / "live" / "20260620.json").read_text())
        assert loaded == record

    def test_load_json_series(self, tmp_raw: Path):
        save_json({"usep": 100}, "live", date(2026, 6, 10))
        save_json({"usep": 200}, "live", date(2026, 6, 20))
        records = load_json_series("live", date(2026, 6, 1), date(2026, 6, 30))
        assert len(records) == 2
        assert records[0]["usep"] == 100
        assert records[1]["usep"] == 200

    def test_load_json_respects_range(self, tmp_raw: Path):
        save_json({"v": 1}, "live", date(2026, 6, 1))
        save_json({"v": 2}, "live", date(2026, 6, 10))
        save_json({"v": 3}, "live", date(2026, 6, 20))
        records = load_json_series("live", date(2026, 6, 5), date(2026, 6, 15))
        assert len(records) == 1
        assert records[0]["v"] == 2

    def test_load_missing_source_returns_empty(self, tmp_raw: Path):
        assert load_json_series("nonexistent", date(2026, 1, 1), date(2026, 12, 31)) == []


# ── inventory ─────────────────────────────────────────────────────────────────

class TestInventory:
    def test_empty_dirs(self, tmp_raw: Path):
        # Create an empty source directory
        (tmp_raw / "emc").mkdir(parents=True)
        (tmp_raw / "emc" / ".gitkeep").touch()
        result = inventory()
        assert result["emc"]["count"] == 0
        assert result["emc"]["earliest"] is None

    def test_with_data(self, tmp_raw: Path, sample_df: pd.DataFrame):
        save_parquet(sample_df, "emc", date(2026, 6, 10))
        save_parquet(sample_df, "emc", date(2026, 6, 20))
        result = inventory()
        assert result["emc"]["count"] == 2
        assert result["emc"]["earliest"] == "20260610"
        assert result["emc"]["latest"] == "20260620"

    def test_skips_non_dirs(self, tmp_raw: Path):
        # If there's a file directly in RAW_DIR, it should be skipped
        tmp_raw.mkdir(parents=True, exist_ok=True)
        (tmp_raw / "stray.txt").write_text("not a dir")
        result = inventory()
        assert "stray.txt" not in result  # not a dir, skipped
