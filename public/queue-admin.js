(() => {
  const $ = (id) => document.getElementById(id);
  async function requestJson(url, options = {}) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      location.href = '/login';
      throw new Error('انتهت جلسة الإدارة');
    }
    if (!response.ok || data.success === false) throw new Error(data.error || `Request failed: ${response.status}`);
    return data;
  }

  function render(data) {
    const panel = $('messageQueuePanel');
    if (!panel) return;
    const queued = Number(data.queued || 0);
    const sessions = Object.keys(data.sessions || {}).length;
    panel.innerHTML = `
      <div class="panel-head">
        <div>
          <span class="eyebrow">OUTBOUND QUEUE</span>
          <h2>طابور الإرسال</h2>
          <p class="hint">طابور مستقل لكل جلسة. عند الإيقاف يعود الإرسال الفوري وكأن الطابور غير موجود.</p>
        </div>
        <span class="status-pill ${data.enabled ? 'status-connected' : 'status-disconnected'}">${data.enabled ? 'مفعّل' : 'متوقف'}</span>
      </div>
      <div class="detail-grid compact">
        <div class="detail-card"><span>حالة الطابور</span><strong>${data.enabled ? 'تأخير عشوائي' : 'إرسال مباشر'}</strong></div>
        <div class="detail-card"><span>الانتظار الحالي</span><strong>${data.enabled ? `${Math.round(data.minDelayMs / 1000)}–${Math.round(data.maxDelayMs / 1000)} ثانية` : '0 ثانية'}</strong></div>
        <div class="detail-card"><span>رسائل معلقة</span><strong>${queued}</strong></div>
        <div class="detail-card"><span>جلسات لها طابور</span><strong>${sessions}</strong></div>
      </div>
      <div class="form-grid four">
        <label>تفعيل الطابور
          <select id="queueEnabled">
            <option value="true" ${data.enabled ? 'selected' : ''}>مفعّل</option>
            <option value="false" ${data.enabled ? '' : 'selected'}>متوقف</option>
          </select>
        </label>
        <label>أقل انتظار (ثانية)
          <input id="queueMin" type="number" min="0" max="600" step="1" value="${Math.round(data.minDelayMs / 1000)}">
        </label>
        <label>أعلى انتظار (ثانية)
          <input id="queueMax" type="number" min="0" max="600" step="1" value="${Math.round(data.maxDelayMs / 1000)}">
        </label>
      </div>
      <div class="row">
        <span class="hint">القيمة الافتراضية: 6 إلى 11 ثوانٍ بين الرسائل لكل جلسة.</span>
        <button class="btn primary" id="saveQueueSettings">حفظ إعدادات الطابور</button>
      </div>`;

    $('saveQueueSettings').onclick = async () => {
      const button = $('saveQueueSettings');
      const min = Math.max(0, Math.min(600, Number($('queueMin').value || 0)));
      const max = Math.max(min, Math.min(600, Number($('queueMax').value || min)));
      button.disabled = true;
      try {
        const result = await requestJson('/api/admin/message-queue', {
          method: 'POST',
          body: JSON.stringify({
            enabled: $('queueEnabled').value === 'true',
            minDelayMs: Math.round(min * 1000),
            maxDelayMs: Math.round(max * 1000)
          })
        });
        render(result.data);
        alert(result.data.enabled ? 'تم تفعيل طابور الإرسال.' : 'تم إيقاف الطابور وعادت الرسائل إلى الإرسال المباشر.');
      } catch (error) {
        alert(error.message);
        button.disabled = false;
      }
    };
  }

  async function load() {
    try {
      const result = await requestJson('/api/admin/message-queue');
      render(result.data);
    } catch (error) {
      console.error(error);
    }
  }

  window.addEventListener('DOMContentLoaded', () => {
    const main = document.querySelector('.main');
    const create = document.getElementById('create');
    if (!main || !create) return;
    const panel = document.createElement('section');
    panel.className = 'panel';
    panel.id = 'messageQueuePanel';
    panel.innerHTML = '<div class="hint">جاري تحميل إعدادات طابور الإرسال…</div>';
    main.insertBefore(panel, create);
    load();
    setInterval(load, 15000);
  });
})();
