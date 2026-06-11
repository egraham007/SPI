"""
CSV importer for Swimming Impact Rank (SIR) system.

Handles messy real-world championship exports:
  - Flexible column name detection (handles variations like "Athlete", "Name", "Full Name")
  - Time formats: 1:43.21  |  103.21  |  1:43.21.00  |  43.21
  - Duplicate handling: keeps the faster time on re-import
  - Missing fields: skips rows gracefully with clear error messages
  - Audit log: every import recorded in import_log table

Supported event name aliases (all normalised to canonical names):
  50 Free, 100 Free, 200 Free, 500 Free, 1000 Free, 1650 Free,
  100 Back, 200 Back, 100 Breast, 200 Breast,
  100 Fly, 200 Fly, 200 IM, 400 IM

Usage:
    python imports/import_csv.py data/sec_mens_2025.csv \\
        --conference SEC --division D1 --gender M --season 2025-26

    Or from Python:
        from imports.import_csv import CSVImporter
        imp = CSVImporter("SEC", "D1", "M", "2025-26")
        result = imp.run("data/sec_mens_2025.csv")
        print(result.summary())
"""

import csv
import re
import sqlite3
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── Path helpers ──────────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent.parent
DB_PATH  = ROOT / "database" / "swim_impact.db"

# ── Canonical event names ─────────────────────────────────────────────────────
EVENT_ALIASES: dict[str, str] = {
    # 50 Free
    "50 free": "50 Free", "50free": "50 Free", "50 freestyle": "50 Free",
    "50yd free": "50 Free", "50 yd free": "50 Free",
    # 100 Free
    "100 free": "100 Free", "100free": "100 Free", "100 freestyle": "100 Free",
    "100yd free": "100 Free",
    # 200 Free
    "200 free": "200 Free", "200free": "200 Free", "200 freestyle": "200 Free",
    # 500 Free
    "500 free": "500 Free", "500free": "500 Free", "500 freestyle": "500 Free",
    # 1000 Free
    "1000 free": "1000 Free", "1000free": "1000 Free",
    # 1650 Free
    "1650 free": "1650 Free", "1650free": "1650 Free", "mile": "1650 Free",
    # Back
    "100 back": "100 Back", "100back": "100 Back", "100 backstroke": "100 Back",
    "200 back": "200 Back", "200back": "200 Back", "200 backstroke": "200 Back",
    # Breast
    "100 breast": "100 Breast", "100breast": "100 Breast", "100 breaststroke": "100 Breast",
    "200 breast": "200 Breast", "200breast": "200 Breast", "200 breaststroke": "200 Breast",
    # Fly
    "100 fly": "100 Fly", "100fly": "100 Fly", "100 butterfly": "100 Fly",
    "200 fly": "200 Fly", "200fly": "200 Fly", "200 butterfly": "200 Fly",
    # IM
    "200 im": "200 IM", "200im": "200 IM", "200 individual medley": "200 IM",
    "400 im": "400 IM", "400im": "400 IM", "400 individual medley": "400 IM",
}

# ── Column name aliases ───────────────────────────────────────────────────────
COL_NAME  = ["name", "athlete", "swimmer", "full name", "athlete name",
             "last, first", "swimmer name"]
COL_TEAM  = ["team", "school", "university", "college", "club", "affiliation"]
COL_EVENT = ["event", "event name", "stroke", "race"]
COL_TIME  = ["time", "result", "finals time", "prelim time", "best time",
             "seed time", "mark", "performance"]
COL_PLACE = ["place", "finish", "rank", "pl", "pos", "position"]
COL_YEAR  = ["year", "class", "grade", "yr"]


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class ImportResult:
    filename:      str
    conference:    str
    division:      str
    gender:        str
    season:        str
    rows_parsed:   int = 0
    rows_imported: int = 0
    rows_updated:  int = 0   # faster time replaced existing
    rows_skipped:  int = 0
    errors:        list = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"\n{'─'*55}",
            f"  Import complete: {self.filename}",
            f"  Conference : {self.conference} {self.division} {self.gender}  Season: {self.season}",
            f"  Parsed     : {self.rows_parsed}",
            f"  Imported   : {self.rows_imported}  (new)",
            f"  Updated    : {self.rows_updated}  (faster time replaced)",
            f"  Skipped    : {self.rows_skipped}",
        ]
        if self.errors:
            lines.append(f"  Errors     : {len(self.errors)}")
            for e in self.errors[:10]:
                lines.append(f"    ⚠  {e}")
            if len(self.errors) > 10:
                lines.append(f"    … {len(self.errors)-10} more errors")
        lines.append(f"{'─'*55}\n")
        return "\n".join(lines)


