const path = require('path');
const fs = require('fs-extra');
const axios = require('axios');
const QRCode = require('qrcode');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const { normalizePhoneToJid, nowIso } = require('./utils');

class WhatsAppSession {
  constructor({ name, rootDir, store, apiBaseUrl = null, backupPhone = null, chromePath, io = null }) {
    this.name = name;
    this.rootDir = rootDir;
    this.store = store;
    this.io = io;
    this.apiBaseUrl = apiBaseUrl || null;
    this.backupPhone = backupPhone || null;
    this.chromePath = chromePath || process.env.CHROME_PATH || '/usr/bin/chromium-browser';
    this.client = null;
    this.status = 'idle';
    this.qr = null;
    this.info = null;
    this.lastError = null;
    this.startedAt = null;
    this.updatedAt = nowIso();
    this.destroying = false;
    this.bootPromise = null;
    this.stopPromise = null;
    this.lastEvent = null;
    this.stats = { incomingCount: 0, outgoingCount: 0, lastMessageAt: null };
  }

  emit(event, payload) { if (this.io) this.io.emit(event, payload); }
  roomEmit(payload) { this.emit('session:update', payload); this.emit(`session:update:${this.name}`, payload); }

  notification(text, level = 'info', extra = {}) {
    const note = { id: `${Date.now()}_${Math.random().toString(16).slice(2, 8)}`, session: this.name, level, text, extra, timestamp: nowIso() };
    this.store.appendNotification(this.name, note).catch(() => {});
    this.emit('session:notification', note);
    this.emit(`session:notification:${this.name}`, note);
    return note;
  }

  async loadMeta() {
    const meta = await this.store.getSessionMeta(this.name);
    if (!meta) return;
    this.apiBaseUrl = meta.apiBaseUrl ?? this.apiBaseUrl;
    this.backupPhone = meta.backupPhone ?? this.backupPhone;
    this.status = meta.status || this.status;
    this.startedAt = meta.startedAt || this.startedAt;
    this.updatedAt = meta.updatedAt || this.updatedAt;
    this.lastError = meta.lastError || this.lastError;
    this.lastEvent = meta.lastEvent || this.lastEvent;
    this.stats = meta.stats || this.stats;
  }

  serialize() {
    return { name: this.name, apiBaseUrl: this.apiBaseUrl, backupPhone: this.backupPhone, status: this.status, qrAvailable: !!this.qr, info: this.info, lastError: this.lastError, startedAt: this.startedAt, updatedAt: this.updatedAt, lastEvent: this.lastEvent, stats: this.stats };
  }

  async persistMeta(extra = {}) {
    this.updatedAt = nowIso();
    const payload = { ...this.serialize(), ...extra, updatedAt: this.updatedAt };
    await this.store.setSessionMeta(this.name, payload);
    this.roomEmit(payload);
  }

