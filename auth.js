const crypto = require('crypto');

const ADMIN_COOKIE = 'wa_admin_auth';
const CLIENT_COOKIE = 'wa_client_auth';
const SESSION_TTL_SECONDS = 12 * 60 * 60;
const LOGIN_WINDOW_MS = 15 * 60 * 1000;
const MAX_LOGIN_ATTEMPTS = 10;
const attempts = new Map();

function requiredEnv(name) {
  if (!process.env[name]) throw new Error(`${name} must be set`);
  return process.env[name];
}

function timingSafeEqualString(a, b) {
  const left = Buffer.from(String(a || ''));
  const right = Buffer.from(String(b || ''));
  return left.length === right.length && crypto.timingSafeEqual(left, right);
}

function hashPassword(password, salt = crypto.randomBytes(16)) {
  if (typeof password !== 'string' || password.length < 10 || password.length > 256) {
    throw new Error('كلمة المرور يجب أن تكون بين 10 و256 حرفًا');
  }
  const derived = crypto.scryptSync(password, salt, 64, { N: 16384, r: 8, p: 1 });
  return { salt: salt.toString('hex'), hash: derived.toString('hex') };
}

function verifyPassword(password, record) {
  if (!record?.passwordHash || !record?.passwordSalt) return false;
  try {
    const derived = crypto.scryptSync(String(password || ''), Buffer.from(record.passwordSalt, 'hex'), 64, { N: 16384, r: 8, p: 1 });
    return timingSafeEqualString(derived.toString('hex'), record.passwordHash);
  } catch {
    return false;
  }
}

function getAuthSecret() {
  return requiredEnv('SESSION_SECRET');
}

function encodeToken(payload) {
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const sig = crypto.createHmac('sha256', getAuthSecret()).update(body).digest('base64url');
  return `${body}.${sig}`;
}

function decodeToken(token) {
  if (!token) return null;
  const parts = String(token).split('.');
  if (parts.length !== 2) return null;
  const [body, signature] = parts;
  const expected = crypto.createHmac('sha256', getAuthSecret()).update(body).digest('base64url');
  if (!timingSafeEqualString(signature, expected)) return null;
  try {
    const payload = JSON.parse(Buffer.from(body, 'base64url').toString('utf8'));
    if (!payload?.sub || !payload?.role || !payload?.exp || payload.exp < Math.floor(Date.now() / 1000)) return null;
    return payload;
  } catch {
    return null;
  }
}

