from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import db
from .models import AuditLog
from .takhfid import TakhfidSetting, _admin_user, _public_pricing, _set_setting
from .takhfid_v2 import TakhfidCustomer, TakhfidProduct, _public_customer
from .takhfid_orders_v2 import TakhfidOrder, _public_order
from .takhfid_chat_v2 import TakhfidChatMessage, _public_message


takhfid_admin_v2_bp = Blueprint("takhfid_admin_v2", __name__, url_prefix="/takhfid/admin")


def _guard():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if not _admin_user():
        return ("غير مصرح", 403)
    return None


def _setting_json(key: str, default: Any):
    row = TakhfidSetting.query.filter_by(key=key).first()
    if not row or not row.value:
        return default
    try:
        value = json.loads(row.value)
        return value
    except (TypeError, ValueError):
        return default


@takhfid_admin_v2_bp.get("/")
@login_required
def dashboard():
    guard = _guard()
    if guard:
        return guard
    customers = TakhfidCustomer.query.count()
    products = TakhfidProduct.query.count()
    orders = TakhfidOrder.query.count()
    pending = TakhfidOrder.query.filter(TakhfidOrder.status.in_(["awaiting_payment", "payment_submitted", "preparing", "in_shipping"])).count()
    recent_orders = TakhfidOrder.query.order_by(TakhfidOrder.created_at.desc()).limit(8).all()
    return render_template(
        "takhfid_admin/dashboard.html",
        title="إدارة التخفيض",
        stats={"customers": customers, "products": products, "orders": orders, "pending": pending},
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
        clean: dict[str, Any] = dict(payload)
        for key in ("price", "discountPrice", "originalPrice"):
            if key in clean and clean[key] != "":
                try:
                    clean[key] = float(clean[key])
                except ValueError:
                    flash(f"قيمة {key} غير صالحة.", "danger")
                    return redirect(url_for("takhfid_admin_v2.products"))
        row = db.session.get(TakhfidProduct, product_id)
        if row:
            row.payload = clean
            row.updated_at = datetime.now(timezone.utc)
        else:
            row = TakhfidProduct(id=product_id, payload=clean)
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
    if row:
        if row.id == _current_customer_id():
            flash("لا يمكن حذف حساب المدير الحالي.", "danger")
        else:
            db.session.delete(row)
            db.session.add(AuditLog(user_id=current_user.id, action="takhfid.customer.deleted", details=uid))
            db.session.commit()
            flash("تم حذف العميل.", "success")
    return redirect(url_for("takhfid_admin_v2.customers"))


def _current_customer_id() -> int | None:
    try:
        from .takhfid_v2 import _current_customer
        customer = _current_customer()
        return customer.id if customer else None
    except Exception:
        return None


@takhfid_admin_v2.get("/orders")
@login_required
def orders():
    guard = _guard()
    if guard:
        return guard
    rows = TakhfidOrder.query.order_by(TakhfidOrder.created_at.desc()).all()
    return render_template("takhfid_admin/orders.html", orders=[_public_order(x) for x in rows])


@takhfid_admin_v2.post("/orders/<order_id>/status")
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


@takhfid_admin_v2.get("/chats/<order_id>")
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


@takhfid_admin_v2.get("/settings")
@login_required
def settings():
    guard = _guard()
    if guard:
        return guard
    integration = {
        "whatsappSession": TakhfidSetting.query.filter_by(key="whatsapp_session").first().value if TakhfidSetting.query.filter_by(key="whatsapp_session").first() else "basheer",
        "adminPhones": TakhfidSetting.query.filter_by(key="admin_phones").first().value if TakhfidSetting.query.filter_by(key="admin_phones").first() else "",
    }
    content = {
        "banners": _setting_json("content:banners", []),
        "campaigns": _setting_json("content:campaigns", []),
        "categories": _setting_json("content:categories", []),
    }
    return render_template("takhfid_admin/settings.html", pricing=_public_pricing(), integration=integration, content=content)


@takhfid_admin_v2.post("/settings")
@login_required
def settings_save():
    guard = _guard()
    if guard:
        return guard
    _set_setting("whatsapp_session", str(request.form.get("whatsappSession") or "basheer").strip() or "basheer")
    _set_setting("admin_phones", ",".join(x for x in str(request.form.get("adminPhones") or "").split(",") if x.strip()))
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
