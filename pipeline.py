"""
SIR Master Pipeline
====================
One command to:
  1. Initialize the database (if needed)
  2. Import all CSVs from the data/ directory
  3. Build percentile benchmarks
  4. Build event rankings
  5. Build SIR impact scores
  6. Export updated benchmarks.js for the website

Usage:
    # Import everything and rebuild
    python pipeline.py --season 2025-26

    # Import a single file
    python pipeline.py --file data/sec_m_2025_26.csv --conference SEC --gender M --season 2025-26

    # Rebuild rankings only (no re-import)
    python pipeline.py --season 2025-26 --rebuild-only

    # Generate sample data then run full pipeline
    python pipeline.py --season 2025-26 --generate-samples
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from database.db_init          import init_database, DB_PATH
from imports.import_csv        import CSVImporter
from analytics.build_benchmarks import run_full_pipeline
from analytics.export_js        import export_benchmarks_js

# Map CSV filename patterns to (conference, division, gender)
# Covers common naming conventions — edit to match your files
FILENAME_PATTERNS = [
    # Pattern: contains both conference slug and gender letter
    ("sec_m",          "SEC",          "D1", "M"),
    ("sec_f",          "SEC",          "D1", "F"),
    ("sec_w",          "SEC",          "D1", "F"),
    ("acc_m",          "ACC",          "D1", "M"),
    ("acc_f",          "ACC",          "D1", "F"),
    ("acc_w",          "ACC",          "D1", "F"),
    ("big10_m",        "Big 10",       "D1", "M"),
    ("big10_f",        "Big 10",       "D1", "F"),
    ("big_10_m",       "Big 10",       "D1", "M"),
    ("big_10_f",       "Big 10",       "D1", "F"),
    ("pac12_m",        "Pac-12",       "D1", "M"),
    ("pac12_f",        "Pac-12",       "D1", "F"),
    ("pac_12_m",       "Pac-12",       "D1", "M"),
    ("pac_12_f",       "Pac-12",       "D1", "F"),
    ("patriot_m",      "Patriot League","D1","M"),
    ("patriot_f",      "Patriot League","D1","F"),
    ("patriot_w",      "Patriot League","D1","F"),
    ("big12_m",        "Big 12",       "D1", "M"),
    ("big12_f",        "Big 12",       "D1", "F"),
    ("mpsf_m",         "MPSF",         "D1", "M"),
    ("mpsf_f",         "MPSF",         "D1", "F"),
    ("ivy_m",          "Ivy League",   "D1", "M"),
    ("ivy_f",          "Ivy League",   "D1", "F"),
    ("a10_m",          "Atlantic 10",  "D1", "M"),
    ("a10_f",          "Atlantic 10",  "D1", "F"),
    # Generic generate_sample_data.py output format
    # e.g. "sec_m_2025_26.csv"
]


def detect_conf_gender(filepath: Path) -> tuple[str, str, str] | None:
    """Try to detect (conference, division, gender) from filename."""
    name = filepath.stem.lower()
    for pattern, conf, div, gender in FILENAME_PATTERNS:
        if pattern in name:
            return conf, div, gender
    return None


def import_directory(data_dir: Path, season: str, source: str = "championship") -> list:
    """Import all CSVs in a directory, auto-detecting conference/gender."""
    csvs = sorted(data_dir.glob("*.csv"))
    if not csvs:
        print(f"  No CSV files found in {data_dir}")
        return []

    results = []
    skipped = []
    for csv_path in csvs:
        detected = detect_conf_gender(csv_path)
        if not detected:
            skipped.append(csv_path.name)
            continue
        conf, div, gender = detected
        print(f"\n  Importing {csv_path.name} → {conf} {div} {gender}")
        importer = CSVImporter(conf, div, gender, season, source)
        result = importer.run(csv_path)
        results.append(result)

    if skipped:
        print(f"\n  ⚠  Skipped (could not detect conference/gender): {skipped}")
        print(f"     Use --file with explicit --conference and --gender flags instead.")

    return results


def main():
    ap = argparse.ArgumentParser(description="SIR Master Pipeline")
    ap.add_argument("--season",     "-s", required=True, help="e.g. 2025-26")
    ap.add_argument("--file",       "-f", default=None,  help="Import single CSV file")
    ap.add_argument("--conference", "-c", default=None,  help="Required with --file")
    ap.add_argument("--division",   "-d", default="D1",  help="Required with --file")
    ap.add_argument("--gender",     "-g", default=None,  help="Required with --file: M or F")
    ap.add_argument("--data-dir",         default="data", help="Directory of CSVs to import")
    ap.add_argument("--source",           default="championship")
    ap.add_argument("--rebuild-only",     action="store_true",
                    help="Skip import, just rebuild rankings and export")
    ap.add_argument("--generate-samples", action="store_true",
                    help="Generate sample CSV data before importing")
    ap.add_argument("--export-js",        default=None,
                    help="Path for benchmarks.js output")
    ap.add_argument("--db",               default=None)
    args = ap.parse_args()

    db = Path(args.db) if args.db else None

    # ── 0. Init DB ──────────────────────────────────────────────
    print(f"\n{'═'*60}")
    print(f"  SIR PIPELINE  —  Season: {args.season}")
    print(f"{'═'*60}")
    print("\n[0] Initializing database...")
    init_database(db)

    # ── Optional: generate sample data ─────────────────────────
    if args.generate_samples:
        print("\n[*] Generating sample CSV data...")
        from data.generate_sample_data import main as gen_main
        gen_main()

    # ── 1. Import ───────────────────────────────────────────────
    if not args.rebuild_only:
        print("\n[1] Importing data...")
        if args.file:
            if not args.conference or not args.gender:
                ap.error("--conference and --gender required when using --file")
            importer = CSVImporter(
                args.conference, args.division, args.gender,
                args.season, args.source, db
            )
            importer.run(args.file)
        else:
            data_dir = Path(args.data_dir)
            import_directory(data_dir, args.season, args.source)
    else:
        print("\n[1] Skipping import (--rebuild-only)")

    # ── 2. Build rankings for all conferences/genders in DB ────
    print("\n[2] Building benchmarks and rankings...")
    import sqlite3
    conn = sqlite3.connect(db or DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT s.conference, s.division, s.gender
        FROM swimmers s
        JOIN times t ON s.id = t.swimmer_id
        WHERE t.season=?
        ORDER BY s.conference, s.gender
    """, (args.season,))
    combos = cur.fetchall()
    conn.close()

    if not combos:
        print("  No data found in database for this season.")
        print(f"  Import some CSV files first: python pipeline.py --season {args.season}")
        sys.exit(0)

    for row in combos:
        run_full_pipeline(row[0], row[1], row[2], args.season, db)

    # ── 3. Export JS ────────────────────────────────────────────
    print("\n[3] Exporting benchmarks.js for website...")
    js_out = Path(args.export_js) if args.export_js else None
    export_benchmarks_js(args.season, js_out, db)

    print(f"\n{'═'*60}")
    print(f"  ✓ Pipeline complete — {args.season}")
    print(f"  Database: {db or DB_PATH}")
    print(f"{'═'*60}\n")


if __name__ == "__main__":
    main()
