from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from . import db
from .models import AuditLog
from .takhfid import TakhfidSetting, _admin_user, _public_pricing, _set_setting
from .takhfid_v2 import TakhfidCustomer, TakhfidProduct, _current_customer, _require_admin, _public_customer
from .takhfid_orders_v2 import TakhfidOrder, _public_order
from .takhfid_chat_v2 import TakhfidChatMessage, _public_message


takhfid_admin_v2_bp = Blueprint("takhfid_admin_v2", __name__, url_prefix="/takhfid/admin")

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGE_SIZE = 8 * 1024 * 1024
MEDIA_SUBDIRS = {"products", "banners", "campaigns", "categories", "general"}


def _guard():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if not _admin_user():
        return ("غير مصرح", 403)
    return None


def _api_guard():
    customer = _require_admin()
    return None if not isinstance(customer, tuple) else customer


def _setting_json(key: str, default: Any):
    row = TakhfidSetting.query.filter_by(key=key).first()
    if not row or not row.value:
        return default
    try:
        return json.loads(row.value)
    except (TypeError, ValueError):
        return default


def _current_customer_id() -> int | None:
    customer = _current_customer()
    return customer.id if customer else None


def _media_root() -> Path:
    root = Path(current_app.instance_path) / "takhfid_uploads" / "media"
    root.mkdir(parents=True, exist_ok=True)
    for name in MEDIA_SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _save_image(upload, kind: str) -> str:
    if kind not in MEDIA_SUBDIRS:
        raise ValueError("نوع الصورة غير صالح")
    if not upload or not upload.filename:
        raise ValueError("الصورة مطلوبة")
    filename = secure_filename(upload.filename)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("صيغة الصورة غير مدعومة")
    upload.seek(0, os.SEEK_END)
    size = upload.tell()
    upload.seek(0)
    if size > MAX_IMAGE_SIZE:
        raise ValueError("حجم الصورة يتجاوز 8MB")
    stem = secrets.token_urlsafe(12).replace("-", "_")
    final_name = f"{stem}{ext}"
    upload.save(_media_root() / kind / final_name)
    return url_for("takhfid_admin_v2.media_file", filename=f"{kind}/{final_name}", _external=True)


@takhfid_admin_v2_bp.get("/media/<path:filename>")
def media_file(filename: str):
    # Product/content images are public because the storefront must be able to display them.
    return send_from_directory(_media_root(), filename, max_age=60 * 60 * 24 * 30)


@takhfid_admin_v2_bp.get("/")
@login_required
def dashboard():
    guard = _guard()
    if guard:
        return guard
    recent_orders = TakhfidOrder.query.order_by(TakhfidOrder.created_at.desc()).limit(8).all()
    return render_template(
        "takhfid_admin/dashboard.html",
        title="إدارة التخفيض",
        stats={
            "customers": TakhfidCustomer.query.count(),
            "products": TakhfidProduct.query.count(),
            "orders": TakhfidOrder.query.count(),
            "pending": TakhfidOrder.query.filter(TakhfidOrder.status.in_(["awaiting_payment", "payment_submitted", "preparing", "in_shipping"])).count(),
        },
        recent_orders=[_public_order(x) for x in recent_orders],
    )


@takhfid_admin_v2_bp.route("/products", methods=["GET", "POST"])
@login_required
def products():
    guard = _guard()
    if guard:
        return guard
    if request.method == "POST":
        payload = dict(request.form)
        product_id = str(payload.pop("id", "")).strip()
        name = str(payload.get("name", "")).strip()
        if not product_id or not name:
            flash("معرف المنتج والاسم مطلوبان.", "danger")
            return redirect(url_for("takhfid_admin_v2.products"))
        payload["name"] = name
        for key in ("price", "discountPrice", "originalPrice"):
            if key in payload and payload[key] != "":
                try:
                    payload[key] = float(payload[key])
                except ValueError:
                    flash(f"قيمة {key} غير صالحة.", "danger")
                    return redirect(url_for("takhfid_admin_v2.products"))
        extra = payload.pop("extra", "").strip()
        if extra:
            try:
                payload.update(json.loads(extra))
            except ValueError:
                flash("البيانات الإضافية ليست JSON صحيحة.", "danger")
                return redirect(url_for("takhfid_admin_v2.products"))
        image = request.files.get("image")
        if image and image.filename:
            try:
                payload["image"] = _save_image(image, "products")
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("takhfid_admin_v2.products"))
        row = db.session.get(TakhfidProduct, product_id)
        if row:
            old = dict(row.payload or {})
            if "image" not in payload and old.get("image"):
                payload["image"] = old["image"]
            row.payload = payload
            row.updated_at = datetime.now(timezone.utc)
        else:
            row = TakhfidProduct(id=product_id, payload=payload)
            db.session.add(row)
        db.session.add(AuditLog(user_id=current_user.id, action="takhfid.product.saved", details=product_id))
        db.session.commit()
        flash("تم حفظ المنتج.", "success")
        return redirect(url_for("takhfid_admin_v2.products"))
    rows = TakhfidProduct.query.order_by(TakhfidProduct.updated_at.desc()).all()
    return render_template("takhfid_admin/products.html", products=[dict(x.payload or {}, id=x.id) for x in rows])


