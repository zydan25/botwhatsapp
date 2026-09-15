from __future__ import annotations

import json
import secrets
from functools import wraps
from pathlib import Path
from typing import Any

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect, text

from . import db
from .models import AuditLog, WhatsAppSession, Notification, MessageLog
from .takhfid_api import (
    GOVERNORATES,
    PUBLIC_SETTING_DEFAULTS,
    TakhfidCustomer,
    TakhfidOrder,
    TakhfidProduct,
    TakhfidSetting,
    product_data,
    json_setting,
    save_json_setting,
    save_setting,
    setting,
)

bp = Blueprint("takhfid_admin_v2", __name__, url_prefix="/store-admin")


def _csrf_token() -> str:
    token = session.get("tk_admin_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["tk_admin_csrf"] = token
    return token


def _check_csrf() -> None:
    expected = session.get("tk_admin_csrf", "")
    supplied = request.form.get("csrf_token", "")
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        abort(400, description="طلب غير صالح")


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not getattr(current_user, "is_authenticated", False):
            abort(401)
        return view(*args, **kwargs)
    return wrapped


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return default


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return default


def split_values(value: str) -> list[str]:
    return [x.strip() for x in (value or "").replace("،", ",").split(",") if x.strip()]


def categories() -> list[dict[str, Any]]:
    content = json_setting("content", PUBLIC_SETTING_DEFAULTS["content"])
    rows = content.get("categories", []) if isinstance(content, dict) else []
    return [x for x in rows if isinstance(x, dict)]


def content_value(key: str) -> list[dict[str, Any]]:
    content = json_setting("content", PUBLIC_SETTING_DEFAULTS["content"])
    rows = content.get(key, []) if isinstance(content, dict) else []
    return [x for x in rows if isinstance(x, dict)]


def save_content_list(key: str, rows: list[dict[str, Any]]) -> None:
    content = json_setting("content", PUBLIC_SETTING_DEFAULTS["content"])
    if not isinstance(content, dict):
        content = dict(PUBLIC_SETTING_DEFAULTS["content"])
    content[key] = rows
    save_json_setting("content", content)


def audit(action: str, details: str = "") -> None:
    db.session.add(AuditLog(user_id=current_user.id, action=action, details=details))


@bp.context_processor
def inject_admin_globals():
    return {"csrf_token": _csrf_token()}


@bp.get("/")
@admin_required
def dashboard():
    content = json_setting("content", PUBLIC_SETTING_DEFAULTS["content"])
    stats = {
        "products": TakhfidProduct.query.count(),
        "active_products": sum(1 for p in TakhfidProduct.query.all() if product_data(p).get("active", True)),
        "customers": TakhfidCustomer.query.count(),
        "orders": TakhfidOrder.query.count(),
        "pending_orders": TakhfidOrder.query.filter_by(status="pending").count(),
        "sessions": WhatsAppSession.query.count(),
        "notifications": Notification.query.filter_by(read=False).count(),
        "categories": len(content.get("categories", [])) if isinstance(content, dict) else 0,
    }
    recent_orders = TakhfidOrder.query.order_by(TakhfidOrder.created_at.desc()).limit(8).all()
    return render_template("takhfid_admin_v2/dashboard.html", stats=stats, recent_orders=recent_orders)


@bp.route("/products", methods=["GET", "POST"])
@admin_required
def products():
    if request.method == "POST":
        _check_csrf()
        product_id = (request.form.get("id") or f"p-{secrets.token_hex(6)}").strip()
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("اسم المنتج مطلوب", "danger")
            return redirect(url_for("takhfid_admin_v2.products"))
        images = split_values(request.form.get("images", ""))
        data = {
            "name": name,
            "slug": (request.form.get("slug") or name.lower().replace(" ", "-")).strip(),
            "sku": (request.form.get("sku") or "").strip(),
            "description": (request.form.get("description") or "").strip(),
            "shortDescription": (request.form.get("shortDescription") or "").strip(),
            "categoryId": (request.form.get("categoryId") or "").strip(),
            "category": (request.form.get("category") or "").strip(),
            "brand": (request.form.get("brand") or "").strip(),
            "images": images,
            "image": images[0] if images else "",
            "price": parse_float(request.form.get("price")),
            "compareAtPrice": parse_float(request.form.get("compareAtPrice")),
            "costPrice": parse_float(request.form.get("costPrice")),
            "discountType": request.form.get("discountType") or "none",
            "discountValue": parse_float(request.form.get("discountValue")),
            "currency": (request.form.get("currency") or "YER").upper(),
            "stock": max(0, parse_int(request.form.get("stock"))),
            "lowStockThreshold": max(0, parse_int(request.form.get("lowStockThreshold"), 5)),
            "active": "active" in request.form,
            "featured": "featured" in request.form,
            "allowBackorder": "allowBackorder" in request.form,
            "sizes": split_values(request.form.get("sizes", "")),
            "colors": split_values(request.form.get("colors", "")),
            "tags": split_values(request.form.get("tags", "")),
            "attributes": {},
            "variants": [],
            "seoTitle": (request.form.get("seoTitle") or "").strip(),
            "seoDescription": (request.form.get("seoDescription") or "").strip(),
            "sortOrder": parse_int(request.form.get("sortOrder")),
        }
        row = db.session.get(TakhfidProduct, product_id)
        if row:
            data["createdAt"] = (row.payload or {}).get("createdAt") or row.created_at.isoformat()
            row.payload = data
        else:
            row = TakhfidProduct(id=product_id, payload=data)
            db.session.add(row)
        audit("takhfid.admin.product.save", product_id)
        db.session.commit()
        flash("تم حفظ المنتج", "success")
        return redirect(url_for("takhfid_admin_v2.products"))

    q = (request.args.get("q") or "").strip().casefold()
    status = request.args.get("status", "all")
    rows = TakhfidProduct.query.order_by(TakhfidProduct.updated_at.desc()).all()
    products_list = [product_data(x) for x in rows]
    if q:
        products_list = [p for p in products_list if q in str(p.get("name", "")).casefold() or q in str(p.get("sku", "")).casefold()]
    if status == "active":
        products_list = [p for p in products_list if p.get("active", True)]
    elif status == "inactive":
        products_list = [p for p in products_list if not p.get("active", True)]
    return render_template("takhfid_admin_v2/products.html", products=products_list, categories=categories())


@bp.post("/products/<product_id>/delete")
@admin_required
def delete_product(product_id):
    _check_csrf()
    row = db.session.get(TakhfidProduct, product_id)
    if not row:
        flash("المنتج غير موجود", "danger")
    else:
        db.session.delete(row)
        audit("takhfid.admin.product.delete", product_id)
        db.session.commit()
        flash("تم حذف المنتج", "success")
    return redirect(url_for("takhfid_admin_v2.products"))


@bp.route("/categories", methods=["GET", "POST"])
@admin_required
def categories_page():
    rows = categories()
    if request.method == "POST":
        _check_csrf()
        action = request.form.get("action", "save")
        cid = (request.form.get("id") or f"cat-{secrets.token_hex(4)}").strip()
        if action == "delete":
            rows = [x for x in rows if str(x.get("id")) != cid]
            flash("تم حذف الصنف", "success")
        else:
            item = {
                "id": cid,
                "name": (request.form.get("name") or "").strip(),
                "description": (request.form.get("description") or "").strip(),
                "image": (request.form.get("image") or "").strip(),
                "sortOrder": parse_int(request.form.get("sortOrder")),
                "active": "active" in request.form,
            }
            if not item["name"]:
                flash("اسم الصنف مطلوب", "danger")
                return redirect(url_for("takhfid_admin_v2.categories_page"))
            rows = [x for x in rows if str(x.get("id")) != cid]
            rows.append(item)
            flash("تم حفظ الصنف", "success")
        rows.sort(key=lambda x: parse_int(x.get("sortOrder")))
        save_content_list("categories", rows)
        audit("takhfid.admin.categories", action)
        db.session.commit()
        return redirect(url_for("takhfid_admin_v2.categories_page"))
    return render_template("takhfid_admin_v2/categories.html", categories=rows)


@bp.route("/content", methods=["GET", "POST"])
@admin_required
def content_page():
    key = request.args.get("type", "banners")
    if key not in {"banners", "campaigns", "announcements"}:
        key = "banners"
    rows = content_value(key)
    if request.method == "POST":
        _check_csrf()
        action = request.form.get("action", "save")
        cid = (request.form.get("id") or f"{key[:-1] if key.endswith('s') else key}-{secrets.token_hex(4)}").strip()
        if action == "delete":
            rows = [x for x in rows if str(x.get("id")) != cid]
            flash("تم الحذف", "success")
        else:
            item = {
                "id": cid,
                "title": (request.form.get("title") or "").strip(),
                "text": (request.form.get("text") or "").strip(),
                "image": (request.form.get("image") or "").strip(),
                "link": (request.form.get("link") or "").strip(),
                "active": "active" in request.form,
                "sortOrder": parse_int(request.form.get("sortOrder")),
            }
            rows = [x for x in rows if str(x.get("id")) != cid]
            rows.append(item)
            flash("تم الحفظ", "success")
        rows.sort(key=lambda x: parse_int(x.get("sortOrder")))
        save_content_list(key, rows)
        audit("takhfid.admin.content", key)
        db.session.commit()
        return redirect(url_for("takhfid_admin_v2.content_page", type=key))
    return render_template("takhfid_admin_v2/content.html", items=rows, content_type=key)


@bp.get("/orders")
@admin_required
def orders():
    status = request.args.get("status", "all")
    q = (request.args.get("q") or "").strip().casefold()
    query = TakhfidOrder.query.order_by(TakhfidOrder.created_at.desc())
    if status != "all":
        query = query.filter_by(status=status)
    rows = query.all()
    if q:
        rows = [r for r in rows if q in r.id.casefold() or q in str((r.payload or {}).get("customerName", "")).casefold() or q in str((r.payload or {}).get("customerPhone", "")).casefold()]
    return render_template("takhfid_admin_v2/orders.html", orders=rows)


@bp.post("/orders/<order_id>")
@admin_required
def order_update(order_id):
    _check_csrf()
    row = db.session.get(TakhfidOrder, order_id)
    if not row:
        flash("الطلب غير موجود", "danger")
        return redirect(url_for("takhfid_admin_v2.orders"))
    data = dict(row.payload or {})
    if request.form.get("status"):
        row.status = request.form.get("status")
        data["status"] = row.status
    if "isPaid" in request.form:
        data["isPaid"] = parse_bool(request.form.get("isPaid"))
    if request.form.get("paymentReference") is not None:
        data["paymentReference"] = request.form.get("paymentReference", "").strip()
    row.payload = data
    audit("takhfid.admin.order.update", order_id)
    db.session.commit()
    flash("تم تحديث الطلب", "success")
    return redirect(url_for("takhfid_admin_v2.orders"))


@bp.get("/customers")
@admin_required
def customers():
    q = (request.args.get("q") or "").strip().casefold()
    rows = TakhfidCustomer.query.order_by(TakhfidCustomer.created_at.desc()).all()
    if q:
        rows = [r for r in rows if q in r.phone.casefold() or q in r.uid.casefold() or q in str(r.first_name or "").casefold()]
    return render_template("takhfid_admin_v2/customers.html", customers=rows)


@bp.post("/customers/<int:customer_id>")
@admin_required
def customer_update(customer_id: int):
    _check_csrf()
    customer = db.session.get(TakhfidCustomer, customer_id)
    if not customer:
        flash("العميل غير موجود", "danger")
        return redirect(url_for("takhfid_admin_v2.customers"))
    customer.first_name = request.form.get("first_name", "").strip()
    customer.second_name = request.form.get("second_name", "").strip() or None
    customer.third_name = request.form.get("third_name", "").strip() or None
    customer.last_name = request.form.get("last_name", "").strip() or None
    customer.governorate = request.form.get("governorate", "").strip() or None
    customer.role = request.form.get("role", "customer").strip() or "customer"
    customer.is_admin = "is_admin" in request.form
    audit("takhfid.admin.customer.update", customer.uid)
    db.session.commit()
    flash("تم تحديث العميل", "success")
    return redirect(url_for("takhfid_admin_v2.customers"))


@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings_page():
    if request.method == "POST":
        _check_csrf()
        store = {
            "name": request.form.get("store_name", "").strip(),
            "description": request.form.get("store_description", "").strip(),
            "logo": request.form.get("store_logo", "").strip(),
            "phone": request.form.get("store_phone", "").strip(),
            "whatsapp": request.form.get("store_whatsapp", "").strip(),
            "email": request.form.get("store_email", "").strip(),
            "currency": request.form.get("currency", "YER").strip().upper(),
            "defaultGovernorate": request.form.get("default_governorate", "أمانة العاصمة").strip(),
            "enabled": "store_enabled" in request.form,
        }
        checkout = {
            "guestCheckout": "guest_checkout" in request.form,
            "requireAddress": "require_address" in request.form,
            "requireDeliveryNotes": "require_delivery_notes" in request.form,
            "minimumOrder": parse_float(request.form.get("minimum_order")),
            "maximumItemsPerOrder": max(1, parse_int(request.form.get("max_items"), 100)),
        }
        shipping = {
            "enabled": "shipping_enabled" in request.form,
            "defaultFee": parse_float(request.form.get("shipping_default")),
            "freeAbove": parse_float(request.form.get("shipping_free_above")),
            "sameGovernorateOnly": "same_governorate" in request.form,
        }
        payments = {k: request.form.get(k) == "on" for k in ("cash_on_delivery", "kuraimi", "jawali", "one_cash", "bank_transfer")}
        catalog = {
            "showOutOfStock": "show_out_of_stock" in request.form,
            "allowBackorder": "allow_backorder" in request.form,
            "featuredLimit": max(1, parse_int(request.form.get("featured_limit"), 12)),
        }
        for key, value in {"store": store, "checkout": checkout, "shipping": shipping, "payments": payments, "catalog": catalog}.items():
            save_json_setting(key, value)
        audit("takhfid.admin.settings", "store/checkout/shipping/payments/catalog")
        db.session.commit()
        flash("تم حفظ إعدادات المتجر", "success")
    return render_template(
        "takhfid_admin_v2/settings.html",
        store=json_setting("store", PUBLIC_SETTING_DEFAULTS["store"]),
        checkout=json_setting("checkout", PUBLIC_SETTING_DEFAULTS["checkout"]),
        shipping=json_setting("shipping", PUBLIC_SETTING_DEFAULTS["shipping"]),
        payments=json_setting("payments", PUBLIC_SETTING_DEFAULTS["payments"]),
        catalog=json_setting("catalog", PUBLIC_SETTING_DEFAULTS["catalog"]),
        governorates=GOVERNORATES,
    )


@bp.post("/pricing/<path:governorate>")
@admin_required
def pricing_update(governorate: str):
    _check_csrf()
    if governorate not in GOVERNORATES:
        abort(404)
    current = dict(GOVERNORATES[governorate])
    current.update({
        "sarToYerRate": parse_float(request.form.get("sarToYerRate"), current["sarToYerRate"]),
        "usdToYerRate": parse_float(request.form.get("usdToYerRate"), current.get("usdToYerRate", 535)),
        "markupValue": parse_float(request.form.get("markupValue"), current.get("markupValue", 0)),
        "deliveryFee": parse_float(request.form.get("deliveryFee"), current.get("deliveryFee", 0)),
    })
    save_json_setting(f"pricing:{governorate}", current)
    audit("takhfid.admin.pricing", governorate)
    db.session.commit()
    flash(f"تم حفظ تسعير {governorate}", "success")
    return redirect(url_for("takhfid_admin_v2.settings") if "settings" in request.referrer.lower() if request.referrer else url_for("takhfid_admin_v2.settings_page"))


@bp.get("/whatsapp")
@admin_required
def whatsapp():
    sessions = WhatsAppSession.query.order_by(WhatsAppSession.id.asc()).all()
    return render_template("takhfid_admin_v2/whatsapp.html", sessions=sessions)


@bp.post("/whatsapp/<int:session_id>")
@admin_required
def whatsapp_update(session_id: int):
    _check_csrf()
    row = db.session.get(WhatsAppSession, session_id)
    if not row:
        abort(404)
    row.display_name = request.form.get("display_name", row.display_name).strip() or row.display_name
    row.api_base_url = request.form.get("api_base_url", row.api_base_url).strip().rstrip("/")
    row.webhook_base_url = request.form.get("webhook_base_url", row.webhook_base_url or "").strip().rstrip("/") or None
    row.active = "active" in request.form
    audit("takhfid.admin.whatsapp.update", row.name)
    db.session.commit()
    flash("تم حفظ الجلسة", "success")
    return redirect(url_for("takhfid_admin_v2.whatsapp"))


@bp.get("/audit")
@admin_required
def audit_page():
    rows = AuditLog.query.order_by(AuditLog.id.desc()).limit(150).all()
    return render_template("takhfid_admin_v2/audit.html", logs=rows)


@bp.get("/diagnostics")
@admin_required
def diagnostics():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    interesting = []
    for table in tables:
        low = table.lower()
        if any(word in low for word in ("product", "category", "catalog", "item", "order")):
            try:
                columns = [c["name"] for c in inspector.get_columns(table)]
            except Exception:
                columns = []
            interesting.append({"name": table, "columns": columns})
    counts = {
        "canonical_products": TakhfidProduct.query.count(),
        "categories": len(categories()),
        "customers": TakhfidCustomer.query.count(),
        "orders": TakhfidOrder.query.count(),
    }
    db_url = str(db.engine.url).split("@")[0]
    return render_template("takhfid_admin_v2/diagnostics.html", tables=interesting, counts=counts, database=db_url)
