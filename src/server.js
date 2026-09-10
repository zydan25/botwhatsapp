const path = require('path');
const http = require('http');
const express = require('express');
const cors = require('cors');
const bodyParser = require('body-parser');
const multer = require('multer');
const fs = require('fs-extra');
const { Server } = require('socket.io');

const { JsonStore } = require('./storage');
const { SessionManager } = require('./sessionManager');
const { sanitizeSessionName, escapeHtml, statusLabel, publicApiList } = require('./utils');
const { setupAuth, setupSocketAuth } = require('../auth');

const ROOT_DIR = path.join(__dirname, '..');
const PORT = Number(process.env.PORT || 3000);
const HOST = process.env.HOST || '127.0.0.1';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/chromium-browser';
const DEFAULT_API_BASE_URL = process.env.API_BASE_URL || null;
const UPLOAD_MAX_BYTES = Number(process.env.UPLOAD_MAX_BYTES || 10 * 1024 * 1024);

const app = express();
const server = http.createServer(app);
const io = new Server(server, { cors: { origin: false } });
const store = new JsonStore(ROOT_DIR);
const manager = new SessionManager({ rootDir: ROOT_DIR, store, chromePath: CHROME_PATH, io });

app.disable('x-powered-by');
app.set('trust proxy', process.env.TRUST_PROXY === 'true');
app.use(cors({ origin: false }));
app.use(bodyParser.json({ limit: '1mb' }));
app.use(bodyParser.urlencoded({ extended: false, limit: '64kb' }));
app.use('/static', express.static(path.join(ROOT_DIR, 'public'), { index: false, maxAge: '1h' }));
app.use('/assets', express.static(path.join(ROOT_DIR, 'public'), { index: false, maxAge: '1h' }));

const upload = multer({
  dest: path.join(ROOT_DIR, 'data', 'uploads'),
  limits: { fileSize: UPLOAD_MAX_BYTES, files: 1, fields: 4, parts: 6 }
});

setupAuth(app);
setupSocketAuth(io);

function jsonError(res, status, error) {
  return res.status(status).json({ success: false, error });
}

async function removeUpload(filePath) {
  if (!filePath) return;
  await fs.remove(filePath).catch(() => {});
}

function pageShell({ title, body }) {
  return `<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHtml(title)}</title>
  <link rel="stylesheet" href="/static/styles.css" />
</head>
<body>
  ${body}
  <script src="/socket.io/socket.io.js"></script>
  <script src="/static/app.js"></script>
</body>
</html>`;
}

function sessionCard(session) {
  const canStart = ['idle', 'disconnected', 'error'].includes(session.status);
  const canStop = ['initializing', 'qr', 'authenticated', 'connected'].includes(session.status);
  return `
    <article class="session-card" data-session="${escapeHtml(session.name)}">
      <a href="/${encodeURIComponent(session.name)}" class="session-link">
        <div class="card-top">
          <div><div class="session-name">${escapeHtml(session.name)}</div><div class="session-sub">${escapeHtml(session.apiBaseUrl || 'لا يوجد API')}</div></div>
          <span class="badge ${escapeHtml(session.status)}"><span class="dot"></span>${escapeHtml(statusLabel(session.status))}</span>
        </div>
        <div class="card-grid">
          <div class="mini-stat"><span>وارد</span><strong>${session.stats?.incomingCount ?? 0}</strong></div>
          <div class="mini-stat"><span>صادر</span><strong>${session.stats?.outgoingCount ?? 0}</strong></div>
          <div class="mini-stat"><span>آخر نشاط</span><strong>${escapeHtml(session.stats?.lastMessageAt || '-')}</strong></div>
        </div>
      </a>
      <div class="session-actions">
        ${canStart ? `<button class="btn btn-good" onclick="startSession('${escapeHtml(session.name)}')">تشغيل</button>` : ''}
        ${canStop ? `<button class="btn btn-warn" onclick="stopSession('${escapeHtml(session.name)}')">إيقاف</button>` : ''}
        <button class="btn btn-bad" onclick="deleteSession('${escapeHtml(session.name)}')">حذف</button>
      </div>
    </article>`;
}

