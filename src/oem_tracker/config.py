from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # repo root (src/oem_tracker/config.py → ../../..)
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

# EMC NEMS download API — public, no auth required, up to 31-day windows, 5-year rolling
# value codes discovered from public URLs; tpcValue=1 includes transmission price component
EMC_DOWNLOAD_URL = "https://www.nems.emcsg.com/api/sitecore/DataSync/DataDownload"
EMC_DATASETS = {
    # value=10: USEP, Demand, Solar, TCL, EHEUR, LCP, RUSEP, MAP, MAPT (half-hourly)
    "usep_demand": {"value": 10, "tpcValue": 1},
}

# Unofficial live API — JSON, no auth, cross-origin enabled, no rate limits
NEMS_LIVE_URL = "https://nems.sn.sg/api/status.json"

# EMA statistics — monthly USEP averages, annual energy stats
EMA_BASE = "https://www.ema.gov.sg"
EMA_MONTHLY_USEP_PAGE = f"{EMA_BASE}/resources/statistics/average-monthly-uniform-singapore-energy-price"
EMA_HALF_HOURLY_DEMAND_PAGE = f"{EMA_BASE}/resources/statistics/half-hourly-system-demand-data"

# OEM market share statistics
OEM_STATS_URL = "https://www.openelectricitymarket.sg/about/statistics"

# Retail plan comparison API (SP Digital, public, no auth, startIndex is 1-based)
RETAIL_API_BASE = "https://public.api.spdigital.sg/retailer"
RETAIL_COMPARE_ORIGIN = "https://compare.openelectricitymarket.sg"
