"""Basic analytics over collected USEP/demand data."""

from __future__ import annotations

import pandas as pd


def price_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Descriptive stats for USEP ($/MWh) by date."""
    if df.empty or "usep" not in df.columns:
        return pd.DataFrame()
    by_date = df.groupby("date")["usep"].agg(
        mean="mean",
        p5=lambda x: x.quantile(0.05),
        p95=lambda x: x.quantile(0.95),
        min="min",
        max="max",
        std="std",
    ).reset_index()
    by_date.columns.name = None
    return by_date.round(2)


def demand_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Peak and average demand by date."""
    if df.empty or "demand_mw" not in df.columns:
        return pd.DataFrame()
    by_date = df.groupby("date")["demand_mw"].agg(
        mean="mean",
        peak="max",
        trough="min",
    ).reset_index()
    by_date.columns.name = None
    return by_date.round(1)


def monthly_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly average USEP and peak demand."""
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["month"] = pd.to_datetime(df["date"].astype(str)).dt.to_period("M")
    agg = df.groupby("month").agg(
        usep_avg=("usep", "mean"),
        demand_peak=("demand_mw", "max"),
        solar_avg=("solar_mw", "mean"),
    ).reset_index()
    agg["month"] = agg["month"].astype(str)
    return agg.round(2)


def vcp_vs_usep(snapshots: list[dict]) -> pd.DataFrame:
    """Compare live VCP (vested contract price) against USEP over time."""
    if not snapshots:
        return pd.DataFrame()
    df = pd.DataFrame(snapshots)[["fetched_at", "usep", "vcp", "demand_mw"]]
    df["date"] = pd.to_datetime(df["fetched_at"]).dt.date
    return df
