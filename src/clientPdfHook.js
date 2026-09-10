const path = require('path');
const crypto = require('crypto');
const express = require('express');
const fs = require('fs-extra');
const { ClientStore } = require('./clientStore');
const { resolveBrowserExecutable } = require('./browser');
let puppeteer = null;
try { puppeteer = require('puppeteer'); } catch (_) {}

const ROOT_DIR = path.join(__dirname, '..');
const clients = new ClientStore(ROOT_DIR);

function e(value) { return String(value ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;'); }
function apiKey(session, secret) { return crypto.createHmac('sha256', process.env.SESSION_SECRET).update(`client-api:${session}:${secret}`).digest('hex'); }
function meta(session) { return fs.readJsonSync(path.join(ROOT_DIR,'data','sessions',`${session}.json`),{}); }

if (!express.application.__clientPdfHook) {
  express.application.__clientPdfHook = true;
  const originalUse = express.application.use;
  express.application.use = function(...args) {
    const result = originalUse.apply(this,args);
    if (args[0] === '/api/client' && !this.__clientPdfMounted) {
      this.__clientPdfMounted = true;
      const requireClient = require('../auth').requireClient;
      this.get('/api/client/integration.pdf', requireClient, async (req,res) => {
        let browser;
        try {
          if (!puppeteer) throw new Error('محرك PDF غير متوفر على الخادم');
          const user = await this.locals.auth.getAuthenticatedUser(req);
          const client = user?.client;
          if (!client) return res.status(401).json({success:false,error:'Authentication required'});
          const m=meta(client.sessionName), secret=String(m.webhookSecret||'');
          const key=apiKey(client.sessionName,secret);
          const base=String(m.apiBaseUrl||'').replace(/\/$/,'');
          const send=`https://whatsapp.alattab.site/api/v1/sessions/${encodeURIComponent(client.sessionName)}/send`;
          const status=`https://whatsapp.alattab.site/api/v1/sessions/${encodeURIComponent(client.sessionName)}/status`;
          const receive=`${base}/webhook/whatsapp`;
          const statusHook=`${base}/webhook/session-status`;
          const qrHook=`${base}/webhook/qr`;
          const curl=`curl -X POST '${send}'\\n  -H 'x-api-key: ${key}'\\n  -H 'Content-Type: application/json'\\n  -d '{\"phoneNumber\":\"9677xxxxxxx\",\"message\":\"مرحبا\"}'`;
          const incoming=JSON.stringify({session:client.sessionName,botId:client.sessionName,direction:'in',messageId:'message-id',from:'9677xxxxxxx@c.us',to:'9677xxxxxxx@c.us',body:'نص الرسالة',type:'chat',hasMedia:false,mediaSkipped:false,timestamp:new Date().toISOString()},null,2);
          const html=`<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><style>@page{size:A4;margin:13mm}body{font-family:Arial,"Noto Sans Arabic",sans-serif;color:#173428;line-height:1.55}h1{margin:0;font-size:26px}h2{font-size:16px;margin:0 0 7px}.hero{background:#123d2d;color:white;padding:20px;border-radius:18px;margin-bottom:12px}.hero p{font-size:11px;color:#d1e7dc}.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.card{border:1px solid #dfe8e3;border-radius:13px;padding:12px;margin:8px 0;break-inside:avoid}.label{font-size:9px;color:#7a8982}.value{font-size:10px;font-weight:700;direction:ltr;text-align:left;word-break:break-word;background:#f7faf8;padding:7px;border-radius:8px;margin:3px 0 6px}.code{direction:ltr;text-align:left;white-space:pre-wrap;word-break:break-word;background:#15241c;color:#e9fff4;border-radius:10px;padding:9px;font:8px/1.65 monospace}.muted{font-size:9px;color:#6e7c75}.footer{text-align:center;color:#87948e;font-size:8px;margin-top:12px}</style><div class="hero"><h1>دليل تكامل WhatsApp Pro</h1><p>${e(client.displayName||client.username)} - الجلسة ${e(client.sessionName)}</p></div><div class="grid"><div class="card"><div class="label">الحالة</div><div class="value">${e(m.status||'idle')}</div></div><div class="card"><div class="label">رقم WhatsApp</div><div class="value">${e(m.info?.wid?.user||'غير مربوط')}</div></div></div><div class="card"><h2>الإرسال من نظامك</h2><div class="label">الرابط</div><div class="value">${e(send)}</div><div class="label">API Key</div><div class="value">${e(key)}</div><div class="code">${e(curl)}</div></div><div class="card"><h2>الاستقبال إلى نظامك</h2><div class="label">Webhook الرسائل</div><div class="value">${e(receive)}</div><div class="label">Webhook Secret</div><div class="value">${e(secret)}</div><div class="muted">تحقق من x-whatsapp-signature باستخدام HMAC-SHA256 على JSON body الخام.</div><div class="code">${e(incoming)}</div></div><div class="card"><h2>العناوين الإضافية</h2><div class="label">Status API</div><div class="value">${e(status)}</div><div class="label">Status Webhook</div><div class="value">${e(statusHook)}</div><div class="label">QR Webhook</div><div class="value">${e(qrHook)}</div></div><div class="card"><h2>ملاحظات</h2><div class="muted">رقم الهاتف يكتب بصيغة دولية بدون + أو مسافات. احفظ API Key وWebhook Secret في الخادم أو مدير أسرار ولا تشاركها مع مستخدمي الواجهة.</div></div><div class="footer">WhatsApp Pro - دليل خاص بالجلسة ${e(client.sessionName)} - تصميم وبرمجة م. زيدان العطاب</div></html>`;
          browser=await puppeteer.launch({headless:true,executablePath:await resolveBrowserExecutable(process.env.CHROME_PATH),args:['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage']});
          const page=await browser.newPage();
          await page.setContent(html,{waitUntil:'load'});
          const pdf=await page.pdf({format:'A4',printBackground:true,margin:{top:'13mm',right:'13mm',bottom:'13mm',left:'13mm'}});
          res.setHeader('Content-Type','application/pdf');res.setHeader('Content-Disposition',`attachment; filename="whatsapp-integration-${client.sessionName}.pdf"`);res.setHeader('Cache-Control','no-store');return res.end(pdf);
        }catch(error){return res.status(500).json({success:false,error:error.message});}finally{if(browser)await browser.close().catch(()=>{});}
      });
    }
    return result;
  };
}
