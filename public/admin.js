const $ = (id) => document.getElementById(id);

async function requestJson(url, options = {}) {
  const r = await fetch(url, { credentials: 'same-origin', ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  const d = await r.json().catch(() => ({}));
  if (r.status === 401 || r.status === 403) { location.href = '/login'; throw new Error('انتهت جلسة الإدارة'); }
  if (!r.ok || d.success === false) throw new Error(d.error || `Request failed: ${r.status}`);
  return d;
}

function escape(v) { const d = document.createElement('div'); d.textContent = String(v ?? ''); return d.innerHTML; }
function statusClass(s) { return `status-${String(s || 'unknown').replace(/[^a-z0-9_-]/gi, '')}`; }

async function loadClients() {
  const response = await requestJson('/api/admin/clients');
  const clients = response.data || [];
  $('kpiClients').textContent = clients.length;
  $('clientGrid').innerHTML = clients.map(renderClient).join('') || '<div class="empty-box">لا توجد حسابات عملاء.</div>';
}

function renderClient(c) {
  const ready = !!c.passwordConfigured;
  return `<article class="session-card client-card" id="client-${escape(c.username)}">
    <div class="session-card-head">
      <div><span class="eyebrow">CLIENT ACCOUNT</span><h3>${escape(c.displayName || c.username)}</h3></div>
      <span class="status-pill ${ready ? 'status-connected' : 'status-error'}">${ready ? 'بيانات الدخول جاهزة' : 'يحتاج كلمة مرور'}</span>
    </div>
    <div class="detail-grid compact">
      <div class="detail-card"><span>اسم المستخدم</span><strong>${escape(c.username)}</strong></div>
      <div class="detail-card"><span>الجلسة</span><strong>${escape(c.sessionName || '—')}</strong></div>
      <div class="detail-card"><span>الإصدار</span><strong>${escape(c.tokenVersion || 1)}</strong></div>
      <div class="detail-card"><span>آخر تحديث</span><strong>${escape(c.updatedAt || '—')}</strong></div>
    </div>
    <div class="api-row-box"><label>رابط العميل</label><div class="copy-row"><code>https://whatsapp.alattab.site</code><button class="btn small ghost" data-copy="https://whatsapp.alattab.site">نسخ</button></div></div>
    <details class="admin-edit" open>
      <summary>إدارة بيانات الدخول</summary>
      <label>اسم العرض<input data-client-display="${escape(c.username)}" value="${escape(c.displayName || '')}" maxlength="100"></label>
      <label>كلمة مرور جديدة<input data-client-password="${escape(c.username)}" type="password" minlength="10" placeholder="10 أحرف على الأقل"></label>
      <div class="row"><button class="btn primary" data-client-action="save" data-username="${escape(c.username)}">حفظ البيانات</button><button class="btn warning" data-client-action="reset" data-username="${escape(c.username)}">إعادة تعيين كلمة المرور</button></div>
      <p class="hint">كلمة المرور الحالية لا يمكن عرضها لأنها لا تُخزّن كنص صريح. إعادة التعيين تنشئ كلمة مرور جديدة وتُلغي جلسات الدخول السابقة.</p>
    </details>
  </article>`;
}

async function loadSessions() {
  const response = await requestJson('/api/admin/sessions');
  const sessions = response.data || [];
  $('kpiTotal').textContent = sessions.length;
  $('kpiConnected').textContent = sessions.filter((s) => s.status === 'connected').length;
  $('kpiQr').textContent = sessions.filter((s) => s.status === 'qr').length;
  $('kpiErrors').textContent = sessions.filter((s) => s.status === 'error').length;
  $('sidebarSessions').innerHTML = sessions.map((s) => `<a href="#session-${encodeURIComponent(s.name)}" class="sidebar-item"><span class="sidebar-dot ${statusClass(s.status)}"></span><span>${escape(s.name)}</span><small>${escape(s.status)}</small></a>`).join('') || '<div class="empty-box">لا توجد جلسات</div>';
  $('sessionGrid').innerHTML = sessions.map(renderSession).join('') || '<div class="empty-box">أنشئ أول جلسة.</div>';
}

function renderSession(s) {
  const c = s.client;
  return `<article class="session-card" id="session-${escape(s.name)}">
    <div class="session-card-head"><div><span class="eyebrow">SESSION</span><h3>${escape(s.name)}</h3></div><span class="status-pill ${statusClass(s.status)}">${escape(s.status)}</span></div>
    <p class="session-description">${escape(s.description || 'بدون وصف')}</p>
    <div class="detail-grid compact"><div class="detail-card"><span>العميل</span><strong>${escape(c?.displayName || '—')}</strong></div><div class="detail-card"><span>Username</span><strong>${escape(c?.username || '—')}</strong></div><div class="detail-card"><span>الجلسة</span><strong>${escape(c?.sessionName || s.name)}</strong></div><div class="detail-card"><span>الوارد</span><strong>${s.stats?.incomingCount ?? 0}</strong></div><div class="detail-card"><span>الصادر</span><strong>${s.stats?.outgoingCount ?? 0}</strong></div><div class="detail-card"><span>الرقم</span><strong>${escape(s.info?.wid?.user || s.backupPhone || '—')}</strong></div></div>
    <div class="api-row-box"><label>API</label><div class="copy-row"><code>${escape(s.apiBaseUrl || '—')}</code><button class="btn small ghost" data-copy="${escape(s.apiBaseUrl || '')}">نسخ</button></div></div>
    <div class="api-row-box"><label>Webhook Secret</label><div class="copy-row"><code>${escape(s.webhookSecret || '—')}</code><button class="btn small ghost" data-copy="${escape(s.webhookSecret || '')}">نسخ</button></div></div>
    <div class="session-actions"><button class="btn primary" data-session-action="start" data-name="${escape(s.name)}">تشغيل</button><button class="btn warning" data-session-action="stop" data-name="${escape(s.name)}">إيقاف</button><button class="btn warning" data-session-action="restart" data-name="${escape(s.name)}">إعادة تشغيل</button><button class="btn danger" data-session-action="reauth" data-name="${escape(s.name)}">إعادة المصادقة</button><button class="btn danger" data-session-action="delete" data-name="${escape(s.name)}">حذف نهائي</button></div>
    <details class="admin-edit"><summary>تعديل الوصف وAPI</summary><label>الوصف<textarea data-description-for="${escape(s.name)}" maxlength="1000">${escape(s.description || '')}</textarea></label><label>API<input data-api-for="${escape(s.name)}" value="${escape(s.apiBaseUrl || '')}"></label><div class="row"><button class="btn primary" data-session-action="save" data-name="${escape(s.name)}">حفظ التغييرات</button></div></details>
  </article>`;
}

async function createSession() {
  const p = { name: $('createName').value.trim(), displayName: $('createDisplayName').value.trim(), username: $('createUsername').value.trim(), password: $('createPassword').value, description: $('createDescription').value.trim(), apiBaseUrl: $('createApiUrl').value.trim(), backupPhone: $('createBackupPhone').value.trim(), autoStart: $('createAutoStart').value === 'true' };
  const d = await requestJson('/api/admin/sessions', { method: 'POST', body: JSON.stringify(p) });
  alert(`تم إنشاء الجلسة ${d.data.session.name}\nحساب العميل: ${d.data.client.username}`);
  ['createName', 'createDisplayName', 'createUsername', 'createPassword', 'createDescription', 'createApiUrl', 'createBackupPhone'].forEach((id) => { $(id).value = ''; });
  await Promise.all([loadSessions(), loadClients()]);
}

async function saveClient(username) {
  const displayName = document.querySelector(`[data-client-display="${CSS.escape(username)}"]`)?.value || '';
  const password = document.querySelector(`[data-client-password="${CSS.escape(username)}"]`)?.value || '';
  await requestJson(`/api/admin/clients/${encodeURIComponent(username)}/display-name`, { method: 'POST', body: JSON.stringify({ displayName }) });
  if (password) {
    if (password.length < 10) throw new Error('كلمة المرور الجديدة يجب ألا تقل عن 10 أحرف');
    await requestJson(`/api/admin/clients/${encodeURIComponent(username)}/password`, { method: 'POST', body: JSON.stringify({ newPassword: password }) });
  }
  alert('تم حفظ بيانات العميل.');
  await loadClients();
}

async function resetClientPassword(username) {
  const input = document.querySelector(`[data-client-password="${CSS.escape(username)}"]`);
  const password = input?.value || '';
  if (password.length < 10) throw new Error('اكتب كلمة المرور الجديدة (10 أحرف على الأقل) أولًا.');
  await requestJson(`/api/admin/clients/${encodeURIComponent(username)}/password`, { method: 'POST', body: JSON.stringify({ newPassword: password }) });
  alert('تمت إعادة تعيين كلمة المرور وإلغاء تسجيلات الدخول السابقة.');
  if (input) input.value = '';
  await loadClients();
}

async function sessionAction(action, name) {
  if (action === 'delete') { const typed = prompt(`لحذف ${name} نهائيًا، اكتب اسم الجلسة:`); if (typed !== name) return; await requestJson(`/api/admin/sessions/${encodeURIComponent(name)}`, { method: 'DELETE' }); return Promise.all([loadSessions(), loadClients()]); }
  if (action === 'reauth' && !confirm(`سيتم حذف بيانات WhatsApp المحلية لـ ${name} وإنشاء اتصال جديد. متابعة؟`)) return;
  if (action === 'save') { const description = document.querySelector(`[data-description-for="${CSS.escape(name)}"]`)?.value || ''; const api = document.querySelector(`[data-api-for="${CSS.escape(name)}"]`)?.value || ''; await requestJson(`/api/admin/sessions/${encodeURIComponent(name)}/description`, { method: 'POST', body: JSON.stringify({ description }) }); await requestJson(`/api/admin/sessions/${encodeURIComponent(name)}/api-url`, { method: 'POST', body: JSON.stringify({ apiBaseUrl: api }) }); return loadSessions(); }
  const route = { start: 'start', stop: 'stop', restart: 'restart', reauth: 'reauthenticate' }[action];
  if (!route) return;
  await requestJson(`/api/admin/sessions/${encodeURIComponent(name)}/${route}`, { method: 'POST', body: '{}' });
  await loadSessions();
}

$('adminApp').addEventListener('click', async (event) => {
  const copy = event.target.closest('[data-copy]');
  if (copy) { try { await navigator.clipboard.writeText(copy.dataset.copy || ''); copy.textContent = 'تم النسخ'; setTimeout(() => { copy.textContent = 'نسخ'; }, 1000); } catch {} return; }
  const scroll = event.target.closest('[data-scroll]');
  if (scroll) { document.getElementById(scroll.dataset.scroll)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
  if (event.target.closest('[data-action="refresh"]')) { Promise.all([loadSessions(), loadClients()]).catch((e) => alert(e.message)); return; }
  const clientButton = event.target.closest('[data-client-action]');
  if (clientButton) { clientButton.disabled = true; try { if (clientButton.dataset.clientAction === 'reset') await resetClientPassword(clientButton.dataset.username); else await saveClient(clientButton.dataset.username); } catch (e) { alert(e.message); } finally { clientButton.disabled = false; } return; }
  const actionButton = event.target.closest('[data-session-action]');
  if (!actionButton) return;
  actionButton.disabled = true;
  try { await sessionAction(actionButton.dataset.sessionAction, actionButton.dataset.name); } catch (e) { alert(e.message); } finally { actionButton.disabled = false; }
});

$('adminApp').addEventListener('click', async (event) => { const b = event.target.closest('[data-action="submit-create"]'); if (!b) return; b.disabled = true; try { await createSession(); } catch (e) { alert(e.message); } finally { b.disabled = false; } });

window.addEventListener('DOMContentLoaded', () => {
  Promise.all([loadSessions(), loadClients()]).catch((e) => alert(e.message));
  if (typeof io === 'function') { const socket = io({ withCredentials: true }); socket.on('session:update', () => { loadSessions().catch(() => {}); }); socket.on('session:deleted', () => { Promise.all([loadSessions(), loadClients()]).catch(() => {}); }); }
  setInterval(() => { Promise.all([loadSessions(), loadClients()]).catch(() => {}); }, 15000);
});
