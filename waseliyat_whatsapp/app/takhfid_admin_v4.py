from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from . import db
from .takhfid_api import (
    ALLOWED_ORDER_STATUSES,
    GOVERNORATES,
    PUBLIC_SETTING_DEFAULTS,
    TakhfidCustomer,
    TakhfidOrder,
    TakhfidProduct,
    TakhfidSetting,
    json_setting,
    product_data,
    public_customer,
    public_order,
    save_json_setting,
    save_setting,
    setting,
    utcnow,
)


takhfid_admin_v4_bp = Blueprint("takhfid_admin_v4", __name__, url_prefix="/takhfid/admin")

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif", "svg"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def admin_required(view):
    """Protect the web dashboard using the existing Flask admin account."""
    return login_required(view)


def csrf_token() -> str:
    token = request.cookies.get("tk_admin_csrf") or secrets.token_urlsafe(24)
    return token


def verify_csrf() -> bool:
    supplied = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
    cookie = request.cookies.get("tk_admin_csrf", "")
    return bool(supplied and cookie and secrets.compare_digest(supplied, cookie))


def media_dir() -> Path:
    path = Path(current_app.instance_path) / "takhfid_media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_url(filename: str) -> str:
    return url_for("takhfid_admin_v4.media", filename=filename)


def save_upload(file_storage, prefix: str = "media") -> str:
    if not file_storage or not file_storage.filename:
        raise ValueError("اختر ملفًا أولًا")
    name = secure_filename(file_storage.filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("نوع الملف غير مسموح")
    file_storage.stream.seek(0, 2)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("حجم الصورة يتجاوز 8 ميجابايت")
    filename = f"{prefix}_{uuid4().hex}.{ext}"
    file_storage.save(media_dir() / filename)
    return media_url(filename)


def parse_json_field(raw: str, default):
    try:
        value = json.loads(raw) if raw.strip() else default
        return value
    except (TypeError, ValueError):
        raise ValueError("JSON غير صالح")


def parse_bool(name: str, default: bool = False) -> bool:
    return request.form.get(name, "").lower() in {"1", "true", "on", "yes"}


def build_product(existing: TakhfidProduct | None = None) -> dict:
    current = dict(existing.payload or {}) if existing else {}
    return {
        "name": request.form.get("name", current.get("name", "")).strip(),
        "slug": request.form.get("slug", current.get("slug", "")).strip(),
        "sku": request.form.get("sku", current.get("sku", "")).strip(),
        "description": request.form.get("description", current.get("description", "")).strip(),
        "shortDescription": request.form.get("shortDescription", current.get("shortDescription", "")).strip(),
        "categoryId": request.form.get("categoryId", current.get("categoryId", "")).strip(),
        "category": request.form.get("category", current.get("category", "")).strip(),
        "brand": request.form.get("brand", current.get("brand", "")).strip(),
        "price": float(request.form.get("price", current.get("price", 0)) or 0),
        "compareAtPrice": float(request.form.get("compareAtPrice", current.get("compareAtPrice", 0)) or 0),
        "costPrice": float(request.form.get("costPrice", current.get("costPrice", 0)) or 0),
        "discountType": request.form.get("discountType", current.get("discountType", "none")),
        "discountValue": float(request.form.get("discountValue", current.get("discountValue", 0)) or 0),
        "currency": request.form.get("currency", current.get("currency", "YER")),
        "stock": int(float(request.form.get("stock", current.get("stock", 0)) or 0)),
        "lowStockThreshold": int(float(request.form.get("lowStockThreshold", current.get("lowStockThreshold", 5)) or 5)),
        "active": parse_bool("active", current.get("active", True)),
        "featured": parse_bool("featured", current.get("featured", False)),
        "allowBackorder": parse_bool("allowBackorder", current.get("allowBackorder", False)),
        "sizes": parse_json_field(request.form.get("sizes", json.dumps(current.get("sizes", []), ensure_ascii=False)), []),
        "colors": parse_json_field(request.form.get("colors", json.dumps(current.get("colors", []), ensure_ascii=False)), []),
        "variants": parse_json_field(request.form.get("variants", json.dumps(current.get("variants", []), ensure_ascii=False)), []),
        "attributes": parse_json_field(request.form.get("attributes", json.dumps(current.get("attributes", {}), ensure_ascii=False)), {}),
        "tags": parse_json_field(request.form.get("tags", json.dumps(current.get("tags", []), ensure_ascii=False)), []),
        "seoTitle": request.form.get("seoTitle", current.get("seoTitle", "")).strip(),
        "seoDescription": request.form.get("seoDescription", current.get("seoDescription", "")).strip(),
        "sortOrder": int(float(request.form.get("sortOrder", current.get("sortOrder", 0)) or 0)),
    }


@takhfid_admin_v4_bp.context_processor
def inject_admin_globals():
    return {
        "tk_csrf": csrf_token(),
        "tk_admin_user": current_user,
        "tk_nav": [
            ("dashboard", "📊", "لوحة التحكم"),
            ("products", "📦", "المنتجات"),
            ("orders", "🛒", "الطلبات"),
            ("customers", "👥", "العملاء"),
            ("content", "🖼️", "المحتوى والبنرات"),
            ("pricing", "💱", "الأسعار والتوصيل"),
            ("settings", "⚙️", "إعدادات المتجر"),
            ("api_docs", "🔌", "API والربط"),
        ],
    }


@takhfid_admin_v4_bp.after_request
def set_csrf_cookie(response):
    if request.path.startswith("/takhfid/admin") and not request.cookies.get("tk_admin_csrf"):
        response.set_cookie("tk_admin_csrf", csrf_token(), httponly=True, samesite="Lax", secure=request.is_secure)
    return response


@takhfid_admin_v4_bp.route("/", endpoint="dashboard")
@admin_required
def dashboard():
    products = TakhfidProduct.query.count()
    active_products = TakhfidProduct.query.filter(TakhfidProduct.payload["active"].as_boolean() == True).count() if db.engine.name == "postgresql" else products
    orders = TakhfidOrder.query.count()
    customers = TakhfidCustomer.query.count()
    pending = TakhfidOrder.query.filter_by(status="pending").count()
    recent_orders = TakhfidOrder.query.order_by(TakhfidOrder.created_at.desc()).limit(8).all()
    return render_template("takhfid_admin_v4/dashboard.html", title="لوحة التحكم", products=products, active_products=active_products, orders=orders, customers=customers, pending=pending, recent_orders=recent_orders)


@takhfid_admin_v4_bp.route("/products", endpoint="products")
@admin_required
def products_page():
    q = request.args.get("q", "").strip()
    query = TakhfidProduct.query.order_by(TakhfidProduct.updated_at.desc())
    rows = query.all()
    if q:
        needle = q.casefold()
        rows = [r for r in rows if needle in str(r.payload.get("name", "")).casefold() or needle in str(r.payload.get("sku", "")).casefold()]
    return render_template("takhfid_admin_v4/products.html", title="المنتجات", products=[product_data(r) for r in rows], query=q)


@takhfid_admin_v4_bp.route("/products/save", methods=["POST"], endpoint="save_product")
@admin_required
def save_product():
    if not verify_csrf():
        flash("انتهت جلسة النموذج؛ أعد تحميل الصفحة.", "error")
        return redirect(url_for("takhfid_admin_v4.products"))
    try:
        product_id = request.form.get("id", "").strip() or f"prd_{uuid4().hex[:14]}"
        row = db.session.get(TakhfidProduct, product_id)
        payload = build_product(row)
        uploaded = []
        for file in request.files.getlist("images"):
            if file and file.filename:
                uploaded.append(save_upload(file, "product"))
        if uploaded:
            old = (row.payload or {}).get("images", []) if row else []
            payload["images"] = old + uploaded
            payload["image"] = payload["images"][0] if payload["images"] else ""
        elif row:
            payload["images"] = (row.payload or {}).get("images", [])
            payload["image"] = payload["images"][0] if payload["images"] else ""
        else:
            payload["images"] = []
            payload["image"] = ""
        if not payload["name"]:
            raise ValueError("اسم المنتج مطلوب")
        if row is None:
            row = TakhfidProduct(id=product_id, payload=payload)
            db.session.add(row)
        else:
            row.payload = payload
            row.updated_at = utcnow()
        db.session.commit()
        flash("تم حفظ المنتج بنجاح.", "success")
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("takhfid_admin_v4.products"))


