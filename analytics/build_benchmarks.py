"""
Benchmark & ranking calculator for Swimming Impact Rank (SIR) system.

Two main jobs:
  1. build_benchmarks()  — compute p10/p25/p50/p75/p90 per conference/event/gender/season
                           and write to conference_benchmarks table
  2. build_rankings()    — rank every swimmer within their conference for each event,
                           then calculate SIR impact scores

Run after every import:
    python analytics/build_benchmarks.py --conference SEC --gender M --season 2025-26

Or rebuild everything:
    python analytics/build_benchmarks.py --all --season 2025-26
"""

import sqlite3
import argparse
import statistics
from pathlib import Path
from typing import Optional

ROOT    = Path(__file__).parent.parent
DB_PATH = ROOT / "database" / "swim_impact.db"

# Weight per event in the SIR formula.
# Three primary events × 28.33% = 85%. Relay contribution = 15% (future).
EVENT_WEIGHT = 0.2833


def get_conn(db_path: Path = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


# ── Percentile helper ─────────────────────────────────────────────────────────
def percentile(sorted_data: list[float], pct: float) -> float:
    """Linear interpolation percentile on sorted ascending data."""
    n = len(sorted_data)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_data[0]
    idx = (pct / 100) * (n - 1)
    lo, hi = int(idx), min(int(idx) + 1, n - 1)
    return sorted_data[lo] + (idx - lo) * (sorted_data[hi] - sorted_data[lo])


# ── 1. Build benchmarks ───────────────────────────────────────────────────────
def build_benchmarks(conference: str, division: str, gender: str,
                     season: str, db_path: Path = None) -> int:
    """
    Compute percentile distributions for every event in a conference/season.
    Returns number of benchmark rows written.
    """
    conn = get_conn(db_path)
    cur  = conn.cursor()

    # Get all distinct events this conference has data for
    cur.execute("""
        SELECT DISTINCT t.event
        FROM times t
        JOIN swimmers s ON t.swimmer_id = s.id
        WHERE s.conference=? AND s.division=? AND s.gender=? AND t.season=?
        ORDER BY t.event
    """, (conference, division, gender, season))
    events = [r[0] for r in cur.fetchall()]

    if not events:
        print(f"  No data found for {conference} {division} {gender} {season}")
        conn.close()
        return 0

    count = 0
    for event in events:
        cur.execute("""
            SELECT t.time_seconds
            FROM times t
            JOIN swimmers s ON t.swimmer_id = s.id
            WHERE s.conference=? AND s.division=? AND s.gender=?
                  AND t.season=? AND t.event=?
            ORDER BY t.time_seconds ASC
        """, (conference, division, gender, season, event))
        times = [r[0] for r in cur.fetchall()]

        if len(times) < 3:
            continue  # not enough data to be meaningful

        bench = {
            "conference": conference,
            "division":   division,
            "gender":     gender,
            "season":     season,
            "event":      event,
            "n":          len(times),
            "p10":        percentile(times, 10),
            "p25":        percentile(times, 25),
            "p50":        percentile(times, 50),
            "p75":        percentile(times, 75),
            "p90":        percentile(times, 90),
            "p_min":      times[0],
            "p_max":      times[-1],
        }

        cur.execute("""
            INSERT INTO conference_benchmarks
                (conference,division,gender,season,event,n,p10,p25,p50,p75,p90,p_min,p_max)
            VALUES (:conference,:division,:gender,:season,:event,:n,
                    :p10,:p25,:p50,:p75,:p90,:p_min,:p_max)
            ON CONFLICT(conference,division,gender,season,event) DO UPDATE SET
                n=excluded.n, p10=excluded.p10, p25=excluded.p25,
                p50=excluded.p50, p75=excluded.p75, p90=excluded.p90,
                p_min=excluded.p_min, p_max=excluded.p_max,
                calculated_at=CURRENT_TIMESTAMP
        """, bench)
        count += 1
        print(f"  ✓ {conference} {gender} {event}: n={len(times)}, "
              f"median={bench['p50']:.2f}s")

    conn.commit()
    conn.close()
    return count


# ── 2. Build event rankings ───────────────────────────────────────────────────
def build_event_rankings(conference: str, division: str, gender: str,
                          season: str, db_path: Path = None) -> int:
    """
    Rank every swimmer within their conference for each event.
    Swimmers tied on time share the same rank (dense rank).
    Returns total ranking rows written.
    """
    conn = get_conn(db_path)
    cur  = conn.cursor()

    cur.execute("""
        SELECT DISTINCT t.event
        FROM times t
        JOIN swimmers s ON t.swimmer_id = s.id
        WHERE s.conference=? AND s.division=? AND s.gender=? AND t.season=?
    """, (conference, division, gender, season))
    events = [r[0] for r in cur.fetchall()]

    total = 0
    for event in events:
        cur.execute("""
            SELECT s.id, t.time_seconds
            FROM times t
            JOIN swimmers s ON t.swimmer_id = s.id
            WHERE s.conference=? AND s.division=? AND s.gender=?
                  AND t.season=? AND t.event=?
            ORDER BY t.time_seconds ASC
        """, (conference, division, gender, season, event))
        rows = cur.fetchall()
        n = len(rows)
        if not rows:
            continue

        # Dense rank (equal times → same rank)
        rank = 1
        prev_time = None
        for i, (swimmer_id, time_s) in enumerate(rows):
            if prev_time is not None and time_s != prev_time:
                rank = i + 1
            cur.execute("""
                INSERT INTO event_rankings
                    (swimmer_id,event,conference,division,gender,season,rank,total,time_seconds)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(swimmer_id,event,conference,season) DO UPDATE SET
                    rank=excluded.rank, total=excluded.total,
                    time_seconds=excluded.time_seconds,
                    calculated_at=CURRENT_TIMESTAMP
            """, (swimmer_id, event, conference, division, gender, season, rank, n, time_s))
            prev_time = time_s
            total += 1

    conn.commit()
    conn.close()
    return total


# ── 3. Build SIR impact scores ────────────────────────────────────────────────
# Priority order: the events that contribute most at conference champs
PRIORITY_EVENTS = [
    "100 Free", "50 Free", "200 Free",
    "100 Fly",  "200 Fly",
    "100 Back", "200 Back",
    "100 Breast","200 Breast",
    "200 IM",   "400 IM",
    "500 Free", "1650 Free", "1000 Free",
]

def build_impact_scores(conference: str, division: str, gender: str,
                        season: str, db_path: Path = None) -> int:
    """
    Calculate SIR score for every swimmer who has ≥1 ranked event.
    Uses best 3 events weighted equally (28.33% each).
    Returns number of impact score rows written.
    """
    conn = get_conn(db_path)
    cur  = conn.cursor()

    # Get all swimmers with rankings in this conference
    cur.execute("""
        SELECT DISTINCT swimmer_id FROM event_rankings
        WHERE conference=? AND division=? AND gender=? AND season=?
    """, (conference, division, gender, season))
    swimmer_ids = [r[0] for r in cur.fetchall()]

    count = 0
    for sid in swimmer_ids:
        # Get all their event rankings, sorted by priority then by rank percentile
        cur.execute("""
            SELECT event, rank, total FROM event_rankings
            WHERE swimmer_id=? AND conference=? AND division=? AND gender=? AND season=?
        """, (sid, conference, division, gender, season))
        raw = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

        if not raw:
            continue

        # Sort by priority list first, then pick best 3 by percentile rank
        def sort_key(ev_data):
            ev, (rank, total) = ev_data
            prio = PRIORITY_EVENTS.index(ev) if ev in PRIORITY_EVENTS else 99
            pct  = rank / total
            return (pct, prio)

        sorted_events = sorted(raw.items(), key=sort_key)
        top3 = sorted_events[:3]

        # SIR score: weighted sum of (rank/total) mapped to 1.0–5.0 scale
        sir = 0.0
        for ev, (rank, total) in top3:
            pct  = (rank - 1) / max(total - 1, 1)   # 0.0 = best, 1.0 = worst
            sir += (1 + pct * 4) * EVENT_WEIGHT

        # Normalise if fewer than 3 events (scale up so score stays comparable)
        sir = sir * (3 / len(top3))

        # Ordinal impact rank within conference (calculated after all scores computed)
        # We'll set a placeholder and update in a second pass
        e = [None]*6
        for i, (ev, (rank, total)) in enumerate(top3[:3]):
            e[i*2]   = ev
            e[i*2+1] = rank

        cur.execute("""
            INSERT INTO impact_scores
                (swimmer_id,conference,division,gender,season,
                 sir_score,impact_rank,events_used,
                 e1_event,e1_rank,e1_total,
                 e2_event,e2_rank,e2_total,
                 e3_event,e3_rank,e3_total)
            VALUES (?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(swimmer_id,conference,season) DO UPDATE SET
                sir_score=excluded.sir_score,
                events_used=excluded.events_used,
                e1_event=excluded.e1_event, e1_rank=excluded.e1_rank, e1_total=excluded.e1_total,
                e2_event=excluded.e2_event, e2_rank=excluded.e2_rank, e2_total=excluded.e2_total,
                e3_event=excluded.e3_event, e3_rank=excluded.e3_rank, e3_total=excluded.e3_total,
                calculated_at=CURRENT_TIMESTAMP
        """, (
            sid, conference, division, gender, season,
            round(sir, 4), len(top3),
            top3[0][0] if len(top3)>0 else None,
            top3[0][1][0] if len(top3)>0 else None,
            top3[0][1][1] if len(top3)>0 else None,
            top3[1][0] if len(top3)>1 else None,
            top3[1][1][0] if len(top3)>1 else None,
            top3[1][1][1] if len(top3)>1 else None,
            top3[2][0] if len(top3)>2 else None,
            top3[2][1][0] if len(top3)>2 else None,
            top3[2][1][1] if len(top3)>2 else None,
        ))
        count += 1

    # Second pass: assign ordinal impact_rank (1 = lowest sir_score = best)
    cur.execute("""
        SELECT id, ROW_NUMBER() OVER (ORDER BY sir_score ASC) as rn
        FROM impact_scores
        WHERE conference=? AND division=? AND gender=? AND season=?
    """, (conference, division, gender, season))
    for row in cur.fetchall():
        cur.execute("UPDATE impact_scores SET impact_rank=? WHERE id=?",
                    (row[0], row[1]))  # sqlite3.Row: row["rn"] and row["id"]

    # Fix: sqlite3.Row doesn't work like that — do it properly
    cur.execute("""
        SELECT id FROM impact_scores
        WHERE conference=? AND division=? AND gender=? AND season=?
        ORDER BY sir_score ASC
    """, (conference, division, gender, season))
    ids = [r[0] for r in cur.fetchall()]
    for rank, id_ in enumerate(ids, 1):
        cur.execute("UPDATE impact_scores SET impact_rank=? WHERE id=?", (rank, id_))

    conn.commit()
    conn.close()
    return count


# ── 4. Full pipeline ──────────────────────────────────────────────────────────
def run_full_pipeline(conference: str, division: str, gender: str,
                      season: str, db_path: Path = None):
    """Run benchmarks → event rankings → impact scores in sequence."""
    print(f"\n{'═'*55}")
    print(f"  SIR Pipeline: {conference} {division} {gender} {season}")
    print(f"{'═'*55}")

    print("\n[1/3] Building percentile benchmarks...")
    n = build_benchmarks(conference, division, gender, season, db_path)
    print(f"  → {n} benchmark distributions written")

    print("\n[2/3] Ranking swimmers by event...")
    n = build_event_rankings(conference, division, gender, season, db_path)
    print(f"  → {n} event ranking rows written")

    print("\n[3/3] Calculating SIR impact scores...")
    n = build_impact_scores(conference, division, gender, season, db_path)
    print(f"  → {n} impact scores written")

    print(f"\n✓ Pipeline complete for {conference} {gender} {season}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Build SIR benchmarks and rankings")
    ap.add_argument("--conference", "-c", help="e.g. SEC, ACC (omit for --all)")
    ap.add_argument("--division",   "-d", default="D1")
    ap.add_argument("--gender",     "-g", help="M or F (omit for --all)")
    ap.add_argument("--season",     "-s", required=True, help="e.g. 2025-26")
    ap.add_argument("--all",        action="store_true",
                    help="Rebuild all conferences/genders found in DB for this season")
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    db = Path(args.db) if args.db else None

    if args.all:
        conn = get_conn(db)
        cur  = conn.cursor()
        cur.execute("""
            SELECT DISTINCT s.conference, s.division, s.gender
            FROM swimmers s
            JOIN times t ON s.id = t.swimmer_id
            WHERE t.season=?
            ORDER BY s.conference, s.gender
        """, (args.season,))
        combos = cur.fetchall()
        conn.close()
        for conf, div, gender in combos:
            run_full_pipeline(conf, div, gender, args.season, db)
    else:
        if not args.conference or not args.gender:
            ap.error("--conference and --gender required unless using --all")
        run_full_pipeline(args.conference, args.division, args.gender, args.season, db)


if __name__ == "__main__":
    main()
