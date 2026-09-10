const path = require('path');
const crypto = require('crypto');
const http = require('http');
const express = require('express');
const bodyParser = require('body-parser');
const multer = require('multer');
const fs = require('fs-extra');
const { Server } = require('socket.io');

const { JsonStore } = require('./storage');
const { ClientStore } = require('./clientStore');
const { SessionManager } = require('./sessionManager');
const { sanitizeSessionName, escapeHtml, statusLabel, validateApiBaseUrl } = require('./utils');
const { setupAuth, setupSocketAuth, bindAuthResolver, requireAdmin, requireClient } = require('../auth');

const ROOT_DIR = path.join(__dirname, '..');
const PORT = Number(process.env.PORT || 3000);
const HOST = process.env.HOST || '127.0.0.1';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/chromium-browser';
const DEFAULT_API_BASE_URL = process.env.API_BASE_URL || null;
const UPLOAD_MAX_BYTES = Math.max(64 * 1024, Number(process.env.UPLOAD_MAX_BYTES || 8 * 1024 * 1024));
const BRAND = 'WhatsApp Pro';

const app = express();
const server = http.createServer(app);
const io = new Server(server, { cors: { origin: false } });
const store = new JsonStore(ROOT_DIR);
const clientStore = new ClientStore(ROOT_DIR);
const manager = new SessionManager({ rootDir: ROOT_DIR, store, chromePath: CHROME_PATH, io });

app.disable('x-powered-by');
app.set('trust proxy', process.env.TRUST_PROXY === 'true');
app.use((req, res, next) => {
  res.setHeader('Referrer-Policy', 'same-origin');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
  next();
});
app.use(bodyParser.json({ limit: '1mb' }));
app.use(bodyParser.urlencoded({ extended: false, limit: '64kb' }));
app.use('/static', express.static(path.join(ROOT_DIR, 'public'), { index: false, maxAge: '1h' }));
app.use('/icons', express.static(path.join(ROOT_DIR, 'public', 'icons'), { index: false, maxAge: '1d' }));
app.get('/manifest.webmanifest', (_req, res) => res.sendFile(path.join(ROOT_DIR, 'public', 'manifest.webmanifest')));
app.get('/sw.js', (_req, res) => res.type('application/javascript').sendFile(path.join(ROOT_DIR, 'public', 'sw.js')));

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: UPLOAD_MAX_BYTES, files: 1, fields: 3, parts: 5 }
});

setupAuth(app, { clientStore });
bindAuthResolver((req) => app.locals.auth.getAuthenticatedUser(req));
setupSocketAuth(io, clientStore);

function jsonError(res, status, error) { return res.status(status).json({ success: false, error }); }
function text(value, max = 1000) { return String(value ?? '').trim().slice(0, max); }
function sessionName(value) { return sanitizeSessionName(value); }
function publicStatus(session, includeSecret = false) {
  const data = session.serialize();
  if (includeSecret) data.webhookSecret = session.webhookSecret;
  return data;
}
function webhookSample(session) {
  return JSON.stringify({
    session: session.name,
    botId: session.name,
    direction: 'in',
    messageId: 'message-id',
    from: '967xxxxxxxxx@c.us',
    to: '967xxxxxxxxx@c.us',
    body: 'نص الرسالة',
    type: 'chat',
    hasMedia: false,
    mediaSkipped: false,
    timestamp: new Date().toISOString()
  }, null, 2);
}

function shell(title, body, script) {
  return `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#f6f8fb"><meta name="description" content="${escapeHtml(BRAND)}"><link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/icons/icon.svg" type="image/svg+xml"><link rel="stylesheet" href="/static/styles.css"><title>${escapeHtml(title)}</title></head><body>${body}<script src="/socket.io/socket.io.js"></script><script src="/static/${script}"></script></body></html>`;
}

