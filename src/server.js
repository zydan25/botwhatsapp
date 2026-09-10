const path = require('path');
const http = require('http');
const express = require('express');
const bodyParser = require('body-parser');
const multer = require('multer');
const fs = require('fs-extra');
const { Server } = require('socket.io');
const { JsonStore } = require('./storage');
const { ClientStore } = require('./clientStore');
const { SessionManager } = require('./sessionManager');
const { sanitizeSessionName, validateApiBaseUrl } = require('./utils');
const { setupAuth, setupSocketAuth, bindAuthResolver, requireAdmin, requireClient } = require('../auth');

const ROOT_DIR = path.join(__dirname, '..');
const PORT = Number(process.env.PORT || 3000);
const HOST = process.env.HOST || '127.0.0.1';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/chromium-browser';
const DEFAULT_API_BASE_URL = process.env.API_BASE_URL || null;
const UPLOAD_MAX_BYTES = Math.max(64 * 1024, Number(process.env.UPLOAD_MAX_BYTES || 8 * 1024 * 1024));

const app = express();
const server = http.createServer(app);
const io = new Server(server, { cors: { origin: false } });
const store = new JsonStore(ROOT_DIR);
const clientStore = new ClientStore(ROOT_DIR);
const manager = new SessionManager({ rootDir: ROOT_DIR, store, chromePath: CHROME_PATH, io });
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: UPLOAD_MAX_BYTES, files: 1, fields: 3, parts: 5 } });

