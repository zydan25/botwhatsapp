const path = require('path');
const express = require('express');
const { ClientStore } = require('./clientStore');

const ROOT_DIR = path.join(__dirname, '..');
const clientStore = new ClientStore(ROOT_DIR);
const originalUse = express.application.use;

if (!express.application.__clientProfileHook) {
  express.application.__clientProfileHook = true;
  express.application.use = function patchedUse(...args) {
    const result = originalUse.apply(this, args);
    const mount = typeof args[0] === 'string' ? args[0] : '';
    if (mount === '/api/client' && !this.__clientProfileMounted) {
      this.__clientProfileMounted = true;
      const requireClient = require('../auth').requireClient;
      this.post('/api/client/profile', requireClient, async (req, res) => {
        try {
          const user = await this.locals.auth.getAuthenticatedUser(req);
          const client = user?.client;
          if (!client) return res.status(401).json({ success: false, error: 'Authentication required' });
          const displayName = String(req.body?.displayName || '').trim().slice(0, 100);
          if (!displayName) return res.status(400).json({ success: false, error: 'اسم العميل مطلوب' });
          client.displayName = displayName;
          client.updatedAt = new Date().toISOString();
          await clientStore.save(client);
          return res.json({ success: true, data: { username: client.username, displayName: client.displayName, sessionName: client.sessionName } });
        } catch (error) {
          return res.status(400).json({ success: false, error: error.message });
        }
      });
    }
    return result;
  };
}
