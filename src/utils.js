function sanitizeSessionName(input) {
  const name = String(input || '').trim();
  if (!name) throw new Error('اسم الجلسة مطلوب');
  if (!/^[a-zA-Z][a-zA-Z0-9_-]{2,31}$/.test(name)) throw new Error('اسم الجلسة يجب أن يكون بالإنجليزية فقط، من 3 إلى 32 حرفًا، ويبدأ بحرف');
  const reserved = new Set(['api', 'health', 'webhook', 'assets', 'static', 'socket.io', 'login', 'logout', 'admin', 'app']);
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

function escapeHtml(str = '') { return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;').replace(/'/g, '&#39;'); }
function nowIso() { return new Date().toISOString(); }
function safeJson(obj) { return JSON.stringify(obj).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026'); }
function statusLabel(status) { const map = { idle: 'متوقف', initializing: 'جاري التشغيل', qr: 'بانتظار QR', authenticated: 'تمت المصادقة', connected: 'متصل', disconnected: 'متوقف', error: 'خطأ' }; return map[status] || status || 'غير معروف'; }

function validateApiBaseUrl(value) {
  if (!value) return null;
  let url;
  try { url = new URL(String(value).trim()); } catch { throw new Error('رابط API غير صالح'); }
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('رابط API يجب أن يكون HTTP أو HTTPS');
  if (url.username || url.password) throw new Error('بيانات الدخول داخل رابط API غير مسموحة');
  if (url.pathname === '/' || url.pathname === '') url.pathname = '';
  url.hash = '';
  return url.toString().replace(/\/$/, '');
}

module.exports = { sanitizeSessionName, normalizePhone, normalizePhoneToJid, escapeHtml, nowIso, statusLabel, safeJson, validateApiBaseUrl };
