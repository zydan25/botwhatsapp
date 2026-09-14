from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from . import db
from .takhfid import TakhfidOtp
from .takhfid_v2 import (
    TakhfidAccessToken,
    TakhfidCustomer,
    _admin_numbers,
    _current_customer,
    _hash_otp,
    _normalize_phone,
    _public_customer,
    _token_hash,
    _utc,
    _issue_token,
)


takhfid_auth_v3_bp = Blueprint("takhfid_auth_v3", __name__, url_prefix="/takhfid/api/v2/auth")


def _verify_code(phone: str, code: str):
    row = TakhfidOtp.query.filter_by(phone=phone).first()
    if not row:
        return None, (jsonify({"success": False, "error": "لا يوجد رمز نشط"}), 400)
    now = datetime.now(timezone.utc)
    expires_at = _utc(row.expires_at)
    if expires_at is None or expires_at < now:
        db.session.delete(row)
        db.session.commit()
        return None, (jsonify({"success": False, "error": "انتهت صلاحية الرمز"}), 400)
    if row.attempts >= 5:
        db.session.delete(row)
        db.session.commit()
        return None, (jsonify({"success": False, "error": "تم تجاوز عدد المحاولات"}), 429)
    if not __import__("hmac").compare_digest(row.code_hash, _hash_otp(phone, code)):
        row.attempts += 1
        db.session.commit()
        return None, (jsonify({"success": False, "error": "رمز التحقق غير صحيح"}), 401)
    return row, None


@takhfid_auth_v3_bp.post("/login-verify")
def login_verify():
    payload = request.get_json(silent=True) or request.form
    phone = _normalize_phone(payload.get("phoneNumber"))
    code = str(payload.get("otp") or "").strip()
    if not (phone.isdigit() and 8 <= len(phone) <= 15 and code.isdigit() and len(code) == 6):
        return jsonify({"success": False, "error": "بيانات التحقق غير صالحة"}), 400

    row, error = _verify_code(phone, code)
    if error:
        return error

    now = datetime.now(timezone.utc)
    uid = f"usr_{phone}"
    customer = TakhfidCustomer.query.filter_by(uid=uid).first()
    is_new = customer is None or not str(customer.first_name or "").strip()
    if customer is None:
        customer = TakhfidCustomer(uid=uid, phone=phone)
        db.session.add(customer)
        db.session.flush()

    is_admin = phone in _admin_numbers()
    customer.phone = phone
    customer.is_admin = is_admin
    customer.role = "admin" if is_admin else "customer"
    customer.last_login_at = now
    customer.updated_at = now

    token, expires = _issue_token(customer)
    db.session.delete(row)
    db.session.commit()

    return jsonify({
        "success": True,
        "needsProfile": bool(is_new),
        "accessToken": token,
        "tokenType": "Bearer",
        "expiresAt": expires.isoformat(),
        "user": _public_customer(customer),
    })


@takhfid_auth_v3_bp.post("/complete-profile")
def complete_profile():
    customer = _current_customer()
    if not customer:
        return jsonify({"success": False, "error": "غير مصرح أو انتهت الجلسة"}), 401
    payload = request.get_json(silent=True) or {}
    first_name = str(payload.get("firstName") or "").strip()
    governorate = str(payload.get("governorate") or "").strip()
    if not first_name:
        return jsonify({"success": False, "error": "الاسم الأول مطلوب"}), 400
    if not governorate:
        return jsonify({"success": False, "error": "المحافظة مطلوبة"}), 400
    customer.first_name = first_name
    customer.second_name = str(payload.get("secondName") or "").strip() or None
    customer.third_name = str(payload.get("thirdName") or "").strip() or None
    customer.last_name = str(payload.get("lastName") or "").strip() or None
    customer.governorate = governorate
    customer.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"success": True, "user": _public_customer(customer)})


@takhfid_auth_v3_bp.post("/session-revoke")
def session_revoke():
    customer = _current_customer()
    if not customer:
        return jsonify({"success": False, "error": "غير مصرح"}), 401
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        raw = header[7:].strip()
        row = TakhfidAccessToken.query.filter_by(token_hash=_token_hash(raw), revoked_at=None).first()
        if row:
            row.revoked_at = datetime.now(timezone.utc)
            db.session.commit()
    return jsonify({"success": True})