async function renderDashboard() {
  const sessions = await manager.listStatuses();
  const connected = sessions.filter((s) => s.status === 'connected').length;
  const waiting = sessions.filter((s) => s.status === 'qr').length;
  const errors = sessions.filter((s) => s.status === 'error').length;
  return pageShell({
    title: 'WhatsApp Pro - لوحة التحكم',
    body: `<div class="app-shell" id="appShell" data-page="dashboard">
      <aside class="sidebar">
        <div class="brand"><div class="brand-icon">WA</div><div><div class="brand-title">WhatsApp Pro</div><div class="brand-sub">Multi Session</div></div></div>
        <div class="side-actions"><button class="btn btn-primary" onclick="openCreateModal()">+ جلسة جديدة</button><form method="post" action="/logout"><button class="btn btn-ghost" type="submit">تسجيل الخروج</button></form></div>
        <div class="sidebar-section"><div class="section-title">الجلسات</div><div id="sidebarSessions" class="sidebar-list"></div></div>
        <div class="sidebar-section"><div class="section-title">الإشعارات</div><div id="globalNotifications" class="notice-list"></div></div>
      </aside>
      <main class="main-panel">
        <section class="hero"><div class="hero-head"><div><h1>لوحة التحكم</h1><p>إدارة الجلسات، التشغيل والإيقاف والحذف من مكان واحد.</p></div><div class="hero-actions"><button class="btn btn-ghost" onclick="refreshDashboard()">تحديث</button></div></div>
          <div class="kpi-grid"><div class="kpi"><span>كل الجلسات</span><strong id="kpiTotal">${sessions.length}</strong></div><div class="kpi"><span>متصلة</span><strong id="kpiConnected">${connected}</strong></div><div class="kpi"><span>QR منتظر</span><strong id="kpiWaiting">${waiting}</strong></div><div class="kpi"><span>أخطاء</span><strong id="kpiErrors">${errors}</strong></div></div>
        </section>
        <section class="panel"><div class="panel-head"><h2>إنشاء جلسة</h2><p>اسم إنجليزي من 3 إلى 32 حرفًا، ويمكن ربط الجلسة بـ API خارجي.</p></div>
          <div class="inline-form"><div class="field"><label>اسم الجلسة</label><input id="createName" class="input" placeholder="alattab1" maxlength="32"></div><div class="field"><label>رقم احتياطي</label><input id="createBackupPhone" class="input" placeholder="9677xxxxxxx"></div><div class="field"><label>رابط API</label><input id="createApiUrl" class="input" placeholder="https://example.com"></div><div class="field"><label>تشغيل تلقائي</label><select id="createAutoStart" class="input"><option value="true">نعم</option><option value="false">لا</option></select></div></div>
          <div class="row-between"><span class="muted small">يتم إنشاء الجلسة ثم فتح صفحتها.</span><button class="btn btn-primary" onclick="createSession()">إنشاء الآن</button></div>
        </section>
        <section class="panel"><div class="panel-head"><h2>الجلسات الحالية</h2></div><div id="sessionGrid" class="session-grid">${sessions.map(sessionCard).join('') || '<div class="empty-box">لا توجد جلسات.</div>'}</div></section>
      </main>
    </div>
    <div class="modal-backdrop" id="createModal"><div class="modal"><div class="modal-head"><h3>إنشاء جلسة جديدة</h3><button class="icon-btn" onclick="closeCreateModal()">×</button></div><div class="modal-body">
      <div class="field"><label>اسم الجلسة</label><input id="modalName" class="input"></div><div class="field"><label>رقم احتياطي</label><input id="modalBackupPhone" class="input"></div><div class="field"><label>رابط API</label><input id="modalApiUrl" class="input"></div><div class="field"><label>تشغيل تلقائي</label><select id="modalAutoStart" class="input"><option value="true">نعم</option><option value="false">لا</option></select></div>
    </div><div class="modal-actions"><button class="btn btn-ghost" onclick="closeCreateModal()">إلغاء</button><button class="btn btn-primary" onclick="createSessionFromModal()">إنشاء</button></div></div></div>`
  });
}

