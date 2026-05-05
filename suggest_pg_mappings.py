"""
suggest_pg_mappings.py — Use Claude AI to suggest price_guide_mapping.csv entries
for descriptions that parse_price_guide.py could not match.

Usage
-----
    # Step 1 — generate suggestions
    python suggest_pg_mappings.py <excel_file>

    # Step 2 — review the staged file
    Open 01_data/reference/price_guide_mapping_staged.csv in Excel or a text editor.
    - Delete rows you do not want.
    - Correct pos_name or units_per_invoice where needed.
    - Keep only the rows you are happy with.

    # Step 3 — apply reviewed suggestions
    python suggest_pg_mappings.py --apply

API key setup
-------------
Set your Anthropic API key in one of three ways (checked in this order):

  1. Environment variable:
        set ANTHROPIC_API_KEY=sk-ant-...          (Windows CMD)
        $env:ANTHROPIC_API_KEY="sk-ant-..."       (Windows PowerShell)

  2. A plain-text file at the project root called  .api_key
        Contents: sk-ant-api03-...

  3. Pass it directly:
        python suggest_pg_mappings.py <excel> --api-key sk-ant-...

Get your key at: https://console.anthropic.com/settings/api-keys
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).parent
STAGED_CSV   = ROOT / "01_data/reference/price_guide_mapping_staged.csv"
MAPPING_CSV  = ROOT / "01_data/reference/price_guide_mapping.csv"
API_KEY_FILE = ROOT / ".api_key"

# Fruit & Veg sub-department names in the sales data
FV_SUBDEPTS = {"Vegetables", "Fruit", "Salads", "Potatoes", "Fruit & Vege Department Open"}

# Claude model — haiku is fast and cheap; plenty accurate for produce matching
MODEL = "claude-haiku-4-5-20251001"

API_URL = "https://api.anthropic.com/v1/messages"


# ── API key ───────────────────────────────────────────────────────────────────
def _load_api_key(cli_key: str | None) -> str:
    """Resolve API key from CLI arg → env var → .api_key file."""
    if cli_key:
        return cli_key.strip()
    env = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env:
        return env
    if API_KEY_FILE.exists():
        key = API_KEY_FILE.read_text().strip()
        if key:
            return key
    print(
        "\nERROR: No Anthropic API key found.\n"
        "Set it with one of:\n"
        "  1. Environment variable:  set ANTHROPIC_API_KEY=sk-ant-...\n"
        "  2. File at project root:  .api_key  (contents: sk-ant-...)\n"
        "  3. CLI arg:               --api-key sk-ant-...\n"
        "Get your key at: https://console.anthropic.com/settings/api-keys\n",
        file=sys.stderr,
    )
    sys.exit(1)


# ── POS name list ─────────────────────────────────────────────────────────────
def _load_pos_names() -> list[str]:
    """
    Load known Fruit & Veg POS names from:
    1. Sales history (sub-dept = Fruit, Vegetables, Salads, Potatoes)
    2. invoice_item_mapping.csv (pos_name column)
    Returns sorted, deduplicated list.
    """
    names: set[str] = set()

    # From sales history
    try:
        from db import load_sales
        df = load_sales()
        fv = df[df["SubDept"].isin(FV_SUBDEPTS)]
        names.update(fv["Name"].dropna().str.strip().str.upper().unique())
    except Exception as e:
        print(f"  Warning: could not load sales data — {e}", file=sys.stderr)

    # From invoice_item_mapping.csv
    inv_csv = ROOT / "01_data/reference/invoice_item_mapping.csv"
    if inv_csv.exists():
        try:
            df2 = pd.read_csv(inv_csv)
            df2.columns = df2.columns.str.strip()
            names.update(df2["pos_name"].dropna().str.strip().str.upper().unique())
        except Exception:
            pass

    return sorted(names)


# ── Unmatched items ───────────────────────────────────────────────────────────
def _get_unmatched(excel_path: Path) -> list[dict]:
    """
    Run parse_price_guide logic and return unmatched items as
    [{desc, qty_str, price}].
    """
    sys.path.insert(0, str(ROOT))
    from parse_price_guide import (
        read_price_guide,
        _load_pg_mapping,
        _load_inv_mapping,
        match_items,
    )

    guide_date, items = read_price_guide(excel_path)
    pg_map  = _load_pg_mapping()
    inv_map = _load_inv_mapping()
    _, unmatched_descs = match_items(items, pg_map, inv_map)

    # Build a lookup: desc → (qty_str, price) — keep first occurrence
    item_lookup: dict[str, tuple[str, float]] = {}
    for desc, qty_str, price in items:
        if desc not in item_lookup:
            item_lookup[desc] = (qty_str, price)

    results = []
    for desc in unmatched_descs:
        qty_str, price = item_lookup.get(desc, ("", 0.0))
        results.append({"desc": desc, "qty_str": qty_str, "price": price})

    return results


# ── Claude API call ───────────────────────────────────────────────────────────
_SYSTEM = """\
You are a produce expert helping an Australian supermarket match Freshlink supplier
price guide descriptions to their POS (point-of-sale) item names.

