function escapeHtml(str = '') {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

async function requestJson(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.success === false) {
    throw new Error(data.error || `Request failed: ${res.status}`);
  }
  return data;
}

function openCreateModal() {
  const modal = document.getElementById('createModal');
  if (!modal) return;
  modal.classList.add('open');
}

function closeCreateModal() {
  const modal = document.getElementById('createModal');
  if (!modal) return;
  modal.classList.remove('open');
}

async function createSession() {
  const name = document.getElementById('createName')?.value?.trim() || document.getElementById('modalName')?.value?.trim();
  const backupPhone = document.getElementById('createBackupPhone')?.value?.trim() || document.getElementById('modalBackupPhone')?.value?.trim();
  const apiBaseUrl = document.getElementById('createApiUrl')?.value?.trim() || document.getElementById('modalApiUrl')?.value?.trim();
  const autoStart = (document.getElementById('createAutoStart')?.value || document.getElementById('modalAutoStart')?.value || 'true') === 'true';

  const result = await requestJson('/api/sessions', {
    method: 'POST',
    body: JSON.stringify({ name, backupPhone, apiBaseUrl, autoStart })
  });

  window.location.href = result.data.url;
}

async function createSessionFromModal() {
  await createSession();
}

async function startSession(name) {
  await requestJson(`/api/sessions/${encodeURIComponent(name)}/connect`, {
    method: 'POST',
    body: JSON.stringify({})
  });
  await refreshSessionPage(name);
}

async function stopSession(name) {
  await requestJson(`/api/sessions/${encodeURIComponent(name)}/disconnect`, {
    method: 'POST',
    body: JSON.stringify({})
  });
  await refreshSessionPage(name);
}

async function logoutSession(name) {
  await requestJson(`/api/sessions/${encodeURIComponent(name)}/logout`, {
    method: 'POST',
    body: JSON.stringify({})
  });
  await refreshSessionPage(name);
}

async function saveApiUrl(name) {
  const input = document.getElementById('apiBaseUrlInput');
  await requestJson(`/api/sessions/${encodeURIComponent(name)}/api-url`, {
    method: 'POST',
    body: JSON.stringify({ apiBaseUrl: input.value.trim() })
  });
  await refreshSessionPage(name);
}