@takhfid_admin_v2_bp.post("/products/<product_id>/delete")
@login_required
def product_delete(product_id: str):
    guard = _guard()
    if guard:
        return guard
    row = db.session.get(TakhfidProduct, product_id)
    if row:
        db.session.delete(row)
        db.session.add(AuditLog(user_id=current_user.id, action="takhfid.product.deleted", details=product_id))
        db.session.commit()
        flash("تم حذف المنتج.", "success")
    return redirect(url_for("takhfid_admin_v2.products"))


@takhfid_admin_v2_bp.get("/customers")
@login_required
def customers():
    guard = _guard()
    if guard:
        return guard
    rows = TakhfidCustomer.query.order_by(TakhfidCustomer.created_at.desc()).all()
    return render_template("takhfid_admin/customers.html", customers=[_public_customer(x) for x in rows])


@takhfid_admin_v2_bp.post("/customers/<uid>/delete")
@login_required
def customer_delete(uid: str):
    guard = _guard()
    if guard:
        return guard
    row = TakhfidCustomer.query.filter_by(uid=uid).first()
    if row and row.id == _current_customer_id():
        flash("لا يمكن حذف حساب المدير الحالي.", "danger")
    elif row:
        db.session.delete(row)
        db.session.add(AuditLog(user_id=current_user.id, action="takhfid.customer.deleted", details=uid))
        db.session.commit()
        flash("تم حذف العميل.", "success")
    return redirect(url_for("takhfid_admin_v2.customers"))


@takhfid_admin_v2_bp.get("/orders")
@login_required
def orders():
    guard = _guard()
    if guard:
        return guard
    rows = TakhfidOrder.query.order_by(TakhfidOrder.created_at.desc()).all()
    return render_template("takhfid_admin/orders.html", orders=[_public_order(x) for x in rows])


@takhfid_admin_v2_bp.post("/orders/<order_id>/status")
@login_required
def order_status(order_id: str):
    guard = _guard()
    if guard:
        return guard
    row = db.session.get(TakhfidOrder, order_id)
    if not row:
        flash("الطلب غير موجود.", "danger")
        return redirect(url_for("takhfid_admin_v2.orders"))
    status = str(request.form.get("status") or "").strip()
    allowed = {"awaiting_payment", "payment_submitted", "preparing", "in_shipping", "delivered", "cancelled"}
    if status not in allowed:
        flash("حالة غير صالحة.", "danger")
        return redirect(url_for("takhfid_admin_v2.orders"))
    data = dict(row.payload or {})
    data["status"] = status
    if request.form.get("is_paid") == "1":
        data["isPaid"] = True
        data["paymentConfirmedAt"] = datetime.now(timezone.utc).isoformat()
    data["updatedAt"] = datetime.now(timezone.utc).isoformat()
    row.payload = data
    row.status = status
    row.updated_at = datetime.now(timezone.utc)
    db.session.add(AuditLog(user_id=current_user.id, action="takhfid.order.status", details=f"{order_id}:{status}"))
    db.session.commit()
    flash("تم تحديث حالة الطلب.", "success")
    return redirect(url_for("takhfid_admin_v2.orders"))


@takhfid_admin_v2_bp.get("/chats/<order_id>")
@login_required
def chat(order_id: str):
    guard = _guard()
    if guard:
        return guard
    order = db.session.get(TakhfidOrder, order_id)
    if not order:
        return ("الطلب غير موجود", 404)
    rows = TakhfidChatMessage.query.filter_by(order_id=order_id).order_by(TakhfidChatMessage.created_at.asc()).limit(300).all()
    return render_template("takhfid_admin/chat.html", order=_public_order(order), messages=[_public_message(x) for x in rows])