@takhfid_admin_v4_bp.route("/products/<product_id>/delete", methods=["POST"], endpoint="delete_product")
@admin_required
def delete_product(product_id: str):
    if not verify_csrf():
        return redirect(url_for("takhfid_admin_v4.products"))
    row = db.session.get(TakhfidProduct, product_id)
    if row:
        db.session.delete(row)
        db.session.commit()
        flash("تم حذف المنتج.", "success")
    return redirect(url_for("takhfid_admin_v4.products"))


@takhfid_admin_v4_bp.route("/products/<product_id>/toggle", methods=["POST"], endpoint="toggle_product")
@admin_required
def toggle_product(product_id: str):
    if not verify_csrf():
        return redirect(url_for("takhfid_admin_v4.products"))
    row = db.session.get(TakhfidProduct, product_id)
    if row:
        row.payload = dict(row.payload or {})
        row.payload["active"] = not bool(row.payload.get("active", True))
        row.updated_at = utcnow()
        db.session.commit()
    return redirect(url_for("takhfid_admin_v4.products"))


@takhfid_admin_v4_bp.route("/orders", endpoint="orders")
@admin_required
def orders_page():
    status = request.args.get("status", "").strip()
    query = TakhfidOrder.query.order_by(TakhfidOrder.created_at.desc())
    if status in ALLOWED_ORDER_STATUSES:
        query = query.filter_by(status=status)
    orders = query.limit(200).all()
    return render_template("takhfid_admin_v4/orders.html", title="الطلبات", orders=orders, statuses=sorted(ALLOWED_ORDER_STATUSES), selected_status=status)