function renderSessionPage(session) {
  const apiCards = publicApiList(session.name).map((item) => `<div class="api-row"><code>${escapeHtml(item.method)} ${escapeHtml(item.path)}</code><span>${escapeHtml(item.desc)}</span></div>`).join('');
  return pageShell({
    title: `${session.name} - WhatsApp Pro`,
    body: `<div class="app-shell" id="appShell" data-page="session" data-session="${escapeHtml(session.name)}">
      <aside class="sidebar"><div class="brand"><div class="brand-icon">WA</div><div><div class="brand-title">WhatsApp Pro</div><div class="brand-sub">Session Manager</div></div></div>
        <div class="side-actions"><a class="btn btn-ghost" href="/">← الرئيسية</a><button class="btn btn-good" onclick="startSession('${escapeHtml(session.name)}')">تشغيل</button><button class="btn btn-warn" onclick="stopSession('${escapeHtml(session.name)}')">إيقاف</button><button class="btn btn-bad" onclick="deleteSession('${escapeHtml(session.name)}')">حذف الجلسة</button><form method="post" action="/logout"><button class="btn btn-ghost" type="submit">خروج</button></form></div>
        <div class="sidebar-section"><div class="section-title">الجلسات</div><div id="sidebarSessions" class="sidebar-list"></div></div><div class="sidebar-section"><div class="section-title">تنبيهات الجلسة</div><div id="sessionNotifications" class="notice-list"></div></div>
      </aside>
      <main class="main-panel"><section class="hero"><div class="hero-head"><div><h1>${escapeHtml(session.name)}</h1><p>تحكم كامل في الاتصال والرسائل والبيانات.</p></div><div class="hero-actions"><span id="statusBadge"></span><button class="btn btn-ghost" onclick="refreshSessionPage('${escapeHtml(session.name)}')">تحديث</button></div></div>
      <div class="kpi-grid"><div class="kpi"><span>وارد</span><strong id="countIncoming">${session.stats?.incomingCount ?? 0}</strong></div><div class="kpi"><span>صادر</span><strong id="countOutgoing">${session.stats?.outgoingCount ?? 0}</strong></div><div class="kpi"><span>آخر نشاط</span><strong id="lastActivity">${escapeHtml(session.stats?.lastMessageAt || session.updatedAt || '-')}</strong></div><div class="kpi"><span>الحالة</span><strong id="statusText">${escapeHtml(statusLabel(session.status))}</strong></div></div></section>
      <section class="content-grid"><div class="panel"><div class="panel-head"><h2>إعدادات الجلسة</h2></div><div class="info-box"><div class="info-row"><span>API Base URL</span><strong id="apiBaseUrlText">${escapeHtml(session.apiBaseUrl || '-')}</strong></div><div class="info-row"><span>الرقم الاحتياطي</span><strong>${escapeHtml(session.backupPhone || '-')}</strong></div></div><div class="field"><label>تحديث رابط API</label><input id="apiBaseUrlInput" class="input" value="${escapeHtml(session.apiBaseUrl || '')}" placeholder="https://example.com"></div><div class="row-between"><span class="muted small">سيتم التحقق من الرابط قبل حفظه.</span><button class="btn btn-primary" onclick="saveApiUrl('${escapeHtml(session.name)}')">حفظ</button></div><div class="api-list">${apiCards}</div></div>
      <div class="panel"><div class="panel-head"><h2>QR</h2><p>يظهر فقط أثناء انتظار تسجيل الدخول.</p></div><div class="qr-box" id="qrBox">${session.qrDataUrl ? `<img src="${session.qrDataUrl}" alt="QR Code">` : '<div class="empty-box">لا يوجد QR حاليًا.</div>'}</div></div></section>
      <section class="content-grid"><div class="panel"><div class="panel-head"><h2>إرسال رسالة</h2></div><div class="inline-form"><div class="field"><label>رقم الهاتف</label><input id="sendPhone" class="input" placeholder="9677xxxxxxx"></div><div class="field"><label>ملف اختياري</label><input id="sendMedia" class="input" type="file"></div><div class="field full"><label>الرسالة</label><textarea id="sendMessage" class="textarea" rows="4"></textarea></div></div><div class="row-between"><span class="muted small">حد أقصى للملف: ${Math.round(UPLOAD_MAX_BYTES / 1024 / 1024)}MB</span><button class="btn btn-good" onclick="sendSessionMessage('${escapeHtml(session.name)}')">إرسال</button></div></div><div class="panel"><div class="panel-head"><h2>آخر الرسائل</h2></div><div class="table-wrap"><table class="data-table"><thead><tr><th>الوقت</th><th>الاتجاه</th><th>الطرف</th><th>المحتوى</th></tr></thead><tbody id="messagesTable"></tbody></table></div></div></section>
      <section class="content-grid"><div class="panel"><div class="panel-head"><h2>التنبيهات</h2></div><div class="table-wrap"><table class="data-table"><thead><tr><th>الوقت</th><th>المستوى</th><th>الرسالة</th></tr></thead><tbody id="notificationsTable"></tbody></table></div></div><div class="panel"><div class="panel-head"><h2>الأخطاء</h2></div><div class="table-wrap"><table class="data-table"><thead><tr><th>الوقت</th><th>النوع</th><th>الرسالة</th></tr></thead><tbody id="errorsTable"></tbody></table></div></div></section>
      </main></div>`
  });
}

