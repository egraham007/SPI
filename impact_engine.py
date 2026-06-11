"""
SIR Fractional Impact Score Engine
====================================
Uses actual ranked swim data (top-50 lists per conference/event) to calculate
precise fractional impact scores.

Key idea: instead of percentile curve estimation, we interpolate *between*
real ranked swims. The gap between #25 and #26 is real time — a swimmer at
the midpoint gets exactly 25.50, proportional to where they land in that gap.

Ties are handled properly: both #14 swimmers share rank 14. A new swimmer
faster than both gets <14.0. A swimmer between them (same time) ties at 14.0.
A swimmer between #14 and #16 interpolates across that gap.

Score scale:
  1.000  = exactly #1 time
  25.00  = exactly ties #25
  25.50  = halfway between #25 and #26
  50.00  = exactly ties #50
  50+    = slower than the list (extrapolated, clearly labeled "outside top 50")
"""

import csv as _csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class RankedSwim:
    rank: int           # official rank (ties share the same rank)
    name: str
    meet: str
    time: float         # seconds

@dataclass
class ImpactResult:
    time: float
    time_display: str
    score: float        # fractional impact score, e.g. 25.13
    rank_display: str   # e.g. "#25" or "~#26.3" or "Outside top 50"
    between_rank_lo: int
    between_rank_hi: Optional[int]
    between_name_lo: str
    between_name_hi: Optional[str]
    between_time_lo: float
    between_time_hi: Optional[float]
    pct_through_gap: float   # 0.0 = exactly at lo, 1.0 = exactly at hi
    in_list: bool            # False = slower than #50

    def summary(self) -> str:
        lines = []
        lines.append(f"\n{'─'*55}")
        lines.append(f"  Time submitted : {self.time_display}")
        lines.append(f"  Impact score   : {self.score:.3f}")
        lines.append(f"  Rank           : {self.rank_display}")

        if self.in_list:
            if self.between_rank_hi and self.between_name_hi:
                lines.append(f"\n  Sits between:")
                lines.append(f"    #{self.between_rank_lo}  {self.between_name_lo:<25} {self.between_time_lo:.2f}s")
                lines.append(f"    #{self.between_rank_hi}  {self.between_name_hi:<25} {self.between_time_hi:.2f}s")
                lines.append(f"    {self.pct_through_gap*100:.1f}% through that gap")
            else:
                lines.append(f"\n  Ties or leads #{self.between_rank_lo}: {self.between_name_lo} ({self.between_time_lo:.2f}s)")
        else:
            lines.append(f"\n  Slower than #{self.between_rank_lo} ({self.between_name_lo}, {self.between_time_lo:.2f}s)")
            lines.append(f"  Score extrapolated beyond the top-50 list")

        lines.append(f"{'─'*55}\n")
        return "\n".join(lines)


# ── CSV loader ────────────────────────────────────────────────────────────────

def load_ranked_list(csv_path: str | Path) -> list[RankedSwim]:
    """
    Load a top-N ranked swim list from CSV.

    Expected columns (flexible, detected by position or header):
      rank, name, [blank/school], meet, time

    Handles:
      - Ties (multiple rows with the same rank number)
      - Time as float (42.48) or string (42.48)
      - Optional header row
    """
    path = Path(csv_path)
    swims = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        # Peek to see if there's a header
        sample = f.read(512)
        f.seek(0)
        has_header = not sample.strip()[0].isdigit()
        reader = _csv.reader(f)
        if has_header:
            next(reader)

        for row in reader:
            if not row or not row[0].strip():
                continue
            try:
                rank = int(row[0].strip())
                name = row[1].strip()
                # Column 2 might be school (blank in this dataset) — skip
                # Column 3 = meet, column 4 = time
                if len(row) >= 5:
                    meet = row[3].strip()
                    time_raw = row[4].strip()
                elif len(row) == 4:
                    meet = row[2].strip()
                    time_raw = row[3].strip()
                else:
                    continue

                time_s = float(time_raw)
                swims.append(RankedSwim(rank=rank, name=name, meet=meet, time=time_s))
            except (ValueError, IndexError):
                continue

    # Sort by time ascending (fastest first), then by rank for ties
    swims.sort(key=lambda s: (s.time, s.rank))
    return swims


# ── Core engine ───────────────────────────────────────────────────────────────

