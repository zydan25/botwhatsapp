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
const {
  sanitizeSessionName,
  escapeHtml,
  statusLabel,
  safeJson,
  publicApiList
} = require('./utils');

const ROOT_DIR = path.join(__dirname, '..');
const PORT = process.env.PORT || 3000;
//const CHROME_PATH = process.env.CHROME_PATH || '/snap/bin/chromium';
const CHROME_PATH = process.env.CHROME_PATH || "/usr/bin/chromium-browser";
const DEFAULT_API_BASE_URL = process.env.API_BASE_URL || null;

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: { origin: '*' }
});

const store = new JsonStore(ROOT_DIR);
const manager = new SessionManager({ rootDir: ROOT_DIR, store, chromePath: CHROME_PATH, io });

app.use(cors());
app.use(bodyParser.json({ limit: '25mb' }));
app.use(bodyParser.urlencoded({ extended: true }));
app.use('/static', express.static(path.join(ROOT_DIR, 'public')));
app.use('/assets', express.static(path.join(ROOT_DIR, 'public')));

const upload = multer({
  dest: path.join(ROOT_DIR, 'data', 'uploads')
});

function pageShell({ title, body, extraHead = '', extraScript = '' }) {
  return `<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHtml(title)}</title>
  <link rel="stylesheet" href="/static/styles.css" />
  ${extraHead}
</head>
<body>
  ${body}
  <script src="/socket.io/socket.io.js"></script>
  <script src="/static/app.js"></script>
  ${extraScript}
</body>
</html>`;
}

async function bootstrap() {
  await store.init();
  await fs.ensureDir(path.join(ROOT_DIR, 'data', 'uploads'));
  await fs.ensureDir(path.join(ROOT_DIR, 'sessions'));
}

function formatStatusCard(session) {
  return `
    <a href="/${encodeURIComponent(session.name)}" class="session-card">
      <div class="card-top">
        <div>
          <div class="session-name">${escapeHtml(session.name)}</div>
          <div class="session-sub">${escapeHtml(session.apiBaseUrl || 'API غير محدد')}</div>
        </div>
        <span class="badge ${escapeHtml(session.status)}">
          <span class="dot"></span>${escapeHtml(statusLabel(session.status))}
        </span>
      </div>
      <div class="card-grid">
        <div class="mini-stat">
          <span>وارد</span><strong>${session.stats?.incomingCount ?? 0}</strong>
        </div>
        <div class="mini-stat">
          <span>صادر</span><strong>${session.stats?.outgoingCount ?? 0}</strong>
        </div>
        <div class="mini-stat">
          <span>آخر نشاط</span><strong>${escapeHtml(session.stats?.lastMessageAt || session.updatedAt || '-')}</strong>
        </div>
      </div>
      <div class="session-footer">
        <span class="pill">QR: ${session.qrAvailable ? 'متاح' : 'لا'}</span>
        <span class="pill">${escapeHtml(session.backupPhone || 'بدون رقم احتياطي')}</span>
      </div>
    </a>
  `;
}

