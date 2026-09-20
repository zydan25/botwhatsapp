from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request, send_from_directory
from flask_login import current_user
from sqlalchemy import UniqueConstraint, or_
from werkzeug.utils import secure_filename

from . import db
from .models import AuditLog
from .services.whatsapp import WhatsAppClient
from .models import WhatsAppSession


takhfid_api_bp = Blueprint("takhfid_api", __name__, url_prefix="/takhfid")

# ---------------------------------------------------------------------------
# Canonical Takhfid models. These replace the old takhfid.py / v2 / v3 model
# duplication. Legacy modules can remain temporarily for compatibility, but
# this blueprint is the only one registered by the main Flask application.
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TakhfidSetting(db.Model):
    __tablename__ = "takhfid_setting"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(160), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=False, default="")
    secret = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class TakhfidOtp(db.Model):
    __tablename__ = "takhfid_otp"
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), nullable=False, unique=True, index=True)
    code_hash = db.Column(db.String(128), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class TakhfidCustomer(db.Model):
    __tablename__ = "takhfid_customer"
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(80), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(20), nullable=False, unique=True, index=True)
    first_name = db.Column(db.String(80), nullable=False, default="")
    second_name = db.Column(db.String(80))
    third_name = db.Column(db.String(80))
    last_name = db.Column(db.String(80))
    governorate = db.Column(db.String(100))
    role = db.Column(db.String(20), nullable=False, default="customer")
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    last_login_at = db.Column(db.DateTime(timezone=True))


class TakhfidAccessToken(db.Model):
    __tablename__ = "takhfid_access_token"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("takhfid_customer.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = db.Column(db.String(128), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    revoked_at = db.Column(db.DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("customer_id", "token_hash", name="uq_takhfid_access_customer_hash"),)


class TakhfidProduct(db.Model):
    __tablename__ = "takhfid_product"
    id = db.Column(db.String(120), primary_key=True)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class TakhfidOrder(db.Model):
    __tablename__ = "takhfid_order"
    id = db.Column(db.String(120), primary_key=True)
    customer_id = db.Column(db.String(80), nullable=False, index=True)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(40), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class TakhfidChatSession(db.Model):
    __tablename__ = "takhfid_chat_session"
    id = db.Column(db.String(180), primary_key=True)
    customer_id = db.Column(db.String(80), nullable=False, index=True)
    order_id = db.Column(db.String(120), nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False, default="دعم العملاء")
    status = db.Column(db.String(30), nullable=False, default="open")
    unread_by_customer = db.Column(db.Integer, nullable=False, default=0)
    unread_by_admin = db.Column(db.Integer, nullable=False, default=0)
    last_message = db.Column(db.Text, nullable=False, default="")
    last_message_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    __table_args__ = (
        UniqueConstraint("customer_id", "order_id", name="uq_takhfid_chat_customer_order"),
    )


class TakhfidChatMessage(db.Model):
    __tablename__ = "takhfid_chat_message"
    id = db.Column(db.String(180), primary_key=True)
    session_id = db.Column(
        db.String(180),
        db.ForeignKey("takhfid_chat_session.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id = db.Column(db.String(80), nullable=False, index=True)
    sender = db.Column(db.String(20), nullable=False, default="customer")
    text = db.Column(db.Text, nullable=False, default="")
    media_url = db.Column(db.Text, nullable=True)
    media_type = db.Column(db.String(80), nullable=True)
    file_name = db.Column(db.String(255), nullable=True)
    is_payment_proof = db.Column(db.Boolean, nullable=False, default=False)
    order_id = db.Column(db.String(120), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    read_by_customer = db.Column(db.Boolean, nullable=False, default=False)


class TakhfidCustomerNotification(db.Model):
    __tablename__ = "takhfid_customer_notification"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.String(80), nullable=False, index=True)
    order_id = db.Column(db.String(120), nullable=True, index=True)
    chat_session_id = db.Column(db.String(180), nullable=True)
    type = db.Column(db.String(40), nullable=False, default="system")
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False, default="")
    data = db.Column(db.JSON, nullable=False, default=dict)
    read = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)


# ---------------------------------------------------------------------------
# Defaults / utilities
# ---------------------------------------------------------------------------

GOVERNORATES = {
    "عدن": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 0, "deliveryFee": 0},
    "حضرموت": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 3, "deliveryFee": 0},
    "شبوة": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 4, "deliveryFee": 0},
    "المهرة": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 5, "deliveryFee": 0},
    "لحج": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 2, "deliveryFee": 0},
    "أبين": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 2, "deliveryFee": 0},
    "الضالع": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 3, "deliveryFee": 0},
    "سقطرى": {"region": "south", "sarToYerRate": 535, "usdToYerRate": 2040, "markupValue": 8, "deliveryFee": 0},
    "صنعاء": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 0, "deliveryFee": 0},
    "أمانة العاصمة": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 0, "deliveryFee": 0},
    "تعز": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 3, "deliveryFee": 0},
    "إب": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 2, "deliveryFee": 0},
    "الحديدة": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 2, "deliveryFee": 0},
    "ذمار": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 2, "deliveryFee": 0},
    "مأرب": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 4, "deliveryFee": 0},
    "صعدة": {"region": "north", "sarToYerRate": 140, "usdToYerRate": 535, "markupValue": 3, "deliveryFee": 0},
    "حجة": {"region": "north", "sarToYerRate": 140, "markupValue": 3, "deliveryFee": 0},
    "عمران": {"region": "north", "sarToYerRate": 140, "markupValue": 2, "deliveryFee": 0},
    "البيضاء": {"region": "north", "sarToYerRate": 140, "markupValue": 3, "deliveryFee": 0},
    "الجوف": {"region": "north", "sarToYerRate": 140, "markupValue": 4, "deliveryFee": 0},
    "المحويت": {"region": "north", "sarToYerRate": 140, "markupValue": 3, "deliveryFee": 0},
    "ريمة": {"region": "north", "sarToYerRate": 140, "markupValue": 3, "deliveryFee": 0},
}

ALLOWED_ORDER_STATUSES = {
    "pending",
    "confirmed",
    "preparing",
    "in_shipping",
    "delivered",
    "completed",
    "cancelled",
}

ALLOWED_PAYMENT_METHODS = {
    "cash_on_delivery",
    "kuraimi",
    "jawali",
    "one_cash",
    "bank_transfer",
}

PUBLIC_SETTING_DEFAULTS: dict[str, Any] = {
    "store": {
        "name": "متجر التخفيض",
        "description": "متجر إلكتروني",
        "logo": "",
        "phone": "",
        "whatsapp": "",
        "email": "",
        "currency": "YER",
        "defaultGovernorate": "أمانة العاصمة",
        "enabled": True,
    },
    "checkout": {
        "guestCheckout": True,
        "requireAddress": True,
        "requireDeliveryNotes": False,
        "minimumOrder": 0,
        "maximumItemsPerOrder": 100,
    },
    "shipping": {
        "enabled": True,
        "defaultFee": 0,
        "freeAbove": 0,
        "sameGovernorateOnly": False,
    },
    "payments": {
        "cash_on_delivery": True,
        "kuraimi": False,
        "jawali": False,
        "one_cash": False,
        "bank_transfer": False,
    },
    "catalog": {
        "showOutOfStock": False,
        "allowBackorder": False,
        "featuredLimit": 12,
    },
    "content": {
        "banners": [],
        "campaigns": [],
        "categories": [],
        "announcements": [],
    },
}