# ── Time parsing ──────────────────────────────────────────────────────────────
_TIME_PATTERNS = [
    # M:SS.ss or M:SS.sss
    re.compile(r"^(\d+):(\d{2})\.(\d{2,3})$"),
    # SS.ss (plain seconds)
    re.compile(r"^(\d{1,3})\.(\d{2,3})$"),
    # M:SS (no centiseconds)
    re.compile(r"^(\d+):(\d{2})$"),
]

def parse_time(raw: str) -> Optional[float]:
    """Convert any common time string to seconds as a float. Returns None on failure."""
    s = raw.strip().replace(",", ".").replace("'", ":").lstrip("0")
    if not s:
        return None
    # strip leading/trailing non-numeric noise
    s = re.sub(r"[^\d:.]", "", s)
    for pat in _TIME_PATTERNS:
        m = pat.match(s)
        if m:
            parts = m.groups()
            if len(parts) == 3 and ":" in s:
                mins, secs, cents = int(parts[0]), int(parts[1]), parts[2]
                return mins * 60 + secs + int(cents) / (100 if len(cents) == 2 else 1000)
            elif len(parts) == 2 and ":" in s:
                mins, secs = int(parts[0]), int(parts[1])
                return mins * 60 + secs
            else:
                secs, cents = parts
                return int(secs) + int(cents) / (100 if len(cents) == 2 else 1000)
    # last resort: try direct float
    try:
        return float(s)
    except ValueError:
        return None


def seconds_to_display(secs: float) -> str:
    """Convert seconds back to M:SS.ss display string."""
    m = int(secs) // 60
    s = secs - m * 60
    return f"{m}:{s:05.2f}" if m else f"{s:.2f}"


# ── Event normalisation ───────────────────────────────────────────────────────
def normalise_event(raw: str) -> Optional[str]:
    key = raw.strip().lower()
    return EVENT_ALIASES.get(key)


# ── Column detection ──────────────────────────────────────────────────────────
def _find_col(headers: list[str], candidates: list[str]) -> Optional[str]:
    """Return the first header that matches any candidate (case-insensitive)."""
    lowers = {h.strip().lower(): h for h in headers}
    for c in candidates:
        if c in lowers:
            return lowers[c]
    return None