@takhfid_admin_v4_bp.route("/orders/<order_id>/status", methods=["POST"], endpoint="update_order_status")
@admin_required
def update_order_status(order_id: str):
    if not verify_csrf():
        return redirect(url_for("takhfid_admin_v4.orders"))
    row = db.session.get(TakhfidOrder, order_id)
    status = request.form.get("status", "")
    if row and status in ALLOWED_ORDER_STATUSES:
        row.status = status
        payload = dict(row.payload or {})
        payload["status"] = status
        row.payload = payload
        row.updated_at = utcnow()
        db.session.commit()
        flash(f"تم تحديث الطلب {order_id} إلى {status}.", "success")
    return redirect(url_for("takhfid_admin_v4.orders"))


@takhfid_admin_v4_bp.route("/orders/<order_id>/payment", methods=["POST"], endpoint="update_order_payment")
@admin_required
def update_order_payment(order_id: str):
    if not verify_csrf():
        return redirect(url_for("takhfid_admin_v4.orders"))
    row = db.session.get(TakhfidOrder, order_id)
    if row:
        payload = dict(row.payload or {})
        payload["isPaid"] = request.form.get("isPaid") == "1"
        payload["paymentReference"] = request.form.get("paymentReference", "").strip()
        row.payload = payload
        row.updated_at = utcnow()
        db.session.commit()
        flash("تم تحديث حالة الدفع.", "success")
    return redirect(url_for("takhfid_admin_v4.orders"))


@takhfid_admin_v4_bp.route("/customers", endpoint="customers")
@admin_required
def customers_page():
    q = request.args.get("q", "").strip()
    rows = TakhfidCustomer.query.order_by(TakhfidCustomer.created_at.desc()).all()
    if q:
        needle = q.casefold()
        rows = [r for r in rows if needle in r.phone.casefold() or needle in (r.first_name or "").casefold()]
    return render_template("takhfid_admin_v4/customers.html", title="العملاء", customers=[public_customer(r) for r in rows], query=q)


@takhfid_admin_v4_bp.route("/content", methods=["GET", "POST"], endpoint="content")
@admin_required
def content_page():
    if request.method == "POST":
        if not verify_csrf():
            flash("انتهت جلسة النموذج؛ أعد تحميل الصفحة.", "error")
            return redirect(url_for("takhfid_admin_v4.content"))
        try:
            content = {
                "banners": json_setting("content", {}).get("banners", []),
                "campaigns": parse_json_field(request.form.get("campaigns", "[]"), []),
                "categories": parse_json_field(request.form.get("categories", "[]"), []),
                "announcements": parse_json_field(request.form.get("announcements", "[]"), []),
            }
            title = request.form.get("bannerTitle", "").strip()
            subtitle = request.form.get("bannerSubtitle", "").strip()
            link = request.form.get("bannerLink", "").strip()
            file = request.files.get("bannerImage")
            if title or subtitle or file:
                image = save_upload(file, "banner") if file and file.filename else ""
                content["banners"].append({"id": f"bn_{uuid4().hex[:12]}", "title": title, "subtitle": subtitle, "image": image, "link": link, "active": True, "sortOrder": len(content["banners"])})
            save_json_setting("content", content)
            db.session.commit()
            flash("تم حفظ المحتوى والبنرات.", "success")
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("takhfid_admin_v4/content.html", title="المحتوى والبنرات", content=json_setting("content", PUBLIC_SETTING_DEFAULTS["content"]))