app.disable('x-powered-by');
app.set('trust proxy', process.env.TRUST_PROXY === 'true');
app.use((req, res, next) => { res.setHeader('Referrer-Policy', 'same-origin'); res.setHeader('X-Content-Type-Options', 'nosniff'); res.setHeader('X-Frame-Options', 'DENY'); res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()'); next(); });
app.use(bodyParser.json({ limit: '1mb' }));
app.use(bodyParser.urlencoded({ extended: false, limit: '64kb' }));
app.use('/static', express.static(path.join(ROOT_DIR, 'public'), { index: false, maxAge: '1h' }));
app.use('/icons', express.static(path.join(ROOT_DIR, 'public', 'icons'), { index: false, maxAge: '1d' }));
app.get('/manifest.webmanifest', (_req, res) => res.sendFile(path.join(ROOT_DIR, 'public', 'manifest.webmanifest')));
app.get('/sw.js', (_req, res) => res.type('application/javascript').sendFile(path.join(ROOT_DIR, 'public', 'sw.js')));

setupAuth(app, { clientStore });
bindAuthResolver((req) => app.locals.auth.getAuthenticatedUser(req));
setupSocketAuth(io, clientStore);

const jsonError = (res, status, error) => res.status(status).json({ success: false, error });
const sessionName = (value) => sanitizeSessionName(value);
const publicStatus = (session, secret = false) => { const data = session.serialize(); if (secret) data.webhookSecret = session.webhookSecret; return data; };

app.get('/health', (_req, res) => res.json({ status: 'ok', service: 'whatsapp-pro', timestamp: new Date().toISOString() }));
app.get('/', (req, res) => { if (app.locals.auth.isAdminHost(req)) return requireAdmin(req, res, () => res.sendFile(path.join(ROOT_DIR, 'public', 'admin.html'))); if (app.locals.auth.isClientHost(req)) return requireClient(req, res, () => res.sendFile(path.join(ROOT_DIR, 'public', 'client.html'))); return res.status(404).send('Unknown host'); });
app.get('/admin', (req, res) => app.locals.auth.isAdminHost(req) ? requireAdmin(req, res, () => res.sendFile(path.join(ROOT_DIR, 'public', 'admin.html'))) : res.status(404).end());
app.get('/app', (req, res) => app.locals.auth.isClientHost(req) ? requireClient(req, res, () => res.sendFile(path.join(ROOT_DIR, 'public', 'client.html'))) : res.status(404).end());

app.use('/api/admin', requireAdmin);
app.get('/api/admin/sessions', async (_req, res) => { try { const sessions = await manager.listStatuses({ includeSecrets: true }); const clients = await clientStore.list(); const map = new Map(clients.map((c) => [c.sessionName, c])); res.json({ success: true, data: sessions.map((s) => ({ ...s, client: map.get(s.name) || null })) }); } catch (e) { jsonError(res, 500, e.message); } });
app.post('/api/admin/sessions', async (req, res) => { try { const name = sessionName(req.body?.name); const username = clientStore.sanitizeUsername(req.body?.username); const password = String(req.body?.password || ''); const displayName = String(req.body?.displayName || '').trim().slice(0,100); const description = String(req.body?.description || '').trim().slice(0,1000); const apiBaseUrl = validateApiBaseUrl(req.body?.apiBaseUrl || DEFAULT_API_BASE_URL || null); const backupPhone = String(req.body?.backupPhone || '').trim().slice(0,32) || null; const autoStart = req.body?.autoStart === true || String(req.body?.autoStart) === 'true'; if (!apiBaseUrl) throw new Error('رابط API مطلوب'); if (password.length < 10) throw new Error('كلمة مرور العميل يجب ألا تقل عن 10 أحرف'); if (await clientStore.getByUsername(username)) throw new Error('حساب العميل موجود بالفعل'); const session = await manager.createSession(name,{apiBaseUrl,backupPhone,description,autoStart}); try { const client = await clientStore.create({username,password,sessionName:name,displayName}); await session.persistMeta({clientUsername:client.username}); if(autoStart) await session.start(); res.status(201).json({success:true,data:{session:publicStatus(session,true),client:{username:client.username,displayName:client.displayName}}}); } catch(e){ await manager.removeSession(name).catch(()=>{}); throw e; } } catch(e){ jsonError(res,400,e.message); } });
app.get('/api/admin/clients', async (_req,res)=>{try{res.json({success:true,data:await clientStore.list()});}catch(e){jsonError(res,500,e.message);}});
app.post('/api/admin/sessions/:name/start', async(req,res)=>{try{const s=await manager.ensureSession(sessionName(req.params.name));res.json({success:true,data:await s.start()});}catch(e){jsonError(res,500,e.message);}});
app.post('/api/admin/sessions/:name/stop', async(req,res)=>{try{const s=await manager.ensureSession(sessionName(req.params.name));res.json({success:true,data:await s.stop()});}catch(e){jsonError(res,500,e.message);}});
app.post('/api/admin/sessions/:name/restart', async(req,res)=>{try{const s=await manager.ensureSession(sessionName(req.params.name));res.json({success:true,data:await s.restart()});}catch(e){jsonError(res,500,e.message);}});
app.post('/api/admin/sessions/:name/reauthenticate', async(req,res)=>{try{const s=await manager.ensureSession(sessionName(req.params.name));res.json({success:true,data:await s.reauthenticate()});}catch(e){jsonError(res,500,e.message);}});
app.post('/api/admin/sessions/:name/api-url', async(req,res)=>{try{const s=await manager.ensureSession(sessionName(req.params.name));s.apiBaseUrl=validateApiBaseUrl(req.body?.apiBaseUrl||null);await s.persistMeta({apiBaseUrl:s.apiBaseUrl});res.json({success:true,data:publicStatus(s,true)});}catch(e){jsonError(res,400,e.message);}});
app.post('/api/admin/sessions/:name/description', async(req,res)=>{try{const s=await manager.ensureSession(sessionName(req.params.name));s.description=String(req.body?.description||'').trim().slice(0,1000);await s.persistMeta({description:s.description});res.json({success:true,data:publicStatus(s,true)});}catch(e){jsonError(res,400,e.message);}});
app.delete('/api/admin/sessions/:name', async(req,res)=>{try{const name=sessionName(req.params.name);const client=await clientStore.getBySession(name);await manager.removeSession(name);if(client)await clientStore.delete(client.username);io.emit('session:deleted',{name});res.json({success:true});}catch(e){jsonError(res,400,e.message);}});

app.use('/api/client', requireClient);
async function clientSession(req){const user=await app.locals.auth.getAuthenticatedUser(req);const client=user?.client;if(!client)throw new Error('Authentication required');const s=await manager.ensureSession(sessionName(client.sessionName));return{client,s};}
app.get('/api/client/me',async(req,res)=>{try{const {client,s}=await clientSession(req);const status=await s.getPublicStatus();res.json({success:true,data:{client:{username:client.username,displayName:client.displayName},session:{...status,description:s.description,webhookSecret:s.webhookSecret},api:{baseUrl:s.apiBaseUrl,webhookUrl:`${s.apiBaseUrl}/webhook/whatsapp`,statusUrl:`${s.apiBaseUrl}/webhook/session-status`,qrUrl:`${s.apiBaseUrl}/webhook/qr`,signatureHeader:'x-whatsapp-signature'},authentication:{method:'HttpOnly signed cookie',scope:'هذا الحساب مربوط بهذه الجلسة فقط'},webhookExample:{session:s.name,botId:s.name,direction:'in',messageId:'message-id',from:'967xxxxxxxxx@c.us',to:'967xxxxxxxxx@c.us',body:'نص الرسالة',type:'chat',hasMedia:false,mediaSkipped:false,timestamp:new Date().toISOString()},docs:{receive:'POST /webhook/whatsapp',signature:'HMAC-SHA256 على JSON body باستخدام Webhook Secret.',media:'المرفقات الواردة لا يتم تنزيلها أو حفظها.'}}});}catch(e){jsonError(res,400,e.message);}});
app.get('/api/client/messages',async(req,res)=>{try{const {client}=await clientSession(req);res.json({success:true,data:await store.getMessages(sessionName(client.sessionName),100,0)});}catch(e){jsonError(res,400,e.message);}});
app.post('/api/client/send',upload.single('media'),async(req,res)=>{try{const {s}=await clientSession(req);const media=req.file?{buffer:req.file.buffer,mimetype:req.file.mimetype,filename:req.file.originalname,size:req.file.size}:null;res.json({success:true,data:await s.sendMessage(req.body?.phoneNumber,req.body?.message||'',media)});}catch(e){jsonError(res,400,e.message);}});
app.post('/api/client/session/start',async(req,res)=>{try{const {s}=await clientSession(req);res.json({success:true,data:await s.start()});}catch(e){jsonError(res,500,e.message);}});
app.post('/api/client/session/stop',async(req,res)=>{try{const {s}=await clientSession(req);res.json({success:true,data:await s.stop()});}catch(e){jsonError(res,500,e.message);}});
app.post('/api/client/session/restart',async(req,res)=>{try{const {s}=await clientSession(req);res.json({success:true,data:await s.restart()});}catch(e){jsonError(res,500,e.message);}});
app.post('/api/client/session/qr/regenerate',async(req,res)=>{try{const {s}=await clientSession(req);res.json({success:true,data:await s.regenerateQr()});}catch(e){jsonError(res,500,e.message);}});
app.post('/api/client/session/reauthenticate',async(req,res)=>{try{const {s}=await clientSession(req);res.json({success:true,data:await s.reauthenticate()});}catch(e){jsonError(res,500,e.message);}});
app.post('/api/client/password',async(req,res)=>{try{const user=await app.locals.auth.getAuthenticatedUser(req);const client=user?.client;if(!client)throw new Error('Authentication required');if(!(await clientStore.verifyCredentials(client.username,req.body?.currentPassword)))throw new Error('كلمة المرور الحالية غير صحيحة');await clientStore.updatePassword(client.username,req.body?.newPassword);res.setHeader('Set-Cookie','wa_client_auth=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0');res.json({success:true});}catch(e){jsonError(res,400,e.message);}});

app.use('/api/sessions', requireAdmin);
app.get('/api/sessions',async(_req,res)=>{try{res.json({success:true,data:await manager.listStatuses({includeSecrets:true})});}catch(e){jsonError(res,500,e.message);}});
app.get('/api/sessions/:name/status',async(req,res)=>{try{const s=await manager.ensureSession(sessionName(req.params.name));res.json({success:true,data:await s.getPublicStatus()});}catch(e){jsonError(res,400,e.message);}});
app.post('/api/sessions/:name/connect',async(req,res)=>{try{const s=await manager.ensureSession(sessionName(req.params.name));res.json({success:true,data:await s.start()});}catch(e){jsonError(res,500,e.message);}});
app.post('/api/sessions/:name/disconnect',async(req,res)=>{try{const s=await manager.ensureSession(sessionName(req.params.name));res.json({success:true,data:await s.stop()});}catch(e){jsonError(res,500,e.message);}});
app.post('/api/sessions/:name/reauthenticate',async(req,res)=>{try{const s=await manager.ensureSession(sessionName(req.params.name));res.json({success:true,data:await s.reauthenticate()});}catch(e){jsonError(res,500,e.message);}});
app.get('/api/sessions/:name/qr-image',async(req,res)=>{try{const s=await manager.ensureSession(sessionName(req.params.name));const data=await s.getQrImageDataUrl();if(!data)return jsonError(res,404,'No QR available');res.type('png').send(Buffer.from(data.split(',')[1],'base64'));}catch(e){jsonError(res,400,e.message);}});
app.delete('/api/sessions/:name',async(req,res)=>{try{const name=sessionName(req.params.name);const client=await clientStore.getBySession(name);await manager.removeSession(name);if(client)await clientStore.delete(client.username);io.emit('session:deleted',{name});res.json({success:true});}catch(e){jsonError(res,400,e.message);}});

app.use((error,_req,res,_next)=>{if(error instanceof multer.MulterError)return jsonError(res,400,error.code==='LIMIT_FILE_SIZE'?`حجم الملف يتجاوز ${Math.ceil(UPLOAD_MAX_BYTES/1024/1024)}MB`:error.message);console.error(error);return jsonError(res,500,'Internal server error');});
app.use((_req,res)=>res.status(404).json({success:false,error:'Not Found'}));

io.on('connection',(socket)=>{socket.emit('hello',{ok:true,timestamp:new Date().toISOString()});socket.on('join-session',(name)=>{if(socket.user?.role==='client'&&socket.user.client?.sessionName!==name)return;if(socket.user?.role==='admin'||socket.user?.client?.sessionName===name)socket.join(`session:${name}`);});});

async function bootstrap(){await store.init();await clientStore.init();await fs.ensureDir(path.join(ROOT_DIR,'sessions'));}
async function shutdown(signal){console.log(`Received ${signal}; shutting down...`);for(const name of await store.listSessionNames())await manager.ensureSession(name).then((s)=>s.stop()).catch(()=>{});server.close(()=>process.exit(0));}
async function main(){await bootstrap();server.listen(PORT,HOST,()=>console.log(`Server running on http://${HOST}:${PORT}`));process.on('SIGINT',()=>shutdown('SIGINT'));process.on('SIGTERM',()=>shutdown('SIGTERM'));}
main().catch((e)=>{console.error(e);process.exit(1);});
