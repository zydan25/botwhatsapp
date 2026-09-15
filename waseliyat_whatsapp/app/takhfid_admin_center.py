from __future__ import annotations

import secrets
from functools import wraps
from typing import Any

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect

from . import db
from .models import AuditLog, WhatsAppSession, Notification
from .takhfid_api import (
    GOVERNORATES, PUBLIC_SETTING_DEFAULTS, TakhfidCustomer, TakhfidOrder,
    TakhfidProduct, json_setting, product_data, save_json_setting,
)

bp = Blueprint("takhfid_admin_center", __name__, url_prefix="/store-admin")


def _csrf() -> str:
    token = session.get("takhfid_admin_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["takhfid_admin_csrf"] = token
    return token


def _check_csrf() -> None:
    if not secrets.compare_digest(str(session.get("takhfid_admin_csrf", "")), str(request.form.get("csrf_token", ""))):
        abort(400, description="طلب غير صالح")


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        return view(*args, **kwargs)
    return wrapped


def num(value: Any, default=0):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return default


def money(value: Any, default=0.0):
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return default


def csv_values(value: str) -> list[str]:
    return [x.strip() for x in (value or "").replace("،", ",").split(",") if x.strip()]


def content() -> dict:
    data = json_setting("content", PUBLIC_SETTING_DEFAULTS["content"])
    return data if isinstance(data, dict) else dict(PUBLIC_SETTING_DEFAULTS["content"])


def save_content(data: dict) -> None:
    save_json_setting("content", data)


def audit(action: str, details=""):
    db.session.add(AuditLog(user_id=current_user.id, action=action, details=details))


@bp.context_processor
def globals_for_templates():
    return {"csrf": _csrf()}


@bp.get("/")
@admin_required
def dashboard():
    rows = TakhfidProduct.query.all()
    products = [product_data(r) for r in rows]
    data = content()
    stats = {
        "products": len(products),
        "active_products": sum(bool(p.get("active", True)) for p in products),
        "out_of_stock": sum(num(p.get("stock")) <= 0 for p in products),
        "categories": len(data.get("categories", [])),
        "customers": TakhfidCustomer.query.count(),
        "orders": TakhfidOrder.query.count(),
        "pending": TakhfidOrder.query.filter_by(status="pending").count(),
        "sessions": WhatsAppSession.query.count(),
        "unread": Notification.query.filter_by(read=False).count(),
    }
    recent = TakhfidOrder.query.order_by(TakhfidOrder.created_at.desc()).limit(8).all()
    return render_template("takhfid_center/dashboard.html", stats=stats, recent_orders=recent)


@bp.route("/products", methods=["GET", "POST"])
@admin_required
def products():
    if request.method == "POST":
        _check_csrf()
        pid = (request.form.get("id") or f"p-{secrets.token_hex(6)}").strip()
        name = request.form.get("name", "").strip()
        if not name:
            flash("اسم المنتج مطلوب", "danger")
            return redirect(url_for("takhfid_admin_center.products"))
        images = csv_values(request.form.get("images", ""))
        row = db.session.get(TakhfidProduct, pid)
        payload = dict(row.payload or {}) if row else {}
        payload.update({
            "name": name, "slug": request.form.get("slug", "").strip() or name.lower().replace(" ", "-"),
            "sku": request.form.get("sku", "").strip(),
            "description": request.form.get("description", "").strip(),
            "shortDescription": request.form.get("shortDescription", "").strip(),
            "categoryId": request.form.get("categoryId", "").strip(),
            "category": request.form.get("category", "").strip(),
            "brand": request.form.get("brand", "").strip(),
            "images": images, "image": images[0] if images else "",
            "price": money(request.form.get("price")),
            "compareAtPrice": money(request.form.get("compareAtPrice")),
            "costPrice": money(request.form.get("costPrice")),
            "discountType": request.form.get("discountType", "none"),
            "discountValue": money(request.form.get("discountValue")),
            "currency": request.form.get("currency", "YER").upper(),
            "stock": max(0, num(request.form.get("stock"))),
            "lowStockThreshold": max(0, num(request.form.get("lowStockThreshold"), 5)),
            "active": "active" in request.form, "featured": "featured" in request.form,
            "allowBackorder": "allowBackorder" in request.form,
            "sizes": csv_values(request.form.get("sizes", "")),
            "colors": csv_values(request.form.get("colors", "")),
            "tags": csv_values(request.form.get("tags", "")),
            "sortOrder": num(request.form.get("sortOrder")),
        })
        if row:
            row.payload = payload
        else:
            db.session.add(TakhfidProduct(id=pid, payload=payload))
        audit("takhfid.admin.product.save", pid)
        db.session.commit()
        flash("تم حفظ المنتج", "success")
        return redirect(url_for("takhfid_admin_center.products"))
    q = request.args.get("q", "").strip().casefold()
    status = request.args.get("status", "all")
    rows = [product_data(r) for r in TakhfidProduct.query.order_by(TakhfidProduct.updated_at.desc()).all()]
    if q: rows = [p for p in rows if q in str(p.get("name", "")).casefold() or q in str(p.get("sku", "")).casefold()]
    if status == "active": rows = [p for p in rows if p.get("active", True)]
    if status == "inactive": rows = [p for p in rows if not p.get("active", True)]
    return render_template("takhfid_center/products.html", products=rows, categories=content().get("categories", []))


@bp.post("/products/<product_id>/delete")
@admin_required
def product_delete(product_id):
    _check_csrf(); row = db.session.get(TakhfidProduct, product_id)
    if row:
        db.session.delete(row); audit("takhfid.admin.product.delete", product_id); db.session.commit(); flash("تم حذف المنتج", "success")
    return redirect(url_for("takhfid_admin_center.products"))


@bp.route("/categories", methods=["GET", "POST"])
@admin_required
def categories():
    data = content(); rows = [x for x in data.get("categories", []) if isinstance(x, dict)]
    if request.method == "POST":
        _check_csrf(); cid = request.form.get("id") or f"cat-{secrets.token_hex(4)}"
        if request.form.get("action") == "delete":
            rows = [x for x in rows if str(x.get("id")) != cid]
        else:
            item = {"id": cid, "name": request.form.get("name", "").strip(), "description": request.form.get("description", "").strip(), "image": request.form.get("image", "").strip(), "sortOrder": num(request.form.get("sortOrder")), "active": "active" in request.form}
            if not item["name"]:
                flash("اسم الصنف مطلوب", "danger"); return redirect(url_for("takhfid_admin_center.categories"))
            rows = [x for x in rows if str(x.get("id")) != cid] + [item]
        rows.sort(key=lambda x: num(x.get("sortOrder"))); data["categories"] = rows; save_content(data); audit("takhfid.admin.categories"); db.session.commit(); flash("تم الحفظ", "success")
        return redirect(url_for("takhfid_admin_center.categories"))
    return render_template("takhfid_center/categories.html", categories=rows)


@bp.route("/content", methods=["GET", "POST"])
@admin_required
def content_page():
    kind = request.args.get("type", "banners")
    if kind not in {"banners", "campaigns", "announcements"}: kind = "banners"
    data = content(); rows = [x for x in data.get(kind, []) if isinstance(x, dict)]
    if request.method == "POST":
        _check_csrf(); cid = request.form.get("id") or f"{kind[:-1]}-{secrets.token_hex(4)}"
        if request.form.get("action") == "delete": rows = [x for x in rows if str(x.get("id")) != cid]
        else: rows = [x for x in rows if str(x.get("id")) != cid] + [{"id": cid, "title": request.form.get("title", "").strip(), "text": request.form.get("text", "").strip(), "image": request.form.get("image", "").strip(), "link": request.form.get("link", "").strip(), "active": "active" in request.form, "sortOrder": num(request.form.get("sortOrder"))}]
        rows.sort(key=lambda x: num(x.get("sortOrder"))); data[kind] = rows; save_content(data); audit("takhfid.admin.content", kind); db.session.commit(); flash("تم الحفظ", "success")
        return redirect(url_for("takhfid_admin_center.content_page", type=kind))
    return render_template("takhfid_center/content.html", items=rows, kind=kind)


@bp.get("/orders")
@admin_required
def orders():
    status = request.args.get("status", "all"); q = request.args.get("q", "").strip().casefold(); query = TakhfidOrder.query.order_by(TakhfidOrder.created_at.desc())
    if status != "all": query = query.filter_by(status=status)
    rows = query.all()
    if q: rows = [r for r in rows if q in r.id.casefold() or q in str((r.payload or {}).get("customerName", "")).casefold() or q in str((r.payload or {}).get("customerPhone", "")).casefold()]
    return render_template("takhfid_center/orders.html", orders=rows)


@bp.post("/orders/<order_id>")
@admin_required
def order_update(order_id):
    _check_csrf(); row = db.session.get(TakhfidOrder, order_id)
    if not row: abort(404)
    payload = dict(row.payload or {})
    status = request.form.get("status", "")
    if status: row.status = status; payload["status"] = status
    payload["isPaid"] = request.form.get("isPaid") == "1"
    payload["paymentReference"] = request.form.get("paymentReference", "").strip()
    row.payload = payload; audit("takhfid.admin.order.update", order_id); db.session.commit(); flash("تم تحديث الطلب", "success")
    return redirect(url_for("takhfid_admin_center.orders"))


@bp.get("/customers")
@admin_required
def customers():
    q = request.args.get("q", "").strip().casefold(); rows = TakhfidCustomer.query.order_by(TakhfidCustomer.created_at.desc()).all()
    if q: rows = [r for r in rows if q in r.phone.casefold() or q in r.uid.casefold() or q in str(r.first_name or "").casefold()]
    return render_template("takhfid_center/customers.html", customers=rows)


@bp.post("/customers/<int:customer_id>")
@admin_required
def customer_update(customer_id):
    _check_csrf(); row = db.session.get(TakhfidCustomer, customer_id)
    if not row: abort(404)
    row.first_name = request.form.get("first_name", "").strip(); row.second_name = request.form.get("second_name", "").strip() or None; row.third_name = request.form.get("third_name", "").strip() or None; row.last_name = request.form.get("last_name", "").strip() or None; row.governorate = request.form.get("governorate", "").strip() or None; row.role = request.form.get("role", "customer").strip() or "customer"; row.is_admin = "is_admin" in request.form
    audit("takhfid.admin.customer.update", row.uid); db.session.commit(); flash("تم تحديث العميل", "success"); return redirect(url_for("takhfid_admin_center.customers"))


@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    data = {k: json_setting(k, v) for k, v in PUBLIC_SETTING_DEFAULTS.items() if k != "content"}
    if request.method == "POST":
        _check_csrf()
        data["store"].update({"name": request.form.get("store_name", "").strip(), "description": request.form.get("store_description", "").strip(), "logo": request.form.get("store_logo", "").strip(), "phone": request.form.get("store_phone", "").strip(), "whatsapp": request.form.get("store_whatsapp", "").strip(), "email": request.form.get("store_email", "").strip(), "currency": request.form.get("currency", "YER").upper(), "defaultGovernorate": request.form.get("default_governorate", "أمانة العاصمة").strip(), "enabled": "store_enabled" in request.form})
        data["checkout"].update({"guestCheckout": "guest_checkout" in request.form, "requireAddress": "require_address" in request.form, "requireDeliveryNotes": "require_delivery_notes" in request.form, "minimumOrder": money(request.form.get("minimum_order")), "maximumItemsPerOrder": max(1, num(request.form.get("max_items"), 100))})
        data["shipping"].update({"enabled": "shipping_enabled" in request.form, "defaultFee": money(request.form.get("shipping_default")), "freeAbove": money(request.form.get("shipping_free_above")), "sameGovernorateOnly": "same_governorate" in request.form})
        data["payments"] = {k: request.form.get(k) == "on" for k in ("cash_on_delivery", "kuraimi", "jawali", "one_cash", "bank_transfer")}
        data["catalog"].update({"showOutOfStock": "show_out_of_stock" in request.form, "allowBackorder": "allow_backorder" in request.form, "featuredLimit": max(1, num(request.form.get("featured_limit"), 12))})
        for k, v in data.items(): save_json_setting(k, v)
        audit("takhfid.admin.settings"); db.session.commit(); flash("تم حفظ إعدادات المتجر", "success")
    return render_template("takhfid_center/settings.html", **data, governorates=GOVERNORATES)


@bp.post("/pricing/<path:governorate>")
@admin_required
def pricing_update(governorate):
    _check_csrf()
    if governorate not in GOVERNORATES: abort(404)
    current = dict(GOVERNORATES[governorate])
    current.update({"sarToYerRate": money(request.form.get("sarToYerRate"), current.get("sarToYerRate", 140)), "usdToYerRate": money(request.form.get("usdToYerRate"), current.get("usdToYerRate", 535)), "markupValue": money(request.form.get("markupValue"), current.get("markupValue", 0)), "deliveryFee": money(request.form.get("deliveryFee"), current.get("deliveryFee", 0))})
    save_json_setting(f"pricing:{governorate}", current); audit("takhfid.admin.pricing", governorate); db.session.commit(); flash("تم حفظ التسعير", "success")
    return redirect(url_for("takhfid_admin_center.settings"))


@bp.get("/whatsapp")
@admin_required
def whatsapp():
    return render_template("takhfid_center/whatsapp.html", sessions=WhatsAppSession.query.order_by(WhatsAppSession.id.asc()).all())


@bp.post("/whatsapp/<int:session_id>")
@admin_required
def whatsapp_update(session_id):
    _check_csrf(); row = db.session.get(WhatsAppSession, session_id)
    if not row: abort(404)
    row.display_name = request.form.get("display_name", row.display_name).strip() or row.display_name; row.api_base_url = request.form.get("api_base_url", row.api_base_url).strip().rstrip("/"); row.webhook_base_url = request.form.get("webhook_base_url", "").strip().rstrip("/") or None; row.active = "active" in request.form
    audit("takhfid.admin.whatsapp.update", row.name); db.session.commit(); flash("تم حفظ جلسة WhatsApp", "success"); return redirect(url_for("takhfid_admin_center.whatsapp"))


@bp.get("/audit")
@admin_required
def audit_page():
    return render_template("takhfid_center/audit.html", logs=AuditLog.query.order_by(AuditLog.id.desc()).limit(150).all())


@bp.get("/diagnostics")
@admin_required
def diagnostics():
    inspector = inspect(db.engine); tables = []
    for name in inspector.get_table_names():
        low = name.lower()
        if any(x in low for x in ("product", "category", "catalog", "item", "order")):
            tables.append({"name": name, "columns": [c["name"] for c in inspector.get_columns(name)]})
    c = {"canonical_products": TakhfidProduct.query.count(), "categories": len(content().get("categories", [])), "customers": TakhfidCustomer.query.count(), "orders": TakhfidOrder.query.count()}
    return render_template("takhfid_center/diagnostics.html", counts=c, tables=tables, database=str(db.engine.url).split("@")[0])