  buildClient() {
    return new Client({
      authStrategy: new LocalAuth({ clientId: this.name, dataPath: path.join(this.rootDir, 'sessions') }),
      fetchMessages: false,
      puppeteer: {
        headless: true,
        executablePath: this.chromePath,
        timeout: 600000,
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--disable-extensions', '--disable-background-networking', '--disable-default-apps', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-features=TranslateUI']
      }
    });
  }

  async start() {
    if (this.client && !this.destroying) return this.serialize();
    if (this.bootPromise) return this.bootPromise;
    this.bootPromise = this._startInternal().finally(() => { this.bootPromise = null; });
    return this.bootPromise;
  }

  async _startInternal() {
    this.destroying = false;
    this.status = 'initializing';
    this.qr = null;
    this.info = null;
    this.lastError = null;
    this.lastEvent = { type: 'start', at: nowIso() };
    this.startedAt = this.startedAt || nowIso();
    await this.persistMeta();
    this.notification('تم بدء تشغيل الجلسة', 'info');

    const client = this.buildClient();
    this.client = client;

    client.on('qr', async (qr) => {
      if (this.client !== client || this.destroying) return;
      try {
        this.qr = qr;
        this.status = 'qr';
        this.lastEvent = { type: 'qr', at: nowIso() };
        await this.persistMeta({ lastEvent: this.lastEvent });
        this.notification('تم توليد QR جديد', 'warning');
        await this.sendToExternalApi('/webhook/qr', { session: this.name, qrCode: qr, timestamp: nowIso() });
      } catch (error) { await this.recordError('QR_HANDLER_ERROR', error); }
    });

    client.on('authenticated', async () => {
      if (this.client !== client || this.destroying) return;
      this.status = 'authenticated';
      this.lastEvent = { type: 'authenticated', at: nowIso() };
      await this.persistMeta({ lastEvent: this.lastEvent });
      this.notification('تمت المصادقة بنجاح', 'success');
    });

    client.on('ready', async () => {
      if (this.client !== client || this.destroying) return;
      this.status = 'connected';
      this.qr = null;
      this.info = client.info || null;
      this.lastError = null;
      this.lastEvent = { type: 'ready', at: nowIso() };
      await this.persistMeta({ lastEvent: this.lastEvent });
      this.notification('الجلسة متصلة وجاهزة', 'success', { phone: this.info?.wid?.user || null });
      await this.sendToExternalApi('/webhook/session-status', { session: this.name, status: 'connected', info: this.info, timestamp: nowIso() });
    });

    client.on('message', async (message) => {
      if (this.client !== client || this.destroying) return;
      try { await this.handleIncomingMessage(message); } catch (error) { await this.recordError('MESSAGE_HANDLER_ERROR', error); }
    });

    client.on('disconnected', async (reason) => {
      if (this.client !== client) return;
      this.client = null;
      this.status = 'disconnected';
      this.info = null;
      this.qr = null;
      this.lastError = reason || 'unknown';
      this.lastEvent = { type: 'disconnected', reason: this.lastError, at: nowIso() };
      await this.persistMeta({ lastEvent: this.lastEvent, qrAvailable: false, disconnectReason: this.lastError });
      this.notification(`تم قطع الاتصال: ${this.lastError}`, 'error');
      await this.sendToExternalApi('/webhook/session-status', { session: this.name, status: 'disconnected', reason: this.lastError, timestamp: nowIso() });
    });

    client.on('auth_failure', async (message) => {
      if (this.client !== client || this.destroying) return;
      this.status = 'error';
      this.lastError = message || 'Authentication failure';
      this.lastEvent = { type: 'auth_failure', at: nowIso() };
      await this.persistMeta({ lastEvent: this.lastEvent });
      await this.recordError('AUTH_FAILURE', new Error(this.lastError));
      this.notification(`فشل المصادقة: ${this.lastError}`, 'error');
    });

    try {
      await client.initialize();
      return this.serialize();
    } catch (error) {
      if (this.client === client) this.client = null;
      this.status = 'error';
      this.lastError = error.message;
      this.lastEvent = { type: 'initialize_error', at: nowIso() };
      await this.persistMeta({ lastEvent: this.lastEvent });
      await this.recordError('INITIALIZE_ERROR', error);
      throw error;
    }
  }

  async stop() {
    if (this.stopPromise) return this.stopPromise;
    this.stopPromise = this._stopInternal().finally(() => { this.stopPromise = null; });
    return this.stopPromise;
  }

  async _stopInternal() {
    this.destroying = true;
    const client = this.client;
    this.client = null;
    if (client) {
      try { client.removeAllListeners(); await client.destroy(); }
      catch (error) { await this.recordError('STOP_ERROR', error); }
    }
    this.status = 'disconnected';
    this.qr = null;
    this.info = null;
    this.lastEvent = { type: 'stop', at: nowIso() };
    await this.persistMeta({ stopped: true, lastEvent: this.lastEvent, qrAvailable: false });
    this.notification('تم إيقاف الجلسة', 'warning');
    return this.serialize();
  }

  async logout() {
    if (!this.client) throw new Error('لا توجد جلسة تعمل');
    const client = this.client;
    await client.logout();
    if (this.client === client) this.client = null;
    this.status = 'disconnected';
    this.qr = null;
    this.info = null;
    this.lastEvent = { type: 'logout', at: nowIso() };
    await this.persistMeta({ loggedOut: true, lastEvent: this.lastEvent, qrAvailable: false });
    this.notification('تم تسجيل الخروج من واتساب', 'warning');
    return this.serialize();
  }

  async sendMessage(phoneNumber, message, mediaPath = null) {
    if (!this.client || this.status !== 'connected') throw new Error('الجلسة غير جاهزة للإرسال');
    const jid = normalizePhoneToJid(phoneNumber);
    const sent = mediaPath ? await this.client.sendMessage(jid, MessageMedia.fromFilePath(mediaPath), { caption: message || '', sendSeen: false }) : await this.client.sendMessage(jid, message || '', { sendSeen: false });
    this.stats.outgoingCount += 1;
    this.stats.lastMessageAt = nowIso();
    this.lastEvent = { type: 'outgoing_message', at: nowIso() };
    await this.store.appendMessage(this.name, { session: this.name, direction: 'out', messageId: sent?.id?._serialized || null, to: phoneNumber, body: message || '', type: mediaPath ? 'media' : 'text', timestamp: nowIso() });
    await this.persistMeta({ stats: this.stats, lastEvent: this.lastEvent });
    await this.sendToExternalApi('/webhook/whatsapp', { session: this.name, direction: 'out', messageId: sent?.id?._serialized || null, to: phoneNumber, body: message || '', type: mediaPath ? 'media' : 'text', timestamp: nowIso() });
    this.notification(`تم إرسال رسالة إلى ${phoneNumber}`, 'info');
    return { success: true, messageId: sent?.id?._serialized || null };
  }

  async handleIncomingMessage(message) {
    const data = { session: this.name, direction: 'in', messageId: message.id?._serialized || null, from: message.from || null, to: message.to || null, body: message.body || '', type: message.type || 'unknown', hasMedia: !!message.hasMedia, mediaSkipped: !!message.hasMedia, timestamp: nowIso() };
    this.stats.incomingCount += 1;
    this.stats.lastMessageAt = nowIso();
    this.lastEvent = { type: 'incoming_message', at: nowIso() };
    await this.store.appendMessage(this.name, data);
    await this.persistMeta({ stats: this.stats, lastEvent: this.lastEvent });
    await this.sendToExternalApi('/webhook/whatsapp', data);
    const preview = (data.body || '').slice(0, 80) || (data.hasMedia ? 'رسالة تحتوي على ملف' : 'رسالة واردة');
    this.notification(`رسالة واردة: ${preview}`, 'info', { from: data.from, hasMedia: data.hasMedia });
  }

  async sendToExternalApi(endpoint, payload) {
    if (!this.apiBaseUrl) return;
    try {
      const url = `${this.apiBaseUrl.replace(/\/$/, '')}${endpoint}`;
      await axios.post(url, { ...payload, botId: this.name }, { timeout: 15000, maxContentLength: 1024 * 1024, maxBodyLength: 1024 * 1024 });
    } catch (error) {
      await this.recordError('EXTERNAL_API_ERROR', error, { endpoint });
    }
  }

  async recordError(type, error, extra = {}) {
    await this.store.appendError(this.name, { type, message: error?.message || String(error), timestamp: nowIso(), ...extra });
  }

  async getQrImageDataUrl() { return this.qr ? QRCode.toDataURL(this.qr, { errorCorrectionLevel: 'M', margin: 2, scale: 8 }) : null; }

  async getPublicStatus() {
    const [messages, errors, notifications] = await Promise.all([this.store.getMessages(this.name, 8, 0), this.store.getErrors(this.name, 8), this.store.getNotifications(this.name, 12)]);
    return { ...this.serialize(), messages, errors, notifications, qrTextAvailable: !!this.qr, qrDataUrl: this.qr ? await this.getQrImageDataUrl() : null, endpoints: this.getApiEndpoints() };
  }

  getApiEndpoints() {
    const base = `/api/sessions/${encodeURIComponent(this.name)}`;
    return { status: `${base}/status`, qr: `${base}/qr`, qrImage: `${base}/qr-image`, connect: `${base}/connect`, disconnect: `${base}/disconnect`, logout: `${base}/logout`, delete: base, send: `${base}/send`, apiUrl: `${base}/api-url`, messages: `${base}/messages`, errors: `${base}/errors`, notifications: `${base}/notifications` };
  }

  async destroyCompletely() {
    await this.stop();
    await fs.remove(path.join(this.rootDir, 'sessions', this.name)).catch(() => {});
    await Promise.all([
      fs.remove(this.store.sessionFile(this.name)).catch(() => {}),
      fs.remove(this.store.messageFile(this.name)).catch(() => {}),
      fs.remove(this.store.errorFile(this.name)).catch(() => {}),
      fs.remove(this.store.notificationFile(this.name)).catch(() => {})
    ]);
  }
}

