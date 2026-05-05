"""
parse_specials_sheet.py — Foodland Wudinna Fruit & Veg
Ingest a weekly specials bulletin and produce a structured specials list
for the order sheet generator.

Current capability:
    Accepts a JPEG/PNG image of the bulletin and applies specials_mapping.csv
    to resolve bulletin descriptions → POS item names. The actual text
    extraction from images is scaffolded below but currently requires manual
    input confirmation until OCR or LLM-based extraction is wired in.

Planned capability (future):
    • XLSX/DOCX input: parse structured Foodland catalogue files directly
    • Automated OCR: extract item names from bulletin image without manual step
    • LLM-based matching: fuzzy-match bulletin text → POS names even without
      a pre-built mapping entry

Usage:
    python parse_specials_sheet.py
    python parse_specials_sheet.py --bulletin path/to/bulletin.jpg
    python parse_specials_sheet.py --week-start 2026-04-08

Output:
    01_data/operational/specials_this_week.csv
    Schema: cycle_start (YYYY-MM-DD) | Name (POS item name)
"""

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT         = Path(__file__).parent.parent.parent   # foodland_wudinna/
MAPPING_CSV  = ROOT / "01_data" / "reference" / "specials_mapping.csv"
OUTPUT_CSV   = ROOT / "01_data" / "operational" / "specials_this_week.csv"


# ── Specials week helpers ──────────────────────────────────────────────────────

def current_specials_week_start(ref_date: date | None = None) -> date:
    """
    Return the Wednesday that started the current specials bulletin week.
    Specials weeks run Wednesday → Tuesday.
    """
    d = ref_date or date.today()
    # dayofweek: Mon=0 … Sun=6. Wednesday=2.
    days_since_wed = (d.weekday() - 2) % 7
    return d - timedelta(days=days_since_wed)


def next_specials_week_start(ref_date: date | None = None) -> date:
    """Return the Wednesday that starts NEXT week's specials bulletin."""
    return current_specials_week_start(ref_date) + timedelta(weeks=1)


# ── Mapping loader ─────────────────────────────────────────────────────────────

