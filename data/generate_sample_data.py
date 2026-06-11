"""
Generate realistic sample championship CSV data for testing the SIR pipeline.
Creates one CSV per conference with ~80-120 swimmers across 3+ events.

Usage:
    python data/generate_sample_data.py
"""

import csv
import random
from pathlib import Path

random.seed(42)

OUT_DIR = Path(__file__).parent

# Conference championship benchmark times (men, seconds)
CONF_BENCHMARKS_M = {
    "SEC": {
        "50 Free":   (19.4, 0.8),
        "100 Free":  (43.0, 1.8),
        "200 Free":  (94.5, 4.0),
        "100 Fly":   (46.5, 2.2),
        "200 Fly":   (102.0, 5.0),
        "100 Back":  (47.5, 2.5),
        "200 Back":  (103.5, 5.5),
        "100 Breast":(52.5, 2.8),
        "200 IM":    (99.0, 4.5),
        "400 IM":    (213.0, 9.0),
    },
    "ACC": {
        "50 Free":   (19.8, 0.9),
        "100 Free":  (43.5, 2.0),
        "200 Free":  (95.2, 4.5),
        "100 Fly":   (47.0, 2.4),
        "200 Fly":   (103.0, 5.5),
        "100 Back":  (48.0, 2.8),
        "200 Back":  (104.5, 6.0),
        "100 Breast":(53.0, 3.0),
        "200 IM":    (100.0, 5.0),
        "400 IM":    (215.0, 10.0),
    },
    "Big 10": {
        "50 Free":   (20.0, 0.9),
        "100 Free":  (43.7, 2.0),
        "200 Free":  (95.5, 4.5),
        "100 Fly":   (47.2, 2.5),
        "200 Fly":   (103.5, 5.5),
        "100 Back":  (48.2, 2.8),
        "200 Back":  (105.0, 6.0),
        "100 Breast":(53.5, 3.0),
        "200 IM":    (100.5, 5.0),
        "400 IM":    (216.0, 10.0),
    },
    "Pac-12": {
        "50 Free":   (19.7, 0.85),
        "100 Free":  (43.3, 1.9),
        "200 Free":  (94.8, 4.2),
        "100 Fly":   (46.8, 2.3),
        "200 Fly":   (102.5, 5.2),
        "100 Back":  (47.8, 2.6),
        "200 Back":  (104.0, 5.8),
        "100 Breast":(52.8, 2.9),
        "200 IM":    (99.5, 4.7),
        "400 IM":    (214.0, 9.5),
    },
    "Patriot League": {
        "50 Free":   (21.5, 1.2),
        "100 Free":  (46.5, 3.0),
        "200 Free":  (102.0, 6.0),
        "100 Fly":   (50.0, 3.5),
        "200 Back":  (110.0, 7.0),
        "100 Breast":(56.5, 4.0),
        "200 IM":    (105.0, 6.5),
    },
}

# Women's benchmark times
CONF_BENCHMARKS_F = {
    "SEC": {
        "50 Free":   (22.0, 0.8),
        "100 Free":  (48.5, 2.0),
        "200 Free":  (107.0, 4.5),
        "100 Fly":   (52.5, 2.5),
        "200 Fly":   (116.0, 6.0),
        "100 Back":  (53.5, 2.8),
        "200 Back":  (117.0, 6.0),
        "100 Breast":(59.5, 3.0),
        "200 IM":    (112.0, 5.5),
        "400 IM":    (240.0, 11.0),
    },
    "ACC": {
        "50 Free":   (22.4, 0.9),
        "100 Free":  (49.2, 2.2),
        "200 Free":  (108.5, 5.0),
        "100 Fly":   (53.2, 2.8),
        "200 Fly":   (117.5, 6.5),
        "100 Back":  (54.2, 3.0),
        "200 Back":  (118.5, 6.5),
        "100 Breast":(60.5, 3.2),
        "200 IM":    (113.5, 6.0),
        "400 IM":    (243.0, 12.0),
    },
    "Big 10": {
        "50 Free":   (22.6, 0.9),
        "100 Free":  (49.5, 2.2),
        "200 Free":  (109.0, 5.0),
        "100 Fly":   (53.5, 2.8),
        "200 Back":  (119.0, 6.5),
        "100 Breast":(61.0, 3.2),
        "200 IM":    (114.0, 6.0),
        "400 IM":    (244.0, 12.0),
    },
    "Patriot League": {
        "50 Free":   (24.0, 1.2),
        "100 Free":  (52.5, 3.0),
        "200 Free":  (116.0, 6.5),
        "100 Fly":   (56.5, 3.5),
        "100 Back":  (57.5, 3.5),
        "200 IM":    (120.0, 7.0),
    },
}

