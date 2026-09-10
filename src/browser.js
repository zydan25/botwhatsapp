const fs = require('fs-extra');

let puppeteer = null;
try { puppeteer = require('puppeteer'); } catch (_) {}

function isSnapPath(value) {
  const p = String(value || '').toLowerCase();
  return p.startsWith('/snap/') || p.includes('/snap/bin/') || p.includes('/var/lib/snapd/');
}

async function usableExecutable(value) {
  if (!value || isSnapPath(value)) return null;
  const candidate = String(value);
  if (!(await fs.pathExists(candidate))) return null;
  try {
    const real = await fs.realpath(candidate);
    if (isSnapPath(real)) return null;
    await fs.access(real, fs.constants.X_OK);
    return real;
  } catch (_) { return null; }
}

async function resolveBrowserExecutable(configuredPath = null) {
  const candidates = [configuredPath, process.env.CHROME_PATH, '/usr/bin/chromium', '/usr/lib/chromium/chromium', '/usr/bin/google-chrome-stable', '/usr/bin/google-chrome'];
  for (const candidate of candidates) {
    const usable = await usableExecutable(candidate);
    if (usable) return usable;
  }
  if (puppeteer?.executablePath) {
    const bundled = await usableExecutable(puppeteer.executablePath());
    if (bundled) return bundled;
  }
  throw new Error('لم يتم العثور على Chromium صالح للتشغيل؛ تم رفض مسار Snap تلقائيًا. ثبّت Chromium/Chrome بنسخة نظامية أو اسمح لـPuppeteer بتنزيل متصفحه.');
}

module.exports = { resolveBrowserExecutable, isSnapPath };
