"""CLI entry point: oem <command>"""

from __future__ import annotations

from datetime import date, timedelta

import click
from rich.console import Console
from rich.table import Table

from . import analytics, storage
from .scrapers import emc, live, retail as retail_scraper

console = Console()


@click.group()
def cli():
    """Singapore Open Electricity Market data tracker."""


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--source", default="all", type=click.Choice(["all", "emc", "live", "retail"]), show_default=True)
@click.option("--date", "run_date", default=None, help="ISO date to label the run (default: today)")
def fetch(source: str, run_date: str | None):
    """Download and store daily electricity market data."""
    today = date.fromisoformat(run_date) if run_date else date.today()

    if source in ("all", "live"):
        _fetch_live(today)

    if source in ("all", "emc"):
        _fetch_emc(today)

    if source in ("all", "retail"):
        _fetch_retail(today)


def _fetch_live(today: date):
    console.print("[bold cyan]live[/] Fetching current USEP snapshot...")
    try:
        snap = live.fetch_snapshot()
        path = storage.save_json(snap, "live", today)
        console.print(f"  [green]✓[/] USEP={snap['usep']} $/MWh  demand={snap['demand_mw']} MW  VCP={snap['vcp']} $/MWh → {path.name}")
    except Exception as e:
        console.print(f"  [red]✗[/] live: {e}")


def _fetch_emc(today: date):
    console.print("[bold cyan]emc[/] Fetching half-hourly USEP + demand (D-7 window)...")
    try:
        # EMC has a D+6 release lag; fetch the day 7 days ago to be safe
        target = today - timedelta(days=7)
        df = emc.fetch_usep_demand(target, target)
        if df.empty:
            console.print("  [yellow]![/] No data returned for", target)
            return
        path = storage.save_parquet(df, "emc", target)
        console.print(f"  [green]✓[/] {len(df)} half-hour periods for {target} → {path.name}")
    except Exception as e:
        console.print(f"  [red]✗[/] emc: {e}")



def _fetch_retail(today: date):
    console.print("[bold cyan]retail[/] Fetching retail plan prices...")
    try:
        df = retail_scraper.fetch_retail_plans()
        path = storage.save_parquet(df, "retail", today)
        tariff = df["regulated_tariff_cents_kwh"].iloc[0] if not df.empty else "?"
        console.print(f"  [green]✓[/] {len(df)} plans, regulated tariff={tariff} ¢/kWh → {path.name}")
    except Exception as e:
        console.print(f"  [red]✗[/] retail: {e}")


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

@cli.group()
def show():
    """Display collected data and analytics."""


@show.command("prices")
@click.option("--days", default=30, show_default=True, help="Look-back window in days")
def show_prices(days: int):
    """Daily USEP price statistics (min/mean/max/p95)."""
    end = date.today()
    start = end - timedelta(days=days)
    df = storage.load_parquet("emc", start, end)
    if df.empty:
        console.print("[yellow]No EMC data in range. Run: oem fetch --source emc[/]")
        return
    summary = analytics.price_summary(df)
    table = Table(title=f"USEP Price Summary — last {days} days ($/MWh)", show_lines=False)
    for col in summary.columns:
        table.add_column(str(col), justify="right" if col != "date" else "left")
    for _, row in summary.iterrows():
        table.add_row(*[str(v) for v in row])
    console.print(table)


@show.command("demand")
@click.option("--days", default=30, show_default=True, help="Look-back window in days")
def show_demand(days: int):
    """Daily demand statistics (peak/mean/trough MW)."""
    end = date.today()
    start = end - timedelta(days=days)
    df = storage.load_parquet("emc", start, end)
    if df.empty:
        console.print("[yellow]No EMC data in range. Run: oem fetch --source emc[/]")
        return
    summary = analytics.demand_summary(df)
    table = Table(title=f"System Demand — last {days} days (MW)", show_lines=False)
    for col in summary.columns:
        table.add_column(str(col), justify="right" if col != "date" else "left")
    for _, row in summary.iterrows():
        table.add_row(*[str(v) for v in row])
    console.print(table)


