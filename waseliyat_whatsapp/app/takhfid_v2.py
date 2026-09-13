from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import UniqueConstraint

from . import db
from .models import WhatsAppSession
from .services.whatsapp import WhatsAppClient


takhfid_v2_bp = Blueprint("takhfid_v2", __name__, url_prefix="/takhfid/api/v2")


class TakhfidCustomer(db.Model):
    __tablename__ = "takhfid_customer"
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(80), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(20), nullable=False, unique=True, index=True)
    first_name = db.Column(db.String(80), nullable=False, default="")
    second_name = db.Column(db.String(80), nullable=True)
    third_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    governorate = db.Column(db.String(80), nullable=True)
    role = db.Column(db.String(20), nullable=False, default="customer")
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)


class TakhfidAccessToken(db.Model):
    __tablename__ = "takhfid_access_token"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("takhfid_customer.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = db.Column(db.String(128), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("customer_id", "token_hash", name="uq_takhfid_access_customer_hash"),)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = "967" + digits[1:]
    if len(digits) == 9 and digits.startswith("7"):
        digits = "967" + digits
    return digits


def _setting(key: str, default: str = "") -> str:
    from .takhfid import TakhfidSetting

    row = TakhfidSetting.query.filter_by(key=key).first()
    return row.value if row else default


def _otp_secret() -> str:
    return _setting("otp_hash_secret") or current_app.config.get("TAKHFIID_OTP_HASH_SECRET", "")


def _hash_otp(phone: str, code: str) -> str:
    secret = _otp_secret()
    if not secret:
        raise RuntimeError("OTP hash secret is not configured")
    return hmac.new(secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def _whatsapp_session() -> WhatsAppSession:
    name = _setting("whatsapp_session", current_app.config.get("TAKHFIID_WHATSAPP_SESSION", "basheer")).strip() or "basheer"
    session = WhatsAppSession.query.filter_by(name=name, active=True).first()
    if not session:
        session = WhatsAppSession.query.filter_by(active=True).order_by(WhatsAppSession.id.asc()).first()
    if not session:
        raise RuntimeError("لا توجد جلسة WhatsApp فعالة")
    return session


def _admin_numbers() -> set[str]:
    return {_normalize_phone(x) for x in _setting("admin_phones", "").split(",") if _normalize_phone(x)}


def _public_customer(customer: TakhfidCustomer) -> dict[str, Any]:
    return {
        "uid": customer.uid,
        "phone": customer.phone,
        "firstName": customer.first_name,
        "secondName": customer.second_name,
        "thirdName": customer.third_name,
        "lastName": customer.last_name,
        "governorate": customer.governorate,
        "role": customer.role,
        "isAdmin": customer.is_admin,
        "createdAt": customer.created_at.isoformat() if customer.created_at else None,
        "lastLoginAt": customer.last_login_at.isoformat() if customer.last_login_at else None,
        "updatedAt": customer.updated_at.isoformat() if customer.updated_at else None,
    }


def _token_hash(token: str) -> str:
    secret = str(current_app.config.get("SECRET_KEY", "")).encode()
    return hmac.new(secret, token.encode(), hashlib.sha256).hexdigest()


def _issue_token(customer: TakhfidCustomer) -> tuple[str, datetime]:
    raw = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    db.session.add(TakhfidAccessToken(customer_id=customer.id, token_hash=_token_hash(raw), expires_at=expires))
    return raw, expires


def _current_customer() -> TakhfidCustomer | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    raw = header[7:].strip()
    if not raw:
        return None
    row = TakhfidAccessToken.query.filter_by(token_hash=_token_hash(raw), revoked_at=None).first()
    if not row:
        return None
    if (_utc(row.expires_at) or datetime.min.replace(tzinfo=timezone.utc)) <= datetime.now(timezone.utc):
        return None
    return db.session.get(TakhfidCustomer, row.customer_id)


def _require_customer() -> TakhfidCustomer | tuple[Any, int]:
    customer = _current_customer()
    if not customer:
        return jsonify({"success": False, "error": "غير مصرح أو انتهت الجلسة"}), 401
    return customer


def _require_admin() -> TakhfidCustomer | tuple[Any, int]:
    customer = _current_customer()
    if not customer:
        return jsonify({"success": False, "error": "غير مصرح أو انتهت الجلسة"}), 401
    if not customer.is_admin:
        return jsonify({"success": False, "error": "صلاحية المدير مطلوبة"}), 403
    return customer


@takhfid_v2_bp.post("/auth/send-otp")
def send_otp_v2():
    from .takhfid import TakhfidOtp

    payload = request.get_json(silent=True) or request.form
    phone = _normalize_phone(payload.get("phoneNumber"))
    if not phone.isdigit() or not 8 <= len(phone) <= 15:
        return jsonify({"success": False, "error": "رقم الهاتف غير صالح"}), 400

    now = datetime.now(timezone.utc)
    old = TakhfidOtp.query.filter_by(phone=phone).first()
    sent_at = _utc(old.sent_at) if old else None
    if sent_at and (now - sent_at).total_seconds() < 60:
        return jsonify({"success": False, "error": "انتظر قبل إعادة الإرسال"}), 429

    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        digest = _hash_otp(phone, code)
        result = WhatsAppClient(_whatsapp_session()).send(
            phone,
            f"رمز تسجيل الدخول إلى التخفيض: {code}\nصالح لمدة 5 دقائق. لا تشاركه مع أي شخص.",
        )
    except Exception as exc:
        current_app.logger.exception("Takhfid v2 OTP send failed")
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
    return jsonify({"success": True, "phoneNumber": phone, "expiresInSeconds": 300, "retryAfterSeconds": 60})


@takhfid_v2_bp.post("/auth/verify-otp")
def verify_otp_v2():
    from .takhfid import TakhfidOtp

    payload = request.get_json(silent=True) or request.form
    phone = _normalize_phone(payload.get("phoneNumber"))
    code = str(payload.get("otp") or "").strip()
    if not (phone.isdigit() and 8 <= len(phone) <= 15 and code.isdigit() and len(code) == 6):
        return jsonify({"success": False, "error": "بيانات التحقق غير صالحة"}), 400

    row = TakhfidOtp.query.filter_by(phone=phone).first()
    if not row:
        return jsonify({"success": False, "error": "لا يوجد رمز نشط"}), 400

    now = datetime.now(timezone.utc)
    expires_at = _utc(row.expires_at)
    if expires_at is None or expires_at < now:
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

    first_name = str(payload.get("firstName") or "").strip()
    if not first_name:
        return jsonify({"success": False, "error": "الاسم الأول مطلوب"}), 400

    is_admin = phone in _admin_numbers()
    uid = f"usr_{phone}"
    customer = TakhfidCustomer.query.filter_by(uid=uid).first()
    if not customer:
        customer = TakhfidCustomer(uid=uid, phone=phone)
        db.session.add(customer)
        db.session.flush()

    customer.first_name = first_name
    customer.second_name = str(payload.get("secondName") or "").strip() or None
    customer.third_name = str(payload.get("thirdName") or "").strip() or None
    customer.last_name = str(payload.get("lastName") or "").strip() or None
    customer.governorate = str(payload.get("governorate") or "").strip() or None
    customer.is_admin = is_admin
    customer.role = "admin" if is_admin else "customer"
    customer.last_login_at = now
    customer.updated_at = now

    raw_token, expires = _issue_token(customer)
    db.session.delete(row)
    db.session.commit()

    return jsonify({
        "success": True,
        "accessToken": raw_token,
        "tokenType": "Bearer",
        "expiresAt": expires.isoformat(),
        "user": _public_customer(customer),
    })


@takhfid_v2_bp.post("/auth/logout")
def logout_v2():
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        row = TakhfidAccessToken.query.filter_by(token_hash=_token_hash(header[7:].strip()), revoked_at=None).first()
        if row:
            row.revoked_at = datetime.now(timezone.utc)
            db.session.commit()
    return jsonify({"success": True})


@takhfid_v2_bp.get("/auth/me")
def me_v2():
    customer = _require_customer()
    if isinstance(customer, tuple):
        return customer
    return jsonify({"success": True, "user": _public_customer(customer)})


class TakhfidProduct(db.Model):
    __tablename__ = "takhfid_product"
    id = db.Column(db.String(120), primary_key=True)
    payload = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


def _product_payload(product: TakhfidProduct) -> dict[str, Any]:
    value = dict(product.payload or {})
    value["id"] = product.id
    return value


@takhfid_v2_bp.get("/products")
def list_products_v2():
    rows = TakhfidProduct.query.order_by(TakhfidProduct.updated_at.desc()).all()
    return jsonify({"success": True, "products": [_product_payload(row) for row in rows]})


@takhfid_v2_bp.post("/products")
def create_product_v2():
    customer = _require_admin()
    if isinstance(customer, tuple):
        return customer
    payload = request.get_json(silent=True) or {}
    product_id = str(payload.get("id") or "").strip()
    if not product_id:
        return jsonify({"success": False, "error": "معرف المنتج مطلوب"}), 400
    data = dict(payload)
    data.pop("id", None)
    row = db.session.get(TakhfidProduct, product_id)
    if not row:
        row = TakhfidProduct(id=product_id, payload=data)
        db.session.add(row)
    else:
        row.payload = data
        row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"success": True, "product": _product_payload(row)})