class SessionManager {
  constructor({ rootDir, store, chromePath, io = null }) { this.rootDir = rootDir; this.store = store; this.chromePath = chromePath; this.io = io; this.sessions = new Map(); }

  async ensureSession(name, apiBaseUrl = null, backupPhone = null) {
    let session = this.sessions.get(name);
    if (!session) {
      session = new WhatsAppSession({ name, rootDir: this.rootDir, store: this.store, apiBaseUrl, backupPhone, chromePath: this.chromePath, io: this.io });
      await session.loadMeta();
      this.sessions.set(name, session);
    }
    if (apiBaseUrl) { session.apiBaseUrl = apiBaseUrl; await session.persistMeta({ apiBaseUrl }); }
    if (backupPhone) { session.backupPhone = backupPhone; await session.persistMeta({ backupPhone }); }
    return session;
  }

  async createSession(name, options = {}) {
    if (await this.store.getSessionMeta(name) || this.sessions.has(name)) throw new Error('هذه الجلسة موجودة بالفعل');
    const session = new WhatsAppSession({ name, rootDir: this.rootDir, store: this.store, apiBaseUrl: options.apiBaseUrl || null, backupPhone: options.backupPhone || null, chromePath: this.chromePath, io: this.io });
    await session.persistMeta({ createdAt: nowIso(), status: 'idle', stats: session.stats });
    this.sessions.set(name, session);
    return session;
  }

  async removeSession(name) {
    const session = await this.ensureSession(name);
    await session.destroyCompletely();
    this.sessions.delete(name);
  }

  async listStatuses() {
    const names = await this.store.listSessionNames();
    const states = [];
    for (const name of names) {
      const session = await this.ensureSession(name);
      states.push(await session.getPublicStatus());
    }
    return states;
  }
}

module.exports = { SessionManager, WhatsAppSession };