class ImpactScoreEngine:
    """
    Calculates fractional impact scores by interpolating between real ranked swims.

    The score for any time T that falls between rank N (time_lo) and rank N+1 (time_hi):

        gap        = time_hi - time_lo
        pct        = (T - time_lo) / gap          # 0.0 at time_lo, 1.0 at time_hi
        score      = rank_lo + pct * (rank_hi - rank_lo)

    This means:
      - Equal times → same score (ties handled correctly)
      - Denser clusters → smaller score differences per hundredth
      - Bigger gaps → larger score differences per hundredth
      - A 0.01s difference between #25 and #26 yields a much smaller score delta
        than a 0.01s difference inside the 0.74s gap between #16 and #17
    """

    def __init__(self, ranked_list: list[RankedSwim],
                 conference: str = "", event: str = "", gender: str = ""):
        self.swims      = ranked_list
        self.conference = conference
        self.event      = event
        self.gender     = gender

        # Build unique-time anchor points: [(time, fractional_rank), ...]
        # For tied ranks: all tied swimmers share the same integer rank.
        # The fractional anchor for a tied group is the integer rank itself.
        self._anchors: list[tuple[float, float]] = self._build_anchors()

        # Extrapolation: average gap of last 5 unique times, used beyond #50
        self._tail_gap = self._compute_tail_gap()

    def _build_anchors(self) -> list[tuple[float, float]]:
        """Build (time, fractional_score) anchor list from the ranked swims."""
        anchors = []
        seen_times = {}

        for swim in self.swims:
            t = swim.time
            if t not in seen_times:
                seen_times[t] = swim.rank
                anchors.append((t, float(swim.rank)))

        anchors.sort(key=lambda x: x[0])
        return anchors

    def _compute_tail_gap(self, n: int = 5) -> float:
        """Average time gap between the last N unique anchor points."""
        if len(self._anchors) < 2:
            return 0.1
        tail = self._anchors[-min(n, len(self._anchors)):]
        gaps = [tail[i+1][0] - tail[i][0] for i in range(len(tail)-1)]
        return sum(gaps) / len(gaps) if gaps else 0.1

    def calculate(self, time_seconds: float) -> ImpactResult:
        """Calculate the fractional impact score for a given time."""
        anchors  = self._anchors
        fastest  = anchors[0]
        slowest  = anchors[-1]

        # ── Faster than or equal to #1 ─────────────────────────────────────
        if time_seconds <= fastest[0]:
            lo_swim = self._swim_at_time(fastest[0])
            return ImpactResult(
                time=time_seconds,
                time_display=self._fmt(time_seconds),
                score=1.0 if time_seconds < fastest[0] else float(fastest[1]),
                rank_display=f"#{fastest[1]:.0f}" if time_seconds >= fastest[0] else "Faster than #1",
                between_rank_lo=int(fastest[1]),
                between_rank_hi=None,
                between_name_lo=lo_swim.name if lo_swim else "",
                between_name_hi=None,
                between_time_lo=fastest[0],
                between_time_hi=None,
                pct_through_gap=0.0,
                in_list=True,
            )

        # ── Within the list ─────────────────────────────────────────────────
        for i in range(len(anchors) - 1):
            time_lo, score_lo = anchors[i]
            time_hi, score_hi = anchors[i + 1]

            if time_lo <= time_seconds <= time_hi:
                if time_seconds == time_lo:
                    pct = 0.0
                elif time_seconds == time_hi:
                    pct = 1.0
                else:
                    gap = time_hi - time_lo
                    pct = (time_seconds - time_lo) / gap

                fractional_score = score_lo + pct * (score_hi - score_lo)

                lo_swim = self._swim_at_time(time_lo)
                hi_swim = self._swim_at_time(time_hi)

                return ImpactResult(
                    time=time_seconds,
                    time_display=self._fmt(time_seconds),
                    score=round(fractional_score, 3),
                    rank_display=self._rank_label(fractional_score, pct, int(score_lo)),
                    between_rank_lo=int(score_lo),
                    between_rank_hi=int(score_hi),
                    between_name_lo=lo_swim.name if lo_swim else "",
                    between_name_hi=hi_swim.name if hi_swim else "",
                    between_time_lo=time_lo,
                    between_time_hi=time_hi,
                    pct_through_gap=round(pct, 4),
                    in_list=True,
                )

        # ── Slower than the list — extrapolate ─────────────────────────────
        last_time, last_score = slowest
        overflow   = time_seconds - last_time
        extra_score = last_score + (overflow / self._tail_gap)
        lo_swim    = self._swim_at_time(last_time)

        return ImpactResult(
            time=time_seconds,
            time_display=self._fmt(time_seconds),
            score=round(extra_score, 3),
            rank_display=f"~#{extra_score:.1f} (outside top {int(last_score)})",
            between_rank_lo=int(last_score),
            between_rank_hi=None,
            between_name_lo=lo_swim.name if lo_swim else "",
            between_name_hi=None,
            between_time_lo=last_time,
            between_time_hi=None,
            pct_through_gap=0.0,
            in_list=False,
        )

    def _swim_at_time(self, time: float) -> Optional[RankedSwim]:
        for s in self.swims:
            if s.time == time:
                return s
        return None

    def _rank_label(self, score: float, pct: float, base_rank: int) -> str:
        if pct == 0.0:
            return f"#{base_rank}"
        return f"~#{score:.2f}"

    @staticmethod
    def _fmt(seconds: float) -> str:
        m = int(seconds) // 60
        s = seconds - m * 60
        return f"{m}:{s:05.2f}" if m else f"{s:.2f}"

    def top_n(self, n: int = 10) -> list[RankedSwim]:
        """Return the top N swimmers from the list."""
        return self.swims[:n]