async function renderAdmin() {
  return shell(`${BRAND} — الإدارة}`, `
    <div class="shell" id="adminApp"><aside class="sidebar"><div class="brand"><img src="/icons/icon.svg" class="brand-logo" alt="WA"><div><strong>${BRAND}</strong><small>Admin Console</small></div></div><div class="side-actions"><button class="btn primary" data-action="create">+ جلسة وعميل</button><form method="post" action="/logout"><button class="btn ghost" type="submit">تسجيل الخروج</button></form></div><div class="sidebar-section"><div class="section-title">الجلسات</div><div id="sidebarSessions" class="sidebar-list"></div></div></aside><main class="main"><header class="topbar"><div><span class="eyebrow">ADMIN</span><h1>لوحة إدارة WhatsApp</h1><p>إدارة الحسابات والجلسات والاتصالات من مكان واحد.</p></div><button class="btn ghost" data-action="refresh">تحديث</button></header><section class="stats-grid"><div class="stat"><span>كل الجلسات</span><strong id="kpiTotal">0</strong></div><div class="stat"><span>متصلة</span><strong id="kpiConnected">0</strong></div><div class="stat"><span>QR</span><strong id="kpiQr">0</strong></div><div class="stat"><span>أخطاء</span><strong id="kpiErrors">0</strong></div></section><section class="panel"><div class="panel-head"><div><span class="eyebrow">CREATE</span><h2>إنشاء جلسة وربط العميل</h2></div></div><div class="form-grid four"><label>اسم الجلسة<input id="createName" maxlength="32" placeholder="client1"></label><label>اسم العميل<input id="createDisplayName" maxlength="100" placeholder="اسم العميل"></label><label>اسم المستخدم<input id="createUsername" maxlength="32" placeholder="client1"></label><label>كلمة المرور<input id="createPassword" type="password" minlength="10" placeholder="10 أحرف على الأقل"></label><label class="wide">وصف الجلسة<textarea id="createDescription" maxlength="1000" rows="3" placeholder="وصف كامل للجلسة والخدمة"></textarea></label><label class="wide">رابط API للاستقبال<input id="createApiUrl" placeholder="http://api.example.com"></label><label>رقم احتياطي<input id="createBackupPhone" placeholder="9677xxxxxxx"></label><label>تشغيل تلقائي<select id="createAutoStart"><option value="true">نعم</option><option value="false">لا</option></select></label></div><div class="row"><span class="hint">المرفقات المرسلة تُحفظ في الذاكرة فقط ثم تُحذف من الذاكرة بعد الإرسال.</span><button class="btn primary" data-action="submit-create">إنشاء</button></div></section><section class="panel"><div class="panel-head"><div><span class="eyebrow">SESSIONS</span><h2>الجلسات</h2></div></div><div id="sessionGrid" class="session-grid"></div></section></main></div>`, 'admin.js');
}

async function renderClient() {
  return shell(`${BRAND} — العميل`, `
    <div class="shell client-shell" id="clientApp"><header class="client-header"><div class="brand"><img src="/icons/icon.svg" class="brand-logo" alt="WA"><div><strong>${BRAND}</strong><small>Client Portal</small></div></div><div class="header-actions"><button id="installBtn" class="btn install hidden">تثبيت كتطبيق</button><form method="post" action="/logout"><button class="btn ghost" type="submit">خروج</button></form></div></header><main class="client-main"><section class="hero-card"><div><span class="eyebrow">YOUR SESSION</span><h1 id="sessionTitle">—</h1><p id="sessionDescription">—</p></div><div id="clientStatus" class="status-pill">—</div></section><section class="client-grid"><article class="panel qr-panel"><div class="panel-head"><div><span class="eyebrow">AUTHENTICATION</span><h2>ربط WhatsApp</h2></div><button class="btn ghost" id="regenerateQr">إعادة توليد QR</button></div><div class="qr-container" id="qrContainer"><div class="empty-box">لا يوجد QR حاليًا</div></div><ol class="steps"><li>افتح WhatsApp في الهاتف.</li><li>الأجهزة المرتبطة ← ربط جهاز.</li><li>امسح QR الموجود هنا.</li></ol></article><article class="panel"><div class="panel-head"><div><span class="eyebrow">CONTROL</span><h2>إدارة الاتصال</h2></div></div><div class="control-grid"><button class="btn primary" id="startBtn">تشغيل / اتصال</button><button class="btn warning" id="stopBtn">إيقاف</button><button class="btn warning" id="restartBtn">إعادة تشغيل</button><button class="btn danger" id="reauthBtn">إعادة المصادقة</button></div><div class="warning-box"><strong>إعادة المصادقة</strong><p>تحذف بيانات اعتماد WhatsApp الحالية للجلسة، وليس حساب العميل أو رابط الـAPI، ثم تولد اتصالًا جديدًا.</p></div></article></section><section class="client-grid"><article class="panel"><div class="panel-head"><div><span class="eyebrow">WEBHOOK</span><h2>استقبال الرسائل</h2></div></div><div id="apiDetails" class="detail-list"></div><pre id="webhookExample" class="code-block"></pre><div class="hint">أرسلنا لك Header باسم <code>x-whatsapp-signature</code> للتحقق من أصالة الطلب باستخدام Webhook Secret.</div></article><article class="panel"><div class="panel-head"><div><span class="eyebrow">ACCOUNT</span><h2>الأمان</h2></div></div><div id="accountDetails" class="detail-list"></div><div class="password-box"><h3>تغيير كلمة المرور</h3><label>كلمة المرور الحالية<input id="currentPassword" type="password"></label><label>كلمة المرور الجديدة<input id="newPassword" type="password" minlength="10"></label><button class="btn primary" id="changePassword">حفظ</button></div></article></section><section class="panel"><div class="panel-head"><div><span class="eyebrow">LIVE</span><h2>تفاصيل الجلسة</h2></div><button class="btn ghost" id="refresh">تحديث</button></div><div id="sessionDetails" class="detail-grid"></div></section><section class="client-grid"><article class="panel"><div class="panel-head"><h2>آخر الرسائل</h2></div><div class="table-wrap"><table class="data-table"><thead><tr><th>الوقت</th><th>الاتجاه</th><th>الطرف</th><th>المحتوى</th></tr></thead><tbody id="messagesTable"></tbody></table></div></article><article class="panel"><div class="panel-head"><h2>الأحداث</h2></div><div id="eventsList" class="events-list"></div></article></section></main><footer class="footer">تصميم وبرمجة <strong>م. زيدان العطاب</strong></footer></div>`, 'client.js');
}