function createToken(role, subject, version = 1) {
  return encodeToken({ role, sub: subject, ver: version, exp: Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS });
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

function hostOf(req) {
  return String(req.hostname || '').toLowerCase().split(':')[0];
}

function isLocalHost(host) {
  return host === 'localhost' || host === '127.0.0.1' || host === '::1';
}

function isAdminHost(req) {
  const configured = String(process.env.ADMIN_HOST || 'admin.whatsapp.alattab.site').toLowerCase();
  return hostOf(req) === configured || isLocalHost(hostOf(req));
}

function isClientHost(req) {
  const configured = String(process.env.CLIENT_HOST || 'whatsapp.alattab.site').toLowerCase();
  return hostOf(req) === configured;
}

function getClientKey(req, role) {
  return `${role}:${req.ip || req.socket?.remoteAddress || 'unknown'}`;
}

function loginAllowed(key) {
  const state = attempts.get(key);
  if (!state) return true;
  if (Date.now() - state.firstAttemptAt > LOGIN_WINDOW_MS) {
    attempts.delete(key);
    return true;
  }
  return state.count < MAX_LOGIN_ATTEMPTS;
}

function registerFailedLogin(key) {
  const now = Date.now();
  const state = attempts.get(key);
  if (!state || now - state.firstAttemptAt > LOGIN_WINDOW_MS) {
    attempts.set(key, { firstAttemptAt: now, count: 1 });
    return;
  }
  state.count += 1;
}

function clearLoginAttempts(key) { attempts.delete(key); }

function safeNext(value, fallback = '/') {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : fallback;
}

function getCookieForRole(req, role) {
  const cookies = parseCookies(req.headers.cookie);
  return decodeToken(cookies[role === 'admin' ? ADMIN_COOKIE : CLIENT_COOKIE]);
}

async function getAuthenticatedUser(req, clientStore) {
  const admin = getCookieForRole(req, 'admin');
  if (admin?.role === 'admin' && admin.sub === process.env.ADMIN_USERNAME) return admin;

  const client = getCookieForRole(req, 'client');
  if (client?.role === 'client' && clientStore) {
    const record = await clientStore.getByUsername(client.sub);
    if (record && Number(record.tokenVersion || 1) === Number(client.ver || 1)) return { ...client, client: record };
  }
  return null;
}

function cookieHeader(name, token, maxAge) {
  const secure = process.env.NODE_ENV === 'production' ? '; Secure' : '';
  return `${name}=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}${secure}`;
}

function clearCookie(name) { return cookieHeader(name, '', 0); }

function loginHtml({ role, next = '/', error = '' }) {
  const client = role === 'client';
  const title = client ? 'دخول العميل' : 'دخول الإدارة';
  const subtitle = client ? 'إدارة جلستك الخاصة' : 'لوحة إدارة جلسات WhatsApp';
  const safeNextValue = safeNext(next);
  const errorHtml = error ? `<div class="error">${String(error).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>` : '';
  return `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#f5f7fb"><link rel="manifest" href="/manifest.webmanifest"><title>${title}</title><style>body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f5f7fb;color:#172033;display:grid;place-items:center;min-height:100vh}.card{width:min(92vw,390px);background:#fff;border:1px solid #e7ebf1;border-radius:24px;padding:30px;box-shadow:0 18px 60px rgba(31,41,55,.08)}.logo{width:54px;height:54px;border-radius:16px;display:grid;place-items:center;background:#172033;color:#fff;font-weight:800;font-size:20px}.muted{color:#6b7280}.field{margin:16px 0}.field label{display:block;font-weight:700;margin-bottom:7px}.field input{width:100%;box-sizing:border-box;border:1px solid #d7dce4;border-radius:12px;padding:12px;font:inherit}.btn{width:100%;border:0;border-radius:12px;padding:12px;background:#172033;color:#fff;font-weight:800;font:inherit;cursor:pointer}.error{margin-top:12px;color:#b42318;background:#fff2f0;border:1px solid #ffd6d1;padding:10px;border-radius:10px}</style></head><body><main class="card"><div class="logo">WA</div><h1>${title}</h1><p class="muted">${subtitle}</p><form method="post" action="/login"><input type="hidden" name="next" value="${safeNextValue.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;')}"/><div class="field"><label>اسم المستخدم</label><input name="username" autocomplete="username" required></div><div class="field"><label>كلمة المرور</label><input type="password" name="password" autocomplete="current-password" required></div><button class="btn" type="submit">تسجيل الدخول</button>${errorHtml}</form></main></body></html>`;
}

function setupAuth(app, { clientStore }) {
  requiredEnv('ADMIN_USERNAME');
  requiredEnv('ADMIN_PASSWORD');
  requiredEnv('SESSION_SECRET');

  app.get('/login', async (req, res) => {
    const role = isClientHost(req) ? 'client' : 'admin';
    const current = await getAuthenticatedUser(req, clientStore);
    if (current?.role === role) return res.redirect(role === 'admin' ? '/admin' : '/');
    res.setHeader('Cache-Control', 'no-store');
    res.type('html').send(loginHtml({ role, next: req.query.next || '/' }));
  });

  app.post('/login', async (req, res) => {
    const role = isClientHost(req) ? 'client' : 'admin';
    const key = getClientKey(req, role);
    if (!loginAllowed(key)) return res.status(429).send('Too many login attempts');

    if (role === 'admin') {
      const valid = timingSafeEqualString(req.body?.username, process.env.ADMIN_USERNAME) && timingSafeEqualString(req.body?.password, process.env.ADMIN_PASSWORD);
      if (!valid) {
        registerFailedLogin(key);
        return res.status(401).send(loginHtml({ role, next: req.body?.next, error: 'بيانات الدخول غير صحيحة' }));
      }
      clearLoginAttempts(key);
      res.setHeader('Set-Cookie', cookieHeader(ADMIN_COOKIE, createToken('admin', process.env.ADMIN_USERNAME), SESSION_TTL_SECONDS));
      return res.redirect(safeNext(req.body?.next, '/admin'));
    }

    const record = await clientStore.verifyCredentials(req.body?.username, req.body?.password);
    if (!record) {
      registerFailedLogin(key);
      return res.status(401).send(loginHtml({ role, next: req.body?.next, error: 'بيانات الدخول غير صحيحة' }));
    }
    clearLoginAttempts(key);
    res.setHeader('Set-Cookie', cookieHeader(CLIENT_COOKIE, createToken('client', record.username, Number(record.tokenVersion || 1)), SESSION_TTL_SECONDS));
    return res.redirect(safeNext(req.body?.next, '/'));
  });

  app.post('/logout', async (req, res) => {
    const role = isClientHost(req) ? 'client' : 'admin';
    res.setHeader('Set-Cookie', clearCookie(role === 'admin' ? ADMIN_COOKIE : CLIENT_COOKIE));
    res.redirect('/login');
  });

  app.locals.auth = { getAuthenticatedUser: (req) => getAuthenticatedUser(req, clientStore), isAdminHost, isClientHost };
}

function requireAdmin(req, res, next) {
  Promise.resolve(appAuthUser(req)).then((user) => {
    if (user?.role === 'admin' && isAdminHost(req)) return next();
    if (req.path.startsWith('/api/')) return res.status(403).json({ success: false, error: 'Admin authentication required' });
    return res.redirect(`/login?next=${encodeURIComponent(req.originalUrl || '/admin')}`);
  }).catch(() => res.status(401).json({ success: false, error: 'Authentication required' }));
}

let appAuthUser = async () => null;
function bindAuthResolver(resolver) { appAuthUser = resolver; }

function requireClient(req, res, next) {
  Promise.resolve(appAuthUser(req)).then((user) => {
    if (user?.role === 'client' && user.client && isClientHost(req)) return next();
    if (req.path.startsWith('/api/')) return res.status(401).json({ success: false, error: 'Client authentication required' });
    return res.redirect(`/login?next=${encodeURIComponent(req.originalUrl || '/')}`);
  }).catch(() => res.status(401).json({ success: false, error: 'Authentication required' }));
}

function setupSocketAuth(io, clientStore) {
  io.use(async (socket, next) => {
    try {
      const cookies = parseCookies(socket.handshake.headers.cookie);
      const admin = decodeToken(cookies[ADMIN_COOKIE]);
      if (admin?.role === 'admin' && admin.sub === process.env.ADMIN_USERNAME) {
        socket.user = admin;
        return next();
      }
      const client = decodeToken(cookies[CLIENT_COOKIE]);
      const record = client?.role === 'client' ? await clientStore.getByUsername(client.sub) : null;
      if (record && Number(record.tokenVersion || 1) === Number(client.ver || 1)) {
        socket.user = { ...client, client: record };
        return next();
      }
      return next(new Error('Authentication required'));
    } catch (error) { return next(error); }
  });
}

module.exports = { setupAuth, setupSocketAuth, bindAuthResolver, requireAdmin, requireClient, hashPassword, verifyPassword, createToken, decodeToken, parseCookies, ADMIN_COOKIE, CLIENT_COOKIE };