# ── Convenience loader ────────────────────────────────────────────────────────

def load_engine(csv_path: str | Path, conference: str = "",
                event: str = "", gender: str = "") -> ImpactScoreEngine:
    """Load a CSV and return a ready-to-use ImpactScoreEngine."""
    swims = load_ranked_list(csv_path)
    return ImpactScoreEngine(swims, conference, event, gender)


# ── CLI demo ──────────────────────────────────────────────────────────────────

def main():
    import argparse

    ap = argparse.ArgumentParser(description="SIR fractional impact score calculator")
    ap.add_argument("csv_file", help="Ranked swim list CSV")
    ap.add_argument("time", type=float, help="Time to score (seconds, e.g. 42.49)")
    ap.add_argument("--conference", default="SEC")
    ap.add_argument("--event",      default="100 Free")
    ap.add_argument("--gender",     default="M")
    args = ap.parse_args()

    engine = load_engine(args.csv_file, args.conference, args.event, args.gender)
    result = engine.calculate(args.time)
    print(result.summary())


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        main()
    else:
        # ── Built-in demo using the SEC Men's 100 Free list ─────────────────
        here = Path(__file__).parent
        csv  = here.parent / "data" / "SIR_Test_Spreadsheet_-_Sheet1.csv"
        if not csv.exists():
            csv = Path("/mnt/user-data/uploads/SIR_Test_Spreadsheet_-_Sheet1.csv")

        engine = load_engine(csv, "SEC", "100 Free", "M")

        print("\n" + "═"*55)
        print("  SIR FRACTIONAL IMPACT SCORE — SEC Men's 100 Free")
        print("═"*55)

        # Test cases that demonstrate the interpolation
        test_times = [
            (42.48, "Exactly #25 (Warner Russ)"),
            (42.485,"Halfway between #25 and #26"),
            (42.49, "Exactly #26 (Calvin Fry)"),
            (42.495,"Halfway between #26 and #27"),
            (42.57, "Exactly #27 (Kalle Mäkinen)"),
            (42.00, "Between #16 and #17 — big gap"),
            (41.86, "Tied at #14"),
            (39.91, "Exactly #1 (Josh Liendo)"),
            (39.50, "Faster than #1"),
            (43.50, "Slower than #50 — extrapolated"),
        ]

        for t, label in test_times:
            r = engine.calculate(t)
            print(f"\n  {label}")
            print(f"  Time: {r.time_display}  →  Score: {r.score:.3f}  ({r.rank_display})")
            if r.between_rank_hi and r.pct_through_gap > 0:
                print(f"    Gap: #{r.between_rank_lo} ({r.between_time_lo:.2f}) → "
                      f"#{r.between_rank_hi} ({r.between_time_hi:.2f}) | "
                      f"{r.pct_through_gap*100:.1f}% through")

        print("\n" + "═"*55)
        print("  FULL TOP-10 LIST")
        print("═"*55)
        for s in engine.top_n(10):
            r = engine.calculate(s.time)
            print(f"  #{s.rank:<3} {s.name:<28} {s.time:.2f}s  → score {r.score:.3f}")
