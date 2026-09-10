(() => {
  const qState = { data: null };
  const $ = (id) => document.getElementById(id);

  function escapeHtml(value) {
    const d = document.createElement('div');
    d.textContent = String(value ?? '');
    return d.innerHTML;
  }

  async function queueApi(url, options = {}) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      location.href = '/login';
      throw new Error('انتهت جلسة الدخول');
    }
    if (!response.ok || data.success === false) throw new Error(data.error || `HTTP ${response.status}`);
    return data.data;
  }

  function ensureStyles() {
    if ($('clientQueueStyles')) return;
    const style = document.createElement('style');
    style.id = 'clientQueueStyles';
    style.textContent = `
      .queue-card{margin-top:14px}
      .queue-status-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-bottom:1px solid rgba(20,40,30,.08)}
      .queue-status-row:last-child{border-bottom:0}
      .queue-switch{position:relative;width:54px;height:30px;flex:0 0 auto}
      .queue-switch input{opacity:0;width:0;height:0}
      .queue-slider{position:absolute;inset:0;border-radius:30px;background:#cfd7d1;cursor:pointer;transition:.2s}
      .queue-slider:before{content:'';position:absolute;width:22px;height:22px;right:4px;top:4px;background:#fff;border-radius:50%;transition:.2s;box-shadow:0 2px 5px rgba(0,0,0,.16)}
      .queue-switch input:checked + .queue-slider{background:#16a36a}
      .queue-switch input:checked + .queue-slider:before{transform:translateX(-24px)}
      .queue-controls{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}
      .queue-stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}
      .queue-stat{padding:10px;border-radius:14px;background:#f6f8f7}
      .queue-stat span{display:block;font-size:12px;opacity:.62;margin-bottom:4px}
      .queue-stat strong{font-size:18px}
      .queue-note{font-size:12px;line-height:1.7;opacity:.72;margin:10px 0 0}
      .queue-home-line{display:flex;align-items:center;justify-content:space-between;gap:12px}
      .queue-badge{display:inline-flex;align-items:center;gap:6px;padding:7px 10px;border-radius:999px;font-size:12px;font-weight:700}
      .queue-badge.on{background:#e7f8f0;color:#087a4c}
      .queue-badge.off{background:#f1f3f2;color:#65716b}
      @media (max-width:480px){.queue-controls{grid-template-columns:1fr}.queue-home-line{align-items:flex-start;flex-direction:column}}
    `;
    document.head.appendChild(style);
  }

  function showToast(message) {
    if (typeof window.toast === 'function') return window.toast(message);
    const el = $('toast');
    if (el) { el.textContent = message; el.classList.add('show'); setTimeout(() => el.classList.remove('show'), 2200); }
  }

  function buildHomeCard() {
    const view = document.querySelector('.view[data-view="home"]');
    const anchor = document.querySelector('.view[data-view="home"] .compact-status');
    if (!view || !anchor || $('clientQueueHome')) return;
    const card = document.createElement('div');
    card.id = 'clientQueueHome';
    card.className = 'section-card queue-card';
    card.innerHTML = `
      <div class="section-head"><div><span class="micro-label">طابور الإرسال</span><h2>التأخير بين الرسائل</h2></div><span id="queueHomeBadge" class="queue-badge off">موقوف</span></div>
      <div class="queue-home-line"><p id="queueHomeText" class="queue-note">الإرسال المباشر يعمل بدون انتظار.</p><button class="app-button soft" id="queueHomeSettings">إدارة الطابور</button></div>`;
    anchor.insertAdjacentElement('afterend', card);
    $('queueHomeSettings').onclick = () => {
      document.querySelector('[data-nav="settings"]')?.click();
      setTimeout(() => $('clientQueueSettings')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
    };
  }

  function buildSettingsCard() {
    const settings = document.querySelector('.view[data-view="settings"]');
    const profile = settings?.querySelector('.profile-card');
    if (!settings || !profile || $('clientQueueSettings')) return;
    const card = document.createElement('div');
    card.id = 'clientQueueSettings';
    card.className = 'section-card queue-card';
    card.innerHTML = `
      <div class="section-head"><div><span class="micro-label">التحكم بالإرسال</span><h2>طابور الرسائل</h2></div><span id="queueSettingsBadge" class="queue-badge off">موقوف</span></div>
      <div class="queue-status-row"><div><b>تشغيل التأخير الذكي</b><p id="queueModeText" class="queue-note">عند الإيقاف يتم الإرسال مباشرة وكأن الطابور غير موجود.</p></div><label class="queue-switch" aria-label="تشغيل أو إيقاف طابور الرسائل"><input id="queueEnabled" type="checkbox"><span class="queue-slider"></span></label></div>
      <div class="queue-controls"><label class="field-label">أقل انتظار (ثانية)<input id="queueMin" type="number" min="0" max="600" step="1"></label><label class="field-label">أعلى انتظار (ثانية)<input id="queueMax" type="number" min="0" max="600" step="1"></label></div>
      <div class="queue-stat-grid"><div class="queue-stat"><span>قيد الانتظار</span><strong id="queueQueued">0</strong></div><div class="queue-stat"><span>قيد التنفيذ</span><strong id="queueActive">0</strong></div></div>
      <p class="queue-note">كل عميل له طابوره الخاص. طابور هذا الحساب لا يوقف عملاء آخرين، والرسائل تحافظ على ترتيبها.</p>
      <button class="app-button primary full" id="saveQueueSettings">حفظ إعدادات الطابور</button>`;
    profile.insertAdjacentElement('afterend', card);

    $('queueEnabled').addEventListener('change', () => updateQueueModeText());
    $('saveQueueSettings').onclick = saveQueue;
  }

  function updateQueueModeText() {
    const enabled = !!$('queueEnabled')?.checked;
    if ($('queueModeText')) $('queueModeText').textContent = enabled
      ? 'الرسائل المتتالية تنتظر مدة عشوائية ضمن الحدين المحددين قبل الإرسال.'
      : 'عند الإيقاف يتم الإرسال مباشرة وكأن الطابور غير موجود.';
  }

  function renderQueue(data) {
    qState.data = data;
    const enabled = !!data?.enabled;
    const min = Math.round((data?.minDelayMs || 0) / 1000);
    const max = Math.round((data?.maxDelayMs || 0) / 1000);
    if ($('queueEnabled')) $('queueEnabled').checked = enabled;
    if ($('queueMin')) $('queueMin').value = min;
    if ($('queueMax')) $('queueMax').value = max;
    if ($('queueQueued')) $('queueQueued').textContent = data?.queued || 0;
    if ($('queueActive')) $('queueActive').textContent = data?.active || 0;
    const badgeText = enabled ? 'مفعّل' : 'موقوف';
    ['queueSettingsBadge', 'queueHomeBadge'].forEach((id) => {
      const badge = $(id);
      if (!badge) return;
      badge.textContent = badgeText;
      badge.className = `queue-badge ${enabled ? 'on' : 'off'}`;
    });
    if ($('queueHomeText')) $('queueHomeText').textContent = enabled
      ? `تأخير عشوائي بين ${min} و${max} ثانية بين الرسائل المتتالية.`
      : 'الإرسال المباشر يعمل بدون انتظار.';
    updateQueueModeText();
  }

  async function loadQueue() {
    try {
      renderQueue(await queueApi('/api/client/message-queue'));
    } catch (error) {
      showToast(error.message);
    }
  }

  async function saveQueue() {
    const enabled = !!$('queueEnabled')?.checked;
    const minDelayMs = Math.max(0, Math.min(600000, Math.floor(Number($('queueMin')?.value || 0) * 1000)));
    const maxDelayMs = Math.max(0, Math.min(600000, Math.floor(Number($('queueMax')?.value || 0) * 1000)));
    if (maxDelayMs < minDelayMs) return showToast('الحد الأعلى يجب أن يكون أكبر من أو يساوي الحد الأدنى');
    const button = $('saveQueueSettings');
    if (button) button.disabled = true;
    try {
      const data = await queueApi('/api/client/message-queue', {
        method: 'POST',
        body: JSON.stringify({ enabled, minDelayMs, maxDelayMs })
      });
      renderQueue(data);
      showToast(enabled ? 'تم تشغيل طابور الرسائل' : 'تم إيقاف الطابور والإرسال أصبح مباشرًا');
    } catch (error) {
      showToast(error.message);
    } finally {
      if (button) button.disabled = false;
    }
  }

  function boot() {
    ensureStyles();
    buildHomeCard();
    buildSettingsCard();
    loadQueue();
    setInterval(loadQueue, 5000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
