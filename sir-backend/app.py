"""
SIR — Swimming Impact Rank  |  Flask API
=========================================
Endpoints:
  POST /api/auth/signup
  POST /api/auth/login
  GET  /api/auth/me

  GET  /api/lists                        — all ranked lists (public)
  GET  /api/score?time=&conf=&event=&gender=   — fractional SIR score (public)

  POST /api/import                       — admin: import CSV ranked list
  GET  /api/import/log                   — admin: import history

  GET  /api/users                        — admin: list all users
  PATCH /api/users/<id>                  — admin: update role / status

Run locally:
    python app.py

Deploy (Render):
    Build command : pip install -r requirements.txt
    Start command : gunicorn app:app
"""

import csv
import io
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, g
from werkzeug.security import generate_password_hash, check_password_hash

# ── App setup ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))

DB_PATH = Path(os.environ.get('DB_PATH', 'sir.db'))

# ── CORS (manual, no extra package needed) ─────────────────────────────────────
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '*')

@app.after_request
def add_cors(response):
    origin = request.headers.get('Origin', '')
    if ALLOWED_ORIGINS == '*':
        response.headers['Access-Control-Allow-Origin'] = '*'
    else:
        if origin in ALLOWED_ORIGINS.split(','):
            response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, DELETE, OPTIONS'
    return response

@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def options_handler(path):
    return jsonify({}), 200


