"""Portable paths shared by the transform, KPI builder and API."""
import os
from pathlib import Path
ROOT = Path(__file__).resolve().parent
RAW = str(Path(os.environ.get("VENDORPULSE_RAW", ROOT / "data")).resolve())
OUT = str(Path(os.environ.get("VENDORPULSE_WAREHOUSE", ROOT)).resolve())

def sql_path(path):
    return str(path).replace("'", "''")
