const crypto = require('crypto');

const COOKIE_NAME = 'wa_auth';
const SESSION_TTL_SECONDS = 12 * 60 * 60;
const LOGIN_WINDOW_MS = 15 * 60 * 1000;
const MAX_LOGIN_ATTEMPTS = 10;
const attempts = new Map();

function timingSafeEqualString(a, b) {
  const left = Buffer.from(String(a || ''));
  const right = Buffer.from(String(b || ''));
  return left.length === right.length && crypto.timingSafeEqual(left, right);
}
function requiredEnv(name) { if (!process.env[name]) throw new Error(`${name} must be set`); return process.env[name]; }
function getSecret() { return requiredEnv('SESSION_SECRET'); }
function createToken(username) {
  const exp = Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS;
  const payload = `${username}.${exp}`;
  const signature = crypto.createHmac('sha256', getSecret()).update(payload).digest('base64url');
  return `${payload}.${signature}`;
}
function verifyToken(token) {
  if (!token) return null;
  const parts = String(token).split('.');
  if (parts.length !== 3) return null;
  const [username, expText, signature] = parts;
  const exp = Number(expText);
  if (!username || !Number.isSafeInteger(exp) || exp < Math.floor(Date.now() / 1000)) return null;
  const payload = `${username}.${exp}`;
  const expected = crypto.createHmac('sha256', getSecret()).update(payload).digest('base64url');
  return timingSafeEqualString(signature, expected) ? { username, exp } : null;
}
function parseCookies(header) {
  const cookies = {};
  for (const part of String(header || '').split(';')) {
    const index = part.indexOf('=');
    if (index < 0) continue;
    const key = part.slice(0, index).trim();
    let value = part.slice(index + 1).trim();
    try { value = decodeURIComponent(value); } catch { continue; }
    cookies[key] = value;
  }
  return cookies;
}
function getClientKey(req) { return req.ip || req.socket?.remoteAddress || 'unknown'; }
function registerFailedLogin(key) {
  const now = Date.now();
  const current = attempts.get(key);
  if (!current || now - current.firstAttemptAt > LOGIN_WINDOW_MS) attempts.set(key, { firstAttemptAt: now, count: 1 });
  else current.count += 1;
}
function loginAllowed(key) {
  const current = attempts.get(key);
  if (!current) return true;
  if (Date.now() - current.firstAttemptAt > LOGIN_WINDOW_MS) { attempts.delete(key); return true; }
  return current.count < MAX_LOGIN_ATTEMPTS;
}
function clearLoginAttempts(key) { attempts.delete(key); }
function safeNext(value) { return typeof value === 'string' && /^\/[A-Za-z0-9_/?&=.%:-]*$/.test(value) ? value : '/'; }
function isAuthenticatedRequest(req) { return !!verifyToken(parseCookies(req.headers.cookie)[COOKIE_NAME]); }
function authMiddleware(req, res, next) {
  if (req.path === '/login' || req.path === '/health') return next();
  if (isAuthenticatedRequest(req)) return next();
  if (req.path.startsWith('/api/')) return res.status(401).json({ success: false, error: 'Authentication required' });
  return res.redirect(`/login?next=${encodeURIComponent(req.originalUrl || '/')}`);
}
function loginPage(nextPath = '/', errorText = '') {
  const next = safeNext(nextPath);
  return `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>تسجيل الدخول</title><style>body{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;background:#f4f7fb;color:#172033}form{width:min(92vw,360px);background:#fff;padding:28px;border-radius:16px;box-shadow:0 10px 35px rgba(0,0,0,.08)}h1{margin-top:0;font-size:22px}label{display:block;margin:14px 0 6px;font-weight:600}input{box-sizing:border-box;width:100%;padding:11px;border:1px solid #d5dce7;border-radius:10px}button{width:100%;margin-top:18px;padding:11px;border:0;border-radius:10px;background:#146c43;color:#fff;font-weight:700;cursor:pointer}.error{color:#b42318;margin-top:12px;min-height:1.2em}</style></head><body><form method="post" action="/login"><h1>WhatsApp Pro</h1><p>تسجيل الدخول إلى لوحة الإدارة</p><input type="hidden" name="next" value="${next.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;')}"><label>اسم المستخدم</label><input name="username" autocomplete="username" required><label>كلمة المرور</label><input name="password" type="password" autocomplete="current-password" required><button type="submit">دخول</button>${errorText ? `<div class="error">${errorText}</div>` : ''}</form></body></html>`;
}
function setupAuth(app) {
  requiredEnv('ADMIN_USERNAME'); requiredEnv('ADMIN_PASSWORD'); requiredEnv('SESSION_SECRET');
  app.get('/login', (req, res) => { res.setHeader('Cache-Control', 'no-store'); res.type('html').send(loginPage(req.query.next || '/')); });
  app.post('/login', (req, res) => {
    const key = getClientKey(req);
    if (!loginAllowed(key)) return res.status(429).send('Too many login attempts');
    const valid = timingSafeEqualString(req.body?.username, process.env.ADMIN_USERNAME) && timingSafeEqualString(req.body?.password, process.env.ADMIN_PASSWORD);
    if (!valid) { registerFailedLogin(key); return res.status(401).send(loginPage(req.body?.next || '/', 'بيانات الدخول غير صحيحة')); }
    clearLoginAttempts(key);
    const token = createToken(process.env.ADMIN_USERNAME);
    res.setHeader('Set-Cookie', `${COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${SESSION_TTL_SECONDS}${process.env.NODE_ENV === 'production' ? '; Secure' : ''}`);
    res.redirect(safeNext(req.body?.next));
  });
  app.post('/logout', (req, res) => { res.setHeader('Set-Cookie', `${COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0${process.env.NODE_ENV === 'production' ? '; Secure' : ''}`); res.redirect('/login'); });
  app.use(authMiddleware);
}
function setupSocketAuth(io) {
  io.use((socket, next) => { try { if (!verifyToken(parseCookies(socket.handshake.headers.cookie)[COOKIE_NAME])) return next(new Error('Authentication required')); next(); } catch (error) { next(error); } });
}
module.exports = { setupAuth, setupSocketAuth, parseCookies, verifyToken, COOKIE_NAME };
