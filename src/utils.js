function sanitizeSessionName(input) {
  const name = String(input || '').trim();
  if (!name) throw new Error('اسم الجلسة مطلوب');
  if (!/^[a-zA-Z][a-zA-Z0-9_-]{2,31}$/.test(name)) throw new Error('اسم الجلسة يجب أن يكون بالإنجليزية فقط، من 3 إلى 32 حرفًا، ويبدأ بحرف');
  const reserved = new Set(['api', 'health', 'webhook', 'assets', 'static', 'socket.io', 'login', 'logout']);
  if (reserved.has(name.toLowerCase())) throw new Error('هذا الاسم محجوز للنظام');
  return name.toLowerCase();
}

function normalizePhone(phoneNumber) {
  const cleaned = String(phoneNumber || '').replace(/[^\d]/g, '');
  if (!cleaned) throw new Error('رقم الهاتف مطلوب');
  if (cleaned.length < 8 || cleaned.length > 15) throw new Error('رقم الهاتف غير صالح');
  return cleaned;
}

function normalizePhoneToJid(phoneNumber) { return `${normalizePhone(phoneNumber)}@c.us`; }

function escapeHtml(str = '') {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;').replace(/'/g, '&#39;');
}

function nowIso() { return new Date().toISOString(); }

function statusLabel(status) {
  const map = { idle: 'متوقف', initializing: 'جاري التشغيل', qr: 'بانتظار QR', authenticated: 'تمت المصادقة', connected: 'متصل', disconnected: 'متوقف', error: 'خطأ' };
  return map[status] || status || 'غير معروف';
}

function safeJson(obj) { return JSON.stringify(obj).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026'); }

function publicApiList(name) {
  const base = `/api/sessions/${encodeURIComponent(name)}`;
  return [
    { method: 'GET', path: `${base}/status`, desc: 'حالة الجلسة' },
    { method: 'GET', path: `${base}/qr`, desc: 'QR النصي' },
    { method: 'GET', path: `${base}/qr-image`, desc: 'QR كصورة' },
    { method: 'POST', path: `${base}/connect`, desc: 'تشغيل الجلسة' },
    { method: 'POST', path: `${base}/disconnect`, desc: 'إيقاف الجلسة' },
    { method: 'POST', path: `${base}/logout`, desc: 'تسجيل خروج' },
    { method: 'DELETE', path: `${base}`, desc: 'حذف الجلسة وبياناتها' },
    { method: 'POST', path: `${base}/send`, desc: 'إرسال رسالة' },
    { method: 'POST', path: `${base}/api-url`, desc: 'تحديث رابط API' },
    { method: 'GET', path: `${base}/messages`, desc: 'سجل الرسائل' },
    { method: 'GET', path: `${base}/errors`, desc: 'سجل الأخطاء' },
    { method: 'GET', path: `${base}/notifications`, desc: 'التنبيهات' }
  ];
}

function validateApiBaseUrl(value) {
  if (!value) return null;
  let url;
  try { url = new URL(value); } catch { throw new Error('رابط API غير صالح'); }
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('رابط API يجب أن يكون HTTP أو HTTPS');
  if (url.username || url.password) throw new Error('بيانات الدخول داخل رابط API غير مسموحة');
  if (url.protocol === 'http:' && !['localhost', '127.0.0.1', '::1'].includes(url.hostname.toLowerCase())) throw new Error('استخدم HTTPS للـAPI الخارجي');
  url.hash = '';
  return url.toString().replace(/\/$/, '');
}

module.exports = { sanitizeSessionName, normalizePhone, normalizePhoneToJid, escapeHtml, nowIso, statusLabel, safeJson, publicApiList, validateApiBaseUrl };
