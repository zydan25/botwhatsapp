const path = require('path');
const fs = require('fs-extra');
const express = require('express');
const { WhatsAppSession } = require('./sessionManager');
const { requireAdmin } = require('../auth');

const ROOT_DIR = path.join(__dirname, '..');
const CONFIG_FILE = path.join(ROOT_DIR, 'data', 'message-queue.json');
const DEFAULT_CONFIG = { enabled: true, minDelayMs: 6000, maxDelayMs: 11000 };

function clampInt(value, fallback, min, max) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.min(max, Math.max(min, Math.floor(n))) : fallback;
}

class MessageQueueManager {
  constructor() {
    this.config = { ...DEFAULT_CONFIG };
    this.queues = new Map();
    this.ready = this.load();
  }

  async load() {
    try {
      const stored = await fs.readJson(CONFIG_FILE);
      this.config = this.normalize(stored);
    } catch {
      const enabled = process.env.MESSAGE_QUEUE_ENABLED === undefined
        ? DEFAULT_CONFIG.enabled
        : !['0', 'false', 'off', 'no'].includes(String(process.env.MESSAGE_QUEUE_ENABLED).toLowerCase());
      this.config = this.normalize({
        enabled,
        minDelayMs: process.env.MESSAGE_QUEUE_MIN_DELAY_MS,
        maxDelayMs: process.env.MESSAGE_QUEUE_MAX_DELAY_MS
      });
      await this.persist();
    }
    return this.config;
  }

  normalize(input = {}) {
    const rawMin = clampInt(input.minDelayMs, DEFAULT_CONFIG.minDelayMs, 0, 10 * 60 * 1000);
    const rawMax = clampInt(input.maxDelayMs, DEFAULT_CONFIG.maxDelayMs, 0, 10 * 60 * 1000);
    return {
      enabled: input.enabled !== false && String(input.enabled).toLowerCase() !== 'false',
      minDelayMs: Math.min(rawMin, rawMax),
      maxDelayMs: Math.max(rawMin, rawMax)
    };
  }

  async persist() {
    await fs.ensureDir(path.dirname(CONFIG_FILE));
    await fs.writeJson(CONFIG_FILE, this.config, { spaces: 2 });
  }

  snapshot() {
    const sessions = {};
    let queued = 0;
    for (const [name, state] of this.queues.entries()) {
      sessions[name] = { queued: state.jobs.length, active: state.running ? 1 : 0 };
      queued += state.jobs.length;
    }
    return { ...this.config, queued, sessions };
  }

  randomDelay() {
    const { minDelayMs, maxDelayMs } = this.config;
    if (maxDelayMs <= minDelayMs) return minDelayMs;
    return Math.floor(Math.random() * (maxDelayMs - minDelayMs + 1)) + minDelayMs;
  }

  stateFor(sessionName) {
    let state = this.queues.get(sessionName);
    if (!state) {
      state = { jobs: [], running: false, wake: null };
      this.queues.set(sessionName, state);
    }
    return state;
  }

  async enqueue(session, phoneNumber, message, media, directSend) {
    await this.ready;
    if (!this.config.enabled) return directSend();

    const state = this.stateFor(session.name);
    return new Promise((resolve, reject) => {
      state.jobs.push({ phoneNumber, message, media, directSend, resolve, reject });
      if (!state.running) this.run(session.name, state).catch(() => {});
    });
  }

  wakeAll() {
    for (const state of this.queues.values()) {
      if (state.wake) {
        state.wake();
        state.wake = null;
      }
    }
  }

  async setConfig(patch = {}) {
    await this.ready;
    const previousEnabled = this.config.enabled;
    this.config = this.normalize({ ...this.config, ...patch });
    await this.persist();
    if (previousEnabled !== this.config.enabled || !this.config.enabled) this.wakeAll();
    return this.snapshot();
  }

  async wait(ms, state) {
    if (ms <= 0 || !this.config.enabled) return;
    await new Promise((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (state.wake === finish) state.wake = null;
        resolve();
      };
      const timer = setTimeout(finish, ms);
      state.wake = finish;
    });
  }

  async run(sessionName, state) {
    if (state.running) return;
    state.running = true;
    try {
      let first = true;
      while (state.jobs.length) {
        const job = state.jobs.shift();
        if (!job) continue;
        try {
          if (!first && this.config.enabled) await this.wait(this.randomDelay(), state);
          first = false;
          const result = await job.directSend();
          job.resolve(result);
        } catch (error) {
          job.reject(error);
        }
      }
    } finally {
      state.running = false;
      state.wake = null;
      if (!state.jobs.length) this.queues.delete(sessionName);
    }
  }
}

if (!global.__messageQueueManager) global.__messageQueueManager = new MessageQueueManager();
const queueManager = global.__messageQueueManager;

if (!WhatsAppSession.prototype.__messageQueuePatched) {
  const originalSendMessage = WhatsAppSession.prototype.sendMessage;
  WhatsAppSession.prototype.sendMessage = function queuedSendMessage(phoneNumber, message, media = null) {
    return queueManager.enqueue(
      this,
      phoneNumber,
      message,
      media,
      () => originalSendMessage.call(this, phoneNumber, message, media)
    );
  };
  WhatsAppSession.prototype.__messageQueuePatched = true;
}

if (!express.application.__messageQueueAdminHook) {
  express.application.__messageQueueAdminHook = true;
  const originalUse = express.application.use;
  express.application.use = function patchedUse(...args) {
    const result = originalUse.apply(this, args);
    const mount = typeof args[0] === 'string' ? args[0] : '';
    if (mount === '/api/admin' && !this.__messageQueueAdminMounted) {
      this.__messageQueueAdminMounted = true;
      this.get('/api/admin/message-queue', requireAdmin, async (_req, res) => {
        try {
          await queueManager.ready;
          res.json({ success: true, data: queueManager.snapshot() });
        } catch (error) {
          res.status(500).json({ success: false, error: error.message });
        }
      });
      this.post('/api/admin/message-queue', requireAdmin, async (req, res) => {
        try {
          const data = await queueManager.setConfig({
            enabled: req.body?.enabled,
            minDelayMs: req.body?.minDelayMs,
            maxDelayMs: req.body?.maxDelayMs
          });
          res.json({ success: true, data });
        } catch (error) {
          res.status(400).json({ success: false, error: error.message });
        }
      });
    }
    return result;
  };
}

module.exports = { MessageQueueManager, queueManager };
