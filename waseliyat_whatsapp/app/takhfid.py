from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import UniqueConstraint

from . import db
from .models import WhatsAppSession
from .services.whatsapp import WhatsAppClient


takhfid_bp = Blueprint("takhfid", __name__, url_prefix="/takhfid")


class TakhfidSetting(db.Model):
    __tablename__ = "takhfid_setting"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), nullable=False, unique=True, index=True)
    value = db.Column(db.Text, default="", nullable=False)
    secret = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class TakhfidOtp(db.Model):
    __tablename__ = "takhfid_otp"
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), nullable=False, index=True)
    code_hash = db.Column(db.String(128), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    sent_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    __table_args__ = (UniqueConstraint("phone", name="uq_takhfid_otp_phone"),)


DEFAULT_PRICING = {
    "عدن": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 0, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "حضرموت": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 3, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "شبوة": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 4, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "المهرة": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 5, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "لحج": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 2, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "أبين": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 2, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "الضالع": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 3, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "سقطرى": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 8, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "صنعاء": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 0, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "أمانة العاصمة": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 0, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "تعز": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 3, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "إب": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 2, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "الحديدة": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 2, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "ذمار": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 2, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "مأرب": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 4, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "صعدة": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 3, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "حجة": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 3, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "عمران": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 2, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "البيضاء": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 3, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "الجوف": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 4, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "المحويت": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 3, "deliveryFee": 0, "freeDeliveryIncluded": True},
    "ريمة": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 3, "deliveryFee": 0, "freeDeliveryIncluded": True},
}


def normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = "967" + digits[1:]
    if len(digits) == 9 and digits.startswith("7"):
        digits = "967" + digits
    return digits


def _setting(key: str, default: str = "") -> str:
    row = TakhfidSetting.query.filter_by(key=key).first()
    return row.value if row else default


def _set_setting(key: str, value: str, secret: bool = False) -> None:
    row = TakhfidSetting.query.filter_by(key=key).first()
    if not row:
        db.session.add(TakhfidSetting(key=key, value=value, secret=secret))
    else:
        row.value = value
        row.secret = secret
        row.updated_at = datetime.now(timezone.utc)


def _admin_user() -> bool:
    if not current_user.is_authenticated:
        return False
    configured = []
    configured.extend(os.getenv("TAKHFIID_ADMIN_USERS", "").split(","))
    configured.extend(os.getenv("ADMIN_USERNAME", "zydan").split(","))
    configured = {str(name).strip().casefold() for name in configured if str(name).strip()}
    username = str(getattr(current_user, "username", "")).strip().casefold()
    return bool(username and username in configured)


def _otp_secret() -> str:
    return _setting("otp_hash_secret") or os.getenv("TAKHFIID_OTP_HASH_SECRET", "") or os.getenv("OTP_HASH_SECRET", "")


