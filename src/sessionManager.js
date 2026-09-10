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
    this.chromePath = chromePath || process.env.CHROME_PATH || '/snap/bin/chromium';

    this.client = null;
    this.status = 'idle';
    this.qr = null;
    this.info = null;
    this.lastError = null;
    this.startedAt = null;
    this.updatedAt = nowIso();
    this.destroying = false;
    this.booting = false;
    this.lastEvent = null;
    this.stats = {
      incomingCount: 0,
      outgoingCount: 0,
      lastMessageAt: null
    };
  }

  emit(event, payload) {
    if (this.io) this.io.emit(event, payload);
  }

  roomEmit(payload) {
    this.emit('session:update', payload);
    this.emit(`session:update:${this.name}`, payload);
  }

  notification(text, level = 'info', extra = {}) {
    const note = {
      id: `${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
      session: this.name,
      level,
      text,
      extra,
      timestamp: nowIso()
    };
    this.store.appendNotification(this.name, note).catch(() => {});
    this.emit('session:notification', note);
    this.emit(`session:notification:${this.name}`, note);
    return note;
  }

  async loadMeta() {
    const meta = await this.store.getSessionMeta(this.name);
    if (!meta) return;
    this.apiBaseUrl = meta.apiBaseUrl || this.apiBaseUrl;
    this.backupPhone = meta.backupPhone || this.backupPhone;
    this.status = meta.status || this.status;
    this.startedAt = meta.startedAt || this.startedAt;
    this.updatedAt = meta.updatedAt || this.updatedAt;
    this.lastError = meta.lastError || this.lastError;
    this.lastEvent = meta.lastEvent || this.lastEvent;
    this.stats = meta.stats || this.stats;
  }

  serialize() {
    return {
      name: this.name,
      apiBaseUrl: this.apiBaseUrl,
      backupPhone: this.backupPhone,
      status: this.status,
      qrAvailable: !!this.qr,
      info: this.info,
      lastError: this.lastError,
      startedAt: this.startedAt,
      updatedAt: this.updatedAt,
      lastEvent: this.lastEvent,
      stats: this.stats
    };
  }

  async persistMeta(extra = {}) {
    this.updatedAt = nowIso();
    const payload = {
      ...this.serialize(),
      ...extra,
      updatedAt: this.updatedAt
    };
    await this.store.setSessionMeta(this.name, payload);
    this.roomEmit(payload);
  }

  buildClient() {
    const sessionsPath = path.join(this.rootDir, 'sessions');
    return new Client({
      authStrategy: new LocalAuth({
        clientId: this.name,
        dataPath: sessionsPath
      }),
      fetchMessages: false,
      puppeteer: {
        headless: true,
        executablePath: this.chromePath,
        timeout: 600000,
        args: [
          '--no-sandbox',
          '--disable-setuid-sandbox',
          '--disable-dev-shm-usage',
          '--disable-gpu',
          '--disable-extensions',
          '--disable-background-networking',
          '--disable-default-apps',
          '--disable-background-timer-throttling',
          '--disable-renderer-backgrounding',
          '--disable-features=TranslateUI'
        ]
      }
    });
  }

  async start() {
    if (this.client && !this.destroying) return this.serialize();

    this.booting = true;
    this.status = 'initializing';
    this.qr = null;
    this.info = null;
    this.lastError = null;
    this.lastEvent = { type: 'start', at: nowIso() };
    this.startedAt = this.startedAt || nowIso();

    await this.persistMeta();
    this.notification('تم بدء تشغيل الجلسة', 'info');

    this.client = this.buildClient();

    this.client.on('qr', async (qr) => {
      this.qr = qr;
      this.status = 'qr';
      this.lastEvent = { type: 'qr', at: nowIso() };
      await this.persistMeta({ qrAvailable: true, lastEvent: this.lastEvent });
      this.notification('تم توليد QR جديد', 'warning');
      await this.sendToExternalApi('/webhook/qr', {
        session: this.name,
        qrCode: qr,
        timestamp: nowIso()
      });
    });

    this.client.on('authenticated', async () => {
      this.status = 'authenticated';
      this.lastEvent = { type: 'authenticated', at: nowIso() };
      await this.persistMeta({ lastEvent: this.lastEvent });
      this.notification('تمت المصادقة بنجاح', 'success');
    });

    this.client.on('ready', async () => {
      this.status = 'connected';
      this.qr = null;
      this.info = this.client.info || null;
      this.lastEvent = { type: 'ready', at: nowIso() };
      await this.persistMeta({ qrAvailable: false, info: this.info, lastEvent: this.lastEvent });
      this.notification('الجلسة متصلة وجاهزة', 'success', {
        phone: this.info?.wid?.user || null
      });
      await this.sendToExternalApi('/webhook/session-status', {
        session: this.name,
        status: 'connected',
        info: this.info,
        timestamp: nowIso()
      });
    });

    this.client.on('message', async (message) => {
      await this.handleIncomingMessage(message);
    });

    this.client.on('disconnected', async (reason) => {
      this.status = 'disconnected';
      this.info = null;
      this.qr = null;
      this.lastError = reason;
      this.lastEvent = { type: 'disconnected', reason, at: nowIso() };
      await this.persistMeta({
        disconnectReason: reason,
        lastEvent: this.lastEvent,
        qrAvailable: false
      });
      this.notification(`تم قطع الاتصال: ${reason}`, 'error');
      await this.sendToExternalApi('/webhook/session-status', {
        session: this.name,
        status: 'disconnected',
        reason,
        timestamp: nowIso()
      });
      this.client = null;
    });

    this.client.on('auth_failure', async (message) => {
      this.status = 'error';
      this.lastError = message;
      this.lastEvent = { type: 'auth_failure', at: nowIso() };
      await this.persistMeta({ authFailure: message, lastEvent: this.lastEvent });
      await this.store.appendError(this.name, {
        type: 'AUTH_FAILURE',
        message,
        timestamp: nowIso()
      });
      this.notification(`فشل المصادقة: ${message}`, 'error');
    });

    try {
      await this.client.initialize();
    } finally {
      this.booting = false;
    }

    return this.serialize();
  }

  async stop() {
    this.destroying = true;
    try {
      if (this.client) {
        try {
          this.client.removeAllListeners();
          await this.client.destroy();
        } catch (error) {
          await this.store.appendError(this.name, {
            type: 'STOP_ERROR',
            message: error.message,
            timestamp: nowIso()
          });
        }
      }
    } finally {
      this.client = null;
      this.destroying = false;
      this.status = 'disconnected';
      this.qr = null;
      this.info = null;
      this.lastEvent = { type: 'stop', at: nowIso() };
      await this.persistMeta({ stopped: true, lastEvent: this.lastEvent, qrAvailable: false });
      this.notification('تم إيقاف الجلسة', 'warning');
      this.roomEmit(await this.getPublicStatus());
    }
    return this.serialize();
  }

  async logout() {
    if (!this.client) throw new Error('لا توجد جلسة تعمل');
    await this.client.logout();
    this.status = 'disconnected';
    this.qr = null;
    this.info = null;
    this.lastEvent = { type: 'logout', at: nowIso() };
    await this.persistMeta({ loggedOut: true, lastEvent: this.lastEvent, qrAvailable: false });
    this.notification('تم تسجيل الخروج من واتساب', 'warning');
    return this.serialize();
  }

  async restart() {
    await this.stop();
    return this.start();
  }

  async sendMessage(phoneNumber, message, mediaPath = null) {
    if (!this.client || this.status !== 'connected') {
      throw new Error('الجلسة غير جاهزة للإرسال');
    }

    const jid = normalizePhoneToJid(phoneNumber);
    let sent = null;

    if (mediaPath) {
      const media = MessageMedia.fromFilePath(mediaPath);
      sent = await this.client.sendMessage(jid, media, { caption: message || '', sendSeen: false });
    } else {
      sent = await this.client.sendMessage(jid, message || '', { sendSeen: false });
    }

    this.stats.outgoingCount += 1;
    this.stats.lastMessageAt = nowIso();
    this.lastEvent = { type: 'outgoing_message', at: nowIso() };
    await this.store.appendMessage(this.name, {
      session: this.name,
      direction: 'out',
      messageId: sent?.id?._serialized || null,
      to: phoneNumber,
      body: message || '',
      type: mediaPath ? 'media' : 'text',
      mediaPath: mediaPath || null,
      timestamp: nowIso()
    });
    await this.persistMeta({ stats: this.stats, lastEvent: this.lastEvent });
    await this.sendToExternalApi('/webhook/whatsapp', {
      session: this.name,
      direction: 'out',
      messageId: sent?.id?._serialized || null,
      to: phoneNumber,
      body: message || '',
      type: mediaPath ? 'media' : 'text',
      timestamp: nowIso()
    });
    this.notification(`تم إرسال رسالة إلى ${phoneNumber}`, 'info');
    return {
      success: true,
      messageId: sent?.id?._serialized || null
    };
  }

  async handleIncomingMessage(message) {
    const data = {
      session: this.name,
      direction: 'in',
      messageId: message.id?._serialized || null,
      from: message.from || null,
      to: message.to || null,
      body: message.body || '',
      type: message.type || 'unknown',
      hasMedia: !!message.hasMedia,
      mediaSkipped: !!message.hasMedia,
      timestamp: nowIso()
    };

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
      await axios.post(url, {
        ...payload,
        botId: this.name
      }, { timeout: 15000 });
    } catch (error) {
      await this.store.appendError(this.name, {
        type: 'EXTERNAL_API_ERROR',
        endpoint,
        message: error.message,
        timestamp: nowIso()
      });
      this.notification(`فشل الإرسال إلى API الخارجي: ${error.message}`, 'error');
    }
  }

  async getQrImageDataUrl() {
    if (!this.qr) return null;
    return QRCode.toDataURL(this.qr, {
      errorCorrectionLevel: 'M',
      margin: 2,
      scale: 8
    });
  }

  async getPublicStatus() {
    const messages = await this.store.getMessages(this.name, 8, 0);
    const errors = await this.store.getErrors(this.name, 8);
    const notifications = await this.store.getNotifications(this.name, 12);
    const qrDataUrl = this.qr ? await this.getQrImageDataUrl() : null;
    return {
      ...this.serialize(),
      messages,
      errors,
      notifications,
      qrTextAvailable: !!this.qr,
      qrDataUrl,
      endpoints: this.getApiEndpoints()
    };
  }

  getApiEndpoints() {
    const base = `/api/sessions/${encodeURIComponent(this.name)}`;
    return {
      status: `${base}/status`,
      qr: `${base}/qr`,
      qrImage: `${base}/qr-image`,
      connect: `${base}/connect`,
      disconnect: `${base}/disconnect`,
      logout: `${base}/logout`,
      send: `${base}/send`,
      apiUrl: `${base}/api-url`,
      messages: `${base}/messages`,
      errors: `${base}/errors`,
      notifications: `${base}/notifications`
    };
  }

  async destroyCompletely() {
    await this.stop();
    const sessionPath = path.join(this.rootDir, 'sessions', this.name);
    await fs.remove(sessionPath).catch(() => {});
    await fs.remove(this.store.sessionFile(this.name)).catch(() => {});
    await fs.remove(this.store.messageFile(this.name)).catch(() => {});
    await fs.remove(this.store.errorFile(this.name)).catch(() => {});
    await fs.remove(this.store.notificationFile(this.name)).catch(() => {});
  }
}

class SessionManager {
  constructor({ rootDir, store, chromePath, io = null }) {
    this.rootDir = rootDir;
    this.store = store;
    this.chromePath = chromePath;
    this.io = io;
    this.sessions = new Map();
  }

  async ensureSession(name, apiBaseUrl = null, backupPhone = null) {
    if (this.sessions.has(name)) {
      const existing = this.sessions.get(name);
      if (apiBaseUrl !== null && apiBaseUrl !== undefined && apiBaseUrl !== '') {
        existing.apiBaseUrl = apiBaseUrl;
        await existing.persistMeta({ apiBaseUrl });
      }
      if (backupPhone !== null && backupPhone !== undefined && backupPhone !== '') {
        existing.backupPhone = backupPhone;
        await existing.persistMeta({ backupPhone });
      }
      return existing;
    }

    const session = new WhatsAppSession({
      name,
      rootDir: this.rootDir,
      store: this.store,
      apiBaseUrl,
      backupPhone,
      chromePath: this.chromePath,
      io: this.io
    });
    await session.loadMeta();
    if (apiBaseUrl !== null && apiBaseUrl !== undefined && apiBaseUrl !== '') {
      session.apiBaseUrl = apiBaseUrl;
      await session.persistMeta({ apiBaseUrl });
    }
    if (backupPhone !== null && backupPhone !== undefined && backupPhone !== '') {
      session.backupPhone = backupPhone;
      await session.persistMeta({ backupPhone });
    }
    this.sessions.set(name, session);
    return session;
  }

  async createSession(name, options = {}) {
    const existing = await this.store.getSessionMeta(name);
    if (existing || this.sessions.has(name)) {
      throw new Error('هذه الجلسة موجودة بالفعل');
    }

    const session = new WhatsAppSession({
      name,
      rootDir: this.rootDir,
      store: this.store,
      apiBaseUrl: options.apiBaseUrl || null,
      backupPhone: options.backupPhone || null,
      chromePath: this.chromePath,
      io: this.io
    });

    await session.persistMeta({
      createdAt: nowIso(),
      apiBaseUrl: session.apiBaseUrl,
      backupPhone: session.backupPhone,
      status: 'idle',
      stats: session.stats
    });

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

module.exports = {
  SessionManager,
  WhatsAppSession
};