app.get('/health', (_req, res) => res.json({ status: 'ok', service: 'whatsapp-pro', timestamp: new Date().toISOString() }));
app.get('/', async (req, res) => {
  if (app.locals.auth.isAdminHost(req)) return requireAdmin(req, res, async () => res.type('html').send(await renderAdmin()));
  if (app.locals.auth.isClientHost(req)) return requireClient(req, res, async () => res.type('html').send(await renderClient()));
  return res.status(404).send('Unknown host');
});
app.get('/admin', (req, res) => app.locals.auth.isAdminHost(req) ? requireAdmin(req, res, async () => res.type('html').send(await renderAdmin())) : res.status(404).end());
app.get('/app', (req, res) => app.locals.auth.isClientHost(req) ? requireClient(req, res, async () => res.type('html').send(await renderClient())) : res.status(404).end());

app.use('/api/admin', requireAdmin);
app.get('/api/admin/sessions', async (_req, res) => { try { const sessions = await manager.listStatuses({ includeSecrets: true }); const clients = await clientStore.list(); const map = new Map(clients.map((c) => [c.sessionName, c])); res.json({ success: true, data: sessions.map((s) => ({ ...s, client: map.get(s.name) || null })) }); } catch (e) { jsonError(res, 500, e.message); } });
app.post('/api/admin/sessions', async (req, res) => {
  try {
    const name = sessionName(req.body?.name); const username = clientStore.sanitizeUsername(req.body?.username); const password = String(req.body?.password || '');
    const description = text(req.body?.description, 1000); const displayName = text(req.body?.displayName, 100); const apiBaseUrl = validateApiBaseUrl(req.body?.apiBaseUrl || DEFAULT_API_BASE_URL || null); const backupPhone = text(req.body?.backupPhone, 32) || null; const autoStart = req.body?.autoStart === true || String(req.body?.autoStart) === 'true';
    if (!apiBaseUrl) throw new Error('رابط API مطلوب');
    if (password.length < 10) throw new Error('كلمة مرور العميل يجب ألا تقل عن 10 أحرف');
    if (await clientStore.getByUsername(username)) throw new Error('حساب العميل موجود بالفعل');
    const session = await manager.createSession(name, { apiBaseUrl, backupPhone, description, autoStart });
    try { const client = await clientStore.create({ username, password, sessionName: name, displayName }); await session.persistMeta({ clientUsername: client.username }); if (autoStart) await session.start(); res.status(201).json({ success: true, data: { session: publicStatus(session, true), client: { username: client.username, displayName: client.displayName } } }); }
    catch (e) { await manager.removeSession(name).catch(() => {}); throw e; }
  } catch (e) { jsonError(res, 400, e.message); }
});
app.get('/api/admin/clients', async (_req, res) => { try { res.json({ success: true, data: await clientStore.list() }); } catch (e) { jsonError(res, 500, e.message); } });
app.delete('/api/admin/sessions/:name', async (req, res) => { try { const name = sessionName(req.params.name); const client = await clientStore.getBySession(name); await manager.removeSession(name); if (client) await clientStore.delete(client.username); io.emit('session:deleted', { name }); res.json({ success: true }); } catch (e) { jsonError(res, 400, e.message); } });
app.post('/api/admin/sessions/:name/start', async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); res.json({ success: true, data: await s.start() }); } catch (e) { jsonError(res, 500, e.message); } });
app.post('/api/admin/sessions/:name/stop', async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); res.json({ success: true, data: await s.stop() }); } catch (e) { jsonError(res, 500, e.message); } });
app.post('/api/admin/sessions/:name/restart', async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); res.json({ success: true, data: await s.restart() }); } catch (e) { jsonError(res, 500, e.message); } });
app.post('/api/admin/sessions/:name/reauthenticate', async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); res.json({ success: true, data: await s.reauthenticate() }); } catch (e) { jsonError(res, 500, e.message); } });
app.post('/api/admin/sessions/:name/api-url', async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); s.apiBaseUrl = validateApiBaseUrl(req.body?.apiBaseUrl || null); await s.persistMeta({ apiBaseUrl: s.apiBaseUrl }); res.json({ success: true, data: publicStatus(s, true) }); } catch (e) { jsonError(res, 400, e.message); } });
app.post('/api/admin/sessions/:name/description', async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); s.description = text(req.body?.description, 1000); await s.persistMeta({ description: s.description }); res.json({ success: true, data: publicStatus(s, true) }); } catch (e) { jsonError(res, 400, e.message); } });

