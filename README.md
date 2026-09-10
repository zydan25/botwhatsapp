# WhatsApp Pro Multi Session

منصة متعددة الجلسات لـ WhatsApp Web مع لوحة إدارة للمشرف وبوابة عميل معزولة، بحيث يكون لكل عميل حساب وجلسة WhatsApp ومفاتيح تكامل مستقلة.

## النطاقات

- لوحة الإدارة: `https://admin.whatsapp.alattab.site`
- بوابة العميل + API: `https://whatsapp.alattab.site`

Node يستمع محليًا على `127.0.0.1:3000` افتراضيًا ويمكن وضعه خلف Nginx أو Cloudflare.

## ربط عميل جديد

من لوحة الإدارة:

1. أنشئ اسم جلسة مثل `client1`.
2. أنشئ حساب العميل واسم العرض وكلمة المرور.
3. أدخل `API Base URL` لنظام العميل الذي سيستقبل Webhooks.
4. فعّل التشغيل التلقائي إذا أردت بدء الجلسة فور الإنشاء.
5. سلّم العميل رابط `https://whatsapp.alattab.site` وبيانات دخوله.

اسم الجلسة هو المعرف الذي يظهر في كل أحداث API/Webhook، وهو منفصل لكل عميل.

## بوابة العميل

بوابة العميل مصممة Mobile-First كواجهة تطبيق، مع شريط تنقل سفلي وأقسام منفصلة للرئيسية والربط وAPI والنشاط والإعدادات.

من الإعدادات يستطيع العميل تعديل **اسم العرض** وتغيير كلمة المرور. اسم المستخدم التقني يبقى ثابتًا حتى لا تنكسر علاقة الحساب بالجلسة.

## ملف الربط الكامل

من شاشة API أو الإعدادات يستطيع العميل تنزيل أو نسخ ملف ربط نصي خاص بجلسة العميل فقط. الملف يتضمن:

- اسم العميل واسم المستخدم واسم الجلسة.
- API URL للإرسال.
- `CLIENT_API_KEY`.
- رابط فحص الحالة.
- Webhook استقبال الرسائل.
- `Webhook Secret`.
- Webhook الحالة وQR.
- نموذج الرسالة الواردة.
- أمثلة جاهزة لـ cURL وJavaScript وPython وPHP.
- ملاحظات الأمان وصيغة رقم الهاتف.

اسم الملف:

`whatsapp-integration-{session}.txt`

## دليل العميل: ربط WhatsApp

1. افتح WhatsApp في الهاتف الذي تريد تشغيل الرقم منه.
2. الإعدادات ← الأجهزة المرتبطة.
3. اختر «ربط جهاز».
4. امسح QR الظاهر في بوابة العميل.
5. انتظر حتى تصبح الحالة «متصل».

بعد أول مصادقة لا يحتاج العميل لمسح QR عند كل تشغيل. «إعادة التشغيل» تحافظ على بيانات المصادقة. «إعادة المصادقة» تحذف بيانات اعتماد WhatsApp المحلية للجلسة فقط وتولد QR جديدًا.

## إرسال الرسائل من نظام العميل إلى WhatsApp

لكل جلسة رابط مستقل:

`POST https://whatsapp.alattab.site/api/v1/sessions/{SESSION_NAME}/send`

التوثيق:

`x-api-key: {CLIENT_API_KEY}`

JSON:

```json
{
  "phoneNumber": "9677xxxxxxx",
  "message": "مرحبا من نظامي"
}
```

مثال:

```bash
curl -X POST 'https://whatsapp.alattab.site/api/v1/sessions/client1/send' \
  -H 'x-api-key: YOUR_CLIENT_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"phoneNumber":"9677xxxxxxx","message":"مرحبا من نظامي"}'
```

المرفقات الخارجة تدعم `multipart/form-data` بالحقل `media` مع `phoneNumber` و`message`.

## استقبال الرسائل من WhatsApp إلى نظام العميل

عند وصول رسالة إلى جلسة العميل، يرسل النظام POST إلى:

`{API_BASE_URL}/webhook/whatsapp`

مثال Payload:

```json
{
  "session": "client1",
  "botId": "client1",
  "direction": "in",
  "messageId": "message-id",
  "from": "9677xxxxxxx@c.us",
  "to": "9677xxxxxxx@c.us",
  "body": "نص الرسالة",
  "type": "chat",
  "hasMedia": false,
  "mediaSkipped": false,
  "timestamp": "2026-09-10T15:00:00.000Z"
}
```

يجب أن يعيد endpoint استجابة HTTP من فئة 2xx بسرعة. المرفقات الواردة لا يتم تنزيلها أو حفظها؛ يصل فقط مؤشر `hasMedia` و`mediaSkipped`.

## التحقق من Webhook

كل Webhook صادر من النظام يحتوي:

`x-whatsapp-signature: sha256=<HMAC-SHA256>`

التوقيع يحسب على **نفس JSON body الخام** باستخدام `Webhook Secret` الخاص بالجلسة. يجب التحقق من التوقيع قبل معالجة البيانات.

أحداث إضافية:

- `/webhook/session-status` عند الاتصال أو الانفصال.
- `/webhook/qr` عند توليد QR.

## فحص حالة الجلسة من النظام

`GET https://whatsapp.alattab.site/api/v1/sessions/{SESSION_NAME}/status`

مع:

`x-api-key: {CLIENT_API_KEY}`

## الفرق بين الإرسال والاستقبال

**الإرسال:** نظام العميل → API الخاص بنا → جلسة WhatsApp → هاتف المستلم.

**الاستقبال:** هاتف WhatsApp → جلسة العميل → Webhook الخاص بالعميل → نظام العميل.

## الأمان

- `CLIENT_API_KEY` خاص بجلسة العميل ويستخدم لاستدعاء API البرمجي.
- `Webhook Secret` خاص بجلسة العميل ويستخدم للتحقق من Webhooks.
- لا تضع المفاتيح السرية داخل JavaScript عام أو تطبيق المستخدم النهائي.
- تغيير كلمة مرور بوابة العميل يلغي رموز الدخول السابقة.

## الخصوصية والملفات

المرفقات الواردة لا يتم تنزيلها أو حفظها. المرفقات الخارجة المرفوعة من لوحة العميل تستخدم `multer.memoryStorage()` وتبقى في الذاكرة أثناء تمريرها إلى WhatsApp، ولا يتم إنشاء ملف upload دائم.

## إعادة المصادقة والحذف

- **إعادة التشغيل:** يعيد تشغيل WhatsApp مع الاحتفاظ بالمصادقة.
- **إعادة توليد QR:** يعيد تشغيل الاتصال عندما تكون الجلسة بانتظار QR.
- **إعادة المصادقة:** تحذف اعتماد WhatsApp المحلي للجلسة فقط وتبدأ QR جديدًا؛ حساب العميل وAPI والـWebhook Secret تبقى.
- **حذف الجلسة:** يوقف WhatsApp ويحذف بيانات اعتماد الجلسة وسجل الرسائل والأخطاء والتنبيهات وحساب العميل المرتبط.

## التشغيل

```bash
cp .env.example .env
npm install
npm start
```

المتغيرات الأساسية:

- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `SESSION_SECRET` بقيمة عشوائية طويلة
- `ADMIN_HOST=admin.whatsapp.alattab.site`
- `CLIENT_HOST=whatsapp.alattab.site`

## PWA

بوابة العميل قابلة للتثبيت كتطبيق على الهاتف والكمبيوتر عندما يدعم المتصفح ذلك.

تصميم وبرمجة: **م. زيدان العطاب**.
