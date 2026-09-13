from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, jsonify, request

from . import db
from .takhfid_v2 import TakhfidCustomer, TakhfidProduct, _current_customer, _require_admin, _require_customer


takhfid_orders_v2_bp = Blueprint("takhfid_orders_v2", __name__, url_prefix="/takhfid/api/v2")


class TakhfidOrder(db.Model):
    __tablename__ = "takhfid_order"
    id = db.Column(db.String(120), primary_key=True)
    customer_id = db.Column(db.String(80), nullable=False, index=True)
    payload = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(40), nullable=False, index=True, default="awaiting_payment")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _public_order(row: TakhfidOrder) -> dict[str, Any]:
    value = dict(row.payload or {})
    value["id"] = row.id
    value["customerId"] = row.customer_id
    value["status"] = row.status
    value["createdAt"] = value.get("createdAt") or row.created_at.isoformat()
    value["updatedAt"] = row.updated_at.isoformat() if row.updated_at else value.get("updatedAt")
    return value


GOVERNORATE_RATES: dict[str, dict[str, Any]] = {
    "عدن": {"region": "south", "sarToYerRate": 535, "markupValue": 0, "deliveryFee": 0},
    "حضرموت": {"region": "south", "sarToYerRate": 535, "markupValue": 3, "deliveryFee": 0},
    "شبوة": {"region": "south", "sarToYerRate": 535, "markupValue": 4, "deliveryFee": 0},
    "المهرة": {"region": "south", "sarToYerRate": 535, "markupValue": 5, "deliveryFee": 0},
    "لحج": {"region": "south", "sarToYerRate": 535, "markupValue": 2, "deliveryFee": 0},
    "أبين": {"region": "south", "sarToYerRate": 535, "markupValue": 2, "deliveryFee": 0},
    "الضالع": {"region": "south", "sarToYerRate": 535, "markupValue": 3, "deliveryFee": 0},
    "سقطرى": {"region": "south", "sarToYerRate": 535, "markupValue": 8, "deliveryFee": 0},
    "صنعاء": {"region": "north", "sarToYerRate": 140, "markupValue": 0, "deliveryFee": 0},
    "أمانة العاصمة": {"region": "north", "sarToYerRate": 140, "markupValue": 0, "deliveryFee": 0},
    "تعز": {"region": "north", "sarToYerRate": 140, "markupValue": 3, "deliveryFee": 0},
    "إب": {"region": "north", "sarToYerRate": 140, "markupValue": 2, "deliveryFee": 0},
    "الحديدة": {"region": "north", "sarToYerRate": 140, "markupValue": 2, "deliveryFee": 0},
    "ذمار": {"region": "north", "sarToYerRate": 140, "markupValue": 2, "deliveryFee": 0},
    "مأرب": {"region": "north", "sarToYerRate": 140, "markupValue": 4, "deliveryFee": 0},
    "صعدة": {"region": "north", "sarToYerRate": 140, "markupValue": 3, "deliveryFee": 0},
    "حجة": {"region": "north", "sarToYerRate": 140, "markupValue": 3, "deliveryFee": 0},
    "عمران": {"region": "north", "sarToYerRate": 140, "markupValue": 2, "deliveryFee": 0},
    "البيضاء": {"region": "north", "sarToYerRate": 140, "markupValue": 3, "deliveryFee": 0},
    "الجوف": {"region": "north", "sarToYerRate": 140, "markupValue": 4, "deliveryFee": 0},
    "المحويت": {"region": "north", "sarToYerRate": 140, "markupValue": 3, "deliveryFee": 0},
    "ريمة": {"region": "north", "sarToYerRate": 140, "markupValue": 3, "deliveryFee": 0},
}


def _rate(governorate: str) -> dict[str, Any]:
    return GOVERNORATE_RATES.get(governorate, GOVERNORATE_RATES["أمانة العاصمة"])


def _convert_price(price: float, currency: str, rate: dict[str, Any]) -> int:
    marked = float(price or 0) * (1 + max(0, float(rate["markupValue"])) / 100)
    if currency == "SAR":
        return round(marked / rate["sarToYerRate"]) if marked >= 1000 else round(marked)
    return round(marked * rate["sarToYerRate"]) if marked < 1000 else round(marked)


def _new_order_id() -> str:
    stamp = int(_now().timestamp() * 1000)
    return f"ord_{stamp}_{random.randint(1000, 9999)}"