app.get('/health', async (_req, res) => {
  res.json({ status: 'ok', service: 'whatsapp-pro', timestamp: new Date().toISOString() });
});

app.get('/api/notifications', async (req, res) => {
  try {
    const raw = Number.parseInt(req.query.limit || '20', 10);
    const limit = Number.isFinite(raw) ? Math.max(1, Math.min(raw, 100)) : 20;
    res.json({ success: true, data: await store.listRecentNotifications(limit) });
  } catch (error) { jsonError(res, 500, error.message); }
});

app.get('/api/sessions', async (_req, res) => {
  try { res.json({ success: true, data: await manager.listStatuses() }); }
  catch (error) { jsonError(res, 500, error.message); }
});

app.post('/api/sessions', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.body?.name);
    const apiBaseUrl = (req.body?.apiBaseUrl || DEFAULT_API_BASE_URL || '').trim() || null;
    const backupPhone = (req.body?.backupPhone || '').trim() || null;
    const autoStart = req.body?.autoStart === true || String(req.body?.autoStart) === 'true';
    const session = await manager.createSession(name, { apiBaseUrl, backupPhone });
    if (autoStart) await session.start();
    res.status(201).json({ success: true, data: { ...session.serialize(), url: `/${encodeURIComponent(name)}` } });
  } catch (error) { jsonError(res, 400, error.message); }
});

app.get('/api/sessions/:name/status', async (req, res) => {
  try { const session = await manager.ensureSession(sanitizeSessionName(req.params.name)); res.json({ success: true, data: await session.getPublicStatus() }); }
  catch (error) { jsonError(res, 400, error.message); }
});

app.post('/api/sessions/:name/connect', async (req, res) => {
  try { const name = sanitizeSessionName(req.params.name); const session = await manager.ensureSession(name, null, null); res.json({ success: true, data: await session.start() }); }
  catch (error) { jsonError(res, 500, error.message); }
});

app.post('/api/sessions/:name/disconnect', async (req, res) => {
  try { const session = await manager.ensureSession(sanitizeSessionName(req.params.name)); res.json({ success: true, data: await session.stop() }); }
  catch (error) { jsonError(res, 500, error.message); }
});

app.post('/api/sessions/:name/logout', async (req, res) => {
  try { const session = await manager.ensureSession(sanitizeSessionName(req.params.name)); res.json({ success: true, data: await session.logout() }); }
  catch (error) { jsonError(res, 400, error.message); }
});

app.get('/api/sessions/:name/qr', async (req, res) => {
  try { const session = await manager.ensureSession(sanitizeSessionName(req.params.name)); res.json({ success: true, qr: session.qr, hasQr: !!session.qr }); }
  catch (error) { jsonError(res, 400, error.message); }
});

app.get('/api/sessions/:name/qr-image', async (req, res) => {
  try { const session = await manager.ensureSession(sanitizeSessionName(req.params.name)); const dataUrl = await session.getQrImageDataUrl(); if (!dataUrl) return jsonError(res, 404, 'No QR available'); const base64 = dataUrl.split(',')[1]; res.type('png').send(Buffer.from(base64, 'base64')); }
  catch (error) { jsonError(res, 400, error.message); }
});

