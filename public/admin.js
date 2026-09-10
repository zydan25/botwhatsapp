const $ = (id) => document.getElementById(id);

async function requestJson(url, options = {}) {
  const response = await fetch(url, { credentials: 'same-origin', ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 || response.status === 403) { window.location.href = '/login'; throw new Error('Authentication required'); }
  if (!response.ok || data.success === false) throw new Error(data.error || `Request failed: ${response.status}`);
  return data;
}

function escape(value) { const d = document.createElement('div'); d.textContent = String(value ?? ''); return d.innerHTML; }
function statusClass(status) { return `status-${String(status || 'unknown').replace(/[^a-z0-9_-]/gi, '')}`; }

async function loadSessions() {
  const response = await requestJson('/api/admin/sessions');
  const sessions = response.data || [];
  $('kpiTotal').textContent = sessions.length;
  $('kpiConnected').textContent = sessions.filter((s) => s.status === 'connected').length;
  $('kpiQr').textContent = sessions.filter((s) => s.status === 'qr').length;
  $('kpiErrors').textContent = sessions.filter((s) => s.status === 'error').length;

  $('sidebarSessions').innerHTML = sessions.map((s) => `<a href="#session-${encodeURIComponent(s.name)}" class="sidebar-item"><span class="sidebar-dot ${statusClass(s.status)}"></span><span>${escape(s.name)}</span><small>${escape(s.status)}</small></a>`).join('') || '<div class="empty-box">لا توجد جلسات</div>';
  $('sessionGrid').innerHTML = sessions.map(renderSession).join('') || '<div class="empty-box">أنشئ أول جلسة من النموذج أعلاه.</div>';
}

function renderSession(s) {
  const client = s.client;
  return `<article class="session-card" id="session-${escape(s.name)}">
    <div class="session-card-head"><div><span class="eyebrow">SESSION</span><h3>${escape(s.name)}</h3></div><span class="status-pill ${statusClass(s.status)}">${escape(s.status)}</span></div>
    <p class="session-description">${escape(s.description || 'بدون وصف')}</p>
    <div class="detail-grid compact"><div><span>العميل</span><strong>${escape(client?.displayName || '—')}</strong></div><div><span>Username</span><strong>${escape(client?.username || '—')}</strong></div><div><span>الوارد</span><strong>${s.stats?.incomingCount ?? 0}</strong></div><div><span>الصادر</span><strong>${s.stats?.outgoingCount ?? 0}</strong></div><div><span>الرقم</span><strong>${escape(s.info?.wid?.user || s.backupPhone || '—')}</strong></div><div><span>آخر نشاط</span><strong>${escape(s.stats?.lastMessageAt || '—')}</strong></div></div>
    <div class="api-row-box"><label>API</label><div class="copy-row"><code>${escape(s.apiBaseUrl || '—')}</code><button class="btn small ghost" data-copy="${escape(s.apiBaseUrl || '')}">نسخ</button></div></div>
    <div class="api-row-box"><label>Webhook Secret</label><div class="copy-row"><code>${escape(s.webhookSecret || '—')}</code><button class="btn small ghost" data-copy="${escape(s.webhookSecret || '')}">نسخ</button></div></div>
    <div class="session-actions"><button class="btn primary" data-session-action="start" data-name="${escape(s.name)}">تشغيل</button><button class="btn warning" data-session-action="stop" data-name="${escape(s.name)}">إيقاف</button><button class="btn warning" data-session-action="restart" data-name="${escape(s.name)}">إعادة تشغيل</button><button class="btn danger" data-session-action="reauth" data-name="${escape(s.name)}">إعادة المصادقة</button><button class="btn danger" data-session-action="delete" data-name="${escape(s.name)}">حذف نهائي</button></div>
    <details class="admin-edit"><summary>تعديل الوصف وAPI</summary><label>الوصف<textarea data-description-for="${escape(s.name)}" maxlength="1000">${escape(s.description || '')}</textarea></label><label>API<input data-api-for="${escape(s.name)}" value="${escape(s.apiBaseUrl || '')}"></label><div class="row"><button class="btn primary" data-session-action="save" data-name="${escape(s.name)}">حفظ التغييرات</button></div></details>
  </article>`;
}

async function createSession() {
  const payload = {
    name: $('createName').value.trim(),
    displayName: $('createDisplayName').value.trim(),
    username: $('createUsername').value.trim(),
    password: $('createPassword').value,
    description: $('createDescription').value.trim(),
    apiBaseUrl: $('createApiUrl').value.trim(),
    backupPhone: $('createBackupPhone').value.trim(),
    autoStart: $('createAutoStart').value === 'true'
  };
  const data = await requestJson('/api/admin/sessions', { method: 'POST', body: JSON.stringify(payload) });
  alert(`تم إنشاء الجلسة ${data.data.session.name}\nحساب العميل: ${data.data.client.username}`);
  ['createName','createDisplayName','createUsername','createPassword','createDescription','createApiUrl','createBackupPhone'].forEach((id) => { $(id).value = ''; });
  await loadSessions();
}

async function sessionAction(action, name) {
  if (action === 'delete') {
    const typed = window.prompt(`لحذف ${name} نهائيًا، اكتب اسم الجلسة مرة أخرى:`);
    if (typed !== name) return;
    await requestJson(`/api/admin/sessions/${encodeURIComponent(name)}`, { method: 'DELETE' });
    await loadSessions();
    return;
  }
  if (action === 'reauth' && !window.confirm(`إعادة المصادقة ستحذف جلسة WhatsApp السابقة لـ ${name}. هل تريد المتابعة؟`)) return;
  if (action === 'save') {
    const description = document.querySelector(`[data-description-for="${CSS.escape(name)}"]`)?.value || '';
    const api = document.querySelector(`[data-api-for="${CSS.escape(name)}"]`)?.value || '';
    await requestJson(`/api/admin/sessions/${encodeURIComponent(name)}/description`, { method: 'POST', body: JSON.stringify({ description }) });
    await requestJson(`/api/admin/sessions/${encodeURIComponent(name)}/api-url`, { method: 'POST', body: JSON.stringify({ apiBaseUrl: api }) });
    await loadSessions();
    return;
  }
  await requestJson(`/api/admin/sessions/${encodeURIComponent(name)}/${action === 'start' ? 'start' : action === 'stop' ? 'stop' : action === 'restart' ? 'restart' : 'reauthenticate'}`, { method: 'POST', body: '{}' });
  await loadSessions();
}

$('adminApp').addEventListener('click', async (event) => {
  const copy = event.target.closest('[data-copy]');
  if (copy) { await navigator.clipboard?.writeText(copy.dataset.copy || ''); return; }
  const button = event.target.closest('[data-session-action]');
  if (!button) return;
  button.disabled = true;
  try { await sessionAction(button.dataset.sessionAction, button.dataset.name); } catch (e) { alert(e.message); } finally { button.disabled = false; }
});

$('adminApp').addEventListener('click', async (event) => {
  if (event.target.closest('[data-action="refresh"]')) loadSessions().catch((e) => alert(e.message));
  if (event.target.closest('[data-action="submit-create"]')) { const b = event.target.closest('button'); b.disabled = true; try { await createSession(); } catch (e) { alert(e.message); } finally { b.disabled = false; } }
});

window.addEventListener('DOMContentLoaded', () => { loadSessions().catch((e) => alert(e.message)); });