FIRST_NAMES_M = ["Alex","Marcus","Jordan","Dylan","Cameron","Nick","Ryan","Lucas",
                  "Tyler","Connor","Jake","Ethan","Noah","Liam","Mason","Owen",
                  "Hunter","Caleb","Logan","Jackson","Aiden","Carter","Eli","Nathan"]
FIRST_NAMES_F = ["Ava","Sara","Maya","Brooke","Taylor","Emma","Lily","Nina",
                  "Kate","Jess","Claire","Sophie","Grace","Olivia","Hannah",
                  "Mia","Zoe","Chloe","Aria","Riley","Aubrey","Paige","Leah","Nora"]
LAST_NAMES    = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller",
                 "Davis","Wilson","Anderson","Taylor","Thomas","Moore","Martin",
                 "Jackson","Lee","White","Harris","Clark","Lewis","Robinson","Walker",
                 "Young","Hall","Allen","King","Wright","Scott","Green","Baker"]

TEAMS = {
    "SEC":    ["Alabama","Auburn","Florida","Georgia","Kentucky","LSU","Missouri",
               "South Carolina","Tennessee","Texas A&M","Vanderbilt"],
    "ACC":    ["Boston College","Clemson","Duke","Florida State","Georgia Tech",
               "Louisville","Miami","NC State","Notre Dame","Pitt","Syracuse",
               "UNC","Virginia","Virginia Tech","Wake Forest"],
    "Big 10": ["Indiana","Iowa","Maryland","Michigan","Michigan State","Minnesota",
               "Nebraska","Northwestern","Ohio State","Penn State","Purdue","Rutgers",
               "Wisconsin"],
    "Pac-12": ["Arizona","Arizona State","Cal","Oregon State","Stanford","UCLA",
               "USC","Utah","Washington","Washington State"],
    "Patriot League": ["American","Army","Boston University","Bucknell","Colgate",
                        "Holy Cross","Lafayette","Lehigh","Navy"],
}


def gen_time(base: float, spread: float) -> float:
    """Generate a time around base ± spread, skewed slightly slower (realistic distribution)."""
    raw = random.gauss(base + spread * 0.3, spread * 0.45)
    return max(base - spread * 0.2, raw)  # floor at near-best


def seconds_to_str(s: float) -> str:
    m = int(s) // 60
    sec = s - m * 60
    return f"{m}:{sec:05.2f}" if m else f"{sec:.2f}"


def generate_conference_csv(conf: str, gender: str, season: str,
                             benchmarks: dict, n_swimmers: int = 90):
    rows = []
    teams = TEAMS.get(conf, ["Unknown"])
    events = list(benchmarks[conf].keys())
    first_names = FIRST_NAMES_M if gender == "M" else FIRST_NAMES_F

    # Each swimmer specialises in 2-4 events
    for i in range(n_swimmers):
        name  = f"{random.choice(first_names)} {random.choice(LAST_NAMES)}"
        team  = random.choice(teams)
        # Swimmer has a "specialty" — slightly better in 1-2 events
        specialty = random.sample(events, k=min(2, len(events)))
        n_events  = random.randint(2, min(4, len(events)))
        swimmer_events = random.sample(events, k=n_events)

        for ev in swimmer_events:
            base, spread = benchmarks[conf][ev]
            # Specialty events are faster
            boost = 0.85 if ev in specialty else 1.0
            time_s = gen_time(base, spread * boost)
            rows.append({
                "name":  name,
                "team":  team,
                "event": ev,
                "time":  seconds_to_str(time_s),
            })

    # Sort by event then time for readability
    rows.sort(key=lambda r: (r["event"], r["time"]))

    safe_conf = conf.lower().replace(" ", "_")
    fname = OUT_DIR / f"{safe_conf}_{gender.lower()}_{season.replace('-','_')}.csv"
    with open(fname, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name","team","event","time"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"✓ {fname.name}  ({len(rows)} rows, {n_swimmers} swimmers)")
    return fname


def main():
    season = "2025-26"
    print(f"\nGenerating sample championship CSVs for {season}...\n")

    sizes = {"SEC": 110, "ACC": 100, "Big 10": 105, "Pac-12": 90, "Patriot League": 60}

    for conf, benchmarks in CONF_BENCHMARKS_M.items():
        generate_conference_csv(conf, "M", season, CONF_BENCHMARKS_M,
                                n_swimmers=sizes.get(conf, 80))

    for conf, benchmarks in CONF_BENCHMARKS_F.items():
        generate_conference_csv(conf, "F", season, CONF_BENCHMARKS_F,
                                n_swimmers=sizes.get(conf, 80))

    print(f"\nDone. CSVs written to {OUT_DIR}/")
    print("\nTo import all of them, run:")
    print("  python pipeline.py --season 2025-26")


if __name__ == "__main__":
    main()
