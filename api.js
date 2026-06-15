/**
 * SIR API Client
 * ==============
 * Thin wrapper around fetch() for all SIR backend calls.
 * Drop this alongside index.html and set API_BASE to your server URL.
 *
 * Usage in index.html:
 *   <script src="api.js"></script>
 *   Then call SIR_API.login(), SIR_API.score(), etc.
 */

const SIR_API = (() => {

  // ── Config ─────────────────────────────────────────────────────
  // In production: set to your Render URL e.g. 'https://sir-api.onrender.com'
  // In local dev:  'http://localhost:5000'
  const API_BASE = window.SIR_API_BASE || 'http://localhost:5000';

  // Token stored in localStorage — just the token string, not user data
  const TOKEN_KEY = 'sir_token';

  function getToken()       { return localStorage.getItem(TOKEN_KEY); }
  function setToken(t)      { localStorage.setItem(TOKEN_KEY, t); }
  function clearToken()     { localStorage.removeItem(TOKEN_KEY); }

  // ── Core fetch wrapper ─────────────────────────────────────────
  async function req(method, path, body = null, isForm = false) {
    const headers = {};
    const token   = getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
    if (body && !isForm) headers['Content-Type'] = 'application/json';

    const opts = { method, headers };
    if (body) opts.body = isForm ? body : JSON.stringify(body);

    const res  = await fetch(API_BASE + path, opts);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  // ── Auth ───────────────────────────────────────────────────────
  async function signup(name, email, password, role, inviteCode = '') {
    const data = await req('POST', '/api/auth/signup',
      { name, email, password, role, invite_code: inviteCode });
    setToken(data.token);
    return data.user;
  }

  async function login(email, password) {
    const data = await req('POST', '/api/auth/login', { email, password });
    setToken(data.token);
    return data.user;
  }

  async function logout() {
    try { await req('POST', '/api/auth/logout'); } catch (_) {}
    clearToken();
  }

  async function me() {
    if (!getToken()) return null;
    try {
      const data = await req('GET', '/api/auth/me');
      return data.user;
    } catch (_) {
      clearToken();
      return null;
    }
  }

  // ── Scoring ────────────────────────────────────────────────────
  async function score(time, conf, event, gender) {
    const params = new URLSearchParams({ time, conf, event, gender });
    return req('GET', `/api/score?${params}`);
  }

  // ── Ranked lists ───────────────────────────────────────────────
  async function getLists() {
    return req('GET', '/api/lists');
  }

  async function getListSwims(listKey) {
    return req('GET', `/api/lists/${encodeURIComponent(listKey)}/swims`);
  }

  // ── Admin: import CSV ─────────────────────────────────────────
  async function importCSV(file, conference, event, gender, season) {
    const form = new FormData();
    form.append('file',        file);
    form.append('conference',  conference);
    form.append('event',       event);
    form.append('gender',      gender);
    form.append('season',      season);
    return req('POST', '/api/import', form, true);
  }

  async function importLog() {
    return req('GET', '/api/import/log');
  }

  // ── Admin: users ───────────────────────────────────────────────
  async function getUsers() {
    return req('GET', '/api/users');
  }

  async function updateUser(id, fields) {
    return req('PATCH', `/api/users/${id}`, fields);
  }

  // ── Health check ───────────────────────────────────────────────
  async function health() {
    return req('GET', '/api/health');
  }

  // ── Public API ─────────────────────────────────────────────────
  return {
    signup, login, logout, me,
    score, getLists, getListSwims,
    importCSV, importLog,
    getUsers, updateUser,
    health,
    isLoggedIn: () => !!getToken(),
  };

})();