Freshlink uses shorthand — for example:
  "LARGE" = their large strawberry 250g punnet
  "CONTINENTAL" = continental cucumber
  "ICEBURG" = iceberg lettuce
  "HASS - 25'S" = Hass avocados, tray of 25

Always respond with valid JSON only. No commentary, no markdown fences.\
"""

_USER_TEMPLATE = """\
Match each Freshlink price guide description to the best POS name from the list below.

DESCRIPTIONS TO MATCH (one per line — use these exact strings as price_guide_key):
{desc_block}

CONTEXT TABLE for reference only (description | qty in guide | invoice price AUD):
{items_block}

AVAILABLE POS NAMES:
{pos_names_block}

Return this JSON structure — one entry per description above, in the same order:
{{
  "matches": [
    {{
      "price_guide_key": "<copy the description exactly from DESCRIPTIONS TO MATCH>",
      "pos_name": "<matched POS name copied exactly from AVAILABLE POS NAMES, or null>",
      "units_per_invoice": <number>,
      "confidence": "high|medium|low",
      "notes": "<brief reasoning, max 10 words>"
    }}
  ]
}}

Rules:
- price_guide_key must be the plain description string — NOT including qty or price.
- pos_name must be copied verbatim from AVAILABLE POS NAMES, or null.
  Do NOT invent or paraphrase names.
- units_per_invoice: sell units the invoice price covers.
    $50 for 12KG carton, sold per kg → 12
    $4.50 per punnet (EA)            → 1
    $60 for box of 15 → sold each    → 15
    $30/kg already per kg            → 1
- confidence: "high" = certain, "medium" = reasonable, "low" = unsure
- null pos_name when item has no POS match, is a section header, or is
  a brand/specialty the store does not stock.