app.use('/api/client', requireClient);
async function clientSession(req) { const user = await app.locals.auth.getAuthenticatedUser(req); const client = user?.client; if (!client) throw new Error('Authentication required'); const s = await manager.ensureSession(sessionName(client.sessionName)); return { user, client, s }; }
app.get('/api/client/me', async (req, res) => { try { const { client, s } = await clientSession(req); const status = await s.getPublicStatus(); res.json({ success: true, data: { client: { username: client.username, displayName: client.displayName }, session: { ...status, description: s.description, webhookSecret: s.webhookSecret }, api: { baseUrl: s.apiBaseUrl, webhookUrl: `${s.apiBaseUrl}/webhook/whatsapp`, statusUrl: `${s.apiBaseUrl}/webhook/session-status`, qrUrl: `${s.apiBaseUrl}/webhook/qr`, signatureHeader: 'x-whatsapp-signature' }, authentication: { method: 'HttpOnly signed cookie', scope: 'This customer account is bound to this session only' }, webhookExample: webhookSample(s), docs: { receive: 'POST /webhook/whatsapp', signature: 'HMAC-SHA256 على JSON body مع Webhook Secret، ويرسل في x-whatsapp-signature.', media: 'المرفقات الواردة لا يتم تنزيلها أو حفظها محليًا.' } } }); } catch (e) { jsonError(res, 400, e.message); } });
app.get('/api/client/messages', async (req, res) => { try { const { client } = await clientSession(req); const limit = Math.min(Math.max(Number.parseInt(req.query.limit || '50', 10) || 50, 1), 100); res.json({ success: true, data: await store.getMessages(sessionName(client.sessionName), limit, 0) }); } catch (e) { jsonError(res, 400, e.message); } });
app.post('/api/client/session/start', async (req, res) => { try { const { s } = await clientSession(req); res.json({ success: true, data: await s.start() }); } catch (e) { jsonError(res, 500, e.message); } });
app.post('/api/client/session/stop', async (req, res) => { try { const { s } = await clientSession(req); res.json({ success: true, data: await s.stop() }); } catch (e) { jsonError(res, 500, e.message); } });
app.post('/api/client/session/restart', async (req, res) => { try { const { s } = await clientSession(req); res.json({ success: true, data: await s.restart() }); } catch (e) { jsonError(res, 500, e.message); } });
app.post('/api/client/session/qr/regenerate', async (req, res) => { try { const { s } = await clientSession(req); res.json({ success: true, data: await s.regenerateQr() }); } catch (e) { jsonError(res, 500, e.message); } });
app.post('/api/client/session/reauthenticate', async (req, res) => { try { const { s } = await clientSession(req); res.json({ success: true, data: await s.reauthenticate() }); } catch (e) { jsonError(res, 500, e.message); } });
app.post('/api/client/password', async (req, res) => { try { const user = await app.locals.auth.getAuthenticatedUser(req); const client = user?.client; if (!client) throw new Error('Authentication required'); if (!(await clientStore.verifyCredentials(client.username, req.body?.currentPassword))) throw new Error('كلمة المرور الحالية غير صحيحة'); await clientStore.updatePassword(client.username, req.body?.newPassword); res.setHeader('Set-Cookie', 'wa_client_auth=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'); res.json({ success: true }); } catch (e) { jsonError(res, 400, e.message); } });

