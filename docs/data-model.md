# Data Model

هذا المشروع يستخدم تخزينًا محليًا بصيغة JSON.

## الملفات
- `data/sessions/<name>.json`
- `data/messages/<name>.json`
- `data/errors/<name>.json`
- `data/notifications/<name>.json`

## مثال Session JSON
```json
{
  "name": "alattab1",
  "apiBaseUrl": "http://127.0.0.1:5000",
  "backupPhone": "9677xxxxxxx",
  "status": "connected",
  "createdAt": "2026-04-26T00:00:00.000Z",
  "updatedAt": "2026-04-26T00:00:00.000Z",
  "stats": {
    "incomingCount": 0,
    "outgoingCount": 0,
    "lastMessageAt": null
  }
}
```
