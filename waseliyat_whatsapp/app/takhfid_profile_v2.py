from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, jsonify, request

from . import db
from .takhfid_v2 import TakhfidCustomer, _current_customer, _normalize_phone, _public_customer, _require_admin, _require_customer


takhfid_profile_v2_bp = Blueprint("takhfid_profile_v2", __name__, url_prefix="/takhfid/api/v2")


def _apply_customer_payload(customer: TakhfidCustomer, payload: dict[str, Any]) -> None:
    if "firstName" in payload:
        value = str(payload.get("firstName") or "").strip()
        if value:
            customer.first_name = value
    for key, attr in (("secondName", "second_name"), ("thirdName", "third_name"), ("lastName", "last_name"), ("governorate", "governorate")):
        if key in payload:
            setattr(customer, attr, str(payload.get(key) or "").strip() or None)


@takhfid_profile_v2_bp.get("/me/profile")
def get_my_profile_v2():
    customer = _require_customer()
    if isinstance(customer, tuple):
        return customer
    return jsonify({"success": True, "user": _public_customer(customer)})


@takhfid_profile_v2_bp.put("/me/profile")
def update_my_profile_v2():
    customer = _current_customer()
    if not customer:
        return jsonify({"success": False, "error": "غير مصرح أو انتهت الجلسة"}), 401
    payload = request.get_json(silent=True) or {}
    _apply_customer_payload(customer, payload)
    customer.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"success": True, "user": _public_customer(customer)})


@takhfid_profile_v2_bp.get("/admin/customers")
def list_customers_v2():
    customer = _require_admin()
    if isinstance(customer, tuple):
        return customer
    rows = TakhfidCustomer.query.order_by(TakhfidCustomer.created_at.desc()).all()
    return jsonify({"success": True, "customers": [_public_customer(row) for row in rows]})


@takhfid_profile_v2_bp.post("/admin/customers/bulk")
def bulk_customers_v2():
    customer = _require_admin()
    if isinstance(customer, tuple):
        return customer
    payload = request.get_json(silent=True) or {}
    customers = payload.get("customers")
    if not isinstance(customers, list):
        return jsonify({"success": False, "error": "customers يجب أن تكون مصفوفة"}), 400

    changed = 0
    for item in customers:
        if not isinstance(item, dict):
            continue
        phone = _normalize_phone(item.get("phone"))
        uid = str(item.get("uid") or (f"usr_{phone}" if phone else "")).strip()
        if not phone or not uid:
            continue
        row = TakhfidCustomer.query.filter_by(uid=uid).first() or TakhfidCustomer.query.filter_by(phone=phone).first()
        if not row:
            row = TakhfidCustomer(uid=uid, phone=phone)
            db.session.add(row)
        row.uid = uid
        row.phone = phone
        _apply_customer_payload(row, item)
        row.role = "admin" if bool(item.get("isAdmin")) else str(item.get("role") or row.role or "customer")
        row.is_admin = bool(item.get("isAdmin")) or row.role == "admin"
        changed += 1
    db.session.commit()
    return jsonify({"success": True, "count": changed})


@takhfid_profile_v2_bp.delete("/admin/customers/<uid>")
def delete_customer_v2(uid: str):
    customer = _require_admin()
    if isinstance(customer, tuple):
        return customer
    row = TakhfidCustomer.query.filter_by(uid=uid).first()
    if not row:
        return jsonify({"success": False, "error": "العميل غير موجود"}), 404
    if row.id == customer.id:
        return jsonify({"success": False, "error": "لا يمكن حذف حساب المدير الحالي"}), 400
    db.session.delete(row)
    db.session.commit()
    return jsonify({"success": True, "uid": uid})