def _build_order(customer: TakhfidCustomer, payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not items or len(items) > 100:
        raise ValueError("السلة غير صالحة")

    governorate = str(payload.get("governorate") or customer.governorate or "أمانة العاصمة").strip()
    currency = "SAR" if payload.get("currency") == "SAR" else "YER"
    payment_method = str(payload.get("paymentMethod") or "cash_on_delivery")
    if payment_method not in {"cash_on_delivery", "kuraimi", "jawali", "one_cash"}:
        payment_method = "cash_on_delivery"

    rate = _rate(governorate)
    order_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        product_id = str(item.get("productId") or "").strip()
        product = db.session.get(TakhfidProduct, product_id)
        if not product:
            raise LookupError(f"المنتج غير موجود: {product_id}")
        product_data = dict(product.payload or {})
        quantity = max(1, min(99, int(float(item.get("quantity") or 1))))
        base_price = float(product_data.get("price") or product_data.get("discountPrice") or product_data.get("originalPrice") or 0)
        order_items.append({
            "productId": product_id,
            "productName": str(product_data.get("name") or "منتج"),
            "quantity": quantity,
            "price": _convert_price(base_price, currency, rate),
            "image": str(product_data.get("image") or ""),
            "color": str(item.get("color")) if item.get("color") else None,
            "size": str(item.get("size")) if item.get("size") else None,
        })

    subtotal = sum(int(item["price"]) * int(item["quantity"]) for item in order_items)
    shipping_fee = round(rate["deliveryFee"] / rate["sarToYerRate"]) if currency == "SAR" else int(rate["deliveryFee"])
    now = _now().isoformat()
    order_id = _new_order_id()
    order_number = f"TK-{random.randint(100000, 999999)}"
    status = "preparing" if payment_method == "cash_on_delivery" else "awaiting_payment"
    return {
        "id": order_id,
        "customerId": customer.uid,
        "orderNumber": order_number,
        "customerName": str(payload.get("customerName") or customer.first_name or "عميل").strip(),
        "customerPhone": customer.phone,
        "governorate": governorate,
        "address": str(payload.get("address") or "").strip(),
        "items": order_items,
        "subtotal": subtotal,
        "shippingFee": shipping_fee,
        "discount": 0,
        "total": subtotal + shipping_fee,
        "currency": currency,
        "status": status,
        "paymentMethod": payment_method,
        "createdAt": now,
        "updatedAt": now,
        "isPaid": False,
        "pricingRegion": rate["region"],
        "pricingMarkupPercent": rate["markupValue"],
        "exchangeRateSarToYer": rate["sarToYerRate"],
    }


@takhfid_orders_v2_bp.post("/orders")
def create_order_v2():
    customer = _require_customer()
    if isinstance(customer, tuple):
        return customer
    try:
        order = _build_order(customer, request.get_json(silent=True) or {})
    except LookupError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (ValueError, TypeError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    row = TakhfidOrder(
        id=order["id"],
        customer_id=customer.uid,
        payload=order,
        status=order["status"],
        created_at=_now(),
        updated_at=_now(),
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({"success": True, "order": _public_order(row)})


@takhfid_orders_v2_bp.get("/orders")
def list_orders_v2():
    customer = _require_customer()
    if isinstance(customer, tuple):
        return customer
    query = TakhfidOrder.query
    if not customer.is_admin:
        query = query.filter_by(customer_id=customer.uid)
    rows = query.order_by(TakhfidOrder.created_at.desc()).all()
    return jsonify({"success": True, "orders": [_public_order(row) for row in rows]})


@takhfid_orders_v2_bp.get("/orders/<order_id>")
def get_order_v2(order_id: str):
    customer = _require_customer()
    if isinstance(customer, tuple):
        return customer
    row = db.session.get(TakhfidOrder, order_id)
    if not row:
        return jsonify({"success": False, "error": "الطلب غير موجود"}), 404
    if not customer.is_admin and row.customer_id != customer.uid:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    return jsonify({"success": True, "order": _public_order(row)})


@takhfid_orders_v2_bp.patch("/orders/<order_id>/status")
def update_order_status_v2(order_id: str):
    customer = _require_admin()
    if isinstance(customer, tuple):
        return customer
    row = db.session.get(TakhfidOrder, order_id)
    if not row:
        return jsonify({"success": False, "error": "الطلب غير موجود"}), 404
    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status") or "").strip()
    allowed = {"awaiting_payment", "payment_submitted", "preparing", "in_shipping", "delivered", "cancelled"}
    if status not in allowed:
        return jsonify({"success": False, "error": "حالة الطلب غير صالحة"}), 400
    data = dict(row.payload or {})
    data["status"] = status
    if isinstance(payload.get("isPaid"), bool):
        data["isPaid"] = payload["isPaid"]
        if payload["isPaid"]:
            data["paymentConfirmedAt"] = _now().isoformat()
    data["updatedAt"] = _now().isoformat()
    row.payload = data
    row.status = status
    row.updated_at = _now()
    db.session.commit()
    return jsonify({"success": True, "order": _public_order(row)})


@takhfid_orders_v2_bp.post("/orders/bulk")
def bulk_orders_v2():
    customer = _require_admin()
    if isinstance(customer, tuple):
        return customer
    payload = request.get_json(silent=True) or {}
    orders = payload.get("orders")
    if not isinstance(orders, list):
        return jsonify({"success": False, "error": "orders يجب أن تكون مصفوفة"}), 400
    changed = 0
    for item in orders:
        if not isinstance(item, dict):
            continue
        order_id = str(item.get("id") or "").strip()
        customer_id = str(item.get("customerId") or "").strip()
        if not order_id or not customer_id:
            continue
        row = db.session.get(TakhfidOrder, order_id)
        if not row:
            row = TakhfidOrder(id=order_id, customer_id=customer_id, payload=dict(item), status=str(item.get("status") or "awaiting_payment"), created_at=_now(), updated_at=_now())
            db.session.add(row)
        else:
            row.customer_id = customer_id
            row.payload = dict(item)
            row.status = str(item.get("status") or row.status)
            row.updated_at = _now()
        changed += 1
    db.session.commit()
    return jsonify({"success": True, "count": changed})