async function renderDashboard() {
  const sessions = await manager.listStatuses();
  const connected = sessions.filter((s) => s.status === 'connected').length;
  const waiting = sessions.filter((s) => s.status === 'qr').length;
  const errors = sessions.filter((s) => s.status === 'error').length;

  return pageShell({
    title: 'لوحة واتساب الاحترافية',
    body: `
    <div class="app-shell" id="appShell" data-page="dashboard">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-icon">WA</div>
          <div>
            <div class="brand-title">WhatsApp Pro</div>
            <div class="brand-sub">Multi Session</div>
          </div>
        </div>

        <div class="side-actions">
          <button class="btn btn-primary" onclick="openCreateModal()">+ جلسة جديدة</button>
          <a class="btn btn-ghost" href="/health">Health</a>
        </div>

        <div class="sidebar-section">
          <div class="section-title">الجلسات</div>
          <div id="sidebarSessions" class="sidebar-list">
            ${sessions.length ? sessions.map((s) => `
              <a href="/${encodeURIComponent(s.name)}" class="sidebar-item ${escapeHtml(s.status)}">
                <span class="sidebar-dot"></span>
                <span class="sidebar-name">${escapeHtml(s.name)}</span>
                <span class="sidebar-status">${escapeHtml(statusLabel(s.status))}</span>
              </a>
            `).join('') : '<div class="empty-box">لا توجد جلسات بعد</div>'}
          </div>
        </div>

        <div class="sidebar-section">
          <div class="section-title">الإشعارات</div>
          <div id="globalNotifications" class="notice-list"></div>
        </div>
      </aside>

      <main class="main-panel">
        <section class="hero">
          <div class="hero-head">
            <div>
              <h1>لوحة التحكم الاحترافية</h1>
              <p>
                جلسات متعددة، QR مباشر، سايدبار للجلسات، وتنبيهات لحظية، مع API مستقل لكل رقم.
              </p>
            </div>
            <div class="hero-actions">
              <button class="btn btn-ghost" onclick="refreshAll()">تحديث الآن</button>
              <a class="btn btn-ghost" href="/api/sessions" target="_blank">JSON</a>
            </div>
          </div>

          <div class="kpi-grid">
            <div class="kpi"><span>كل الجلسات</span><strong id="kpiTotal">${sessions.length}</strong></div>
            <div class="kpi"><span>متصلة</span><strong id="kpiConnected">${connected}</strong></div>
            <div class="kpi"><span>QR منتظر</span><strong id="kpiWaiting">${waiting}</strong></div>
            <div class="kpi"><span>أخطاء</span><strong id="kpiErrors">${errors}</strong></div>
          </div>
        </section>

        <section class="content-grid">
          <div class="panel">
            <div class="panel-head">
              <h2>إنشاء جلسة جديدة</h2>
              <p>أدخل اسمًا بالإنجليزية، ورقمًا احتياطيًا، ورابط API الخاص بهذه الجلسة.</p>
            </div>

            <div class="inline-form">
              <div class="field">
                <label>اسم الجلسة</label>
                <input id="createName" class="input" placeholder="alattab1" />
              </div>
              <div class="field">
                <label>رقم احتياطي</label>
                <input id="createBackupPhone" class="input" placeholder="9677xxxxxxx" />
              </div>
              <div class="field">
                <label>رابط API</label>
                <input id="createApiUrl" class="input" placeholder="http://127.0.0.1:5000" />
              </div>
              <div class="field">
                <label>تشغيل تلقائي</label>
                <select id="createAutoStart" class="input">
                  <option value="true">نعم</option>
                  <option value="false">لا</option>
                </select>
              </div>
            </div>

            <div class="row-between">
              <div class="muted small">بعد الإنشاء سيتم فتح صفحة الجلسة مباشرة.</div>
              <button class="btn btn-primary" onclick="createSession()">إنشاء الآن</button>
            </div>
          </div>

          <div class="panel">
            <div class="panel-head">
              <h2>ماذا يميز هذه النسخة</h2>
            </div>
            <div class="feature-grid">
              <div class="feature"><strong>واجهة جانبية</strong><span>كل الجلسات في سايدبار ثابت.</span></div>
              <div class="feature"><strong>تنبيهات منفصلة</strong><span>كل جلسة لها إشعاراتها وسجلها.</span></div>
              <div class="feature"><strong>Socket لحظي</strong><span>التحديثات تصل بدون إعادة تحميل.</span></div>
              <div class="feature"><strong>بدون تنزيل ملفات</strong><span>لا يتم حفظ مرفقات واتساب الواردة.</span></div>
              <div class="feature"><strong>API مستقل</strong><span>كل جلسة تتصل بـ webhook خاص بها.</span></div>
              <div class="feature"><strong>مسار مستقل</strong><span>مثال: /alattab1</span></div>
            </div>
          </div>
        </section>

        <section class="cards-area">
          <div class="panel">
            <div class="panel-head">
              <h2>الجلسات الحالية</h2>
            </div>
            <div class="session-grid" id="sessionGrid">
              ${sessions.length ? sessions.map(formatStatusCard).join('') : '<div class="empty-box">ابدأ بإنشاء جلسة جديدة.</div>'}
            </div>
          </div>
        </section>
      </main>
    </div>

    <div class="modal-backdrop" id="createModal">
      <div class="modal">
        <div class="modal-head">
          <h3>إنشاء جلسة جديدة</h3>
          <button class="icon-btn" onclick="closeCreateModal()">×</button>
        </div>
        <div class="modal-body">
          <div class="field"><label>اسم الجلسة</label><input id="modalName" class="input" placeholder="alattab1" /></div>
          <div class="field"><label>رقم احتياطي</label><input id="modalBackupPhone" class="input" placeholder="9677xxxxxxx" /></div>
          <div class="field"><label>رابط API</label><input id="modalApiUrl" class="input" placeholder="http://127.0.0.1:5000" /></div>
          <div class="field"><label>تشغيل تلقائي</label><select id="modalAutoStart" class="input"><option value="true">نعم</option><option value="false">لا</option></select></div>
        </div>
        <div class="modal-actions">
          <button class="btn btn-ghost" onclick="closeCreateModal()">إلغاء</button>
          <button class="btn btn-primary" onclick="createSessionFromModal()">إنشاء</button>
        </div>
      </div>
    </div>
    `
  });
}

