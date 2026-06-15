# SIR Backend — Setup & Deployment Guide

## File structure
```
sir-backend/
├── app.py            ← Flask API (the whole backend)
├── api.js            ← Frontend JS client (put next to index.html)
├── requirements.txt  ← Python dependencies
├── render.yaml       ← One-click Render deploy config
├── .env.example      ← Copy to .env for local dev
└── sir.db            ← SQLite database (auto-created on first run)
```

---

## Local development

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env — change passwords and invite code
```

### 3. Run the server
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
1. Go to https://render.com → New → Web Service
2. Connect your GitHub repo
3. Render auto-detects `render.yaml` — click **Apply**

### 3. Set environment variables in Render dashboard
| Variable | Value |
|----------|-------|
| `SECRET_KEY` | (auto-generated) |
| `ADMIN_EMAIL` | your email |
| `ADMIN_PASSWORD` | strong password |
| `ADMIN_INVITE_CODE` | your secret code |
| `ALLOWED_ORIGINS` | https://your-site.com |

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

## Notes on SQLite + Render
Render's free tier uses an ephemeral filesystem — the database resets on each deploy.
To persist data across deploys, either:
- Upgrade to Render's paid disk ($7/mo), or
- Migrate to PostgreSQL (Render offers a free 90-day PG instance), or
- Export your ranked lists as a JSON seed file and re-import on startup

The simplest production path: add a `seed_data.json` file with your ranked lists
and call `seed_from_file()` in `init_db()`. Data always survives deploys that way.
