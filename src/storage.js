const fs = require('fs-extra');
const path = require('path');

class JsonStore {
  constructor(rootDir) {
    this.rootDir = rootDir;
    this.dataDir = path.join(rootDir, 'data');
    this.sessionsDir = path.join(this.dataDir, 'sessions');
    this.messagesDir = path.join(this.dataDir, 'messages');
    this.errorsDir = path.join(this.dataDir, 'errors');
    this.notificationsDir = path.join(this.dataDir, 'notifications');
    this.uploadsDir = path.join(this.dataDir, 'uploads');
  }

  async init() {
    await fs.ensureDir(this.sessionsDir);
    await fs.ensureDir(this.messagesDir);
    await fs.ensureDir(this.errorsDir);
    await fs.ensureDir(this.notificationsDir);
    await fs.ensureDir(this.uploadsDir);
  }

  sessionFile(name) {
    return path.join(this.sessionsDir, `${name}.json`);
  }

  messageFile(name) {
    return path.join(this.messagesDir, `${name}.json`);
  }

  errorFile(name) {
    return path.join(this.errorsDir, `${name}.json`);
  }

  notificationFile(name) {
    return path.join(this.notificationsDir, `${name}.json`);
  }

  async readJsonSafe(filePath, fallback) {
    try {
      if (await fs.pathExists(filePath)) {
        return await fs.readJson(filePath);
      }
      return fallback;
    } catch {
      return fallback;
    }
  }

  async writeJsonSafe(filePath, data) {
    await fs.ensureDir(path.dirname(filePath));
    await fs.writeJson(filePath, data, { spaces: 2 });
  }

  async getSessionMeta(name) {
    return this.readJsonSafe(this.sessionFile(name), null);
  }

  async setSessionMeta(name, data) {
    return this.writeJsonSafe(this.sessionFile(name), data);
  }

  async appendMessage(name, message) {
    const file = this.messageFile(name);
    const list = await this.readJsonSafe(file, []);
    list.push(message);
    await this.writeJsonSafe(file, list.slice(-2000));
  }

  async appendError(name, error) {
    const file = this.errorFile(name);
    const list = await this.readJsonSafe(file, []);
    list.push(error);
    await this.writeJsonSafe(file, list.slice(-1000));
  }

  async appendNotification(name, note) {
    const file = this.notificationFile(name);
    const list = await this.readJsonSafe(file, []);
    list.push(note);
    await this.writeJsonSafe(file, list.slice(-250));
  }

  async listSessionNames() {
    if (!(await fs.pathExists(this.sessionsDir))) return [];
    const files = await fs.readdir(this.sessionsDir);
    return files
      .filter((f) => f.endsWith('.json'))
      .map((f) => path.basename(f, '.json'))
      .sort();
  }

  async getMessages(name, limit = 50, offset = 0) {
    const list = await this.readJsonSafe(this.messageFile(name), []);
    const end = list.length - offset;
    const start = Math.max(0, end - limit);
    return list.slice(start, end).reverse();
  }

  async getErrors(name, limit = 25) {
    const list = await this.readJsonSafe(this.errorFile(name), []);
    return list.slice(-limit).reverse();
  }

  async getNotifications(name, limit = 50) {
    const list = await this.readJsonSafe(this.notificationFile(name), []);
    return list.slice(-limit).reverse();
  }

  async listRecentNotifications(limit = 50) {
    const names = await this.listSessionNames();
    const items = [];
    for (const name of names) {
      const notes = await this.getNotifications(name, limit);
      items.push(...notes);
    }
    return items
      .sort((a, b) => String(b.timestamp || '').localeCompare(String(a.timestamp || '')))
      .slice(0, limit);
  }
}

module.exports = { JsonStore };