function renderSessionPage(session) {
  const apiList = publicApiList(session.name);
  const apiCards = apiList.map((i) => `
    <div class="api-row">
      <code>${escapeHtml(i.method)} ${escapeHtml(i.path)}</code>
      <span>${escapeHtml(i.desc)}</span>
    </div>
  `).join('');

  return pageShell({
    title: `${session.name} - الجلسة`,
    body: `
    <div class="app-shell" id="appShell" data-page="session" data-session="${escapeHtml(session.name)}">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-icon">WA</div>
          <div>
            <div class="brand-title">WhatsApp Pro</div>
            <div class="brand-sub">Session Manager</div>
          </div>
        </div>

        <div class="side-actions">
          <a class="btn btn-ghost" href="/">← الرئيسية</a>
          <button class="btn btn-primary" onclick="startSession('${escapeHtml(session.name)}')">تشغيل</button>
        </div>

        <div class="sidebar-section">
          <div class="section-title">الجلسات</div>
          <div id="sidebarSessions" class="sidebar-list"></div>
        </div>

        <div class="sidebar-section">
          <div class="section-title">إشعارات الجلسة</div>
          <div id="sessionNotifications" class="notice-list"></div>
        </div>
      </aside>

      <main class="main-panel">
        <section class="hero">
          <div class="hero-head">
            <div>
              <h1>${escapeHtml(session.name)}</h1>
              <p>واجهة الجلسة مع QR مباشر، API واضح، وتنبيهات مستقلة.</p>
            </div>
            <div class="hero-actions">
              <span id="statusBadge"></span>
              <button class="btn btn-ghost" onclick="refreshSessionPage('${escapeHtml(session.name)}')">تحديث</button>
              <button class="btn btn-warn" onclick="stopSession('${escapeHtml(session.name)}')">إيقاف</button>
              <button class="btn btn-bad" onclick="logoutSession('${escapeHtml(session.name)}')">Logout</button>
            </div>
          </div>

          <div class="kpi-grid">
            <div class="kpi"><span>وارد</span><strong id="countIncoming">${session.stats?.incomingCount ?? 0}</strong></div>
            <div class="kpi"><span>صادر</span><strong id="countOutgoing">${session.stats?.outgoingCount ?? 0}</strong></div>
            <div class="kpi"><span>آخر نشاط</span><strong id="lastActivity">${escapeHtml(session.stats?.lastMessageAt || session.updatedAt || '-')}</strong></div>
            <div class="kpi"><span>الحالة</span><strong id="statusText">${escapeHtml(statusLabel(session.status))}</strong></div>
          </div>
        </section>

        <section class="content-grid">
          <div class="panel">
            <div class="panel-head">
              <h2>معلومات الجلسة وAPI</h2>
              <p>هذه الجلسة ترسل إلى رابطها الخاص، ويمكنك نسخه من هنا.</p>
            </div>

            <div class="info-box">
              <div class="info-row"><span>API Base URL</span><strong id="apiBaseUrlText">${escapeHtml(session.apiBaseUrl || '-')}</strong></div>
              <div class="info-row"><span>رقم احتياطي</span><strong>${escapeHtml(session.backupPhone || '-')}</strong></div>
              <div class="info-row"><span>رابط الوصول</span><strong>/${escapeHtml(session.name)}</strong></div>
            </div>

            <div class="field" style="margin-top:14px">
              <label>تحديث رابط API</label>
              <input id="apiBaseUrlInput" class="input" value="${escapeHtml(session.apiBaseUrl || '')}" placeholder="http://127.0.0.1:5000" />
            </div>
            <div class="row-between">
              <div class="muted small">الرسائل الواردة والصادرة ترتبط بهذه الجلسة فقط.</div>
              <button class="btn btn-primary" onclick="saveApiUrl('${escapeHtml(session.name)}')">حفظ الرابط</button>
            </div>

            <div class="api-list">
              ${apiCards}
            </div>
          </div>

          <div class="panel">
            <div class="panel-head">
              <h2>QR مباشر</h2>
              <p>يظهر هنا فور توليد الكود ويتم تحديثه تلقائيًا.</p>
            </div>
            <div class="qr-box" id="qrBox">
              ${session.qrDataUrl ? `<img src="${session.qrDataUrl}" alt="QR Code" />` : '<div class="empty-box">لا يوجد QR حاليًا</div>'}
            </div>
            <div class="row-between" style="margin-top:12px">
              <div class="muted small">API: <code id="qrApiHint">/api/sessions/${escapeHtml(session.name)}/qr-image</code></div>
              <a class="btn btn-ghost" href="/api/sessions/${encodeURIComponent(session.name)}/qr-image" target="_blank">فتح الصورة</a>
            </div>
          </div>
        </section>

        <section class="content-grid">
          <div class="panel">
            <div class="panel-head">
              <h2>إرسال رسالة</h2>
            </div>
            <div class="inline-form">
              <div class="field">
                <label>رقم الهاتف</label>
                <input id="sendPhone" class="input" placeholder="9677xxxxxxx" />
              </div>
              <div class="field">
                <label>ملف اختياري</label>
                <input id="sendMedia" class="input" type="file" />
              </div>
              <div class="field full">
                <label>الرسالة</label>
                <textarea id="sendMessage" class="textarea" rows="4" placeholder="اكتب الرسالة هنا"></textarea>
              </div>
            </div>
            <div class="row-between">
              <div class="muted small">ترسل الرسائل من هذه الجلسة فقط.</div>
              <button class="btn btn-good" onclick="sendSessionMessage('${escapeHtml(session.name)}')">إرسال</button>
            </div>
          </div>

          <div class="panel">
            <div class="panel-head">
              <h2>آخر الرسائل</h2>
            </div>
            <div class="table-wrap">
              <table class="data-table">
                <thead><tr><th>الوقت</th><th>الاتجاه</th><th>الطرف</th><th>المحتوى</th></tr></thead>
                <tbody id="messagesTable">
                  ${(session.messages || []).map((m) => `
                    <tr>
                      <td>${escapeHtml(m.timestamp || '-')}</td>
                      <td>${escapeHtml(m.direction || '-')}</td>
                      <td>${escapeHtml(m.from || m.to || '-')}</td>
                      <td>${escapeHtml((m.body || '').slice(0, 120))}${m.hasMedia ? ' <span class="badge mini">Media skipped</span>' : ''}</td>
                    </tr>
                  `).join('') || '<tr><td colspan="4" class="empty-cell">لا توجد رسائل بعد</td></tr>'}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section class="content-grid">
          <div class="panel">
            <div class="panel-head">
              <h2>التنبيهات</h2>
            </div>
            <div class="table-wrap">
              <table class="data-table">
                <thead><tr><th>الوقت</th><th>المستوى</th><th>الرسالة</th></tr></thead>
                <tbody id="notificationsTable">
                  ${(session.notifications || []).map((n) => `
                    <tr>
                      <td>${escapeHtml(n.timestamp || '-')}</td>
                      <td>${escapeHtml(n.level || '-')}</td>
                      <td>${escapeHtml(n.text || '-')}</td>
                    </tr>
                  `).join('') || '<tr><td colspan="3" class="empty-cell">لا توجد تنبيهات بعد</td></tr>'}
                </tbody>
              </table>
            </div>
          </div>

          <div class="panel">
            <div class="panel-head">
              <h2>الأخطاء الأخيرة</h2>
            </div>
            <div class="table-wrap">
              <table class="data-table">
                <thead><tr><th>الوقت</th><th>النوع</th><th>الرسالة</th></tr></thead>
                <tbody id="errorsTable">
                  ${(session.errors || []).map((e) => `
                    <tr>
                      <td>${escapeHtml(e.timestamp || '-')}</td>
                      <td>${escapeHtml(e.type || '-')}</td>
                      <td>${escapeHtml(e.message || '-')}</td>
                    </tr>
                  `).join('') || '<tr><td colspan="3" class="empty-cell">لا توجد أخطاء</td></tr>'}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </main>
    </div>
    `,
    extraScript: `<script>window.__SESSION_NAME__ = ${JSON.stringify(session.name)};</script>`
  });
}