def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def normalize_phone(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = "967" + digits[1:]
    if len(digits) == 9 and digits.startswith("7"):
        digits = "967" + digits
    return digits


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def json_setting(key: str, default: Any) -> Any:
    row = TakhfidSetting.query.filter_by(key=key).first()
    if not row or not row.value:
        return default
    try:
        return json.loads(row.value)
    except (TypeError, ValueError):
        return default


def save_json_setting(key: str, value: Any, secret: bool = False) -> None:
    row = TakhfidSetting.query.filter_by(key=key).first()
    raw = json.dumps(value, ensure_ascii=False)
    if not row:
        row = TakhfidSetting(key=key, value=raw, secret=secret)
        db.session.add(row)
    else:
        row.value = raw
        row.secret = secret
        row.updated_at = utcnow()


def setting(key: str, default: str = "") -> str:
    row = TakhfidSetting.query.filter_by(key=key).first()
    return row.value if row else default


def save_setting(key: str, value: str, secret: bool = False) -> None:
    row = TakhfidSetting.query.filter_by(key=key).first()
    if not row:
        db.session.add(TakhfidSetting(key=key, value=value, secret=secret))
    else:
        row.value = value
        row.secret = secret
        row.updated_at = utcnow()


def admin_numbers() -> set[str]:
    return {normalize_phone(x) for x in setting("admin_phones", "").split(",") if normalize_phone(x)}


def is_admin_customer(customer: TakhfidCustomer | None) -> bool:
    return bool(customer and customer.is_admin)


def token_hash(raw: str) -> str:
    secret = str(current_app.config.get("SECRET_KEY", "")).encode()
    return hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest()


def current_customer() -> TakhfidCustomer | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    raw = header[7:].strip()
    if not raw:
        return None
    row = TakhfidAccessToken.query.filter_by(token_hash=token_hash(raw), revoked_at=None).first()
    if not row or (as_utc(row.expires_at) or datetime.min.replace(tzinfo=timezone.utc)) <= utcnow():
        return None
    return db.session.get(TakhfidCustomer, row.customer_id)


def require_customer():
    customer = current_customer()
    if not customer:
        return jsonify({"success": False, "error": "غير مصرح أو انتهت الجلسة"}), 401
    return customer


def require_admin():
    customer = require_customer()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    if not customer.is_admin:
        return jsonify({"success": False, "error": "صلاحية المدير مطلوبة"}), 403
    return customer


def public_customer(customer: TakhfidCustomer) -> dict[str, Any]:
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
        "updatedAt": customer.updated_at.isoformat() if customer.updated_at else None,
        "lastLoginAt": customer.last_login_at.isoformat() if customer.last_login_at else None,
    }


def product_data(row: TakhfidProduct) -> dict[str, Any]:
    data = dict(row.payload or {})
    data["id"] = row.id
    data.setdefault("images", [data["image"]] if data.get("image") else [])
    data.setdefault("active", True)
    data.setdefault("featured", False)
    data.setdefault("currency", "YER")
    data.setdefault("stock", 0)
    data.setdefault("sizes", [])
    data.setdefault("colors", [])
    data.setdefault("variants", [])
    data.setdefault("attributes", {})
    data["createdAt"] = data.get("createdAt") or row.created_at.isoformat()
    data["updatedAt"] = row.updated_at.isoformat() if row.updated_at else data.get("updatedAt")
    return data


def public_order(row: TakhfidOrder) -> dict[str, Any]:
    data = dict(row.payload or {})
    data["id"] = row.id
    data["orderId"] = row.id
    data["customerId"] = row.customer_id if not str(row.customer_id).startswith("guest_") else None
    data["status"] = row.status
    data["createdAt"] = data.get("createdAt") or row.created_at.isoformat()
    data["updatedAt"] = row.updated_at.isoformat() if row.updated_at else data.get("updatedAt")
    data.pop("privateAccessToken", None)
    return data


def audit(action: str, details: str = "") -> None:
    user_id = current_user.id if getattr(current_user, "is_authenticated", False) else None
    db.session.add(AuditLog(user_id=user_id, action=action, details=details))


def otp_secret() -> str:
    return setting("otp_hash_secret") or os.getenv("TAKHFIID_OTP_HASH_SECRET", "") or os.getenv("OTP_HASH_SECRET", "")


