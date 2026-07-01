# SIR — Swimming Impact Rank

**How valuable are you where it matters?**

A 43.5 in the 100 free means average in the SEC, good in the ACC, elite in
the Patriot League. SIR ranks a swimmer's time against the *actual* ranked
results of a specific conference/event/gender/season, instead of comparing
against a single global scale — so the same time can mean something very
different depending on where you'd swim it.

## How scoring works

Every ranked list (e.g. "SEC Men's 100 Free, 2025-26") is a real, ordered
list of swims imported from championship results. A submitted time is
**interpolated between the two nearest real swims** in that list rather than
matched against a smoothed curve:

- The gap between #25 and #26 is real time — a swimmer at the midpoint
  scores exactly `25.50`.
- Ties share a rank; a time between #14 and #16 interpolates across that
  gap.
- Scores run from `1.000` (best) upward, lower is better — a `1.000` is the
  top of the conference, `3.000` is roughly average, `5.000` is near the
  bottom of the field.
- The same process runs independently per conference using that
  conference's own benchmarks, which is why a swimmer ranked #42 in the ACC
  might rank #3 in the Patriot League.

## Features

- **Recruit mode** — enter your best times, see your projected rank across
  every conference with real ranked-list data.
- **Transfer portal mode** — see where you'd land on a specific team's
  roster.
- **Coach search** — filter ranked swimmers by event, conference, and
  gender.
- **Roles** — swimmer, coach, and invite-only admin accounts, with paid
  swimmer/coach tiers gating unlimited searches.
- **Admin CSV import** — admins upload a ranked-list CSV (rank, name,
  school, meet, time) per conference/event/gender/season; the list fully
  replaces any existing one with the same key.

## Architecture

```
index.html + api.js   →  static frontend, deployed on Vercel
sir-backend/app.py    →  Flask API, deployed on Render
Postgres (Render)     →  single source of truth for users, ranked lists,
                          ranked swims, and computed benchmarks
```

There is no client-side data store beyond a session token in
`localStorage` — all scoring, ranked-list data, and percentile benchmarks
are fetched live from the API. See [`sir-backend/backend_README.md`](sir-backend/backend_README.md)
for the full API reference, database schema, and deployment instructions.

## Project structure

```
index.html                    ← the entire frontend (single page)
api.js                        ← fetch() wrapper for the backend API
sir-backend/
├── app.py                    ← Flask API (auth, scoring, benchmarks, admin import)
├── requirements.txt
├── render.yaml                ← Render deploy config (web service + Postgres)
├── env.example
└── backend_README.md          ← API reference & deployment guide
```

## Local development

**Frontend** — any static file server works, e.g.:
```bash
python3 -m http.server 5500
```
Then edit the `SIR_API_BASE` in `index.html` to point at your local or
deployed backend.

**Backend** — see [`sir-backend/backend_README.md`](sir-backend/backend_README.md).