app.get('/health', async (_, res) => {
  res.json({
    status: 'ok',
    timestamp: new Date().toISOString()
  });
});


app.get('/api/notifications', async (req, res) => {
  try {
    const limit = Math.min(parseInt(req.query.limit || '20', 10), 100);
    const data = await store.listRecentNotifications(limit);
    res.json({ success: true, data, count: data.length });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

app.get('/api/sessions', async (req, res) => {
  try {
    const data = await manager.listStatuses();
    res.json({ success: true, data });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

app.post('/api/sessions', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.body.name);
    const apiBaseUrl = (req.body.apiBaseUrl || DEFAULT_API_BASE_URL || '').trim() || null;
    const backupPhone = (req.body.backupPhone || '').trim() || null;
    const autoStart = String(req.body.autoStart) === 'true' || req.body.autoStart === true;

    const session = await manager.createSession(name, { apiBaseUrl, backupPhone });
    if (autoStart) {
      await session.start();
    }

    res.json({
      success: true,
      data: {
        ...session.serialize(),
        url: `/${encodeURIComponent(name)}`
      }
    });
  } catch (error) {
    res.status(400).json({ success: false, error: error.message });
  }
});

app.get('/api/sessions/:name/status', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const session = await manager.ensureSession(name);
    res.json({ success: true, data: await session.getPublicStatus() });
  } catch (error) {
    res.status(400).json({ success: false, error: error.message });
  }
});

app.post('/api/sessions/:name/connect', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const apiBaseUrl = (req.body.apiBaseUrl || DEFAULT_API_BASE_URL || '').trim() || null;
    const backupPhone = (req.body.backupPhone || '').trim() || null;
    const session = await manager.ensureSession(name, apiBaseUrl, backupPhone);
    const data = await session.start();
    res.json({ success: true, data });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

app.post('/api/sessions/:name/disconnect', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const session = await manager.ensureSession(name);
    const data = await session.stop();
    res.json({ success: true, data });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

app.post('/api/sessions/:name/logout', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const session = await manager.ensureSession(name);
    const data = await session.logout();
    res.json({ success: true, data });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

app.get('/api/sessions/:name/qr', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const session = await manager.ensureSession(name);
    res.json({ success: true, qr: session.qr, hasQr: !!session.qr });
  } catch (error) {
    res.status(400).json({ success: false, error: error.message });
  }
});

app.get('/api/sessions/:name/qr-image', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const session = await manager.ensureSession(name);
    const dataUrl = await session.getQrImageDataUrl();
    if (!dataUrl) return res.status(404).json({ success: false, error: 'No QR available' });
    const base64 = dataUrl.split(',')[1];
    const buf = Buffer.from(base64, 'base64');
    res.setHeader('Content-Type', 'image/png');
    res.send(buf);
  } catch (error) {
    res.status(400).json({ success: false, error: error.message });
  }
});

