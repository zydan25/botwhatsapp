# ربطيات واتساب — Waseliyat WhatsApp

لوحة Flask PWA عربية RTL لإدارة جلسات WhatsApp Pro Multi Session، مع واجهة مستوحاة من التصميم المرفق: بطاقة نظيفة، ألوان نبيذية، أزرار صغيرة ومتناسقة، واستجابة للهاتف والكمبيوتر.

## ما تم تجهيزه

- Flask + SQLAlchemy + Flask-Login + Flask-SocketIO.
- PWA: manifest + service worker + أيقونة SVG.
- تشغيل افتراضي على المنفذ **3333**.
- نظام مستخدم أولي من `.env`، افتراضيًا `zydan` / `774952665`، مع تغيير الاسم وكلمة المرور من الداخل.
- عقد استخدام إجباري قبل لوحة التحكم، مع حفظ قبول العقد والإصدار.
- جلسات متعددة، ولكل جلسة بوابة WhatsApp API قابلة للتغيير، و`Webhook/API الخارجي` قابل للتغيير ويُرسل إلى مسار `api-url` في الخادم البعيد.
- أزرار واضحة: ربط، فصل الجلسة، تسجيل خروج واتساب.
- عرض QR عند توفره.
- تجربة إرسال رسالة مع دعم `media`.
- صفحة API موحدة مع نسخ المسارات وتصدير PDF.
- Webhooks لاستقبال الرسائل والحالة وQR.
- قاعدة بيانات منظمة + `schema.sql` كمرجع PostgreSQL.
- سجل رسائل وإشعارات وAudit Log.
- ملف Nginx جاهز.
- إعداد **PM2** جاهز لإدارة العملية وإعادة تشغيلها تلقائيًا.
- ملف systemd موجود كخيار بديل فقط، وليس مدير التشغيل الأساسي.

## المسار على السيرفر

يجب أن يكون المشروع في:

```text
/home/root/projects/waseliyat
```

والبيئة الافتراضية:

```text
/home/root/projects/waseliyat/.venv
```

## API المعتمد

تمت مواءمة التكامل مع الدليل المرفق للمشروع، وليس مع API افتراضي. الدليل يحدد base URL الحالي `https://whatsapp.alattab.site`، ومسارات الجلسة مثل status/qr/connect/disconnect/logout/send/api-url/messages/errors/notifications، ويدعم `multipart/form-data` للإرسال مع `phoneNumber` و`message` و`media`. كما يوضح استخدام Socket.IO والتحديثات الفورية، والـwebhooks الخاصة بالرسائل والحالة وQR.

## التشغيل محليًا

```bash
cd /home/root/projects/waseliyat
python3 -m venv .venv
source .venv/bin/activate
cp .env.example .env
nano .env
pip install -r requirements.txt
python run.py
```

افتح: `http://127.0.0.1:3333`

## التشغيل الإنتاجي باستخدام PM2

هذا هو مدير التشغيل الأساسي لهذا المشروع.

```bash
cd /home/root/projects/waseliyat

# تثبيت المتطلبات
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# إعداد البيئة
cp .env.example .env
nano .env

# تثبيت PM2 إذا لم يكن موجودًا
npm install -g pm2

# تشغيل التطبيق
pm2 start ecosystem.config.js
pm2 save
```

التحقق:

```bash
pm2 status
pm2 logs waseliyat
```

إعادة التشغيل:

```bash
pm2 restart waseliyat
```

الإيقاف:

```bash
pm2 stop waseliyat
```

## تشغيل PM2 تلقائيًا بعد إعادة تشغيل السيرفر

بعد تسجيل الدخول بنفس المستخدم الذي يشغل PM2 نفذ:

```bash
pm2 startup
```

ثم نفذ أمر `sudo` الذي سيطبعه PM2، وبعده:

```bash
pm2 save
```

## التثبيت الآلي

بعد وضع المشروع في `/home/root/projects/waseliyat`:

```bash
cd /home/root/projects/waseliyat
bash deploy/install.sh
```

يقوم الملف بإنشاء `.venv` وتثبيت المتطلبات وتهيئة `.env` إن لم يكن موجودًا وتثبيت PM2 وتشغيل التطبيق باسمه `waseliyat` ثم حفظ قائمة PM2.

## PostgreSQL

اضبط في `.env`:

```text
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/waseliyat
```

`schema.sql` مرفق كمرجع SQL مباشر. التطبيق نفسه ينشئ الجداول عند أول تشغيل عبر SQLAlchemy، ولذلك لا يحتاج تنفيذ schema.sql عند الاستخدام العادي.

## Nginx + HTTPS

```bash
cp deploy/nginx-whats.alattab.site.conf /etc/nginx/sites-available/whats.alattab.site
ln -s /etc/nginx/sites-available/whats.alattab.site /etc/nginx/sites-enabled/whats.alattab.site
nginx -t
systemctl reload nginx
certbot --nginx -d whats.alattab.site
```

ملف Nginx يمرر الدومين إلى `127.0.0.1:3333` ويدعم ترقية WebSocket.

## ملاحظات أمنية

لا تترك كلمة المرور الافتراضية في الإنتاج. غيّر `SECRET_KEY` وكلمة المرور من `.env` ثم من داخل لوحة التحكم. لا تسجل QR أو البيانات الحساسة في سجلات Nginx أو التطبيق. اضبط `WEBHOOK_SECRET` عند الحاجة لطبقة تحقق إضافية، واستخدم HTTPS ومعدل إرسال مناسب عند تعريض API للخارج.

## ملاحظة مهمة عن مصدر الـAPI

الملف المرفق يذكر أن الـAPI الحالي لا يحتوي على Authorization مخصص في المسارات المعروضة، ويوصي بوضع طبقة حماية أمامه مثل API Key/Bearer Token وIP allow-list وRate limiting. هذه النسخة تحمي لوحة Flask بحساب دخول منفصل، لكنها لا تخترع Authorization غير موجود في الدليل.