@takhfid_admin_v4_bp.route("/content/banner/<banner_id>/delete", methods=["POST"], endpoint="delete_banner")
@admin_required
def delete_banner(banner_id: str):
    if not verify_csrf():
        return redirect(url_for("takhfid_admin_v4.content"))
    content = json_setting("content", PUBLIC_SETTING_DEFAULTS["content"])
    content["banners"] = [b for b in content.get("banners", []) if str(b.get("id")) != banner_id]
    save_json_setting("content", content)
    db.session.commit()
    return redirect(url_for("takhfid_admin_v4.content"))


@takhfid_admin_v4_bp.route("/pricing", methods=["GET", "POST"], endpoint="pricing")
@admin_required
def pricing_page():
    if request.method == "POST":
        if not verify_csrf():
            flash("انتهت جلسة النموذج؛ أعد تحميل الصفحة.", "error")
            return redirect(url_for("takhfid_admin_v4.pricing"))
        try:
            gov = request.form.get("governorate", "")
            if gov not in GOVERNORATES:
                raise ValueError("المحافظة غير معروفة")
            data = {
                "region": request.form.get("region", GOVERNORATES[gov].get("region", "north")),
                "sarToYerRate": float(request.form.get("sarToYerRate", 0) or 0),
                "usdToYerRate": float(request.form.get("usdToYerRate", 0) or 0),
                "markupValue": float(request.form.get("markupValue", 0) or 0),
                "deliveryFee": float(request.form.get("deliveryFee", 0) or 0),
            }
            save_json_setting(f"pricing:{gov}", data)
            db.session.commit()
            flash(f"تم حفظ أسعار {gov}.", "success")
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    pricing = {gov: json_setting(f"pricing:{gov}", data) for gov, data in GOVERNORATES.items()}
    return render_template("takhfid_admin_v4/pricing.html", title="الأسعار والتوصيل", pricing=pricing, governorates=GOVERNORATES)


@takhfid_admin_v4_bp.route("/settings", methods=["GET", "POST"], endpoint="settings")
@admin_required
def settings_page():
    if request.method == "POST":
        if not verify_csrf():
            flash("انتهت جلسة النموذج؛ أعد تحميل الصفحة.", "error")
            return redirect(url_for("takhfid_admin_v4.settings"))
        try:
            sections = ["store", "checkout", "shipping", "payments", "catalog"]
            for section in sections:
                raw = request.form.get(section, "")
                save_json_setting(section, parse_json_field(raw, PUBLIC_SETTING_DEFAULTS[section]))
            logo = request.files.get("logo")
            if logo and logo.filename:
                store = json_setting("store", PUBLIC_SETTING_DEFAULTS["store"])
                store["logo"] = save_upload(logo, "logo")
                save_json_setting("store", store)
            db.session.commit()
            flash("تم حفظ إعدادات المتجر.", "success")
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    settings = {key: json_setting(key, value) for key, value in PUBLIC_SETTING_DEFAULTS.items() if key != "content"}
    return render_template("takhfid_admin_v4/settings.html", title="إعدادات المتجر", settings=settings)


@takhfid_admin_v4_bp.route("/api", endpoint="api_docs")
@admin_required
def api_docs():
    return render_template("takhfid_admin_v4/api.html", title="API والربط")


@takhfid_admin_v4_bp.route("/media/<path:filename>", endpoint="media")
def media(filename: str):
    return send_from_directory(media_dir(), filename)


@takhfid_admin_v4_bp.route("/pwa/manifest.webmanifest", endpoint="manifest")
def manifest():
    return current_app.send_static_file("takhfid-admin/manifest.webmanifest")


def register_pwa_headers(response):
    return response