@takhfid_admin_v2_bp.get("/settings")
@login_required
def settings():
    guard = _guard()
    if guard:
        return guard
    integration = {
        "whatsappSession": (TakhfidSetting.query.filter_by(key="whatsapp_session").first().value if TakhfidSetting.query.filter_by(key="whatsapp_session").first() else "basheer"),
        "adminPhones": (TakhfidSetting.query.filter_by(key="admin_phones").first().value if TakhfidSetting.query.filter_by(key="admin_phones").first() else ""),
    }
    content = {key: _setting_json(f"content:{key}", []) for key in ("banners", "campaigns", "categories")}
    return render_template("takhfid_admin/settings.html", pricing=_public_pricing(), integration=integration, content=content)


@takhfid_admin_v2_bp.post("/settings")
@login_required
def settings_save():
    guard = _guard()
    if guard:
        return guard
    _set_setting("whatsapp_session", str(request.form.get("whatsappSession") or "basheer").strip() or "basheer")
    _set_setting("admin_phones", ",".join(x.strip() for x in str(request.form.get("adminPhones") or "").split(",") if x.strip()))
    for key in ("banners", "campaigns", "categories"):
        raw = str(request.form.get(key) or "[]")
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError
        except ValueError:
            flash(f"محتوى {key} يجب أن يكون JSON مصفوفة صحيحة.", "danger")
            return redirect(url_for("takhfid_admin_v2.settings"))
        _set_setting(f"content:{key}", json.dumps(parsed, ensure_ascii=False))
    db.session.add(AuditLog(user_id=current_user.id, action="takhfid.settings.updated", details="admin"))
    db.session.commit()
    flash("تم حفظ إعدادات التخفيض.", "success")
    return redirect(url_for("takhfid_admin_v2.settings"))


@takhfid_admin_v2_bp.post("/api/media/upload")
@login_required
def media_upload():
    guard = _guard()
    if guard:
        return guard
    kind = str(request.form.get("kind") or "general").strip()
    upload = request.files.get("file")
    try:
        image_url = _save_image(upload, kind)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    db.session.add(AuditLog(user_id=current_user.id, action="takhfid.media.uploaded", details=image_url))
    db.session.commit()
    return jsonify({"success": True, "url": image_url})


@takhfid_admin_v2_bp.get("/api/pricing")
def api_pricing_get():
    guard = _api_guard()
    if guard:
        return guard
    return jsonify({"success": True, "pricing": _public_pricing()})


@takhfid_admin_v2_bp.put("/api/pricing/<path:governorate>")
def api_pricing_put(governorate: str):
    guard = _api_guard()
    if guard:
        return guard
    payload = request.get_json(silent=True) or {}
    current = _public_pricing().get(governorate)
    if current is None:
        return jsonify({"success": False, "error": "المحافظة غير معروفة"}), 404
    current.update(payload)
    _set_setting(f"pricing:{governorate}", json.dumps(current, ensure_ascii=False))
    db.session.commit()
    return jsonify({"success": True, "pricing": current})


@takhfid_admin_v2_bp.get("/api/integrations")
def api_integrations_get():
    guard = _api_guard()
    if guard:
        return guard
    values = {}
    for key in ("whatsapp_session", "admin_phones", "otp_hash_secret", "whatsapp_send_url", "whatsapp_api_key", "whatsapp_api_key_header", "whatsapp_api_key_prefix"):
        row = TakhfidSetting.query.filter_by(key=key).first()
        if row:
            values[key] = row.value
    return jsonify({"success": True, "settings": values})


@takhfid_admin_v2_bp.put("/api/integrations")
def api_integrations_put():
    guard = _api_guard()
    if guard:
        return guard
    payload = request.get_json(silent=True) or {}
    for key in ("whatsapp_session", "admin_phones", "otp_hash_secret", "whatsapp_send_url", "whatsapp_api_key", "whatsapp_api_key_header", "whatsapp_api_key_prefix"):
        if key in payload:
            _set_setting(key, str(payload.get(key) or ""), secret=key in {"otp_hash_secret", "whatsapp_api_key"})
    db.session.commit()
    return jsonify({"success": True})


@takhfid_admin_v2_bp.get("/api/content")
def api_content_get():
    return jsonify({"success": True, "content": {key: _setting_json(f"content:{key}", []) for key in ("categories", "banners", "campaigns")}})


@takhfid_admin_v2_bp.put("/api/content")
def api_content_put():
    guard = _api_guard()
    if guard:
        return guard
    payload = request.get_json(silent=True) or {}
    for key in ("categories", "banners", "campaigns"):
        value = payload.get(key)
        if isinstance(value, list):
            _set_setting(f"content:{key}", json.dumps(value, ensure_ascii=False))
    db.session.commit()
    return jsonify({"success": True, "content": {key: _setting_json(f"content:{key}", []) for key in ("categories", "banners", "campaigns")}})