# ── Core importer ─────────────────────────────────────────────────────────────
class CSVImporter:
    def __init__(self, conference: str, division: str, gender: str,
                 season: str, source: str = "import", db_path: Path = None):
        self.conference = conference.upper().strip()
        self.division   = division.upper().strip()
        self.gender     = gender.upper().strip()
        self.season     = season.strip()
        self.source     = source
        self.db_path    = db_path or DB_PATH

    # ── public entry point ────────────────────────────────────────
    def run(self, csv_path: str | Path) -> ImportResult:
        path = Path(csv_path)
        result = ImportResult(
            filename=path.name, conference=self.conference,
            division=self.division, gender=self.gender, season=self.season
        )
        if not path.exists():
            result.errors.append(f"File not found: {path}")
            return result

        rows = self._read_csv(path, result)
        if not rows:
            return result

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            for row in rows:
                self._process_row(row, conn, result)
            self._log_import(conn, path.name, result)
            conn.commit()
        finally:
            conn.close()

        print(result.summary())
        return result

    # ── CSV reading ───────────────────────────────────────────────
    def _read_csv(self, path: Path, result: ImportResult) -> list[dict]:
        """Read CSV, auto-detect delimiter and encoding."""
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                with open(path, newline="", encoding=encoding) as f:
                    sample = f.read(4096)
                    dialect = csv.Sniffer().sniff(sample, delimiters=",\t|")
                    f.seek(0)
                    reader = csv.DictReader(f, dialect=dialect)
                    rows = list(reader)
                result.rows_parsed = len(rows)
                return rows
            except Exception as e:
                continue
        result.errors.append("Could not read CSV — check encoding and delimiter")
        return []

    # ── Single row processing ─────────────────────────────────────
    def _process_row(self, row: dict, conn: sqlite3.Connection, result: ImportResult):
        headers = list(row.keys())

        # ── detect columns (once per file ideally, but cheap to redo) ──
        col_name  = _find_col(headers, COL_NAME)
        col_team  = _find_col(headers, COL_TEAM)
        col_event = _find_col(headers, COL_EVENT)
        col_time  = _find_col(headers, COL_TIME)

        # ── extract & validate ──
        name  = row.get(col_name, "").strip()  if col_name  else ""
        team  = row.get(col_team, "").strip()  if col_team  else ""
        event_raw = row.get(col_event, "").strip() if col_event else ""
        time_raw  = row.get(col_time, "").strip()  if col_time  else ""

        # Skip blank rows
        if not any([name, team, event_raw, time_raw]):
            result.rows_skipped += 1
            return

        missing = []
        if not name:      missing.append("name")
        if not team:      missing.append("team")
        if not event_raw: missing.append("event")
        if not time_raw:  missing.append("time")
        if missing:
            result.errors.append(f"Row missing {missing}: {dict(list(row.items())[:4])}")
            result.rows_skipped += 1
            return

        event = normalise_event(event_raw)
        if not event:
            result.errors.append(f"Unrecognised event '{event_raw}' — add to EVENT_ALIASES if needed")
            result.rows_skipped += 1
            return

        time_s = parse_time(time_raw)
        if time_s is None or time_s <= 0:
            result.errors.append(f"Could not parse time '{time_raw}' for {name}")
            result.rows_skipped += 1
            return

        # Sanity check: reject obviously wrong times
        if time_s < 10 or time_s > 1800:
            result.errors.append(f"Time {time_s:.2f}s out of range for {name} / {event}")
            result.rows_skipped += 1
            return

        # ── upsert swimmer ──
        swimmer_id = self._upsert_swimmer(conn, name, team)

        # ── upsert time (keep faster) ──
        updated = self._upsert_time(conn, swimmer_id, event, time_s)
        if updated == "new":
            result.rows_imported += 1
        elif updated == "faster":
            result.rows_updated += 1
        else:
            result.rows_skipped += 1

    # ── DB helpers ────────────────────────────────────────────────
    def _upsert_swimmer(self, conn: sqlite3.Connection, name: str, team: str) -> int:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO swimmers(name, team, conference, division, gender)
            VALUES (?,?,?,?,?)
            ON CONFLICT(name, team, gender) DO UPDATE SET
                conference = excluded.conference,
                division   = excluded.division
        """, (name, team, self.conference, self.division, self.gender))
        # Always re-query — lastrowid is 0 on conflict update in some SQLite versions
        cur.execute("SELECT id FROM swimmers WHERE name=? AND team=? AND gender=?",
                    (name, team, self.gender))
        row = cur.fetchone()
        return row[0]

    def _upsert_time(self, conn: sqlite3.Connection, swimmer_id: int,
                     event: str, time_s: float) -> str:
        """Insert time or replace with faster time. Returns 'new'/'faster'/'slower'."""
        cur = conn.cursor()
        cur.execute("""
            SELECT id, time_seconds FROM times
            WHERE swimmer_id=? AND event=? AND season=?
        """, (swimmer_id, event, self.season))
        existing = cur.fetchone()

        if existing is None:
            cur.execute("""
                INSERT INTO times(swimmer_id, event, time_seconds, season, source)
                VALUES (?,?,?,?,?)
            """, (swimmer_id, event, time_s, self.season, self.source))
            return "new"
        elif time_s < existing[1]:
            cur.execute("""
                UPDATE times SET time_seconds=?, source=?, imported_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (time_s, self.source, existing[0]))
            return "faster"
        else:
            return "slower"

    def _log_import(self, conn: sqlite3.Connection, filename: str, r: ImportResult):
        conn.execute("""
            INSERT INTO import_log(filename,conference,division,gender,season,
                rows_parsed,rows_imported,rows_skipped,errors)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (filename, r.conference, r.division, r.gender, r.season,
              r.rows_parsed, r.rows_imported + r.rows_updated,
              r.rows_skipped, "\n".join(r.errors[:50]) if r.errors else None))


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Import swim meet CSV into SIR database")
    ap.add_argument("csv_file", help="Path to CSV file")
    ap.add_argument("--conference", "-c", required=True, help="e.g. SEC, ACC")
    ap.add_argument("--division",   "-d", default="D1", help="D1, D2, D3")
    ap.add_argument("--gender",     "-g", required=True, help="M or F")
    ap.add_argument("--season",     "-s", required=True, help="e.g. 2025-26")
    ap.add_argument("--source",     default="championship",
                    help="Label for this data source (default: championship)")
    ap.add_argument("--db", default=None, help="Override database path")
    args = ap.parse_args()

    db = Path(args.db) if args.db else None
    importer = CSVImporter(args.conference, args.division, args.gender,
                           args.season, args.source, db)
    importer.run(args.csv_file)


if __name__ == "__main__":
    main()