"""


def _call_claude(
    unmatched: list[dict],
    pos_names: list[str],
    api_key: str,
    retries: int = 3,
) -> list[dict]:
    """
    Send unmatched items to Claude and return parsed match list.
    Each element: {price_guide_key, pos_name, units_per_invoice, confidence, notes}
    """
    desc_block      = "\n".join(u["desc"] for u in unmatched)
    items_block     = "\n".join(
        f"{u['desc']} | {u['qty_str'] or '—'} | ${u['price']:.2f}"
        for u in unmatched
    )
    pos_names_block = "\n".join(pos_names)

    payload = {
        "model": MODEL,
        "max_tokens": 8192,
        "system": _SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": _USER_TEMPLATE.format(
                    desc_block=desc_block,
                    items_block=items_block,
                    pos_names_block=pos_names_block,
                ),
            }
        ],
    }

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=120, verify=False)
            if resp.status_code == 200:
                break
            last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
            if resp.status_code in (429, 529):
                wait = 10 * attempt
                print(f"  Rate limit — waiting {wait}s (attempt {attempt}/{retries})…")
                time.sleep(wait)
            else:
                print(f"  API error: {last_err}", file=sys.stderr)
                sys.exit(1)
        except requests.exceptions.RequestException as e:
            last_err = str(e)
            if attempt < retries:
                time.sleep(5)
    else:
        print(f"  ERROR: all retries failed — {last_err}", file=sys.stderr)
        sys.exit(1)

    raw = resp.json()["content"][0]["text"].strip()

    # Strip markdown fences if the model added them despite instructions
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
        return data.get("matches", [])
    except json.JSONDecodeError as e:
        print(f"  ERROR: could not parse Claude response as JSON — {e}", file=sys.stderr)
        print(f"  Raw response:\n{raw[:500]}", file=sys.stderr)
        sys.exit(1)


# ── Write staged CSV ──────────────────────────────────────────────────────────
def _write_staged(matches: list[dict], unmatched: list[dict]) -> None:
    """Write price_guide_mapping_staged.csv for human review."""
    # Build a quick lookup for invoice prices
    price_lookup = {u["desc"]: u["price"] for u in unmatched}

    rows = []
    for m in matches:
        key   = str(m.get("price_guide_key", "")).strip()
        pos   = str(m.get("pos_name", "") or "").strip()
        units = m.get("units_per_invoice", 1)
        conf  = str(m.get("confidence", "low")).strip()
        notes = str(m.get("notes", "")).strip()
        inv_price = price_lookup.get(key, 0.0)

        try:
            units_f = float(units)
        except (TypeError, ValueError):
            units_f = 1.0

        sell_price = round((inv_price / max(units_f, 0.01)) / 0.60, 2) if inv_price else None

        rows.append({
            "price_guide_key":   key,
            "pos_name":          pos if pos else "",
            "units_per_invoice": units_f,
            "confidence":        conf,
            "suggested_sell":    sell_price,
            "invoice_price":     inv_price,
            "notes":             notes,
        })

    # Sort: high confidence first, then alpha
    order = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda r: (order.get(r["confidence"], 3), r["price_guide_key"]))

    df = pd.DataFrame(rows, columns=[
        "price_guide_key", "pos_name", "units_per_invoice",
        "confidence", "suggested_sell", "invoice_price", "notes",
    ])
    STAGED_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(STAGED_CSV, index=False)


# ── Apply staged CSV ──────────────────────────────────────────────────────────
def _apply_staged() -> None:
    """
    Read price_guide_mapping_staged.csv and append approved rows to
    price_guide_mapping.csv.  Skips rows where pos_name is blank or the
    key already exists in the main mapping.
    """
    if not STAGED_CSV.exists():
        print(f"ERROR: No staged file found at {STAGED_CSV.relative_to(ROOT)}", file=sys.stderr)
        print("Run the script without --apply first to generate suggestions.", file=sys.stderr)
        sys.exit(1)

    staged = pd.read_csv(STAGED_CSV)
    staged.columns = staged.columns.str.strip()

    # Load existing mapping keys
    existing_keys: set[str] = set()
    if MAPPING_CSV.exists():
        existing = pd.read_csv(MAPPING_CSV)
        existing.columns = existing.columns.str.strip()
        existing_keys = set(
            existing["price_guide_key"].str.strip().str.upper().dropna()
        )

    approved = staged[staged["pos_name"].notna() & (staged["pos_name"].str.strip() != "")]
    new_rows  = approved[~approved["price_guide_key"].str.strip().str.upper().isin(existing_keys)]

    if new_rows.empty:
        print("Nothing new to apply (all rows already in mapping or pos_name is blank).")
        return

    # Append to mapping CSV
    append_df = new_rows[["price_guide_key", "pos_name", "units_per_invoice", "notes"]].copy()
    append_df.to_csv(MAPPING_CSV, mode="a", header=not MAPPING_CSV.exists(), index=False)

    print(f"  Applied {len(new_rows)} new row(s) to {MAPPING_CSV.relative_to(ROOT)}")
    for _, r in new_rows.iterrows():
        conf_tag = f"[{r['confidence']}]" if "confidence" in r else ""
        print(f"    {r['price_guide_key']:<35}  →  {r['pos_name']}  {conf_tag}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM-assisted price guide → POS name mapping suggestions"
    )
    parser.add_argument(
        "excel_file", nargs="?",
        help="Path to the Freshlink price guide Excel (.xlsx)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply the reviewed staged CSV to price_guide_mapping.csv",
    )
    parser.add_argument(
        "--api-key", dest="api_key", default=None,
        help="Anthropic API key (overrides env var / .api_key file)",
    )
    args = parser.parse_args()

    # ── Apply mode ────────────────────────────────────────────────────────────
    if args.apply:
        print(f"Applying staged mappings from {STAGED_CSV.relative_to(ROOT)} …")
        print()
        _apply_staged()
        print()
        print("Done.  Run parse_price_guide.py again to see the updated match rate.")
        return

    # ── Suggest mode ──────────────────────────────────────────────────────────
    if not args.excel_file:
        parser.error("Provide the price guide Excel file, or use --apply to merge a staged file.")

    xl_path = Path(args.excel_file)
    if not xl_path.exists():
        print(f"ERROR: File not found: {xl_path}", file=sys.stderr)
        sys.exit(1)

    api_key = _load_api_key(args.api_key)

    print(f"Price guide: {xl_path.name}")
    print()

    # Get unmatched items
    print("  Running parser to find unmatched descriptions …")
    unmatched = _get_unmatched(xl_path)
    if not unmatched:
        print("  Nothing to match — all descriptions already have mappings.")
        return
    print(f"  Unmatched: {len(unmatched)} descriptions")

    # Load POS names
    print("  Loading POS names from database …")
    pos_names = _load_pos_names()
    print(f"  POS names available: {len(pos_names)}")
    print()

    # Call Claude
    print(f"  Calling Claude ({MODEL}) …")
    t0 = time.time()
    matches = _call_claude(unmatched, pos_names, api_key)
    elapsed = time.time() - t0
    print(f"  Response received in {elapsed:.1f}s")
    print()

    # Summary
    matched_count = sum(1 for m in matches if m.get("pos_name"))
    null_count    = len(matches) - matched_count
    high  = sum(1 for m in matches if m.get("confidence") == "high"   and m.get("pos_name"))
    med   = sum(1 for m in matches if m.get("confidence") == "medium" and m.get("pos_name"))
    low   = sum(1 for m in matches if m.get("confidence") == "low"    and m.get("pos_name"))

    print(f"  Matched:   {matched_count}  (high: {high}, medium: {med}, low: {low})")
    print(f"  No match:  {null_count}  (items not in POS or not applicable)")
    print()

    # Print suggestions
    col_w = max((len(m.get("price_guide_key","")) for m in matches), default=10)
    print(f"  {'Description':<{col_w}}  {'POS Name':<45}  {'Units':>5}  {'Sell':>6}  Conf    Notes")
    print(f"  {'-'*col_w}  {'-'*45}  {'-'*5}  {'-'*6}  ------  -----")

    price_lookup = {u["desc"]: u["price"] for u in unmatched}
    for m in sorted(matches, key=lambda x: ({"high":0,"medium":1,"low":2}.get(x.get("confidence","low"),3), x.get("price_guide_key",""))):
        key   = m.get("price_guide_key", "")
        pos   = m.get("pos_name") or "—  (no match)"
        units = m.get("units_per_invoice", 1)
        conf  = m.get("confidence", "?")
        notes = m.get("notes", "")[:50]
        price = price_lookup.get(key, 0)
        try:
            sell = round((price / max(float(units), 0.01)) / 0.60, 2) if price else 0
            sell_str = f"${sell:.2f}" if sell else "  —"
        except (TypeError, ValueError):
            sell_str = "  —"
        print(f"  {key:<{col_w}}  {pos:<45}  {units!s:>5}  {sell_str:>6}  {conf:<6}  {notes}")

    # Write staged CSV
    _write_staged(matches, unmatched)
    print()
    print(f"  Staged file written: {STAGED_CSV.relative_to(ROOT)}")
    print()
    print("Next steps:")
    print("  1. Review the staged CSV — edit pos_name / units, delete unwanted rows.")
    print("  2. Run:  python suggest_pg_mappings.py --apply")
    print("  3. Run:  python parse_price_guide.py <excel>  to verify the new match rate.")
    print()
    print("Done.")


if __name__ == "__main__":
    main()