app.use('/api/sessions', requireAdmin);
app.get('/api/sessions', async (_req, res) => { try { res.json({ success: true, data: await manager.listStatuses({ includeSecrets: true }) }); } catch (e) { jsonError(res, 500, e.message); } });
app.get('/api/sessions/:name/status', async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); res.json({ success: true, data: await s.getPublicStatus() }); } catch (e) { jsonError(res, 400, e.message); } });
app.get('/api/sessions/:name/qr', async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); res.json({ success: true, qr: s.qr, hasQr: !!s.qr }); } catch (e) { jsonError(res, 400, e.message); } });
app.get('/api/sessions/:name/qr-image', async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); const dataUrl = await s.getQrImageDataUrl(); if (!dataUrl) return jsonError(res, 404, 'No QR available'); res.type('png').send(Buffer.from(dataUrl.split(',')[1], 'base64')); } catch (e) { jsonError(res, 400, e.message); } });
app.post('/api/sessions/:name/connect', async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); res.json({ success: true, data: await s.start() }); } catch (e) { jsonError(res, 500, e.message); } });
app.post('/api/sessions/:name/disconnect', async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); res.json({ success: true, data: await s.stop() }); } catch (e) { jsonError(res, 500, e.message); } });
app.post('/api/sessions/:name/logout', async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); res.json({ success: true, data: await s.logout() }); } catch (e) { jsonError(res, 400, e.message); } });
app.post('/api/sessions/:name/send', upload.single('media'), async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); const media = req.file ? { buffer: req.file.buffer, mimetype: req.file.mimetype, filename: req.file.originalname, size: req.file.size } : null; res.json({ success: true, data: await s.sendMessage(req.body?.phoneNumber, req.body?.message || '', media) }); } catch (e) { jsonError(res, 400, e.message); } });
app.get('/api/sessions/:name/messages', async (req, res) => { try { const data = await store.getMessages(sessionName(req.params.name), 100, 0); res.json({ success: true, data }); } catch (e) { jsonError(res, 400, e.message); } });
app.get('/api/sessions/:name/errors', async (req, res) => { try { res.json({ success: true, data: await store.getErrors(sessionName(req.params.name), 100) }); } catch (e) { jsonError(res, 400, e.message); } });
app.get('/api/sessions/:name/notifications', async (req, res) => { try { res.json({ success: true, data: await store.getNotifications(sessionName(req.params.name), 100) }); } catch (e) { jsonError(res, 400, e.message); } });
app.post('/api/sessions/:name/reauthenticate', async (req, res) => { try { const s = await manager.ensureSession(sessionName(req.params.name)); res.json({ success: true, data: await s.reauthenticate() }); } catch (e) { jsonError(res, 500, e.message); } });
app.delete('/api/sessions/:name', async (req, res) => { try { const name = sessionName(req.params.name); const client = await clientStore.getBySession(name); await manager.removeSession(name); if (client) await clientStore.delete(client.username); io.emit('session:deleted', { name }); res.json({ success: true }); } catch (e) { jsonError(res, 400, e.message); } });

app.use((error, _req, res, _next) => { if (error instanceof multer.MulterError) return jsonError(res, 400, error.code === 'LIMIT_FILE_SIZE' ? `حجم الملف يتجاوز ${Math.ceil(UPLOAD_MAX_BYTES / 1024 / 1024)}MB` : error.message); console.error(error); return jsonError(res, 500, 'Internal server error'); });
app.use((_req, res) => res.status(404).json({ success: false, error: 'Not Found' }));

io.on('connection', (socket) => {
  socket.emit('hello', { ok: true, timestamp: new Date().toISOString() });
  socket.on('join-session', (name) => { if (socket.user?.role === 'client' && socket.user.client?.sessionName !== name) return; if (socket.user?.role === 'admin' || socket.user?.client?.sessionName === name) socket.join(`session:${name}`); });
});

async function bootstrap() { await store.init(); await clientStore.init(); await fs.ensureDir(path.join(ROOT_DIR, 'sessions')); }
async function shutdown(signal) { console.log(`Received ${signal}; shutting down...`); for (const name of await store.listSessionNames()) await manager.ensureSession(name).then((s) => s.stop()).catch(() => {}); server.close(() => process.exit(0)); }
async function main() { await bootstrap(); server.listen(PORT, HOST, () => console.log(`Server running on http://${HOST}:${PORT}`)); process.on('SIGINT', () => shutdown('SIGINT')); process.on('SIGTERM', () => shutdown('SIGTERM')); }
main().catch((e) => { console.error(e); process.exit(1); });
