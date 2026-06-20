#!/usr/bin/env python3
"""Thin CLI wrapper — delegates to oem_tracker.exporter.build_all() and oem_tracker.reports.build_all_reports()."""
from __future__ import annotations

from pathlib import Path

from oem_tracker.exporter import build_all
from oem_tracker.reports import build_all_reports

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "docs" / "data"

if __name__ == "__main__":
    manifest = build_all(RAW, OUT)
    print(f"Built: {len(manifest['emc']['dates'])} EMC dates, "
          f"{manifest['live']['count']} live, "
          f"{manifest['retail']['plan_count']} retail plans → {OUT}")

    reports = build_all_reports(RAW, OUT)
    print(f"Reports: daily={reports['daily_diff']} weekly={reports['weekly_brief']} "
          f"monthly={reports['monthly_analytics']} quarterly={reports['quarterly_prediction']}")
