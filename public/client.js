const state = { deferredInstall: null, data: null };
const $ = (id) => document.getElementById(id);

async function api(url, options = {}) {
  const response = await fetch(url, { credentials: 'same-origin', ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 || response.status === 403) { window.location.href = '/login'; throw new Error('انتهت الجلسة'); }
  if (!response.ok || data.success === false) throw new Error(data.error || 'حدث خطأ');
  return data.data;
}
function esc(value) { const d = document.createElement('div'); d.textContent = String(value ?? ''); return d.innerHTML; }
function statusText(s) { const map = { connected:'متصل', qr:'بانتظار QR', initializing:'جاري التشغيل', authenticated:'تمت المصادقة', disconnected:'متوقف', idle:'متوقف', error:'خطأ' }; return map[s] || s || 'غير معروف'; }
function setStatus(s) { const el = $('clientStatus'); el.textContent = statusText(s.status); el.className = `status-pill status-${esc(s.status)}`; }
function renderDetails(s, client) { $('sessionDetails').innerHTML = [['اسم الجلسة',s.name],['الحالة',statusText(s.status)],['رقم الحساب',s.info?.wid?.user || 'غير متاح'],['إصدار الحساب',s.info?.platform || 'غير متاح'],['تاريخ البدء',s.startedAt || '—'],['آخر تحديث',s.updatedAt || '—'],['الوارد',s.stats?.incomingCount ?? 0],['الصادر',s.stats?.outgoingCount ?? 0],['آخر نشاط',s.stats?.lastMessageAt || '—'],['الـAPI',s.apiBaseUrl || '—']].map(([k,v])=>`<div class="detail-card"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join(''); $('accountDetails').innerHTML = `<div class="detail-card"><span>اسم العميل</span><strong>${esc(client.displayName || '—')}</strong></div><div class="detail-card"><span>اسم المستخدم</span><strong>${esc(client.username)}</strong></div><div class="detail-card"><span>نطاق الحساب</span><strong>جلسة واحدة فقط</strong></div>`; }
function renderApi(data) { const a = data.api; $('apiDetails').innerHTML = [['رابط API',a.baseUrl],['Webhook الرسائل',a.webhookUrl],['Webhook الحالة',a.statusUrl],['Webhook QR',a.qrUrl],['Header التوقيع',a.signatureHeader],['Webhook Secret',data.session.webhookSecret]].map(([k,v])=>`<div class="detail-card"><span>${esc(k)}</span><div class="copy-row"><code>${esc(v)}</code><button class="btn small ghost" data-copy="${esc(v)}">نسخ</button></div></div>`).join(''); $('webhookExample').textContent = data.webhookExample; }
function renderMessages(list) { $('messagesTable').innerHTML = (list || []).map((m)=>`<tr><td>${esc(m.timestamp)}</td><td>${esc(m.direction)}</td><td>${esc(m.from || m.to || '—')}</td><td>${esc((m.body || '').slice(0,160))}${m.hasMedia ? ' • مرفق لم يتم تنزيله' : ''}</td></tr>`).join('') || '<tr><td colspan="4">لا توجد رسائل محفوظة</td></tr>'; }
function renderEvents(s) { const items = [...(s.notifications || []).map((n)=>({t:n.timestamp,x:n.text,l:n.level})),...(s.errors || []).map((e)=>({t:e.timestamp,x:e.message,l:e.type}))].sort((a,b)=>String(b.t).localeCompare(String(a.t))).slice(0,20); $('eventsList').innerHTML = items.map((i)=>`<div class="event"><span>${esc(i.t)}</span><strong>${esc(i.l)}</strong><p>${esc(i.x)}</p></div>`).join('') || '<div class="empty-box">لا توجد أحداث</div>'; }
async function load() { const data = await api('/api/client/me'); state.data = data; $('sessionTitle').textContent = data.session.name; $('sessionDescription').textContent = data.session.description || 'بدون وصف'; setStatus(data.session); renderDetails(data.session, data.client); renderApi(data); renderMessages(data.session.messages); renderEvents(data.session); const qr = $('qrContainer'); qr.innerHTML = data.session.qrDataUrl ? `<img class="qr-image" src="${data.session.qrDataUrl}" alt="WhatsApp QR">` : `<div class="empty-box">${data.session.status === 'connected' ? 'الجلسة متصلة بالفعل.' : 'اضغط تشغيل للحصول على QR.'}</div>`; }
async function doAction(endpoint, message) { if (message && !window.confirm(message)) return; document.body.classList.add('busy'); try { await api(endpoint,{method:'POST',body:'{}'}); await load(); } catch(e){ alert(e.message); } finally { document.body.classList.remove('busy'); } }

$('startBtn').onclick = () => doAction('/api/client/session/start');
$('stopBtn').onclick = () => doAction('/api/client/session/stop');
$('restartBtn').onclick = () => doAction('/api/client/session/restart','سيتم إيقاف الجلسة ثم تشغيلها من جديد مع الاحتفاظ ببيانات المصادقة. متابعة؟');
$('reauthBtn').onclick = () => doAction('/api/client/session/reauthenticate','سيتم حذف بيانات جلسة WhatsApp السابقة فقط وإنشاء اتصال جديد بنفس الـAPI. متابعة؟');
$('regenerateQr').onclick = () => doAction('/api/client/session/qr/regenerate','سيتم إعادة تشغيل الاتصال لتوليد QR جديد. متابعة؟');
$('refresh').onclick = () => load().catch((e)=>alert(e.message));
$('changePassword').onclick = async () => { const currentPassword=$('currentPassword').value; const newPassword=$('newPassword').value; if(newPassword.length<10){alert('كلمة المرور الجديدة يجب ألا تقل عن 10 أحرف');return;} try{await api('/api/client/password',{method:'POST',body:JSON.stringify({currentPassword,newPassword})});alert('تم تغيير كلمة المرور. سيتم تحويلك إلى تسجيل الدخول.');window.location.href='/login';}catch(e){alert(e.message);} };
$('clientApp').addEventListener('click', async (e)=>{const b=e.target.closest('[data-copy]');if(b){try{await navigator.clipboard.writeText(b.dataset.copy);b.textContent='تم النسخ';setTimeout(()=>b.textContent='نسخ',1200);}catch{alert(b.dataset.copy);}}});
window.addEventListener('beforeinstallprompt',(e)=>{e.preventDefault();state.deferredInstall=e;$('installBtn').classList.remove('hidden');});
$('installBtn').onclick = async ()=>{if(!state.deferredInstall)return;state.deferredInstall.prompt();await state.deferredInstall.userChoice;state.deferredInstall=null;$('installBtn').classList.add('hidden');};

window.addEventListener('DOMContentLoaded',()=>{load().catch((e)=>alert(e.message));try{navigator.serviceWorker?.register('/sw.js');}catch{}setInterval(()=>load().catch(()=>{}),5000); if(typeof io==='function'){const socket=io({withCredentials:true});socket.on('session:update',()=>load().catch(()=>{}));}});