@takhfid_v2_bp.put("/products/<product_id>")
def update_product_v2(product_id: str):
    customer = _require_admin()
    if isinstance(customer, tuple):
        return customer
    payload = request.get_json(silent=True) or {}
    row = db.session.get(TakhfidProduct, product_id)
    if not row:
        return jsonify({"success": False, "error": "المنتج غير موجود"}), 404
    data = dict(payload)
    data.pop("id", None)
    row.payload = data
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"success": True, "product": _product_payload(row)})


@takhfid_v2_bp.delete("/products/<product_id>")
def delete_product_v2(product_id: str):
    customer = _require_admin()
    if isinstance(customer, tuple):
        return customer
    row = db.session.get(TakhfidProduct, product_id)
    if not row:
        return jsonify({"success": False, "error": "المنتج غير موجود"}), 404
    db.session.delete(row)
    db.session.commit()
    return jsonify({"success": True, "id": product_id})


@takhfid_v2_bp.post("/products/bulk")
def bulk_products_v2():
    customer = _require_admin()
    if isinstance(customer, tuple):
        return customer
    payload = request.get_json(silent=True) or {}
    products = payload.get("products")
    if not isinstance(products, list):
        return jsonify({"success": False, "error": "products يجب أن تكون مصفوفة"}), 400
    changed = 0
    for item in products:
        if not isinstance(item, dict):
            continue
        product_id = str(item.get("id") or "").strip()
        if not product_id:
            continue
        data = dict(item)
        data.pop("id", None)
        row = db.session.get(TakhfidProduct, product_id)
        if not row:
            row = TakhfidProduct(id=product_id, payload=data)
            db.session.add(row)
        else:
            row.payload = data
            row.updated_at = datetime.now(timezone.utc)
        changed += 1
    db.session.commit()
    return jsonify({"success": True, "count": changed})
