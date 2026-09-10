const path = require('path');
const fs = require('fs-extra');
const express = require('express');
const { WhatsAppSession } = require('./sessionManager');
const { requireAdmin, requireClient } = require('../auth');

const ROOT_DIR = path.join(__dirname, '..');
const CONFIG_FILE = path.join(ROOT_DIR, 'data', 'message-queue.json');
const DEFAULT_CONFIG = { enabled: true, minDelayMs: 6000, maxDelayMs: 11000, sessions: {} };

function clampInt(value, fallback, min, max) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.min(max, Math.max(min, Math.floor(n))) : fallback;
}

function asBool(value, fallback = true) {
  if (value === undefined || value === null || value === '') return fallback;
  return !['0', 'false', 'off', 'no'].includes(String(value).toLowerCase());
}

class MessageQueueManager {
  constructor() {
    this.config = { ...DEFAULT_CONFIG, sessions: {} };
    this.queues = new Map();
    this.ready = this.load();
  }

  normalize(input = {}) {
    const rawMin = clampInt(input.minDelayMs, DEFAULT_CONFIG.minDelayMs, 0, 10 * 60 * 1000);
    const rawMax = clampInt(input.maxDelayMs, DEFAULT_CONFIG.maxDelayMs, 0, 10 * 60 * 1000);
    const sessions = {};
    for (const [name, value] of Object.entries(input.sessions || {})) {
      if (!name || !value || typeof value !== 'object') continue;
      const minDelayMs = clampInt(value.minDelayMs, Math.min(rawMin, rawMax), 0, 10 * 60 * 1000);
      const maxDelayMs = clampInt(value.maxDelayMs, Math.max(rawMin, rawMax), 0, 10 * 60 * 1000);
      sessions[name] = {
        enabled: asBool(value.enabled, true),
        minDelayMs: Math.min(minDelayMs, maxDelayMs),
        maxDelayMs: Math.max(minDelayMs, maxDelayMs)
      };
    }
    return {
      enabled: asBool(input.enabled, DEFAULT_CONFIG.enabled),
      minDelayMs: Math.min(rawMin, rawMax),
      maxDelayMs: Math.max(rawMin, rawMax),
      sessions
    };
  }

  async load() {
    try {
      const stored = await fs.readJson(CONFIG_FILE);
      this.config = this.normalize(stored);
    } catch {
      const enabled = process.env.MESSAGE_QUEUE_ENABLED === undefined
        ? DEFAULT_CONFIG.enabled
        : asBool(process.env.MESSAGE_QUEUE_ENABLED, DEFAULT_CONFIG.enabled);
      this.config = this.normalize({
        enabled,
        minDelayMs: process.env.MESSAGE_QUEUE_MIN_DELAY_MS,
        maxDelayMs: process.env.MESSAGE_QUEUE_MAX_DELAY_MS,
        sessions: {}
      });
      await this.persist();
    }
    return this.config;
  }

  async persist() {
    await fs.ensureDir(path.dirname(CONFIG_FILE));
    await fs.writeJson(CONFIG_FILE, this.config, { spaces: 2 });
  }

  getSessionConfig(sessionName) {
    const specific = this.config.sessions?.[sessionName];
    return {
      enabled: specific?.enabled ?? this.config.enabled,
      minDelayMs: specific?.minDelayMs ?? this.config.minDelayMs,
      maxDelayMs: specific?.maxDelayMs ?? this.config.maxDelayMs,
      customized: !!specific
    };
  }

  snapshot(sessionName = null) {
    if (sessionName) {
      const setting = this.getSessionConfig(sessionName);
      const state = this.queues.get(sessionName);
      return {
        ...setting,
        queued: state?.jobs?.length || 0,
        active: state?.running ? 1 : 0,
        session: sessionName
      };
    }
    const sessions = {};
    let queued = 0;
    for (const [name, state] of this.queues.entries()) {
      sessions[name] = { ...this.getSessionConfig(name), queued: state.jobs.length, active: state.running ? 1 : 0 };
      queued += state.jobs.length;
    }
    for (const [name, value] of Object.entries(this.config.sessions || {})) {
      if (!sessions[name]) sessions[name] = { ...this.getSessionConfig(name), queued: 0, active: 0 };
    }
    return { ...this.config, queued, sessions };
  }

  randomDelay(sessionName) {
    const { minDelayMs, maxDelayMs } = this.getSessionConfig(sessionName);
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
    const config = this.getSessionConfig(session.name);
    const existing = this.queues.get(session.name);
    if (!config.enabled && !existing) return directSend();

    const state = existing || this.stateFor(session.name);
    return new Promise((resolve, reject) => {
      state.jobs.push({ phoneNumber, message, media, directSend, resolve, reject });
      if (!state.running) this.run(session.name, state).catch(() => {});
    });
  }

  wake(sessionName = null) {
    const states = sessionName ? [this.queues.get(sessionName)] : [...this.queues.values()];
    for (const state of states) {
      if (state?.wake) {
        state.wake();
        state.wake = null;
      }
    }
  }

  async setConfig(patch = {}) {
    await this.ready;
    this.config = this.normalize({ ...this.config, ...patch, sessions: this.config.sessions });
    await this.persist();
    this.wake();
    return this.snapshot();
  }

  async setSessionConfig(sessionName, patch = {}) {
    await this.ready;
    const current = this.getSessionConfig(sessionName);
    const next = this.normalize({
      enabled: patch.enabled ?? current.enabled,
      minDelayMs: patch.minDelayMs ?? current.minDelayMs,
      maxDelayMs: patch.maxDelayMs ?? current.maxDelayMs,
      sessions: {}
    });
    this.config.sessions[sessionName] = {
      enabled: next.enabled,
      minDelayMs: next.minDelayMs,
      maxDelayMs: next.maxDelayMs
    };
    await this.persist();
    if (!next.enabled) this.wake(sessionName);
    return this.snapshot(sessionName);
  }

  async wait(ms, state, sessionName) {
    if (ms <= 0 || !this.getSessionConfig(sessionName).enabled) return;
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
          const config = this.getSessionConfig(sessionName);
          if (!first && config.enabled) await this.wait(this.randomDelay(sessionName), state, sessionName);
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
    if (mount === '/api/client' && !this.__messageQueueClientMounted) {
      this.__messageQueueClientMounted = true;
      this.get('/api/client/message-queue', requireClient, async (req, res) => {
        try {
          await queueManager.ready;
          const user = await this.locals.auth.getAuthenticatedUser(req);
          const sessionName = user?.client?.sessionName;
          if (!sessionName) return res.status(401).json({ success: false, error: 'Authentication required' });
          res.json({ success: true, data: queueManager.snapshot(sessionName) });
        } catch (error) {
          res.status(400).json({ success: false, error: error.message });
        }
      });
      this.post('/api/client/message-queue', requireClient, async (req, res) => {
        try {
          const user = await this.locals.auth.getAuthenticatedUser(req);
          const sessionName = user?.client?.sessionName;
          if (!sessionName) return res.status(401).json({ success: false, error: 'Authentication required' });
          const data = await queueManager.setSessionConfig(sessionName, {
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