@show.command("trend")
@click.option("--days", default=90, show_default=True)
def show_trend(days: int):
    """Monthly USEP average and peak demand trend."""
    end = date.today()
    start = end - timedelta(days=days)
    df = storage.load_parquet("emc", start, end)
    if df.empty:
        console.print("[yellow]No EMC data in range.[/]")
        return
    trend = analytics.monthly_trend(df)
    table = Table(title="Monthly Trend", show_lines=False)
    for col in trend.columns:
        table.add_column(str(col), justify="right" if col != "month" else "left")
    for _, row in trend.iterrows():
        table.add_row(*[str(v) for v in row])
    console.print(table)


@show.command("live")
@click.option("--days", default=7, show_default=True)
def show_live(days: int):
    """Recent live USEP snapshots (VCP vs USEP)."""
    end = date.today()
    start = end - timedelta(days=days)
    snaps = storage.load_json_series("live", start, end)
    if not snaps:
        console.print("[yellow]No live snapshots. Run: oem fetch --source live[/]")
        return
    df = analytics.vcp_vs_usep(snaps)
    table = Table(title="Live Snapshots — USEP vs VCP", show_lines=False)
    for col in df.columns:
        table.add_column(str(col))
    for _, row in df.iterrows():
        table.add_row(*[str(v) for v in row])
    console.print(table)


@show.command("summary")
def show_summary():
    """Inventory of all collected data files."""
    inv = storage.inventory()
    if not inv:
        console.print("[yellow]No data collected yet. Run: oem fetch[/]")
        return
    table = Table(title="Data Inventory", show_lines=False)
    table.add_column("Source")
    table.add_column("Files", justify="right")
    table.add_column("Earliest")
    table.add_column("Latest")
    for source, info in inv.items():
        table.add_row(source, str(info["count"]), info["earliest"] or "—", info["latest"] or "—")
    console.print(table)


# ---------------------------------------------------------------------------
# backfill
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--from-date", required=True, help="Start date YYYY-MM-DD")
@click.option("--to-date", default=None, help="End date YYYY-MM-DD (default: today - 7)")
def backfill(from_date: str, to_date: str | None):
    """Backfill historical EMC USEP data in 31-day chunks."""
    from datetime import timedelta

    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date) if to_date else date.today() - timedelta(days=7)

    cursor = start
    chunk = timedelta(days=30)
    while cursor <= end:
        chunk_end = min(cursor + chunk, end)
        console.print(f"[cyan]Fetching {cursor} → {chunk_end}...[/]", end=" ")
        try:
            df = emc.fetch_usep_demand(cursor, chunk_end)
            if df.empty:
                console.print("[yellow]no data[/]")
            else:
                # Save one file per calendar date within the chunk
                for d, group in df.groupby("date"):
                    storage.save_parquet(group, "emc", d)
                console.print(f"[green]{len(df)} rows[/]")
        except Exception as e:
            console.print(f"[red]{e}[/]")
        cursor = chunk_end + timedelta(days=1)


# ---------------------------------------------------------------------------
# cron
# ---------------------------------------------------------------------------

@cli.command()
def cron():
    """Print cron setup instructions for daily automated fetch."""
    import shutil
    oem_path = shutil.which("oem") or "oem"
    console.print("\n[bold]Add to crontab (runs at 06:00 daily):[/]")
    console.print(f"\n  [cyan]0 6 * * * {oem_path} fetch >> ~/oem-tracker.log 2>&1[/]\n")
    console.print("Edit with: [cyan]crontab -e[/]")
    console.print("\n[bold]Or for launchd on macOS:[/]")
    console.print("  Copy scripts/com.oem.tracker.plist to ~/Library/LaunchAgents/ and load it.\n")