def load_mapping() -> list[dict]:
    """
    Load specials_mapping.csv.

    Returns a list of dicts with keys:
        bulletin_description, pos_name, supplier, verified, notes
    """
    if not MAPPING_CSV.exists():
        print(f"ERROR: Mapping file not found at {MAPPING_CSV}")
        sys.exit(1)

    with open(MAPPING_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── Bulletin extraction (scaffold) ────────────────────────────────────────────

def extract_items_from_image(image_path: Path) -> list[str]:
    """
    Extract item descriptions from a bulletin JPEG/PNG.

    CURRENT BEHAVIOUR: Returns empty list — image OCR not yet implemented.
    Operator is prompted to confirm items manually via the CLI.

    FUTURE: Replace this function body with:
        1. Tesseract OCR pass to get raw text
        2. Line-by-line matching against mapping['bulletin_description']
        3. Return matched descriptions for auto-selection
    """
    print(f"\nImage provided: {image_path.name}")
    print("Automated image extraction not yet implemented.")
    print("Items will be selected manually from the mapping list below.\n")
    return []


def extract_items_from_xlsx(xlsx_path: Path) -> list[str]:
    """
    Extract item descriptions from a structured Foodland catalogue XLSX.

    CURRENT BEHAVIOUR: Scaffold — not yet implemented.

    FUTURE: Read the 'Specials' sheet, extract 'Item Description' column,
    return as list of strings for matching against the mapping.
    """
    print(f"\nXLSX provided: {xlsx_path.name}")
    print("Catalogue XLSX parsing not yet implemented.")
    print("Items will be selected manually from the mapping list below.\n")
    return []


# ── Interactive selection ──────────────────────────────────────────────────────

def select_items_interactively(
    mapping: list[dict],
    pre_selected: list[str] | None = None,
) -> list[str]:
    """
    Present all mapped items and let the operator tick which are on special.

    pre_selected: list of bulletin_descriptions pre-extracted from image/xlsx.
    Returns a list of pos_names for selected items.
    """
    pre_set = set(pre_selected or [])
    selected_pos_names = []

    print("=" * 60)
    print("  SELECT ITEMS ON SPECIAL THIS WEEK")
    print("  Press Enter to skip, 'y' to include, 'n' to exclude.")
    print("  Items marked (auto) were found in the bulletin image.")
    print("=" * 60)

    supplier_groups: dict[str, list[dict]] = {}
    for row in mapping:
        sup = row["supplier"]
        supplier_groups.setdefault(sup, []).append(row)

    for supplier, items in sorted(supplier_groups.items()):
        print(f"\n── {supplier} ──")
        for item in items:
            desc    = item["bulletin_description"]
            pos     = item["pos_name"]
            is_auto = desc in pre_set
            verified = "(✓)" if item.get("verified", "false").lower() == "true" else "(?)"

            auto_tag = " [auto]" if is_auto else ""
            prompt = f"  {verified}{auto_tag} {desc} → {pos}\n  Include? [y/N]: "

            try:
                answer = input(prompt).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                sys.exit(0)

            if answer == "y":
                selected_pos_names.append(pos)

    return selected_pos_names


# ── Output writer ──────────────────────────────────────────────────────────────

def write_output(pos_names: list[str], week_start: date) -> None:
    """Write selected POS names to specials_this_week.csv."""
    week_str = week_start.strftime("%Y-%m-%d")
    rows = [{"cycle_start": week_str, "Name": name} for name in pos_names]

    # Read existing rows for other weeks and preserve them
    existing: list[dict] = []
    if OUTPUT_CSV.exists():
        with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("cycle_start") != week_str:
                    existing.append(row)

    all_rows = existing + rows

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["cycle_start", "Name"])
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\n✅ {len(pos_names)} item(s) written to {OUTPUT_CSV.name}")
    print(f"   Week starting: {week_str}")
    for name in pos_names:
        print(f"   • {name}")


# ── CLI entrypoint ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Parse the weekly Foodland specials bulletin and output "
                    "a structured specials list for the order sheet generator."
    )
    parser.add_argument(
        "--bulletin", "-b",
        type=Path, default=None,
        help="Path to the bulletin image (JPEG/PNG) or catalogue file (XLSX/DOCX).",
    )
    parser.add_argument(
        "--week-start", "-w",
        default=None,
        help="Specials week start date as YYYY-MM-DD (default: current Wednesday).",
    )
    parser.add_argument(
        "--next-week", "-n",
        action="store_true",
        help="Use NEXT week's start date instead of current.",
    )
    args = parser.parse_args()

    # Resolve week start date
    if args.week_start:
        week_start = date.fromisoformat(args.week_start)
    elif args.next_week:
        week_start = next_specials_week_start()
    else:
        week_start = current_specials_week_start()

    print(f"\nSpecials bulletin parser — Foodland Wudinna Fruit & Veg")
    print(f"Processing week starting: {week_start.strftime('%A %d %B %Y')}\n")

    # Load mapping
    mapping = load_mapping()

    # Extract from bulletin file (if provided)
    pre_selected: list[str] = []
    if args.bulletin:
        p = Path(args.bulletin)
        if not p.exists():
            print(f"ERROR: File not found: {p}")
            sys.exit(1)
        suffix = p.suffix.lower()
        if suffix in (".jpg", ".jpeg", ".png"):
            pre_selected = extract_items_from_image(p)
        elif suffix in (".xlsx", ".xls"):
            pre_selected = extract_items_from_xlsx(p)
        else:
            print(f"Unsupported file type: {suffix}")
            sys.exit(1)

    # Interactive selection
    pos_names = select_items_interactively(mapping, pre_selected)

    if not pos_names:
        print("\nNo items selected — output file not updated.")
        return

    # Write output
    write_output(pos_names, week_start)


if __name__ == "__main__":
    main()