def hash_otp(phone: str, code: str) -> str:
    secret = otp_secret()
    if not secret:
        raise RuntimeError("OTP hash secret is not configured")
    return hmac.new(secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def whatsapp_session() -> WhatsAppSession:
    name = setting("whatsapp_session", current_app.config.get("TAKHFIID_WHATSAPP_SESSION", "basheer")).strip() or "basheer"
    session = WhatsAppSession.query.filter_by(name=name, active=True).first()
    if not session:
        session = WhatsAppSession.query.filter_by(active=True).order_by(WhatsAppSession.id.asc()).first()
    if not session:
        raise RuntimeError("لا توجد جلسة WhatsApp فعالة")
    return session


def build_pricing() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for governorate, default in GOVERNORATES.items():
        value = dict(default)
        stored = json_setting(f"pricing:{governorate}", {})
        if isinstance(stored, dict):
            value.update(stored)
        result[governorate] = value
    return result


def normalize_product_payload(payload: dict[str, Any], product_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("بيانات المنتج غير صالحة")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("اسم المنتج مطلوب")
    currency = str(payload.get("currency") or "YER").upper()
    if currency not in {"YER", "SAR", "USD"}:
        currency = "YER"
    images = payload.get("images")
    if not isinstance(images, list):
        images = [payload.get("image")] if payload.get("image") else []
    images = [str(x).strip() for x in images if str(x or "").strip()]
    variants = payload.get("variants") if isinstance(payload.get("variants"), list) else []
    sizes = payload.get("sizes") if isinstance(payload.get("sizes"), list) else []
    colors = payload.get("colors") if isinstance(payload.get("colors"), list) else []
    attributes = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    return {
        "name": name,
        "slug": str(payload.get("slug") or name.lower().replace(" ", "-")).strip(),
        "sku": str(payload.get("sku") or "").strip(),
        "description": str(payload.get("description") or "").strip(),
        "shortDescription": str(payload.get("shortDescription") or "").strip(),
        "categoryId": str(payload.get("categoryId") or "").strip(),
        "category": str(payload.get("category") or "").strip(),
        "brand": str(payload.get("brand") or "").strip(),
        "images": images,
        "image": images[0] if images else "",
        "price": parse_float(payload.get("price")),
        "compareAtPrice": parse_float(payload.get("compareAtPrice") or payload.get("originalPrice")),
        "costPrice": parse_float(payload.get("costPrice")),
        "discountType": str(payload.get("discountType") or "none"),
        "discountValue": parse_float(payload.get("discountValue")),
        "currency": currency,
        "stock": max(0, parse_int(payload.get("stock"))),
        "lowStockThreshold": max(0, parse_int(payload.get("lowStockThreshold"), 5)),
        "active": bool(payload.get("active", True)),
        "featured": bool(payload.get("featured", False)),
        "allowBackorder": bool(payload.get("allowBackorder", False)),
        "sizes": sizes,
        "colors": colors,
        "variants": variants,
        "attributes": attributes,
        "tags": [str(x).strip() for x in tags if str(x).strip()],
        "seoTitle": str(payload.get("seoTitle") or "").strip(),
        "seoDescription": str(payload.get("seoDescription") or "").strip(),
        "sortOrder": parse_int(payload.get("sortOrder")),
        "id": product_id,
    }


def select_unit_price(product: dict[str, Any], item: dict[str, Any]) -> float:
    variants = product.get("variants") if isinstance(product.get("variants"), list) else []
    wanted_size = str(item.get("size") or "").strip()
    wanted_color = str(item.get("color") or "").strip()
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if wanted_size and str(variant.get("size") or "").strip() != wanted_size:
            continue
        if wanted_color and str(variant.get("color") or "").strip() != wanted_color:
            continue
        if variant.get("price") is not None:
            return parse_float(variant.get("price"))
    price = parse_float(product.get("price"))
    if product.get("discountType") == "percent":
        price -= price * max(0, parse_float(product.get("discountValue"))) / 100
    elif product.get("discountType") == "fixed":
        price -= max(0, parse_float(product.get("discountValue")))
    return max(0, round(price, 2))


def convert_amount(amount: float, from_currency: str, to_currency: str, rate: dict[str, Any]) -> float:
    if from_currency == to_currency:
        return amount
    if from_currency == "SAR" and to_currency == "YER":
        return amount * parse_float(rate.get("sarToYerRate"), 140)
    if from_currency == "USD" and to_currency == "YER":
        return amount * parse_float(rate.get("usdToYerRate"), 535)
    if from_currency == "YER" and to_currency == "SAR":
        return amount / max(parse_float(rate.get("sarToYerRate"), 140), 1)
    if from_currency == "YER" and to_currency == "USD":
        return amount / max(parse_float(rate.get("usdToYerRate"), 535), 1)
    return amount


def generate_order_id() -> str:
    return f"#SH-{secrets.token_hex(2).upper()}{str(int(utcnow().timestamp()))[-4:]}"


# ---------------------------------------------------------------------------
# Customer chat, media and notification API
# ---------------------------------------------------------------------------

CHAT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
CHAT_MAX_IMAGE_SIZE = 8 * 1024 * 1024


def customer_name(customer: TakhfidCustomer) -> str:
    value = " ".join(
        str(x).strip()
        for x in (
            customer.first_name,
            customer.second_name,
            customer.third_name,
            customer.last_name,
        )
        if x and str(x).strip()
    )
    return value or "عميل المتجر"


def customer_notification(
    customer_id: str,
    title: str,
    body: str,
    *,
    type: str = "system",
    order_id: str | None = None,
    chat_session_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> TakhfidCustomerNotification:
    item = TakhfidCustomerNotification(
        customer_id=customer_id,
        order_id=order_id,
        chat_session_id=chat_session_id,
        type=type,
        title=title,
        body=body,
        data=data or {},
    )
    db.session.add(item)
    return item


def chat_session_id(customer_id: str, order_id: str | None = None) -> str:
    if order_id:
        safe_order_id = (
            str(order_id)
            .replace("#", "")
            .replace("/", "_")
            .replace("\\", "_")
            .replace(" ", "_")
        )
        return "chat_" + customer_id + "_order_" + safe_order_id
    return "chat_" + customer_id


def ensure_chat_session(
    *,
    customer_id: str,
    order_id: str | None = None,
    title: str = "دعم العملاء",
    status: str = "open",
) -> TakhfidChatSession:
    session_id = chat_session_id(customer_id, order_id)
    row = db.session.get(TakhfidChatSession, session_id)
    if row:
        return row
    row = TakhfidChatSession(
        id=session_id,
        customer_id=customer_id,
        order_id=order_id,
        title=title,
        status=status,
    )
    db.session.add(row)
    db.session.flush()
    return row


def public_chat_session(row: TakhfidChatSession) -> dict[str, Any]:
    return {
        "id": row.id,
        "customerId": row.customer_id,
        "orderId": row.order_id,
        "title": row.title,
        "status": row.status,
        "unreadByCustomer": row.unread_by_customer,
        "unreadByAdmin": row.unread_by_admin,
        "lastMessage": row.last_message,
        "lastMessageAt": row.last_message_at.isoformat() if row.last_message_at else None,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def public_chat_message(row: TakhfidChatMessage) -> dict[str, Any]:
    return {
        "id": row.id,
        "sessionId": row.session_id,
        "customerId": row.customer_id,
        "sender": row.sender,
        "text": row.text,
        "mediaUrl": row.media_url,
        "mediaType": row.media_type,
        "fileName": row.file_name,
        "isPaymentProof": row.is_payment_proof,
        "orderId": row.order_id,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


def public_notification(row: TakhfidCustomerNotification) -> dict[str, Any]:
    return {
        "id": row.id,
        "customerId": row.customer_id,
        "orderId": row.order_id,
        "chatSessionId": row.chat_session_id,
        "type": row.type,
        "title": row.title,
        "body": row.body,
        "data": row.data or {},
        "read": row.read,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


def _owned_chat_session(session_id: str, customer: TakhfidCustomer) -> TakhfidChatSession | None:
    row = db.session.get(TakhfidChatSession, session_id)
    if not row or row.customer_id != customer.uid:
        return None
    return row


def _admin_or_owner_chat_session(session_id: str, customer: TakhfidCustomer) -> TakhfidChatSession | None:
    row = db.session.get(TakhfidChatSession, session_id)
    if not row:
        return None
    if customer.is_admin or row.customer_id == customer.uid:
        return row
    return None


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def chat_media_root(session_id: str) -> Path:
    safe_id = secure_filename(session_id)
    root = Path(current_app.instance_path) / "takhfid_uploads" / "chat" / safe_id
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# Public catalog/store API
# ---------------------------------------------------------------------------

@takhfid_api_bp.get("/api/v4/health")
def health():
    return jsonify({"success": True, "service": "takhfid", "version": "4", "status": "ready"})


@takhfid_api_bp.get("/api/v4/store")
def get_store():
    content = json_setting("content", PUBLIC_SETTING_DEFAULTS["content"])
    return jsonify({
        "success": True,
        "store": json_setting("store", PUBLIC_SETTING_DEFAULTS["store"]),
        "checkout": json_setting("checkout", PUBLIC_SETTING_DEFAULTS["checkout"]),
        "shipping": json_setting("shipping", PUBLIC_SETTING_DEFAULTS["shipping"]),
        "payments": json_setting("payments", PUBLIC_SETTING_DEFAULTS["payments"]),
        "catalog": json_setting("catalog", PUBLIC_SETTING_DEFAULTS["catalog"]),
        "content": content,
        "pricing": build_pricing(),
        "governorates": sorted(GOVERNORATES.keys()),
    })


@takhfid_api_bp.get("/api/v4/content")
def get_content():
    return jsonify({"success": True, "content": json_setting("content", PUBLIC_SETTING_DEFAULTS["content"])})


@takhfid_api_bp.get("/api/v4/categories")
def get_categories():
    content = json_setting("content", PUBLIC_SETTING_DEFAULTS["content"])
    categories = content.get("categories", []) if isinstance(content, dict) else []
    return jsonify({"success": True, "categories": categories})


@takhfid_api_bp.get("/api/v4/pricing")
def get_pricing():
    return jsonify({"success": True, "pricing": build_pricing()})


@takhfid_api_bp.get("/api/v4/products")
def list_products():
    query = TakhfidProduct.query
    category_id = str(request.args.get("categoryId") or "").strip()
    q = str(request.args.get("q") or "").strip()
    featured = request.args.get("featured")
    active_only = request.args.get("active", "true").lower() != "false"
    if active_only:
        # JSON payload fields are normalized, so this remains portable across SQLite/PostgreSQL.
        rows = query.order_by(TakhfidProduct.updated_at.desc()).all()
        rows = [x for x in rows if bool((x.payload or {}).get("active", True))]
    else:
        rows = query.order_by(TakhfidProduct.updated_at.desc()).all()
    if category_id:
        rows = [x for x in rows if str((x.payload or {}).get("categoryId") or "") == category_id]
    if q:
        needle = q.casefold()
        rows = [x for x in rows if needle in str((x.payload or {}).get("name") or "").casefold() or needle in str((x.payload or {}).get("description") or "").casefold()]
    if featured is not None:
        want = featured.lower() == "true"
        rows = [x for x in rows if bool((x.payload or {}).get("featured", False)) == want]
    limit = max(1, min(100, parse_int(request.args.get("limit"), 50)))
    offset = max(0, parse_int(request.args.get("offset"), 0))
    page = rows[offset: offset + limit]
    return jsonify({"success": True, "products": [product_data(x) for x in page], "total": len(rows), "limit": limit, "offset": offset})


@takhfid_api_bp.get("/api/v4/products/<product_id>")
def get_product(product_id: str):
    row = db.session.get(TakhfidProduct, product_id)
    if not row:
        return jsonify({"success": False, "error": "المنتج غير موجود"}), 404
    return jsonify({"success": True, "product": product_data(row)})


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

@takhfid_api_bp.post("/api/v4/auth/send-otp")
def send_otp():
    payload = request.get_json(silent=True) or request.form
    phone = normalize_phone(payload.get("phoneNumber"))
    if not (phone.isdigit() and 8 <= len(phone) <= 15):
        return jsonify({"success": False, "error": "رقم الهاتف غير صالح"}), 400
    now = utcnow()
    old = TakhfidOtp.query.filter_by(phone=phone).first()
    if old and (now - (as_utc(old.sent_at) or now)).total_seconds() < 60:
        return jsonify({"success": False, "error": "انتظر قبل إعادة الإرسال", "retryAfterSeconds": 60}), 429
    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        digest = hash_otp(phone, code)
        result = WhatsAppClient(whatsapp_session()).send(phone, f"رمز تسجيل الدخول إلى المتجر: {code}\nصالح لمدة 5 دقائق. لا تشاركه مع أي شخص.")
    except Exception as exc:
        current_app.logger.exception("Takhfid OTP send failed")
        return jsonify({"success": False, "error": "تعذر إرسال رمز التحقق", "details": str(exc)}), 503
    if not result.get("ok"):
        return jsonify({"success": False, "error": result.get("error") or "تعذر إرسال رمز التحقق"}), 502
    if old:
        old.code_hash = digest
        old.expires_at = now + timedelta(minutes=5)
        old.attempts = 0
        old.sent_at = now
    else:
        db.session.add(TakhfidOtp(phone=phone, code_hash=digest, expires_at=now + timedelta(minutes=5), sent_at=now))
    db.session.commit()
    return jsonify({"success": True, "phoneNumber": phone, "expiresInSeconds": 300, "retryAfterSeconds": 60})


@takhfid_api_bp.post("/api/v4/auth/verify-otp")
def verify_otp():
    payload = request.get_json(silent=True) or request.form
    phone = normalize_phone(payload.get("phoneNumber"))
    code = str(payload.get("otp") or "").strip()
    if not (phone.isdigit() and 8 <= len(phone) <= 15 and code.isdigit() and len(code) == 6):
        return jsonify({"success": False, "error": "بيانات التحقق غير صالحة"}), 400
    row = TakhfidOtp.query.filter_by(phone=phone).first()
    if not row:
        return jsonify({"success": False, "error": "لا يوجد رمز نشط"}), 400
    now = utcnow()
    if (as_utc(row.expires_at) or datetime.min.replace(tzinfo=timezone.utc)) <= now:
        db.session.delete(row)
        db.session.commit()
        return jsonify({"success": False, "error": "انتهت صلاحية الرمز"}), 400
    if row.attempts >= 5:
        db.session.delete(row)
        db.session.commit()
        return jsonify({"success": False, "error": "تم تجاوز عدد المحاولات"}), 429
    if not hmac.compare_digest(row.code_hash, hash_otp(phone, code)):
        row.attempts += 1
        db.session.commit()
        return jsonify({"success": False, "error": "رمز التحقق غير صحيح"}), 401
    customer = TakhfidCustomer.query.filter_by(phone=phone).first()
    if not customer:
        customer = TakhfidCustomer(uid=f"usr_{phone}", phone=phone)
        db.session.add(customer)
        db.session.flush()
    is_admin = phone in admin_numbers()
    customer.is_admin = is_admin
    customer.role = "admin" if is_admin else "customer"
    customer.last_login_at = now
    raw = secrets.token_urlsafe(48)
    expires = now + timedelta(days=30)
    db.session.add(TakhfidAccessToken(customer_id=customer.id, token_hash=token_hash(raw), expires_at=expires))
    db.session.delete(row)
    db.session.commit()
    needs_profile = not str(customer.first_name or "").strip()
    return jsonify({"success": True, "needsProfile": needs_profile, "accessToken": raw, "tokenType": "Bearer", "expiresAt": expires.isoformat(), "user": public_customer(customer)})


@takhfid_api_bp.get("/api/v4/auth/me")
def auth_me():
    customer = require_customer()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    return jsonify({"success": True, "user": public_customer(customer)})


@takhfid_api_bp.post("/api/v4/auth/complete-profile")
def complete_profile():
    customer = require_customer()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    payload = request.get_json(silent=True) or {}
    first_name = str(payload.get("firstName") or "").strip()
    governorate = str(payload.get("governorate") or "").strip()
    if not first_name or not governorate:
        return jsonify({"success": False, "error": "الاسم والمحافظة مطلوبان"}), 400
    customer.first_name = first_name
    customer.second_name = str(payload.get("secondName") or "").strip() or None
    customer.third_name = str(payload.get("thirdName") or "").strip() or None
    customer.last_name = str(payload.get("lastName") or "").strip() or None
    customer.governorate = governorate
    customer.updated_at = utcnow()
    db.session.commit()
    return jsonify({"success": True, "user": public_customer(customer)})


@takhfid_api_bp.post("/api/v4/auth/logout")
def auth_logout():
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        raw = header[7:].strip()
        token = TakhfidAccessToken.query.filter_by(token_hash=token_hash(raw), revoked_at=None).first()
        if token:
            token.revoked_at = utcnow()
            db.session.commit()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Customer chat/media
# ---------------------------------------------------------------------------

@takhfid_api_bp.get("/api/v4/chat/sessions")
def chat_sessions():
    customer = require_customer()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    rows = (
        TakhfidChatSession.query
        .filter_by(customer_id=customer.uid)
        .order_by(TakhfidChatSession.updated_at.desc())
        .limit(50)
        .all()
    )
    return jsonify({
        "success": True,
        "sessions": [public_chat_session(x) for x in rows],
    })


@takhfid_api_bp.post("/api/v4/chat/sessions")
def chat_session_create():
    customer = require_customer()
    if not isinstance(customer, TakhfidCustomer):
        return customer

    payload = request.get_json(silent=True) or {}
    order_id = str(payload.get("orderId") or "").strip() or None
    if order_id:
        order = db.session.get(TakhfidOrder, order_id)
        if not order or order.customer_id != customer.uid:
            return jsonify({"success": False, "error": "الطلب غير موجود أو غير مصرح"}), 403

    title = "محادثة الطلب " + order_id if order_id else "دعم العملاء"
    row = ensure_chat_session(
        customer_id=customer.uid,
        order_id=order_id,
        title=title,
    )
    db.session.commit()
    return jsonify({"success": True, "session": public_chat_session(row)}), 201


@takhfid_api_bp.get("/api/v4/chat/sessions/<session_id>/messages")
def chat_messages(session_id: str):
    customer = require_customer()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    row = _owned_chat_session(session_id, customer)
    if not row:
        return jsonify({"success": False, "error": "المحادثة غير موجودة أو غير مصرح"}), 403

    query = TakhfidChatMessage.query.filter_by(session_id=row.id)
    since = _parse_since(request.args.get("since"))
    if since:
        query = query.filter(TakhfidChatMessage.created_at > since)

    limit = max(1, min(200, parse_int(request.args.get("limit"), 100)))
    offset = max(0, parse_int(request.args.get("offset"), 0))
    messages = (
        query.order_by(TakhfidChatMessage.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return jsonify({
        "success": True,
        "session": public_chat_session(row),
        "messages": [public_chat_message(x) for x in messages],
    })


@takhfid_api_bp.post("/api/v4/chat/sessions/<session_id>/messages")
def chat_send_message(session_id: str):
    customer = require_customer()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    row = _owned_chat_session(session_id, customer)
    if not row:
        return jsonify({"success": False, "error": "المحادثة غير موجودة أو غير مصرح"}), 403
    if row.status != "open":
        return jsonify({"success": False, "error": "المحادثة مغلقة"}), 409

    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text") or "").strip()
    media_url = str(payload.get("mediaUrl") or "").strip() or None
    media_type = str(payload.get("mediaType") or "").strip() or None
    file_name = str(payload.get("fileName") or "").strip() or None
    is_payment_proof = bool(payload.get("isPaymentProof", False))

    if not text and not media_url:
        return jsonify({"success": False, "error": "الرسالة فارغة"}), 400

    if media_url and not media_url.startswith("/takhfid/api/v4/chat/media/"):
        return jsonify({"success": False, "error": "رابط المرفق غير صالح"}), 400

    if is_payment_proof and not row.order_id:
        return jsonify({"success": False, "error": "سند الدفع يجب أن يرتبط بطلب"}), 400

    now = utcnow()
    message = TakhfidChatMessage(
        id="msg-c-" + secrets.token_hex(10),
        session_id=row.id,
        customer_id=customer.uid,
        sender="customer",
        text=text,
        media_url=media_url,
        media_type=media_type,
        file_name=file_name,
        is_payment_proof=is_payment_proof,
        order_id=row.order_id,
        created_at=now,
    )
    db.session.add(message)
    row.last_message = text or "مرفق 📎"
    row.last_message_at = now
    row.updated_at = now
    row.unread_by_admin += 1
    db.session.commit()

    return jsonify({
        "success": True,
        "message": public_chat_message(message),
        "session": public_chat_session(row),
    }), 201


@takhfid_api_bp.patch("/api/v4/chat/sessions/<session_id>/read")
def chat_mark_read(session_id: str):
    customer = require_customer()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    row = _owned_chat_session(session_id, customer)
    if not row:
        return jsonify({"success": False, "error": "المحادثة غير موجودة أو غير مصرح"}), 403
    row.unread_by_customer = 0
    db.session.query(TakhfidChatMessage).filter_by(
        session_id=row.id,
        sender="admin",
    ).update({"read_by_customer": True}, synchronize_session=False)
    db.session.commit()
    return jsonify({"success": True, "session": public_chat_session(row)})


@takhfid_api_bp.post("/api/v4/chat/sessions/<session_id>/media/upload")
def chat_upload_media(session_id: str):
    customer = require_customer()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    row = _owned_chat_session(session_id, customer)
    if not row:
        return jsonify({"success": False, "error": "المحادثة غير موجودة أو غير مصرح"}), 403

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"success": False, "error": "الصورة مطلوبة"}), 400

    filename = secure_filename(upload.filename)
    ext = Path(filename).suffix.lower()
    if ext not in CHAT_IMAGE_EXTENSIONS:
        return jsonify({"success": False, "error": "صيغة الصورة غير مدعومة"}), 400

    upload.seek(0, os.SEEK_END)
    size = upload.tell()
    upload.seek(0)
    if size > CHAT_MAX_IMAGE_SIZE:
        return jsonify({"success": False, "error": "حجم الصورة يتجاوز 8MB"}), 400

    final_name = secrets.token_urlsafe(16).replace("-", "_") + ext
    upload.save(chat_media_root(row.id) / final_name)
    relative = (
        "/takhfid/api/v4/chat/media/"
        + secure_filename(row.id)
        + "/"
        + final_name
    )
    db.session.commit()
    return jsonify({
        "success": True,
        "relativeUrl": relative,
        "url": current_app.config["APP_BASE_URL"].rstrip("/") + relative,
        "mediaType": upload.mimetype or "image/*",
        "fileName": filename,
    }), 201


@takhfid_api_bp.get("/api/v4/chat/media/<session_id>/<filename>")
def chat_media(session_id: str, filename: str):
    customer = current_customer()
    if not customer:
        return jsonify({"success": False, "error": "تسجيل الدخول مطلوب"}), 401
    row = _admin_or_owner_chat_session(session_id, customer)
    if not row:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    safe_name = secure_filename(filename)
    if safe_name != filename:
        return jsonify({"success": False, "error": "اسم ملف غير صالح"}), 400
    return send_from_directory(
        chat_media_root(row.id),
        safe_name,
        max_age=60 * 60 * 24 * 7,
    )


# ---------------------------------------------------------------------------
# Customer notifications
# ---------------------------------------------------------------------------

@takhfid_api_bp.get("/api/v4/notifications")
def customer_notifications():
    customer = require_customer()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    limit = max(1, min(100, parse_int(request.args.get("limit"), 50)))
    offset = max(0, parse_int(request.args.get("offset"), 0))
    rows = (
        TakhfidCustomerNotification.query
        .filter_by(customer_id=customer.uid)
        .order_by(TakhfidCustomerNotification.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    unread = (
        TakhfidCustomerNotification.query
        .filter_by(customer_id=customer.uid, read=False)
        .count()
    )
    return jsonify({
        "success": True,
        "notifications": [public_notification(x) for x in rows],
        "unreadCount": unread,
    })


@takhfid_api_bp.patch("/api/v4/notifications/<int:notification_id>/read")
def customer_notification_read(notification_id: int):
    customer = require_customer()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    row = db.session.get(TakhfidCustomerNotification, notification_id)
    if not row or row.customer_id != customer.uid:
        return jsonify({"success": False, "error": "الإشعار غير موجود"}), 404
    row.read = True
    db.session.commit()
    return jsonify({"success": True, "notification": public_notification(row)})


@takhfid_api_bp.post("/api/v4/notifications/read-all")
def customer_notifications_read_all():
    customer = require_customer()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    TakhfidCustomerNotification.query.filter_by(
        customer_id=customer.uid,
        read=False,
    ).update({"read": True}, synchronize_session=False)
    db.session.commit()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Admin chat API
# ---------------------------------------------------------------------------

@takhfid_api_bp.get("/api/v4/admin/chat/sessions")
def admin_chat_sessions():
    customer = require_admin()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    rows = (
        TakhfidChatSession.query
        .order_by(TakhfidChatSession.updated_at.desc())
        .limit(200)
        .all()
    )
    return jsonify({
        "success": True,
        "sessions": [public_chat_session(x) for x in rows],
    })


@takhfid_api_bp.get("/api/v4/admin/chat/sessions/<session_id>/messages")
def admin_chat_messages(session_id: str):
    customer = require_admin()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    row = db.session.get(TakhfidChatSession, session_id)
    if not row:
        return jsonify({"success": False, "error": "المحادثة غير موجودة"}), 404
    limit = max(1, min(200, parse_int(request.args.get("limit"), 100)))
    messages = (
        TakhfidChatMessage.query
        .filter_by(session_id=row.id)
        .order_by(TakhfidChatMessage.created_at.asc())
        .limit(limit)
        .all()
    )
    row.unread_by_admin = 0
    db.session.commit()
    return jsonify({
        "success": True,
        "session": public_chat_session(row),
        "messages": [public_chat_message(x) for x in messages],
    })


@takhfid_api_bp.post("/api/v4/admin/chat/sessions/<session_id>/messages")
def admin_chat_send_message(session_id: str):
    customer = require_admin()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    row = db.session.get(TakhfidChatSession, session_id)
    if not row:
        return jsonify({"success": False, "error": "المحادثة غير موجودة"}), 404
    if row.status != "open":
        return jsonify({"success": False, "error": "المحادثة مغلقة"}), 409

    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text") or "").strip()
    media_url = str(payload.get("mediaUrl") or "").strip() or None
    media_type = str(payload.get("mediaType") or "").strip() or None
    file_name = str(payload.get("fileName") or "").strip() or None
    if not text and not media_url:
        return jsonify({"success": False, "error": "الرسالة فارغة"}), 400

    now = utcnow()
    message = TakhfidChatMessage(
        id="msg-a-" + secrets.token_hex(10),
        session_id=row.id,
        customer_id=row.customer_id,
        sender="admin",
        text=text,
        media_url=media_url,
        media_type=media_type,
        file_name=file_name,
        order_id=row.order_id,
        created_at=now,
    )
    db.session.add(message)
    row.last_message = text or "مرفق 📎"
    row.last_message_at = now
    row.updated_at = now
    row.unread_by_customer += 1

    customer_row = TakhfidCustomer.query.filter_by(uid=row.customer_id).first()
    if customer_row:
        customer_notification(
            customer_row.uid,
            "رسالة جديدة",
            text or "أرسل الدعم مرفقًا جديدًا",
            type="chat",
            order_id=row.order_id,
            chat_session_id=row.id,
            data={"sessionId": row.id, "orderId": row.order_id},
        )
    db.session.commit()

    return jsonify({
        "success": True,
        "message": public_chat_message(message),
        "session": public_chat_session(row),
    }), 201


# ---------------------------------------------------------------------------
# Admin catalog/content/settings API
# ---------------------------------------------------------------------------

@takhfid_api_bp.post("/api/v4/admin/products")
def admin_create_product():
    customer = require_admin()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    payload = request.get_json(silent=True) or {}
    product_id = str(payload.get("id") or f"p-{secrets.token_hex(6)}").strip()
    try:
        data = normalize_product_payload(payload, product_id)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    row = db.session.get(TakhfidProduct, product_id)
    if row:
        data["createdAt"] = (row.payload or {}).get("createdAt") or row.created_at.isoformat()
        row.payload = data
        row.updated_at = utcnow()
    else:
        row = TakhfidProduct(id=product_id, payload=data)
        db.session.add(row)
    audit("takhfid.product.saved", product_id)
    db.session.commit()
    return jsonify({"success": True, "product": product_data(row)}), 201 if row.created_at == row.updated_at else 200


@takhfid_api_bp.put("/api/v4/admin/products/<product_id>")
def admin_update_product(product_id: str):
    customer = require_admin()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    row = db.session.get(TakhfidProduct, product_id)
    if not row:
        return jsonify({"success": False, "error": "المنتج غير موجود"}), 404
    payload = dict(row.payload or {})
    incoming = request.get_json(silent=True) or {}
    payload.update(incoming)
    try:
        data = normalize_product_payload(payload, product_id)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    data["createdAt"] = payload.get("createdAt") or row.created_at.isoformat()
    row.payload = data
    row.updated_at = utcnow()
    audit("takhfid.product.updated", product_id)
    db.session.commit()
    return jsonify({"success": True, "product": product_data(row)})


@takhfid_api_bp.delete("/api/v4/admin/products/<product_id>")
def admin_delete_product(product_id: str):
    customer = require_admin()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    row = db.session.get(TakhfidProduct, product_id)
    if not row:
        return jsonify({"success": False, "error": "المنتج غير موجود"}), 404
    db.session.delete(row)
    audit("takhfid.product.deleted", product_id)
    db.session.commit()
    return jsonify({"success": True, "deletedId": product_id})


@takhfid_api_bp.post("/api/v4/admin/products/bulk")
def admin_bulk_products():
    customer = require_admin()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    payload = request.get_json(silent=True) or {}
    products = payload.get("products")
    if not isinstance(products, list):
        return jsonify({"success": False, "error": "products يجب أن تكون مصفوفة"}), 400
    changed = 0
    for item in products:
        if not isinstance(item, dict):
            continue
        product_id = str(item.get("id") or f"p-{secrets.token_hex(6)}")
        data = normalize_product_payload(item, product_id)
        row = db.session.get(TakhfidProduct, product_id)
        if row:
            row.payload = data
            row.updated_at = utcnow()
        else:
            db.session.add(TakhfidProduct(id=product_id, payload=data))
        changed += 1
    audit("takhfid.products.bulk", str(changed))
    db.session.commit()
    return jsonify({"success": True, "count": changed})


@takhfid_api_bp.put("/api/v4/admin/store/settings")
def admin_store_settings():
    customer = require_admin()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    payload = request.get_json(silent=True) or {}
    allowed = {"store", "checkout", "shipping", "payments", "catalog", "content"}
    for key, value in payload.items():
        if key in allowed and isinstance(value, (dict, list)):
            save_json_setting(key, value)
    audit("takhfid.store.settings", "updated")
    db.session.commit()
    return get_store()


@takhfid_api_bp.put("/api/v4/admin/content")
def admin_content():
    customer = require_admin()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    payload = request.get_json(silent=True) or {}
    content = json_setting("content", PUBLIC_SETTING_DEFAULTS["content"])
    if not isinstance(content, dict):
        content = dict(PUBLIC_SETTING_DEFAULTS["content"])
    for key in ("banners", "campaigns", "categories", "announcements"):
        if key in payload:
            if not isinstance(payload[key], list):
                return jsonify({"success": False, "error": f"{key} يجب أن تكون مصفوفة"}), 400
            content[key] = payload[key]
    save_json_setting("content", content)
    audit("takhfid.content.updated", ",".join(payload.keys()))
    db.session.commit()
    return jsonify({"success": True, "content": content})


@takhfid_api_bp.put("/api/v4/admin/pricing/<path:governorate>")
def admin_pricing(governorate: str):
    customer = require_admin()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    if governorate not in GOVERNORATES:
        return jsonify({"success": False, "error": "المحافظة غير معروفة"}), 404
    payload = request.get_json(silent=True) or {}
    current = dict(build_pricing()[governorate])
    current.update(payload)
    save_json_setting(f"pricing:{governorate}", current)
    audit("takhfid.pricing.updated", governorate)
    db.session.commit()
    return jsonify({"success": True, "governorate": governorate, "pricing": current})


# ---------------------------------------------------------------------------
# Orders: guest checkout + authenticated customer + admin lifecycle
# ---------------------------------------------------------------------------

def build_order(payload: dict[str, Any], customer: TakhfidCustomer | None) -> tuple[dict[str, Any], str]:
    items = payload.get("items")
    if not isinstance(items, list) or not items or len(items) > 100:
        raise ValueError("السلة غير صالحة")
    customer_name = str(payload.get("customerName") or (customer.first_name if customer else "") or "عميل المتجر").strip()
    phone = normalize_phone(payload.get("customerPhone") or (customer.phone if customer else ""))
    if not phone or len(phone) < 8:
        raise ValueError("رقم العميل مطلوب")
    governorate = str(payload.get("governorate") or (customer.governorate if customer else "أمانة العاصمة")).strip()
    currency = str(payload.get("currency") or "YER").upper()
    if currency not in {"YER", "SAR"}:
        currency = "YER"
    payment_method = str(payload.get("paymentMethod") or "cash_on_delivery")
    payments = json_setting("payments", PUBLIC_SETTING_DEFAULTS["payments"])
    if payment_method not in ALLOWED_PAYMENT_METHODS or not bool(payments.get(payment_method, False)):
        if payment_method != "cash_on_delivery" or not bool(payments.get("cash_on_delivery", True)):
            raise ValueError("طريقة الدفع غير متاحة")
    rate = build_pricing().get(governorate, GOVERNORATES["أمانة العاصمة"])
    order_items: list[dict[str, Any]] = []
    subtotal = 0.0
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        product_id = str(raw_item.get("productId") or raw_item.get("id") or "").strip()
        product = db.session.get(TakhfidProduct, product_id)
        if not product:
            raise LookupError(f"المنتج غير موجود: {product_id}")
        data = product_data(product)
        quantity = max(1, min(99, parse_int(raw_item.get("quantity"), 1)))
        stock = parse_int(data.get("stock"))
        if not bool(data.get("allowBackorder", False)) and stock < quantity:
            raise ValueError(f"الكمية غير متوفرة للمنتج: {data.get('name') or product_id}")
        source_currency = str(data.get("currency") or "YER").upper()
        unit_source_price = select_unit_price(data, raw_item)
        unit_price = convert_amount(unit_source_price, source_currency, currency, rate)
        line_total = round(unit_price * quantity, 2)
        subtotal += line_total
        order_items.append({
            "productId": product_id,
            "productName": str(data.get("name") or "منتج"),
            "sku": str(data.get("sku") or ""),
            "quantity": quantity,
            "unitPrice": round(unit_price, 2),
            "lineTotal": line_total,
            "currency": currency,
            "image": str(data.get("image") or ""),
            "size": raw_item.get("size"),
            "color": raw_item.get("color"),
            "variantId": raw_item.get("variantId"),
        })
    discount = max(0.0, parse_float(payload.get("discount")))
    if discount > subtotal:
        discount = subtotal
    shipping = parse_float(payload.get("shippingFee"), parse_float(rate.get("deliveryFee")))
    shipping_cfg = json_setting("shipping", PUBLIC_SETTING_DEFAULTS["shipping"])
    if shipping_cfg.get("freeAbove") and subtotal >= parse_float(shipping_cfg.get("freeAbove")):
        shipping = 0
    if currency == "SAR":
        shipping = round(shipping / max(parse_float(rate.get("sarToYerRate"), 140), 1), 2)
    total = round(max(0, subtotal - discount + shipping), 2)
    checkout = json_setting("checkout", PUBLIC_SETTING_DEFAULTS["checkout"])
    if total < parse_float(checkout.get("minimumOrder"), 0):
        raise ValueError("قيمة الطلب أقل من الحد الأدنى")
    order_id = str(payload.get("orderId") or payload.get("id") or generate_order_id()).strip()
    private_token = secrets.token_urlsafe(24)
    customer_id = customer.uid if customer else f"guest_{secrets.token_hex(8)}"
    now = utcnow().isoformat()
    order = {
        "id": order_id,
        "orderId": order_id,
        "customerName": customer_name,
        "customerPhone": phone,
        "governorate": governorate,
        "address": str(payload.get("address") or "").strip(),
        "deliveryNotes": str(payload.get("deliveryNotes") or "").strip(),
        "currency": currency,
        "paymentMethod": payment_method,
        "subtotal": round(subtotal, 2),
        "discount": round(discount, 2),
        "shippingFee": round(shipping, 2),
        "totalAmount": total,
        "total": total,
        "items": order_items,
        "status": "pending",
        "isPaid": False,
        "paymentReference": str(payload.get("paymentReference") or "").strip(),
        "createdAt": now,
        "updatedAt": now,
        "pricingRegion": rate.get("region"),
        "exchangeRateSarToYer": rate.get("sarToYerRate"),
        "exchangeRateUsdToYer": rate.get("usdToYerRate"),
        "privateAccessToken": private_token,
    }
    return order, customer_id


@takhfid_api_bp.post("/api/v4/orders")
def create_order():
    payload = request.get_json(silent=True) or {}
    customer = current_customer()
    try:
        order, customer_id = build_order(payload, customer)
    except LookupError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (ValueError, TypeError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    if db.session.get(TakhfidOrder, order["id"]):
        return jsonify({"success": False, "error": "رقم الطلب مستخدم بالفعل"}), 409
    row = TakhfidOrder(id=order["id"], customer_id=customer_id, payload=order, status="pending")
    db.session.add(row)
    # Decrement stock atomically at the database transaction level for each line.
    for line in order["items"]:
        product = db.session.get(TakhfidProduct, line["productId"])
        if not product:
            db.session.rollback()
            return jsonify({"success": False, "error": "المنتج غير موجود"}), 404
        data = dict(product.payload or {})
        if not bool(data.get("allowBackorder", False)):
            data["stock"] = max(0, parse_int(data.get("stock")) - parse_int(line["quantity"], 1))
            product.payload = data
            product.updated_at = utcnow()
    audit("takhfid.order.created", order["id"])
    chat_id = None
    if not str(customer_id).startswith("guest_"):
        chat_row = ensure_chat_session(
            customer_id=customer_id,
            order_id=row.id,
            title="محادثة الطلب " + row.id,
        )
        chat_id = chat_row.id
        customer_notification(
            customer_id,
            "تم استلام طلبك",
            "تم إنشاء الطلب " + row.id + " بنجاح.",
            type="order",
            order_id=row.id,
            chat_session_id=chat_row.id,
            data={"orderId": row.id, "sessionId": chat_row.id},
        )
    db.session.commit()
    safe_order = public_order(row)
    return jsonify({
        "success": True,
        "order": safe_order,
        "orderId": row.id,
        "accessToken": order["privateAccessToken"],
        "chatSessionId": chat_id,
    }), 201


@takhfid_api_bp.get("/api/v4/orders")
def list_orders():
    customer = current_customer()
    if not customer:
        return jsonify({"success": False, "error": "تسجيل الدخول مطلوب"}), 401
    query = TakhfidOrder.query
    if not customer.is_admin:
        query = query.filter_by(customer_id=customer.uid)
    status = str(request.args.get("status") or "").strip()
    q = str(request.args.get("q") or "").strip()
    if status and status in ALLOWED_ORDER_STATUSES:
        query = query.filter_by(status=status)
    rows = query.order_by(TakhfidOrder.created_at.desc()).all()
    if q:
        rows = [r for r in rows if q.casefold() in r.id.casefold() or q.casefold() in str((r.payload or {}).get("customerPhone") or "").casefold() or q.casefold() in str((r.payload or {}).get("customerName") or "").casefold()]
    limit = max(1, min(100, parse_int(request.args.get("limit"), 50)))
    offset = max(0, parse_int(request.args.get("offset"), 0))
    page = rows[offset: offset + limit]
    return jsonify({"success": True, "orders": [public_order(r) for r in page], "total": len(rows), "limit": limit, "offset": offset})


def can_access_order(row: TakhfidOrder, customer: TakhfidCustomer | None, access_token: str) -> bool:
    if customer and (customer.is_admin or row.customer_id == customer.uid):
        return True
    stored = str((row.payload or {}).get("privateAccessToken") or "")
    return bool(access_token and stored and hmac.compare_digest(access_token, stored))


@takhfid_api_bp.get("/api/v4/orders/<order_id>")
def get_order(order_id: str):
    row = db.session.get(TakhfidOrder, order_id)
    if not row:
        return jsonify({"success": False, "error": "الطلب غير موجود"}), 404
    customer = current_customer()
    access_token = str(request.args.get("accessToken") or request.headers.get("X-Order-Access-Token") or "")
    if not can_access_order(row, customer, access_token):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    return jsonify({"success": True, "order": public_order(row)})


@takhfid_api_bp.patch("/api/v4/orders/<order_id>/status")
def update_order_status(order_id: str):
    customer = require_admin()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    row = db.session.get(TakhfidOrder, order_id)
    if not row:
        return jsonify({"success": False, "error": "الطلب غير موجود"}), 404
    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status") or "").strip()
    if status not in ALLOWED_ORDER_STATUSES:
        return jsonify({"success": False, "error": "حالة الطلب غير صالحة"}), 400
    data = dict(row.payload or {})
    data["status"] = status
    if isinstance(payload.get("isPaid"), bool):
        data["isPaid"] = payload["isPaid"]
        if payload["isPaid"]:
            data["paymentConfirmedAt"] = utcnow().isoformat()
    if payload.get("paymentReference") is not None:
        data["paymentReference"] = str(payload.get("paymentReference") or "").strip()
    data["updatedAt"] = utcnow().isoformat()
    row.payload = data
    row.status = status
    row.updated_at = utcnow()
    audit("takhfid.order.status", f"{order_id}:{status}")
    if not str(row.customer_id).startswith("guest_"):
        customer_notification(
            row.customer_id,
            "تحديث حالة طلبك",
            "تم تحديث حالة الطلب " + order_id + " إلى " + status + ".",
            type="order_status",
            order_id=order_id,
            chat_session_id=chat_session_id(row.customer_id, order_id),
            data={"orderId": order_id, "status": status},
        )
    db.session.commit()
    return jsonify({"success": True, "order": public_order(row)})


@takhfid_api_bp.patch("/api/v4/orders/<order_id>/payment")
def update_order_payment(order_id: str):
    customer = require_admin()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    row = db.session.get(TakhfidOrder, order_id)
    if not row:
        return jsonify({"success": False, "error": "الطلب غير موجود"}), 404
    payload = request.get_json(silent=True) or {}
    is_paid = payload.get("isPaid")
    if not isinstance(is_paid, bool):
        return jsonify({"success": False, "error": "isPaid يجب أن تكون true أو false"}), 400
    data = dict(row.payload or {})
    data["isPaid"] = is_paid
    data["paymentReference"] = str(payload.get("paymentReference") or data.get("paymentReference") or "").strip()
    data["updatedAt"] = utcnow().isoformat()
    if is_paid:
        data["paymentConfirmedAt"] = utcnow().isoformat()
    row.payload = data
    row.updated_at = utcnow()
    audit("takhfid.order.payment", order_id)
    if not str(row.customer_id).startswith("guest_"):
        customer_notification(
            row.customer_id,
            "تحديث الدفع",
            "تم تحديث حالة الدفع للطلب " + order_id + ".",
            type="payment",
            order_id=order_id,
            chat_session_id=chat_session_id(row.customer_id, order_id),
            data={"orderId": order_id, "isPaid": is_paid},
        )
    db.session.commit()
    return jsonify({"success": True, "order": public_order(row)})


# ---------------------------------------------------------------------------
# Media upload + admin file serving
# ---------------------------------------------------------------------------

MEDIA_KINDS = {"products", "banners", "campaigns", "categories", "general"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGE_SIZE = 8 * 1024 * 1024


def media_root() -> Path:
    root = Path(current_app.instance_path) / "takhfid_uploads" / "media"
    for kind in MEDIA_KINDS:
        (root / kind).mkdir(parents=True, exist_ok=True)
    return root


@takhfid_api_bp.post("/api/v4/admin/media/upload")
def upload_media():
    customer = require_admin()
    if not isinstance(customer, TakhfidCustomer):
        return customer
    kind = str(request.form.get("kind") or "general").strip()
    upload = request.files.get("file")
    if kind not in MEDIA_KINDS or not upload or not upload.filename:
        return jsonify({"success": False, "error": "ملف أو نوع وسائط غير صالح"}), 400
    filename = secure_filename(upload.filename)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({"success": False, "error": "صيغة الصورة غير مدعومة"}), 400
    upload.seek(0, os.SEEK_END)
    size = upload.tell()
    upload.seek(0)
    if size > MAX_IMAGE_SIZE:
        return jsonify({"success": False, "error": "حجم الصورة يتجاوز 8MB"}), 400
    final_name = f"{secrets.token_urlsafe(12).replace('-', '_')}{ext}"
    upload.save(media_root() / kind / final_name)
    url = request.host_url.rstrip("/") + f"/takhfid/media/{kind}/{final_name}"
    audit("takhfid.media.uploaded", url)
    db.session.commit()
    return jsonify({"success": True, "url": url, "kind": kind}), 201


@takhfid_api_bp.get("/media/<path:filename>")
def media_file(filename: str):
    return send_from_directory(media_root(), filename, max_age=60 * 60 * 24 * 30)


# ---------------------------------------------------------------------------
# Seed defaults
# ---------------------------------------------------------------------------

def seed_takhfid_defaults(app) -> None:
    with app.app_context():
        for key, value in PUBLIC_SETTING_DEFAULTS.items():
            if not TakhfidSetting.query.filter_by(key=key).first():
                save_json_setting(key, value)
        if not TakhfidSetting.query.filter_by(key="admin_phones").first():
            save_setting("admin_phones", os.getenv("TAKHFIID_ADMIN_PHONES", ""))
        if not TakhfidSetting.query.filter_by(key="otp_hash_secret").first() and (os.getenv("TAKHFIID_OTP_HASH_SECRET") or os.getenv("OTP_HASH_SECRET")):
            save_setting("otp_hash_secret", os.getenv("TAKHFIID_OTP_HASH_SECRET") or os.getenv("OTP_HASH_SECRET"), secret=True)
        db.session.commit()
