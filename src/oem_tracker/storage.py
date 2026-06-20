from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .config import RAW_DIR

# Raw data files use compact YYYYMMDD format (no dashes).
_DATE_FMT = "%Y%m%d"


def _parse_stem(stem: str) -> date:
    """Parse a YYYYMMDD filename stem to a date."""
    return datetime.strptime(stem, _DATE_FMT).date()


def _format_date(d: date) -> str:
    """Format a date as YYYYMMDD for use in filenames."""
    return d.strftime(_DATE_FMT)


def save_parquet(df: pd.DataFrame, source: str, run_date: date) -> Path:
    dest = RAW_DIR / source / f"{_format_date(run_date)}.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(dest, index=False)
    return dest


def load_parquet(source: str, start: date, end: date) -> pd.DataFrame:
    src_dir = RAW_DIR / source
    if not src_dir.exists():
        return pd.DataFrame()
    frames = []
    for f in sorted(src_dir.glob("*.parquet")):
        file_date = _parse_stem(f.stem)
        if start <= file_date <= end:
            frames.append(pd.read_parquet(f))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def save_json(record: dict, source: str, run_date: date) -> Path:
    dest = RAW_DIR / source / f"{_format_date(run_date)}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record, indent=2))
    return dest


def load_json_series(source: str, start: date, end: date) -> list[dict]:
    src_dir = RAW_DIR / source
    if not src_dir.exists():
        return []
    records = []
    for f in sorted(src_dir.glob("*.json")):
        file_date = _parse_stem(f.stem)
        if start <= file_date <= end:
            records.append(json.loads(f.read_text()))
    return records


def inventory() -> dict[str, dict]:
    result = {}
    for source_dir in sorted(RAW_DIR.iterdir()):
        if not source_dir.is_dir():
            continue
        files = sorted(f for f in source_dir.iterdir() if f.suffix in (".parquet", ".json"))
        if not files:
            result[source_dir.name] = {"count": 0, "earliest": None, "latest": None}
            continue
        stems = [f.stem for f in files]
        result[source_dir.name] = {
            "count": len(files),
            "earliest": stems[0],
            "latest": stems[-1],
        }
    return result