def _hash_otp(phone: str, code: str) -> str:
    secret = _otp_secret()
    if not secret:
        raise RuntimeError("OTP hash secret is not configured")
    return hmac.new(secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def _firebase_auth():
    try:
        import firebase_admin
        from firebase_admin import auth as firebase_auth, credentials
    except ImportError as exc:
        raise RuntimeError("firebase-admin is not installed") from exc
    if not firebase_admin._apps:
        service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
        cred = credentials.Certificate(service_account_path) if service_account_path else credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
    return firebase_auth


def _whatsapp_session() -> WhatsAppSession:
    name = _setting("whatsapp_session", current_app.config.get("TAKHFIID_WHATSAPP_SESSION", "basheer")).strip() or "basheer"
    session = WhatsAppSession.query.filter_by(name=name, active=True).first()
    if not session:
        session = WhatsAppSession.query.filter_by(active=True).order_by(WhatsAppSession.id.asc()).first()
    if not session:
        raise RuntimeError("لا توجد جلسة WhatsApp فعالة")
    return session


def _public_pricing() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for governorate, default in DEFAULT_PRICING.items():
        value = default.copy()
        raw = _setting(f"pricing:{governorate}")
        if raw:
            try:
                value.update(json.loads(raw))
            except (TypeError, ValueError):
                pass
        result[governorate] = value
    return result


@takhfid_bp.get("/")
@login_required
def dashboard():
    session = _whatsapp_session()
    return render_template("takhfid/dashboard.html", title="إدارة التخفيض", pricing=_public_pricing(), session=session, can_manage=_admin_user())


@takhfid_bp.get("/health")
def health():
    return jsonify({"ok": True, "service": "takhfid", "status": "ready"})


@takhfid_bp.get("/api/pricing")
def pricing():
    return jsonify({"success": True, "pricing": _public_pricing()})


@takhfid_bp.post("/api/auth/send-otp")
def send_otp():
    payload = request.get_json(silent=True) or request.form
    phone = normalize_phone(payload.get("phoneNumber"))
    if not phone or not phone.isdigit() or not 8 <= len(phone) <= 15:
        return jsonify({"success": False, "error": "رقم الهاتف غير صالح"}), 400
    now = datetime.now(timezone.utc)
    old = TakhfidOtp.query.filter_by(phone=phone).first()
    if old and (now - old.sent_at).total_seconds() < 60:
        return jsonify({"success": False, "error": "انتظر قبل إعادة الإرسال"}), 429
    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        digest = _hash_otp(phone, code)
        result = WhatsAppClient(_whatsapp_session()).send(phone, f"رمز تسجيل الدخول إلى التخفيض: {code}\nصالح لمدة 5 دقائق. لا تشاركه مع أي شخص.")
    except Exception as exc:
        current_app.logger.exception("Takhfid OTP send failed")
        return jsonify({"success": False, "error": str(exc)}), 503
    if not result.get("ok"):
        return jsonify({"success": False, "error": result.get("error") or "تعذر إرسال رمز التحقق"}), 502
    if old:
        old.code_hash = digest
        old.expires_at = now + timedelta(minutes=5)
        old.attempts = 0
        old.sent_at = now
    else:
        db.session.add(TakhfidOtp(phone=phone, code_hash=digest, expires_at=now + timedelta(minutes=5), attempts=0, sent_at=now))
    db.session.commit()
    return jsonify({"success": True, "expiresInSeconds": 300, "retryAfterSeconds": 60})


@takhfid_bp.post("/api/auth/verify-otp")
def verify_otp():
    payload = request.get_json(silent=True) or request.form
    phone = normalize_phone(payload.get("phoneNumber"))
    code = str(payload.get("otp") or "").strip()
    if not (phone.isdigit() and 8 <= len(phone) <= 15 and code.isdigit() and len(code) == 6):
        return jsonify({"success": False, "error": "بيانات التحقق غير صالحة"}), 400
    row = TakhfidOtp.query.filter_by(phone=phone).first()
    if not row:
        return jsonify({"success": False, "error": "لا يوجد رمز نشط"}), 400
    now = datetime.now(timezone.utc)
    if row.expires_at < now:
        db.session.delete(row)
        db.session.commit()
        return jsonify({"success": False, "error": "انتهت صلاحية الرمز"}), 400
    if row.attempts >= 5:
        db.session.delete(row)
        db.session.commit()
        return jsonify({"success": False, "error": "تم تجاوز عدد المحاولات"}), 429
    if not hmac.compare_digest(row.code_hash, _hash_otp(phone, code)):
        row.attempts += 1
        db.session.commit()
        return jsonify({"success": False, "error": "رمز التحقق غير صحيح"}), 401
    try:
        firebase_auth = _firebase_auth()
        uid = f"usr_{phone}"
        try:
            firebase_auth.get_user(uid)
        except firebase_auth.UserNotFoundError:
            firebase_auth.create_user(uid=uid, phone_number=f"+{phone}")
        admin_numbers = {normalize_phone(x) for x in _setting("admin_phones", "").split(",") if normalize_phone(x)}
        is_admin = phone in admin_numbers
        role = "admin" if is_admin else "customer"
        firebase_auth.set_custom_user_claims(uid, {"admin": is_admin, "role": role})
        token = firebase_auth.create_custom_token(uid, {"admin": is_admin, "role": role})
        db.session.delete(row)
        db.session.commit()
        return jsonify({"success": True, "customToken": token.decode() if isinstance(token, bytes) else token, "user": {"uid": uid, "phone": phone, "role": role, "isAdmin": is_admin}})
    except Exception as exc:
        current_app.logger.exception("Takhfid Firebase login failed")
        return jsonify({"success": False, "error": f"Firebase غير مهيأ على الخادم: {exc}"}), 503


@takhfid_bp.get("/api/admin/settings")
@login_required
def settings_get():
    if not _admin_user():
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    rows = TakhfidSetting.query.order_by(TakhfidSetting.key.asc()).all()
    return jsonify({"success": True, "settings": [{"key": r.key, "value": "********" if r.secret else r.value, "secret": r.secret} for r in rows], "pricing": _public_pricing()})


@takhfid_bp.post("/api/admin/settings")
@login_required
def settings_save():
    if not _admin_user():
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    payload = request.get_json(silent=True) or {}
    key = str(payload.get("key") or "").strip()
    value = str(payload.get("value") or "").strip()
    allowed = {"whatsapp_session", "admin_phones", "otp_hash_secret"}
    if key not in allowed:
        return jsonify({"success": False, "error": "إعداد غير مسموح"}), 400
    if key == "otp_hash_secret" and not value:
        return jsonify({"success": False, "error": "سر OTP مطلوب"}), 400
    _set_setting(key, value, key == "otp_hash_secret")
    db.session.commit()
    return jsonify({"success": True})


@takhfid_bp.post("/api/admin/pricing/<path:governorate>")
@login_required
def pricing_save(governorate: str):
    if not _admin_user():
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    if governorate not in DEFAULT_PRICING:
        return jsonify({"success": False, "error": "محافظة غير معروفة"}), 404
    payload = request.get_json(silent=True) or {}
    current = DEFAULT_PRICING[governorate].copy()
    raw = _setting(f"pricing:{governorate}")
    if raw:
        try:
            current.update(json.loads(raw))
        except (TypeError, ValueError):
            pass
    for field in ("sarToYerRate", "usdToYerRate", "markupValue", "deliveryFee"):
        if field in payload:
            number = float(payload[field])
            if number < 0:
                return jsonify({"success": False, "error": f"قيمة سالبة غير مسموحة: {field}"}), 400
            current[field] = number
    if "freeDeliveryIncluded" in payload:
        current["freeDeliveryIncluded"] = bool(payload["freeDeliveryIncluded"])
    _set_setting(f"pricing:{governorate}", json.dumps(current, ensure_ascii=False))
    db.session.commit()
    return jsonify({"success": True, "governorate": governorate, "pricing": current})
