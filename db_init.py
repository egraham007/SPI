"""
Database initialization for Swimming Impact Rank (SIR) system.
Run this once to create the schema. Safe to re-run (CREATE IF NOT EXISTS).

Usage:
    python database/db_init.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "swim_impact.db"


def init_database(db_path: Path = None) -> Path:
    target = db_path or DB_PATH
    conn = sqlite3.connect(target)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    # ── swimmers ──────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS swimmers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            team        TEXT    NOT NULL,
            conference  TEXT    NOT NULL,
            division    TEXT    NOT NULL DEFAULT 'D1',
            gender      TEXT    NOT NULL CHECK(gender IN ('M','F')),
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, team, gender)
        )
    """)

    # ── times ─────────────────────────────────────────────────────
    # One best time per swimmer/event/season.
    # On re-import we keep the faster time (handled in import layer).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS times (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            swimmer_id  INTEGER NOT NULL REFERENCES swimmers(id) ON DELETE CASCADE,
            event       TEXT    NOT NULL,
            time_seconds REAL   NOT NULL,
            season      TEXT    NOT NULL,
            source      TEXT,                 -- e.g. 'conference_champs', 'dual_meet'
            imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(swimmer_id, event, season)
        )
    """)

    # ── event_rankings ────────────────────────────────────────────
    # Rank of every swimmer within their conference for a given event/season.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS event_rankings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            swimmer_id  INTEGER NOT NULL REFERENCES swimmers(id) ON DELETE CASCADE,
            event       TEXT    NOT NULL,
            conference  TEXT    NOT NULL,
            division    TEXT    NOT NULL,
            gender      TEXT    NOT NULL,
            season      TEXT    NOT NULL,
            rank        INTEGER NOT NULL,
            total       INTEGER NOT NULL,     -- total swimmers ranked in this event
            time_seconds REAL   NOT NULL,
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(swimmer_id, event, conference, season)
        )
    """)

    # ── impact_scores ─────────────────────────────────────────────
    # Final SIR score per swimmer/conference/season.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS impact_scores (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            swimmer_id   INTEGER NOT NULL REFERENCES swimmers(id) ON DELETE CASCADE,
            conference   TEXT    NOT NULL,
            division     TEXT    NOT NULL,
            gender       TEXT    NOT NULL,
            season       TEXT    NOT NULL,
            sir_score    REAL    NOT NULL,    -- 1.000 best, ~5.000 worst
            impact_rank  INTEGER NOT NULL,    -- ordinal rank within conference
            events_used  INTEGER NOT NULL,    -- how many events contributed
            e1_event     TEXT,
            e1_rank      INTEGER,
            e1_total     INTEGER,
            e2_event     TEXT,
            e2_rank      INTEGER,
            e2_total     INTEGER,
            e3_event     TEXT,
            e3_rank      INTEGER,
            e3_total     INTEGER,
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(swimmer_id, conference, season)
        )
    """)

    # ── conference_benchmarks ─────────────────────────────────────
    # Percentile distribution per conference/event/gender/season.
    # Built automatically after each import via build_benchmarks().
    # This is what the website JS reads instead of hardcoded values.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS conference_benchmarks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            conference  TEXT    NOT NULL,
            division    TEXT    NOT NULL,
            gender      TEXT    NOT NULL,
            season      TEXT    NOT NULL,
            event       TEXT    NOT NULL,
            n           INTEGER NOT NULL,     -- number of swimmers in sample
            p10         REAL    NOT NULL,
            p25         REAL    NOT NULL,
            p50         REAL    NOT NULL,
            p75         REAL    NOT NULL,
            p90         REAL    NOT NULL,
            p_min       REAL    NOT NULL,
            p_max       REAL    NOT NULL,
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(conference, division, gender, season, event)
        )
    """)

    # ── import_log ────────────────────────────────────────────────
    # Audit trail of every CSV import.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS import_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            filename     TEXT    NOT NULL,
            conference   TEXT    NOT NULL,
            division     TEXT    NOT NULL,
            gender       TEXT    NOT NULL,
            season       TEXT    NOT NULL,
            rows_parsed  INTEGER NOT NULL DEFAULT 0,
            rows_imported INTEGER NOT NULL DEFAULT 0,
            rows_skipped  INTEGER NOT NULL DEFAULT 0,
            errors       TEXT,
            imported_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── indexes ───────────────────────────────────────────────────
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_swimmers_conf     ON swimmers(conference)",
        "CREATE INDEX IF NOT EXISTS idx_swimmers_team     ON swimmers(team)",
        "CREATE INDEX IF NOT EXISTS idx_swimmers_gender   ON swimmers(gender)",
        "CREATE INDEX IF NOT EXISTS idx_times_swimmer     ON times(swimmer_id)",
        "CREATE INDEX IF NOT EXISTS idx_times_event       ON times(event)",
        "CREATE INDEX IF NOT EXISTS idx_times_season      ON times(season)",
        "CREATE INDEX IF NOT EXISTS idx_rankings_conf     ON event_rankings(conference, event, season)",
        "CREATE INDEX IF NOT EXISTS idx_rankings_swimmer  ON event_rankings(swimmer_id)",
        "CREATE INDEX IF NOT EXISTS idx_impact_conf       ON impact_scores(conference, season)",
        "CREATE INDEX IF NOT EXISTS idx_impact_swimmer    ON impact_scores(swimmer_id)",
        "CREATE INDEX IF NOT EXISTS idx_benchmarks_lookup ON conference_benchmarks(conference, gender, season, event)",
    ]
    for idx in indexes:
        cur.execute(idx)

    conn.commit()
    conn.close()
    print(f"✓ Database ready: {target}")
    return target


if __name__ == "__main__":
    init_database()