app.post('/api/sessions/:name/api-url', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const apiBaseUrl = (req.body.apiBaseUrl || '').trim() || null;
    const session = await manager.ensureSession(name);
    session.apiBaseUrl = apiBaseUrl;
    await session.persistMeta({ apiBaseUrl });
    res.json({ success: true, data: await session.getPublicStatus() });
  } catch (error) {
    res.status(400).json({ success: false, error: error.message });
  }
});

app.post('/api/sessions/:name/send', upload.single('media'), async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const session = await manager.ensureSession(name);
    const phoneNumber = req.body.phoneNumber;
    const message = req.body.message || '';
    const mediaPath = req.file ? req.file.path : null;
    const result = await session.sendMessage(phoneNumber, message, mediaPath);
    res.json({ success: true, data: result });
  } catch (error) {
    res.status(400).json({ success: false, error: error.message });
  }
});

app.get('/api/sessions/:name/messages', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const limit = Math.min(parseInt(req.query.limit || '50', 10), 100);
    const offset = Math.max(parseInt(req.query.offset || '0', 10), 0);
    const messages = await store.getMessages(name, limit, offset);
    res.json({ success: true, data: messages, count: messages.length });
  } catch (error) {
    res.status(400).json({ success: false, error: error.message });
  }
});

app.get('/api/sessions/:name/errors', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const limit = Math.min(parseInt(req.query.limit || '25', 10), 100);
    const errors = await store.getErrors(name, limit);
    res.json({ success: true, data: errors, count: errors.length });
  } catch (error) {
    res.status(400).json({ success: false, error: error.message });
  }
});