# ── Database ───────────────────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys=ON")
    cur = db.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL,
        email       TEXT    NOT NULL UNIQUE,
        password    TEXT    NOT NULL,
        role        TEXT    NOT NULL DEFAULT 'swimmer'
                    CHECK(role IN ('swimmer','coach','admin')),
        status      TEXT    NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','suspended','pending')),
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS sessions (
        token       TEXT PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires_at  TIMESTAMP NOT NULL,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS ranked_lists (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        list_key    TEXT    NOT NULL UNIQUE,   -- "SEC|100free|M"
        conference  TEXT    NOT NULL,
        event       TEXT    NOT NULL,
        gender      TEXT    NOT NULL CHECK(gender IN ('M','F')),
        season      TEXT    NOT NULL,
        swim_count  INTEGER NOT NULL DEFAULT 0,
        imported_by INTEGER REFERENCES users(id),
        imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS ranked_swims (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        list_key    TEXT    NOT NULL,
        rank        INTEGER NOT NULL,
        name        TEXT    NOT NULL,
        school      TEXT,
        meet        TEXT,
        time        REAL    NOT NULL,
        FOREIGN KEY(list_key) REFERENCES ranked_lists(list_key) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_swims_list   ON ranked_swims(list_key);
    CREATE INDEX IF NOT EXISTS idx_swims_time   ON ranked_swims(list_key, time);
    CREATE INDEX IF NOT EXISTS idx_sessions_tok ON sessions(token);
    CREATE INDEX IF NOT EXISTS idx_sessions_exp ON sessions(expires_at);
    """)

    # Seed admin account if none exists
    existing = db.execute("SELECT id FROM users WHERE role='admin'").fetchone()
    if not existing:
        pw = os.environ.get('ADMIN_PASSWORD', 'admin123')
        db.execute(
            "INSERT OR IGNORE INTO users(name,email,password,role) VALUES(?,?,?,?)",
            ('Admin', os.environ.get('ADMIN_EMAIL', 'admin@sir.app'),
             generate_password_hash(pw), 'admin')
        )
        print(f"  Seeded admin: {os.environ.get('ADMIN_EMAIL','admin@sir.app')} / {pw}")

    db.commit()
    db.close()


# ── Auth helpers ───────────────────────────────────────────────────────────────
SESSION_DAYS = 30

def create_session(user_id: int) -> str:
    token  = secrets.token_urlsafe(32)
    expiry = datetime.utcnow() + timedelta(days=SESSION_DAYS)
    get_db().execute(
        "INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)",
        (token, user_id, expiry.isoformat())
    )
    get_db().commit()
    return token

def get_current_user():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[7:]
    row = get_db().execute("""
        SELECT u.* FROM users u
        JOIN sessions s ON s.user_id = u.id
        WHERE s.token=? AND s.expires_at > datetime('now')
    """, (token,)).fetchone()
    return dict(row) if row else None

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        g.current_user = user
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        if user['role'] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        g.current_user = user
        return f(*args, **kwargs)
    return decorated


# ── Time parsing ───────────────────────────────────────────────────────────────
_TIME_RE_COLON = re.compile(r'^(\d+):(\d{2})(\.\d+)?$')
_TIME_RE_PLAIN  = re.compile(r'^\d+(\.\d+)?$')

def parse_time(raw: str) -> float | None:
    """Parse M:SS.xx or SS.xx into seconds. Returns None on failure."""
    s = raw.strip().replace(',', '.')
    m = _TIME_RE_COLON.match(s)
    if m:
        mins = int(m.group(1))
        secs = float(m.group(2) + (m.group(3) or ''))
        if secs >= 60: return None
        return round(mins * 60 + secs, 3)
    if _TIME_RE_PLAIN.match(s):
        return round(float(s), 3)
    return None


# ── Fractional SIR engine ──────────────────────────────────────────────────────
def build_anchors(swims: list[dict]) -> list[dict]:
    """Unique-time anchor points sorted ascending."""
    seen = {}
    for s in swims:
        if s['time'] not in seen:
            seen[s['time']] = s['rank']
    return sorted([{'time': t, 'rank': r} for t, r in seen.items()],
                  key=lambda x: x['time'])

def tail_gap(anchors: list[dict], n: int = 5) -> float:
    tail = anchors[-min(n, len(anchors)):]
    if len(tail) < 2: return 0.10
    gaps = [tail[i+1]['time'] - tail[i]['time'] for i in range(len(tail)-1)]
    return sum(gaps) / len(gaps)

def fractional_score(time: float, swims: list[dict]) -> dict:
    """
    Calculate fractional SIR score by interpolating between real ranked swims.
    Returns score, rank_label, surrounding swimmers, and pct through gap.
    """
    anchors = build_anchors(swims)
    first, last = anchors[0], anchors[-1]

    def swim_at(t):
        return next((s for s in swims if s['time'] == t), None)

    # Faster than #1
    if time <= first['time']:
        s = swim_at(first['time'])
        return {
            'score':      float(first['rank']),
            'rank_label': f"#{first['rank']}",
            'lo_swim':    s,
            'hi_swim':    None,
            'pct':        0.0,
            'in_list':    True,
        }

    # Within the list
    for i in range(len(anchors) - 1):
        lo, hi = anchors[i], anchors[i+1]
        if lo['time'] <= time <= hi['time']:
            gap = hi['time'] - lo['time']
            pct = 0.0 if gap == 0 else (time - lo['time']) / gap
            score = lo['rank'] + pct * (hi['rank'] - lo['rank'])
            return {
                'score':      round(score, 3),
                'rank_label': f"#{lo['rank']}" if pct == 0 else f"~#{score:.2f}",
                'lo_swim':    swim_at(lo['time']),
                'hi_swim':    swim_at(hi['time']),
                'pct':        round(pct, 4),
                'in_list':    True,
            }

    # Beyond the list — extrapolate
    gap   = tail_gap(anchors)
    extra = last['rank'] + (time - last['time']) / gap
    return {
        'score':      round(extra, 3),
        'rank_label': f"~#{extra:.1f} (beyond top {last['rank']})",
        'lo_swim':    swim_at(last['time']),
        'hi_swim':    None,
        'pct':        0.0,
        'in_list':    False,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

# ── Auth ───────────────────────────────────────────────────────────────────────
@app.post('/api/auth/signup')
def signup():
    data = request.get_json() or {}
    name     = (data.get('name') or '').strip()
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    role     = data.get('role', 'swimmer')
    code     = data.get('invite_code', '')

    if not name or not email or not password:
        return jsonify({'error': 'Name, email and password required'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    if role not in ('swimmer', 'coach', 'admin'):
        return jsonify({'error': 'Invalid role'}), 400
    if role == 'admin':
        valid_code = os.environ.get('ADMIN_INVITE_CODE', 'SIR-ADMIN-2025')
        if code != valid_code:
            return jsonify({'error': 'Invalid admin invite code'}), 403

    db = get_db()
    if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
        return jsonify({'error': 'Email already registered'}), 409

    cur = db.execute(
        "INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)",
        (name, email, generate_password_hash(password), role)
    )
    db.commit()
    token = create_session(cur.lastrowid)
    user  = dict(db.execute("SELECT id,name,email,role,status,created_at FROM users WHERE id=?",
                             (cur.lastrowid,)).fetchone())
    return jsonify({'token': token, 'user': user}), 201


@app.post('/api/auth/login')
def login():
    data  = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    pw    = data.get('password') or ''

    db   = get_db()
    row  = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not row or not check_password_hash(row['password'], pw):
        return jsonify({'error': 'Invalid email or password'}), 401
    if row['status'] == 'suspended':
        return jsonify({'error': 'Account suspended — contact admin'}), 403

    token = create_session(row['id'])
    user  = {k: row[k] for k in ('id','name','email','role','status','created_at')}
    return jsonify({'token': token, 'user': user})


@app.get('/api/auth/me')
@require_auth
def me():
    return jsonify({'user': {k: g.current_user[k]
                             for k in ('id','name','email','role','status','created_at')}})


@app.post('/api/auth/logout')
@require_auth
def logout():
    auth  = request.headers.get('Authorization', '')
    token = auth[7:] if auth.startswith('Bearer ') else ''
    if token:
        get_db().execute("DELETE FROM sessions WHERE token=?", (token,))
        get_db().commit()
    return jsonify({'ok': True})


# ── Ranked lists (public read) ─────────────────────────────────────────────────
@app.get('/api/lists')
def get_lists():
    """Return metadata for all loaded ranked lists."""
    db   = get_db()
    rows = db.execute("""
        SELECT rl.*, u.name as imported_by_name
        FROM ranked_lists rl
        LEFT JOIN users u ON rl.imported_by = u.id
        ORDER BY rl.conference, rl.event, rl.gender
    """).fetchall()
    return jsonify({'lists': [dict(r) for r in rows]})


@app.get('/api/lists/<path:list_key>/swims')
def get_list_swims(list_key):
    """Return all swims for a ranked list."""
    db   = get_db()
    meta = db.execute("SELECT * FROM ranked_lists WHERE list_key=?",
                      (list_key,)).fetchone()
    if not meta:
        return jsonify({'error': 'List not found'}), 404
    swims = db.execute(
        "SELECT rank,name,school,meet,time FROM ranked_swims WHERE list_key=? ORDER BY time",
        (list_key,)
    ).fetchall()
    return jsonify({'list': dict(meta), 'swims': [dict(s) for s in swims]})


# ── Scoring (public) ──────────────────────────────────────────────────────────
@app.get('/api/score')
def score():
    """
    Calculate fractional SIR score for a given time.
    Query params: time, conf, event, gender
    Example: /api/score?time=42.49&conf=SEC&event=100free&gender=M
    """
    time_raw = request.args.get('time', '')
    conf     = request.args.get('conf', '').upper()
    event    = request.args.get('event', '').lower()
    gender   = request.args.get('gender', '').upper()

    if not all([time_raw, conf, event, gender]):
        return jsonify({'error': 'time, conf, event, gender are all required'}), 400

    time = parse_time(time_raw)
    if time is None:
        return jsonify({'error': f'Cannot parse time: {time_raw}'}), 400

    list_key = f"{conf}|{event}|{gender}"
    db       = get_db()
    swims_rows = db.execute(
        "SELECT rank,name,school,meet,time FROM ranked_swims WHERE list_key=? ORDER BY time",
        (list_key,)
    ).fetchall()

    if not swims_rows:
        return jsonify({'error': f'No ranked list found for {list_key}'}), 404

    swims  = [dict(r) for r in swims_rows]
    result = fractional_score(time, swims)
    return jsonify({
        'list_key':   list_key,
        'input_time': time,
        'score':      result['score'],
        'rank_label': result['rank_label'],
        'in_list':    result['in_list'],
        'pct':        result['pct'],
        'lo_swim':    result['lo_swim'],
        'hi_swim':    result['hi_swim'],
    })


# ── Import (admin only) ────────────────────────────────────────────────────────
@app.post('/api/import')
@require_admin
def import_list():
    """
    Import a ranked list CSV.
    Form fields: conference, event, gender, season
    File field:  file (CSV)
    """
    conf   = (request.form.get('conference') or '').strip().upper()
    event  = (request.form.get('event') or '').strip().lower()
    gender = (request.form.get('gender') or '').strip().upper()
    season = (request.form.get('season') or '2025-26').strip()

    if not all([conf, event, gender]):
        return jsonify({'error': 'conference, event, and gender are required'}), 400
    if gender not in ('M', 'F'):
        return jsonify({'error': 'gender must be M or F'}), 400
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file_bytes = request.files['file'].read().decode('utf-8-sig', errors='replace')
    rows       = _parse_csv(file_bytes)

    if not rows:
        return jsonify({'error': 'No valid rows found in CSV'}), 400

    list_key = f"{conf}|{event}|{gender}"
    db       = get_db()

    # Delete existing list if present (full replace)
    db.execute("DELETE FROM ranked_swims WHERE list_key=?", (list_key,))
    db.execute("DELETE FROM ranked_lists WHERE list_key=?", (list_key,))

    db.execute("""
        INSERT INTO ranked_lists(list_key,conference,event,gender,season,swim_count,imported_by)
        VALUES(?,?,?,?,?,?,?)
    """, (list_key, conf, event, gender, season, len(rows), g.current_user['id']))

    db.executemany("""
        INSERT INTO ranked_swims(list_key,rank,name,school,meet,time)
        VALUES(?,?,?,?,?,?)
    """, [(list_key, r['rank'], r['name'], r.get('school',''), r.get('meet',''), r['time'])
          for r in rows])

    db.commit()
    return jsonify({
        'ok':       True,
        'list_key': list_key,
        'imported': len(rows),
        'best':     f"{rows[0]['name']} {rows[0]['time']}s" if rows else '',
    }), 201


def _parse_csv(text: str) -> list[dict]:
    """
    Parse a ranked list CSV. Flexible column detection.
    Expected: rank, name, [school], meet, time
    """
    reader = csv.reader(io.StringIO(text))
    rows   = []
    for line in reader:
        cols = [c.strip() for c in line]
        if not cols or not cols[0]: continue
        try:
            rank = int(cols[0])
        except ValueError:
            continue  # header or blank
        if len(cols) < 4: continue
        name = cols[1]
        # Detect if col[2] is school (blank or text) and col[3/4] is meet/time
        if len(cols) >= 5:
            school, meet, time_raw = cols[2], cols[3], cols[4]
        else:
            school, meet, time_raw = '', cols[2], cols[3]
        time = parse_time(time_raw)
        if time is None or time <= 0: continue
        rows.append({'rank': rank, 'name': name, 'school': school,
                     'meet': meet, 'time': time})
    return rows


@app.get('/api/import/log')
@require_admin
def import_log():
    db   = get_db()
    rows = db.execute("""
        SELECT rl.*, u.name as imported_by_name
        FROM ranked_lists rl
        LEFT JOIN users u ON rl.imported_by = u.id
        ORDER BY rl.imported_at DESC
    """).fetchall()
    return jsonify({'log': [dict(r) for r in rows]})


# ── Users (admin only) ────────────────────────────────────────────────────────
@app.get('/api/users')
@require_admin
def list_users():
    rows = get_db().execute(
        "SELECT id,name,email,role,status,created_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    return jsonify({'users': [dict(r) for r in rows]})


@app.patch('/api/users/<int:user_id>')
@require_admin
def update_user(user_id):
    data   = request.get_json() or {}
    fields = {}
    if 'role' in data:
        if data['role'] not in ('swimmer','coach','admin'):
            return jsonify({'error': 'Invalid role'}), 400
        fields['role'] = data['role']
    if 'status' in data:
        if data['status'] not in ('active','suspended','pending'):
            return jsonify({'error': 'Invalid status'}), 400
        fields['status'] = data['status']
    if not fields:
        return jsonify({'error': 'Nothing to update'}), 400

    db  = get_db()
    set_clause = ', '.join(f"{k}=?" for k in fields)
    db.execute(f"UPDATE users SET {set_clause} WHERE id=?",
               (*fields.values(), user_id))
    db.commit()
    user = db.execute("SELECT id,name,email,role,status FROM users WHERE id=?",
                      (user_id,)).fetchone()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'user': dict(user)})


# ── Health check ───────────────────────────────────────────────────────────────
@app.get('/api/health')
def health():
    return jsonify({'status': 'ok', 'db': str(DB_PATH)})


# ── Startup ────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("Initializing database...")
    init_db()
    print(f"Starting SIR API on http://localhost:5000")
    app.run(debug=True, port=5000)
else:
    # Gunicorn entry point
    init_db()
