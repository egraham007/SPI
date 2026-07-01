# SIR Backend — Setup & Deployment Guide

## File structure
```
sir-backend/
├── app.py            ← Flask API (the whole backend)
├── api.js            ← Frontend JS client (put next to index.html)
├── requirements.txt  ← Python dependencies
├── render.yaml       ← One-click Render deploy config (web service + Postgres)
└── .env.example      ← Copy to .env for local dev
```

Data lives in Postgres (`DATABASE_URL`), not in a local file — this is what
survives Render deploys (see "Notes on Postgres + Render" below).

---

## Local development

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Create a local Postgres database
```bash
createdb sir
# or via Docker:
# docker run --name sir-pg -e POSTGRES_HOST_AUTH_METHOD=trust -p 5432:5432 -d postgres
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env — change passwords, invite code, and DATABASE_URL if needed
```

### 4. Run the server
```bash
python app.py
# Server starts at http://localhost:5000
# Admin account auto-created: admin@sir.app / admin123
```

### 4. Connect the frontend
In `index.html`, add before the closing `</body>`:
```html
<script>window.SIR_API_BASE = 'http://localhost:5000';</script>
<script src="api.js"></script>
```

---

## Deploy to Render (free tier)

### 1. Push to GitHub
```bash
git init
git add .
git commit -m "SIR backend"
git remote add origin https://github.com/YOUR_USERNAME/sir-backend.git
git push -u origin main
```

### 2. Create Render Web Service
1. Go to https://render.com → New → Blueprint
2. Connect your GitHub repo
3. Render auto-detects `render.yaml` — click **Apply**
   (this provisions both the web service and a free Postgres database,
   and wires `DATABASE_URL` between them automatically)

### 3. Set environment variables in Render dashboard
| Variable | Value |
|----------|-------|
| `SECRET_KEY` | (auto-generated) |
| `ADMIN_EMAIL` | your email |
| `ADMIN_PASSWORD` | strong password |
| `ADMIN_INVITE_CODE` | your secret code |
| `ALLOWED_ORIGINS` | https://your-site.com |
| `DATABASE_URL` | (auto-filled from the linked database) |

### 4. Update frontend API base URL
In `index.html`:
```html
<script>window.SIR_API_BASE = 'https://sir-api.onrender.com';</script>
<script src="api.js"></script>
```

---

## API reference

### Auth
| Method | Endpoint | Body | Auth |
|--------|----------|------|------|
| POST | `/api/auth/signup` | `{name, email, password, role, invite_code?}` | — |
| POST | `/api/auth/login` | `{email, password}` | — |
| GET  | `/api/auth/me` | — | Bearer |
| POST | `/api/auth/logout` | — | Bearer |

### Scoring
| Method | Endpoint | Params | Auth |
|--------|----------|--------|------|
| GET | `/api/score` | `?time=42.49&conf=SEC&event=100free&gender=M` | — |
| GET | `/api/lists` | — | — |
| GET | `/api/lists/{key}/swims` | — | — |

### Admin
| Method | Endpoint | Notes | Auth |
|--------|----------|-------|------|
| POST | `/api/import` | Form: file + conference + event + gender + season | Admin |
| GET  | `/api/import/log` | All import history | Admin |
| GET  | `/api/users` | All accounts | Admin |
| PATCH | `/api/users/{id}` | `{role?, status?}` | Admin |

### Score response example
```json
{
  "list_key":   "SEC|100free|M",
  "input_time": 42.49,
  "score":      26.0,
  "rank_label": "~#26.00",
  "in_list":    true,
  "pct":        1.0,
  "lo_swim":    {"rank": 25, "name": "Warner Russ", "time": 42.48, "meet": "James E Martin Inv."},
  "hi_swim":    {"rank": 26, "name": "Calvin Fry",  "time": 42.49, "meet": "Texas HOF Inv."}
}
```

---

## CSV import format
```
rank, name, school, meet, time
1, Josh Liendo, Tennessee, NCAA Championships, 39.91
2, Jere Hribar, Florida, NCAA Championships, 40.33
...
```
- One file = one conference + event + gender
- School column can be blank
- Time: `42.49` or `1:45.00` — both work
- Ties: same rank number on multiple rows

---

## Notes on Postgres + Render
The backend now stores everything in Postgres via `DATABASE_URL`, so data
survives redeploys — the old SQLite setup lost its database file on every
deploy because Render's web service filesystem is ephemeral.

Render's free Postgres tier is time-limited (historically expires after
30–90 days, subject to change) and gets deleted after that — check the
current policy in the Render dashboard before you rely on it long-term.
When it's about to expire, either upgrade to a paid Postgres plan or spin up
a new free instance and re-import your ranked lists (`/api/import`) into it.