app.get('/api/sessions/:name/notifications', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const limit = Math.min(parseInt(req.query.limit || '50', 10), 100);
    const notifications = await store.getNotifications(name, limit);
    res.json({ success: true, data: notifications, count: notifications.length });
  } catch (error) {
    res.status(400).json({ success: false, error: error.message });
  }
});

app.delete('/api/sessions/:name', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    await manager.removeSession(name);
    res.json({ success: true, message: 'Deleted' });
  } catch (error) {
    res.status(400).json({ success: false, error: error.message });
  }
});

app.post('/webhook/:name/whatsapp', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const session = await manager.ensureSession(name);
    await session.store.appendMessage(name, {
      direction: 'external',
      payload: req.body,
      timestamp: new Date().toISOString()
    });
    res.json({ success: true });
  } catch (error) {
    res.status(400).json({ success: false, error: error.message });
  }
});

app.post('/webhook/:name/qr', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const session = await manager.ensureSession(name);
    await session.store.appendNotification(name, {
      session: name,
      level: 'info',
      text: 'تم استقبال QR في webhook',
      timestamp: new Date().toISOString()
    });
    res.json({ success: true });
  } catch (error) {
    res.status(400).json({ success: false, error: error.message });
  }
});

app.post('/webhook/:name/session-status', async (req, res) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    const session = await manager.ensureSession(name);
    await session.store.appendNotification(name, {
      session: name,
      level: 'info',
      text: `تحديث حالة: ${req.body?.status || 'unknown'}`,
      timestamp: new Date().toISOString()
    });
    res.json({ success: true });
  } catch (error) {
    res.status(400).json({ success: false, error: error.message });
  }
});

app.get('/:name', async (req, res, next) => {
  try {
    const name = sanitizeSessionName(req.params.name);
    await manager.ensureSession(name);
    const session = await manager.ensureSession(name);
    const status = await session.getPublicStatus();
    res.send(renderSessionPage(status));
  } catch (error) {
    next();
  }
});

app.get('/', async (req, res) => {
  res.send(await renderDashboard());
});

app.use((req, res) => {
  res.status(404).json({ success: false, error: 'Not Found' });
});

io.on('connection', (socket) => {
  socket.emit('hello', { ok: true, timestamp: new Date().toISOString() });
});

async function main() {
  await bootstrap();
  server.listen(PORT, '127.0.0.1', () => {
    console.log(`Server running on http://127.0.0.1:${PORT}`);
  });

  process.on('SIGINT', async () => {
    try {
      for (const name of await store.listSessionNames()) {
        const session = await manager.ensureSession(name);
        await session.stop().catch(() => {});
      }
    } finally {
      process.exit(0);
    }
  });
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