async function sendSessionMessage(name) {
  const phone = document.getElementById('sendPhone')?.value?.trim();
  const message = document.getElementById('sendMessage')?.value?.trim() || '';
  const mediaInput = document.getElementById('sendMedia');
  const formData = new FormData();
  formData.append('phoneNumber', phone);
  formData.append('message', message);
  if (mediaInput?.files?.[0]) {
    formData.append('media', mediaInput.files[0]);
  }

  const res = await fetch(`/api/sessions/${encodeURIComponent(name)}/send`, {
    method: 'POST',
    body: formData
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.success === false) {
    throw new Error(data.error || 'Send failed');
  }
  document.getElementById('sendMessage').value = '';
  document.getElementById('sendMedia').value = '';
  await refreshSessionPage(name);
}

function statusBadge(status) {
  return `<span class="badge ${escapeHtml(status)}"><span class="dot"></span>${escapeHtml(status)}</span>`;
}

function setSidebarSessions(sessions) {
  const sidebar = document.getElementById('sidebarSessions');
  if (!sidebar) return;
  sidebar.innerHTML = (sessions || []).map((s) => `
    <a href="/${encodeURIComponent(s.name)}" class="sidebar-item ${escapeHtml(s.status)}">
      <span class="sidebar-dot"></span>
      <span class="sidebar-name">${escapeHtml(s.name)}</span>
      <span class="sidebar-status">${escapeHtml(s.status)}</span>
    </a>
  `).join('') || '<div class="empty-box">لا توجد جلسات</div>';
}

function setNotifications(list, targetId = 'globalNotifications') {
  const el = document.getElementById(targetId);
  if (!el) return;
  el.innerHTML = (list || []).map((n) => `
    <div class="notice ${escapeHtml(n.level || 'info')}">
      <div class="line1"><strong>${escapeHtml(n.session || '')}</strong><span class="small">${escapeHtml(n.timestamp || '')}</span></div>
      <div class="txt">${escapeHtml(n.text || '')}</div>
    </div>
  `).join('') || '<div class="empty-box">لا توجد تنبيهات</div>';
}

async function refreshDashboard() {
  const res = await requestJson('/api/sessions');
  const sessions = res.data || [];
  setSidebarSessions(sessions);

  const total = document.getElementById('kpiTotal');
  const connected = document.getElementById('kpiConnected');
  const waiting = document.getElementById('kpiWaiting');
  const errors = document.getElementById('kpiErrors');
  if (total) total.textContent = sessions.length;
  if (connected) connected.textContent = sessions.filter(s => s.status === 'connected').length;
  if (waiting) waiting.textContent = sessions.filter(s => s.status === 'qr').length;
  if (errors) errors.textContent = sessions.filter(s => s.status === 'error').length;

  const grid = document.getElementById('sessionGrid');
  if (grid) {
    grid.innerHTML = sessions.map((session) => `
      <a href="/${encodeURIComponent(session.name)}" class="session-card">
        <div class="card-top">
          <div>
            <div class="session-name">${escapeHtml(session.name)}</div>
            <div class="session-sub">${escapeHtml(session.apiBaseUrl || 'API غير محدد')}</div>
          </div>
          <span class="badge ${escapeHtml(session.status)}"><span class="dot"></span>${escapeHtml(session.status)}</span>
        </div>
        <div class="card-grid">
          <div class="mini-stat"><span>وارد</span><strong>${session.stats?.incomingCount ?? 0}</strong></div>
          <div class="mini-stat"><span>صادر</span><strong>${session.stats?.outgoingCount ?? 0}</strong></div>
          <div class="mini-stat"><span>آخر نشاط</span><strong>${escapeHtml(session.stats?.lastMessageAt || session.updatedAt || '-')}</strong></div>
        </div>
        <div class="session-footer">
          <span class="pill">QR: ${session.qrAvailable ? 'متاح' : 'لا'}</span>
          <span class="pill">${escapeHtml(session.backupPhone || 'بدون رقم احتياطي')}</span>
        </div>
      </a>
    `).join('');
  }

  const globalNotes = document.getElementById('globalNotifications');
  if (globalNotes) {
    const notesRes = await requestJson('/api/notifications?limit=8');
    setNotifications(notesRes.data || [], 'globalNotifications');
  }
}

async function refreshSessionPage(name) {
  const res = await requestJson(`/api/sessions/${encodeURIComponent(name)}/status`);
  const data = res.data || {};

  const statusBadgeEl = document.getElementById('statusBadge');
  if (statusBadgeEl) statusBadgeEl.innerHTML = statusBadge(data.status);

  const statusText = document.getElementById('statusText');
  if (statusText) statusText.textContent = data.status || '-';

  const incoming = document.getElementById('countIncoming');
  const outgoing = document.getElementById('countOutgoing');
  const lastActivity = document.getElementById('lastActivity');
  if (incoming) incoming.textContent = data.stats?.incomingCount ?? 0;
  if (outgoing) outgoing.textContent = data.stats?.outgoingCount ?? 0;
  if (lastActivity) lastActivity.textContent = data.stats?.lastMessageAt || data.updatedAt || '-';

  const apiText = document.getElementById('apiBaseUrlText');
  const apiInput = document.getElementById('apiBaseUrlInput');
  if (apiText) apiText.textContent = data.apiBaseUrl || '-';
  if (apiInput && typeof data.apiBaseUrl === 'string') apiInput.value = data.apiBaseUrl;

  const qrBox = document.getElementById('qrBox');
  if (qrBox) {
    if (data.qrDataUrl) {
      qrBox.innerHTML = `<img src="${data.qrDataUrl}" alt="QR Code" />`;
    } else if (data.status === 'qr') {
      qrBox.innerHTML = '<div class="empty-box">QR موجود لكن لم يُحوّل لصورة بعد</div>';
    } else {
      qrBox.innerHTML = '<div class="empty-box">لا يوجد QR حاليًا</div>';
    }
  }

  const messagesTable = document.getElementById('messagesTable');
  if (messagesTable) {
    messagesTable.innerHTML = (data.messages || []).map((m) => `
      <tr>
        <td>${escapeHtml(m.timestamp || '-')}</td>
        <td>${escapeHtml(m.direction || '-')}</td>
        <td>${escapeHtml(m.from || m.to || '-')}</td>
        <td>${escapeHtml((m.body || '').slice(0, 120))}${m.hasMedia ? ' <span class="badge mini">Media skipped</span>' : ''}</td>
      </tr>
    `).join('') || '<tr><td colspan="4" class="empty-cell">لا توجد رسائل بعد</td></tr>';
  }

  const notificationsTable = document.getElementById('notificationsTable');
  if (notificationsTable) {
    notificationsTable.innerHTML = (data.notifications || []).map((n) => `
      <tr>
        <td>${escapeHtml(n.timestamp || '-')}</td>
        <td>${escapeHtml(n.level || '-')}</td>
        <td>${escapeHtml(n.text || '-')}</td>
      </tr>
    `).join('') || '<tr><td colspan="3" class="empty-cell">لا توجد تنبيهات بعد</td></tr>';
  }

  const errorsTable = document.getElementById('errorsTable');
  if (errorsTable) {
    errorsTable.innerHTML = (data.errors || []).map((e) => `
      <tr>
        <td>${escapeHtml(e.timestamp || '-')}</td>
        <td>${escapeHtml(e.type || '-')}</td>
        <td>${escapeHtml(e.message || '-')}</td>
      </tr>
    `).join('') || '<tr><td colspan="3" class="empty-cell">لا توجد أخطاء</td></tr>';
  }

  const resSessions = await requestJson('/api/sessions');
  setSidebarSessions(resSessions.data || []);

  const notesRes = await requestJson(`/api/sessions/${encodeURIComponent(name)}/notifications`);
  setNotifications(notesRes.data || [], 'sessionNotifications');
}

async function refreshAll() {
  const page = document.getElementById('appShell')?.dataset?.page;
  if (page === 'dashboard') {
    await refreshDashboard();
  } else {
    const name = document.getElementById('appShell')?.dataset?.session;
    if (name) await refreshSessionPage(name);
  }
}

function bindSocket() {
  if (typeof io !== 'function') return;
  const socket = io();
  socket.on('session:update', async () => {
    await refreshAll().catch(() => {});
  });
  socket.on('session:notification', async () => {
    await refreshAll().catch(() => {});
  });
}

window.openCreateModal = openCreateModal;
window.closeCreateModal = closeCreateModal;
window.createSession = createSession;
window.createSessionFromModal = createSessionFromModal;
window.startSession = startSession;
window.stopSession = stopSession;
window.logoutSession = logoutSession;
window.saveApiUrl = saveApiUrl;
window.sendSessionMessage = sendSessionMessage;
window.refreshDashboard = refreshDashboard;
window.refreshSessionPage = refreshSessionPage;
window.refreshAll = refreshAll;

document.addEventListener('DOMContentLoaded', () => {
  bindSocket();

  const page = document.getElementById('appShell')?.dataset?.page;
  if (page === 'dashboard') {
    refreshDashboard().catch(() => {});
    setInterval(() => refreshDashboard().catch(() => {}), 4000);
  } else if (page === 'session') {
    const name = document.getElementById('appShell')?.dataset?.session;
    if (name) {
      refreshSessionPage(name).catch(() => {});
      setInterval(() => refreshSessionPage(name).catch(() => {}), 3500);
    }
  }

  document.addEventListener('click', (e) => {
    const modal = document.getElementById('createModal');
    if (!modal) return;
    if (e.target === modal) modal.classList.remove('open');
  });
});
