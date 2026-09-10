const fs = require('fs-extra');
const path = require('path');
const { hashPassword, verifyPassword } = require('../auth');

class ClientStore {
  constructor(rootDir) {
    this.rootDir = rootDir;
    this.clientsDir = path.join(rootDir, 'data', 'clients');
  }

  async init() {
    await fs.ensureDir(this.clientsDir);
  }

  sanitizeUsername(input) {
    const username = String(input || '').trim().toLowerCase();
    if (!/^[a-z][a-z0-9_.-]{2,31}$/.test(username)) throw new Error('اسم مستخدم العميل يجب أن يكون 3-32 حرفًا ويبدأ بحرف');
    if (['admin', 'administrator', 'root', 'support', 'api', 'whatsapp'].includes(username)) throw new Error('اسم المستخدم محجوز');
    return username;
  }

  fileFor(username) {
    return path.join(this.clientsDir, `${this.sanitizeUsername(username)}.json`);
  }

  async getByUsername(username) {
    const safe = this.sanitizeUsername(username);
    try { return await fs.readJson(this.fileFor(safe)); } catch { return null; }
  }

  async getBySession(sessionName) {
    const files = await fs.readdir(this.clientsDir);
    for (const file of files.filter((item) => item.endsWith('.json'))) {
      const record = await fs.readJson(path.join(this.clientsDir, file)).catch(() => null);
      if (record?.sessionName === sessionName) return record;
    }
    return null;
  }

  async list() {
    const files = await fs.readdir(this.clientsDir);
    const records = [];
    for (const file of files.filter((item) => item.endsWith('.json')).sort()) {
      const record = await fs.readJson(path.join(this.clientsDir, file)).catch(() => null);
      if (record) records.push({ username: record.username, displayName: record.displayName, sessionName: record.sessionName, createdAt: record.createdAt, updatedAt: record.updatedAt, tokenVersion: record.tokenVersion || 1 });
    }
    return records;
  }

  async create({ username, password, sessionName, displayName = '' }) {
    const safe = this.sanitizeUsername(username);
    if (await this.getByUsername(safe)) throw new Error('حساب العميل موجود بالفعل');
    const passwordData = hashPassword(password);
    const record = { username: safe, displayName: String(displayName || '').trim().slice(0, 100), sessionName, ...passwordData, tokenVersion: 1, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
    await fs.writeJson(this.fileFor(safe), record, { spaces: 2, mode: 0o600 });
    return record;
  }

  async verifyCredentials(username, password) {
    const record = await this.getByUsername(username);
    return record && verifyPassword(password, record) ? record : null;
  }

  async updatePassword(username, newPassword) {
    const record = await this.getByUsername(username);
    if (!record) throw new Error('حساب العميل غير موجود');
    const passwordData = hashPassword(newPassword);
    record.passwordHash = passwordData.hash;
    record.passwordSalt = passwordData.salt;
    record.tokenVersion = Number(record.tokenVersion || 1) + 1;
    record.updatedAt = new Date().toISOString();
    await fs.writeJson(this.fileFor(record.username), record, { spaces: 2, mode: 0o600 });
    return record;
  }

  async delete(username) {
    await fs.remove(this.fileFor(username));
  }
}

module.exports = { ClientStore };
