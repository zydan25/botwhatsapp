function escapeHtml(str = '') {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;').replace(/'/g, '&#39;');
}

async function requestJson(url, options = {}) {
  const res = await fetch(url, { credentials: 'same-origin', ...options });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    throw new Error('Authentication required');
  }
  if (!res.ok || data.success === false) throw new Error(data.error || `Request failed: ${res.status}`);
  return data;
}

function showError(error) {
  console.error(error);
  const message = error?.message || 'حدث خطأ غير متوقع';
  window.alert(message);
}

function openCreateModal() { document.getElementById('createModal')?.classList.add('open'); }
function closeCreateModal() { document.getElementById('createModal')?.classList.remove('open'); }

function formValue(id1, id2) {
  return document.getElementById(id1)?.value?.trim() || document.getElementById(id2)?.value?.trim() || '';
}

async function createSession() {
  try {
    const name = formValue('createName', 'modalName');
    const backupPhone = formValue('createBackupPhone', 'modalBackupPhone');
    const apiBaseUrl = formValue('createApiUrl', 'modalApiUrl');
    const select = document.getElementById('createAutoStart') || document.getElementById('modalAutoStart');
    const autoStart = (select?.value || 'true') === 'true';
    if (!name) throw new Error('اسم الجلسة مطلوب');
    const result = await requestJson('/api/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, backupPhone, apiBaseUrl, autoStart }) });
    window.location.href = result.data.url;
  } catch (error) { showError(error); }
}
async function createSessionFromModal() { await createSession(); }

async function startSession(name) {
  try { await requestJson(`/api/sessions/${encodeURIComponent(name)}/connect`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); await refreshAll(); }
  catch (error) { showError(error); }
}
async function stopSession(name) {
  try { await requestJson(`/api/sessions/${encodeURIComponent(name)}/disconnect`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); await refreshAll(); }
  catch (error) { showError(error); }
}
async function logoutSession(name) {
  try { if (!window.confirm(`هل تريد تسجيل الخروج من ${name}؟`)) return; await requestJson(`/api/sessions/${encodeURIComponent(name)}/logout`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); await refreshAll(); }
  catch (error) { showError(error); }
}
async function deleteSession(name) {
  try {
    const answer = window.prompt(`اكتب اسم الجلسة "${name}" لتأكيد الحذف. سيتم حذف جلسة WhatsApp وبيانات الرسائل والأخطاء والتنبيهات.`);
    if (answer !== name) return;
    await requestJson(`/api/sessions/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (document.getElementById('appShell')?.dataset?.page === 'session') window.location.href = '/';
    else await refreshDashboard();
  } catch (error) { showError(error); }
}

async function saveApiUrl(name) {
  try {
    const input = document.getElementById('apiBaseUrlInput');
    await requestJson(`/api/sessions/${encodeURIComponent(name)}/api-url`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ apiBaseUrl: input?.value?.trim() || '' }) });
    await refreshSessionPage(name);
  } catch (error) { showError(error); }
}

async function sendSessionMessage(name) {
  try {
    const formData = new FormData();
    formData.append('phoneNumber', document.getElementById('sendPhone')?.value?.trim() || '');
    formData.append('message', document.getElementById('sendMessage')?.value?.trim() || '');
    const media = document.getElementById('sendMedia')?.files?.[0];
    if (media) formData.append('media', media);
    const res = await fetch(`/api/sessions/${encodeURIComponent(name)}/send`, { method: 'POST', credentials: 'same-origin', body: formData });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) { window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`; return; }
    if (!res.ok || data.success === false) throw new Error(data.error || 'فشل الإرسال');
    document.getElementById('sendMessage').value = '';
    document.getElementById('sendMedia').value = '';
    await refreshSessionPage(name);
  } catch (error) { showError(error); }
}

function statusBadge(status) { return `<span class="badge ${escapeHtml(status)}"><span class="dot"></span>${escapeHtml(status)}</span>`; }

function actionButtons(session) {
  const startable = ['idle', 'disconnected', 'error'].includes(session.status);
  const stoppable = ['initializing', 'qr', 'authenticated', 'connected'].includes(session.status);
  return `${startable ? `<button class="btn btn-good" onclick="startSession('${escapeHtml(session.name)}')">تشغيل</button>` : ''}${stoppable ? `<button class="btn btn-warn" onclick="stopSession('${escapeHtml(session.name)}')">إيقاف</button>` : ''}<button class="btn btn-bad" onclick="deleteSession('${escapeHtml(session.name)}')">حذف</button>`;
}

function setSidebarSessions(sessions) {
  const sidebar = document.getElementById('sidebarSessions');
  if (!sidebar) return;
  sidebar.innerHTML = (sessions || []).map((s) => `<a href="/${encodeURIComponent(s.name)}" class="sidebar-item ${escapeHtml(s.status)}"><span class="sidebar-dot"></span><span class="sidebar-name">${escapeHtml(s.name)}</span><span class="sidebar-status">${escapeHtml(s.status)}</span></a>`).join('') || '<div class="empty-box">لا توجد جلسات</div>';
}

function setNotifications(list, targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  el.innerHTML = (list || []).map((n) => `<div class="notice ${escapeHtml(n.level || 'info')}"><div class="line1"><strong>${escapeHtml(n.session || '')}</strong><span class="small">${escapeHtml(n.timestamp || '')}</span></div><div class="txt">${escapeHtml(n.text || '')}</div></div>`).join('') || '<div class="empty-box">لا توجد تنبيهات</div>';
}

function renderSessionGrid(sessions) {
  const grid = document.getElementById('sessionGrid');
  if (!grid) return;
  grid.innerHTML = (sessions || []).map((s) => `<article class="session-card"><a href="/${encodeURIComponent(s.name)}" class="session-link"><div class="card-top"><div><div class="session-name">${escapeHtml(s.name)}</div><div class="session-sub">${escapeHtml(s.apiBaseUrl || 'لا يوجد API')}</div></div>${statusBadge(s.status)}</div><div class="card-grid"><div class="mini-stat"><span>وارد</span><strong>${s.stats?.incomingCount ?? 0}</strong></div><div class="mini-stat"><span>صادر</span><strong>${s.stats?.outgoingCount ?? 0}</strong></div><div class="mini-stat"><span>آخر نشاط</span><strong>${escapeHtml(s.stats?.lastMessageAt || '-')}</strong></div></div></a><div class="session-actions">${actionButtons(s)}</div></article>`).join('') || '<div class="empty-box">لا توجد جلسات.</div>';
}

async function refreshDashboard() {
  try {
    const res = await requestJson('/api/sessions');
    const sessions = res.data || [];
    setSidebarSessions(sessions);
    renderSessionGrid(sessions);
    const set = (id, value) => { const e = document.getElementById(id); if (e) e.textContent = value; };
    set('kpiTotal', sessions.length);
    set('kpiConnected', sessions.filter((s) => s.status === 'connected').length);
    set('kpiWaiting', sessions.filter((s) => s.status === 'qr').length);
    set('kpiErrors', sessions.filter((s) => s.status === 'error').length);
    const notes = await requestJson('/api/notifications?limit=8');
    setNotifications(notes.data || [], 'globalNotifications');
  } catch (error) { showError(error); }
}

async function refreshSessionPage(name) {
  const res = await requestJson(`/api/sessions/${encodeURIComponent(name)}/status`);
  const data = res.data || {};
  const badge = document.getElementById('statusBadge'); if (badge) badge.innerHTML = statusBadge(data.status);
  const statusText = document.getElementById('statusText'); if (statusText) statusText.textContent = data.status || '-';
  const incoming = document.getElementById('countIncoming'); if (incoming) incoming.textContent = data.stats?.incomingCount ?? 0;
  const outgoing = document.getElementById('countOutgoing'); if (outgoing) outgoing.textContent = data.stats?.outgoingCount ?? 0;
  const last = document.getElementById('lastActivity'); if (last) last.textContent = data.stats?.lastMessageAt || data.updatedAt || '-';
  const apiText = document.getElementById('apiBaseUrlText'); if (apiText) apiText.textContent = data.apiBaseUrl || '-';
  const apiInput = document.getElementById('apiBaseUrlInput'); if (apiInput) apiInput.value = data.apiBaseUrl || '';
  const qr = document.getElementById('qrBox'); if (qr) qr.innerHTML = data.qrDataUrl ? `<img src="${data.qrDataUrl}" alt="QR Code">` : '<div class="empty-box">لا يوجد QR حاليًا.</div>';
  const fill = (id, rows, empty, cells) => { const el = document.getElementById(id); if (!el) return; el.innerHTML = (rows || []).map(cells).join('') || empty; };
  fill('messagesTable', data.messages, '<tr><td colspan="4" class="empty-cell">لا توجد رسائل بعد</td></tr>', (m) => `<tr><td>${escapeHtml(m.timestamp || '-')}</td><td>${escapeHtml(m.direction || '-')}</td><td>${escapeHtml(m.from || m.to || '-')}</td><td>${escapeHtml((m.body || '').slice(0, 120))}${m.hasMedia ? ' <span class="badge mini">Media</span>' : ''}</td></tr>`);
  fill('notificationsTable', data.notifications, '<tr><td colspan="3" class="empty-cell">لا توجد تنبيهات بعد</td></tr>', (n) => `<tr><td>${escapeHtml(n.timestamp || '-')}</td><td>${escapeHtml(n.level || '-')}</td><td>${escapeHtml(n.text || '-')}</td></tr>`);
  fill('errorsTable', data.errors, '<tr><td colspan="3" class="empty-cell">لا توجد أخطاء</td></tr>', (e) => `<tr><td>${escapeHtml(e.timestamp || '-')}</td><td>${escapeHtml(e.type || '-')}</td><td>${escapeHtml(e.message || '-')}</td></tr>`);
  const sessions = await requestJson('/api/sessions'); setSidebarSessions(sessions.data || []);
  const notes = await requestJson(`/api/sessions/${encodeURIComponent(name)}/notifications?limit=12`); setNotifications(notes.data || [], 'sessionNotifications');
}

async function refreshAll() {
  const shell = document.getElementById('appShell');
  try { if (shell?.dataset?.page === 'dashboard') await refreshDashboard(); else if (shell?.dataset?.page === 'session' && shell.dataset.session) await refreshSessionPage(shell.dataset.session); }
  catch (error) { showError(error); }
}

function bindSocket() {
  if (typeof io !== 'function') return;
  const socket = io({ transports: ['websocket', 'polling'], withCredentials: true });
  socket.on('session:update', () => refreshAll().catch(() => {}));
  socket.on('session:notification', () => refreshAll().catch(() => {}));
  socket.on('session:deleted', (payload) => { if (document.getElementById('appShell')?.dataset?.session === payload?.name) window.location.href = '/'; else refreshAll().catch(() => {}); });
  socket.on('connect_error', (error) => console.warn('Socket unavailable:', error.message));
}

window.openCreateModal = openCreateModal;
window.closeCreateModal = closeCreateModal;
window.createSession = createSession;
window.createSessionFromModal = createSessionFromModal;
window.startSession = startSession;
window.stopSession = stopSession;
window.logoutSession = logoutSession;
window.deleteSession = deleteSession;
window.saveApiUrl = saveApiUrl;
window.sendSessionMessage = sendSessionMessage;
window.refreshDashboard = refreshDashboard;
window.refreshSessionPage = refreshSessionPage;
window.refreshAll = refreshAll;

document.addEventListener('DOMContentLoaded', () => {
  bindSocket();
  const page = document.getElementById('appShell')?.dataset?.page;
  if (page === 'dashboard') refreshDashboard().catch(() => {});
  if (page === 'session') { const name = document.getElementById('appShell')?.dataset?.session; if (name) refreshSessionPage(name).catch(() => {}); }
  document.addEventListener('click', (event) => { const modal = document.getElementById('createModal'); if (modal && event.target === modal) modal.classList.remove('open'); });
});