app.post('/api/sessions/:name/api-url', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const apiBaseUrl = (req.body?.apiBaseUrl || '').trim() || null;
    const session = await manager.ensureSession(name);
    session.apiBaseUrl = apiBaseUrl;
    await session.persistMeta({ apiBaseUrl });
    res.json({ success: true, data: await session.getPublicStatus() });
  } catch (error) { jsonError(res, 400, error.message); }
});

app.post('/api/sessions/:name/send', upload.single('media'), async (req, res) => {
  let mediaPath = req.file?.path || null;
  try {
    const name = sanitizeSessionName(req.params.name);
    const session = await manager.ensureSession(name);
    const result = await session.sendMessage(req.body?.phoneNumber, req.body?.message || '', mediaPath);
    res.json({ success: true, data: result });
  } catch (error) {
    jsonError(res, 400, error.message);
  } finally {
    await removeUpload(mediaPath);
  }
});

app.get('/api/sessions/:name/messages', async (req, res) => {
  try { const name = sanitizeSessionName(req.params.name); const limit = Math.min(Math.max(Number.parseInt(req.query.limit || '50', 10) || 50, 1), 100); const offset = Math.max(Number.parseInt(req.query.offset || '0', 10) || 0, 0); const data = await store.getMessages(name, limit, offset); res.json({ success: true, data, count: data.length }); }
  catch (error) { jsonError(res, 400, error.message); }
});

app.get('/api/sessions/:name/errors', async (req, res) => {
  try { const name = sanitizeSessionName(req.params.name); const limit = Math.min(Math.max(Number.parseInt(req.query.limit || '25', 10) || 25, 1), 100); const data = await store.getErrors(name, limit); res.json({ success: true, data, count: data.length }); }
  catch (error) { jsonError(res, 400, error.message); }
});

app.get('/api/sessions/:name/notifications', async (req, res) => {
  try { const name = sanitizeSessionName(req.params.name); const limit = Math.min(Math.max(Number.parseInt(req.query.limit || '50', 10) || 50, 1), 100); const data = await store.getNotifications(name, limit); res.json({ success: true, data, count: data.length }); }
  catch (error) { jsonError(res, 400, error.message); }
});

app.delete('/api/sessions/:name', async (req, res) => {
  try { const name = sanitizeSessionName(req.params.name); await manager.removeSession(name); io.emit('session:deleted', { name }); res.json({ success: true, message: 'Deleted' }); }
  catch (error) { jsonError(res, 400, error.message); }
});

app.get('/:name', async (req, res, next) => {
  try { const name = sanitizeSessionName(req.params.name); const session = await manager.ensureSession(name); res.type('html').send(renderSessionPage(await session.getPublicStatus())); }
  catch (_error) { next(); }
});

app.get('/', async (_req, res) => {
  res.type('html').send(await renderDashboard());
});

app.use((error, _req, res, _next) => {
  if (error instanceof multer.MulterError) return jsonError(res, 400, error.code === 'LIMIT_FILE_SIZE' ? `حجم الملف يتجاوز ${Math.round(UPLOAD_MAX_BYTES / 1024 / 1024)}MB` : error.message);
  console.error(error);
  return jsonError(res, 500, 'Internal server error');
});

app.use((_req, res) => jsonError(res, 404, 'Not Found'));

io.on('connection', (socket) => {
  socket.emit('hello', { ok: true, timestamp: new Date().toISOString() });
});

async function bootstrap() {
  await store.init();
  await fs.ensureDir(path.join(ROOT_DIR, 'sessions'));
  await fs.ensureDir(path.join(ROOT_DIR, 'data', 'uploads'));
}

async function shutdown(signal) {
  console.log(`Received ${signal}; shutting down...`);
  server.close();
  for (const name of await store.listSessionNames()) {
    await manager.ensureSession(name).then((session) => session.stop()).catch(() => {});
  }
  process.exit(0);
}

async function main() {
  await bootstrap();
  server.listen(PORT, HOST, () => console.log(`Server running on http://${HOST}:${PORT}`));
  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
}

main().catch((error) => { console.error(error); process.exit(1); });
