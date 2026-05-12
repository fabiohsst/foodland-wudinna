"""
export_sales_snapshot.py — Export Sales Snapshot for Cloud Pipeline
Foodland Wudinna

Exports the last 10 weeks of F&V sales from the local DB to a CSV file
that GitHub Actions can read when generating the automated order sheet.

Run this after importing new sales data via the Import Panel.
It is called automatically by import_panel.py after a successful sales import.

Usage:
    python export_sales_snapshot.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def export_snapshot(weeks: int = 10) -> Path:
    """
    Read the last `weeks` weeks of F&V sales from the DB and write to
    03_model/sales_snapshot.csv. Returns the output path.
    """
    import pandas as pd
    from db import load_sales as _db_load_sales

    output_path = ROOT / "03_model/sales_snapshot.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("[snapshot] Loading sales from DB…")
    df = _db_load_sales()

    if df.empty:
        raise RuntimeError("No sales data found in DB — nothing to export.")

    # Normalise column names (db.py returns lowercase)
    col_map = {
        "date":          "Date",
        "name":          "Name",
        "sub_dept":      "SubDept",
        "department":    "Department",
        "sales_ex_gst":  "Revenue",
        "cost_ex_gst":   "Cost",
        "gp_dollars":    "GP",
        "quantity":      "Qty",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # Enforce F&V only
    if "Department" in df.columns:
        df = df[df["Department"] == "FRUIT & VEG"].copy()

    df["Date"] = pd.to_datetime(df["Date"])
    cutoff = df["Date"].max() - pd.Timedelta(weeks=weeks)
    df = df[df["Date"] >= cutoff].copy()

    df.to_csv(output_path, index=False)
    print(f"[snapshot] Exported {len(df):,} rows ({weeks}w) → {output_path.relative_to(ROOT)}")
    return output_path


def git_push_snapshot(snapshot_path: Path):
    """Stage, commit, and push the snapshot file."""
    import subprocess

    def _run(cmd):
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        if result.returncode != 0:
            raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr.strip()}")
        return result.stdout.strip()

    import datetime
    today = datetime.date.today().isoformat()

    print("[snapshot] Staging snapshot for git…")
    _run(["git", "add", str(snapshot_path.relative_to(ROOT))])
    _run(["git", "commit", "-m", f"data: sales snapshot {today}", "--allow-empty"])
    _run(["git", "push"])
    print("[snapshot] Pushed to GitHub.")


if __name__ == "__main__":
    try:
        path = export_snapshot()
        git_push_snapshot(path)
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)
