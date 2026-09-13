from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from . import db, socketio
from .takhfid_v2 import _current_customer
from .takhfid_orders_v2 import TakhfidOrder


takhfid_chat_v2_bp = Blueprint("takhfid_chat_v2", __name__, url_prefix="/takhfid/api/v2")


class TakhfidChatMessage(db.Model):
    __tablename__ = "takhfid_chat_message"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(120), nullable=False, index=True)
    sender_id = db.Column(db.String(80), nullable=False, index=True)
    sender_role = db.Column(db.String(20), nullable=False)
    type = db.Column(db.String(40), nullable=False, default="text")
    text = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


def _public_message(row: TakhfidChatMessage) -> dict[str, Any]:
    return {"id": str(row.id), "orderId": row.order_id, "senderId": row.sender_id, "senderRole": row.sender_role, "type": row.type, "text": row.text, "imageUrl": row.image_url, "createdAt": row.created_at.isoformat() if row.created_at else datetime.now(timezone.utc).isoformat()}


def _proof_dir() -> Path:
    root = Path(current_app.instance_path) / "takhfid_uploads" / "payment_proofs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _proof_signature(order_id: str, filename: str, expires: int) -> str:
    secret = str(current_app.config.get("SECRET_KEY", "")).encode()
    return hmac.new(secret, f"{order_id}:{filename}:{expires}".encode(), hashlib.sha256).hexdigest()


def _proof_url(order_id: str, filename: str) -> str:
    expires = int(datetime.now(timezone.utc).timestamp()) + 7 * 24 * 60 * 60
    sig = _proof_signature(order_id, filename, expires)
    return f"{request.url_root.rstrip('/')}/takhfid/api/v2/orders/{order_id}/payment-proof/file/{filename}?expires={expires}&sig={sig}"


def _authorized_order(order_id: str):
    customer = _current_customer()
    if not customer:
        return None, (jsonify({"success": False, "error": "غير مصرح أو انتهت الجلسة"}), 401)
    order = db.session.get(TakhfidOrder, order_id)
    if not order:
        return None, (jsonify({"success": False, "error": "الطلب غير موجود"}), 404)
    if not customer.is_admin and order.customer_id != customer.uid:
        return None, (jsonify({"success": False, "error": "غير مصرح"}), 403)
    return order, None


@takhfid_chat_v2_bp.get("/orders/<order_id>/chat")
def list_chat_messages_v2(order_id: str):
    order, error = _authorized_order(order_id)
    if error:
        return error
    rows = TakhfidChatMessage.query.filter_by(order_id=order.id).order_by(TakhfidChatMessage.created_at.asc()).limit(300).all()
    return jsonify({"success": True, "messages": [_public_message(row) for row in rows]})


@takhfid_chat_v2_bp.post("/orders/<order_id>/chat/messages")
def send_chat_message_v2(order_id: str):
    order, error = _authorized_order(order_id)
    if error:
        return error
    customer = _current_customer()
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text") or "").strip()
    message_type = str(payload.get("type") or "text").strip() or "text"
    image_url = str(payload.get("imageUrl") or "").strip() or None
    if message_type == "text" and not text:
        return jsonify({"success": False, "error": "نص الرسالة مطلوب"}), 400
    if message_type not in {"text", "payment_proof", "system", "order_snapshot"}:
        return jsonify({"success": False, "error": "نوع الرسالة غير صالح"}), 400
    now = datetime.now(timezone.utc)
    row = TakhfidChatMessage(order_id=order.id, sender_id=customer.uid, sender_role="admin" if customer.is_admin else "customer", type=message_type, text=text or None, image_url=image_url, created_at=now)
    db.session.add(row)
    db.session.commit()
    message = _public_message(row)
    socketio.emit("takhfid:chat_message", message, room=f"takhfid-order:{order.id}")
    return jsonify({"success": True, "message": message})


@takhfid_chat_v2_bp.post("/orders/<order_id>/payment-proof/upload")
def upload_payment_proof_v2(order_id: str):
    order, error = _authorized_order(order_id)
    if error:
        return error
    customer = _current_customer()
    if customer.is_admin:
        return jsonify({"success": False, "error": "العميل فقط يمكنه إرسال إثبات الدفع"}), 403
    file = request.files.get("file")
    note = str(request.form.get("note") or "").strip()
    if not file or not file.filename:
        return jsonify({"success": False, "error": "صورة إثبات الدفع مطلوبة"}), 400
    content_type = (file.mimetype or "").lower()
    if not content_type.startswith("image/"):
        return jsonify({"success": False, "error": "الملف يجب أن يكون صورة"}), 400
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > 5 * 1024 * 1024:
        return jsonify({"success": False, "error": "حجم الصورة يتجاوز 5MB"}), 400
    extension = Path(secure_filename(file.filename)).suffix.lower() or ".jpg"
    if extension not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return jsonify({"success": False, "error": "امتداد الصورة غير مسموح"}), 400
    filename = f"{secrets.token_urlsafe(18)}{extension}"
    file.save(_proof_dir() / filename)
    now = datetime.now(timezone.utc)
    image_url = _proof_url(order.id, filename)
    data = dict(order.payload or {})
    data.update({"status": "payment_submitted", "paymentProofUrl": image_url, "paymentNote": note, "updatedAt": now.isoformat()})
    order.payload = data
    order.status = "payment_submitted"
    order.updated_at = now
    row = TakhfidChatMessage(order_id=order.id, sender_id=customer.uid, sender_role="customer", type="payment_proof", text=note or "تم إرسال إثبات الدفع، يرجى المراجعة.", image_url=image_url, created_at=now)
    db.session.add(row)
    db.session.commit()
    message = _public_message(row)
    socketio.emit("takhfid:order_updated", {"order": data | {"id": order.id, "customerId": order.customer_id}}, room=f"takhfid-order:{order.id}")
    socketio.emit("takhfid:chat_message", message, room=f"takhfid-order:{order.id}")
    return jsonify({"success": True, "order": data | {"id": order.id, "customerId": order.customer_id}, "message": message, "url": image_url})


@takhfid_chat_v2_bp.get("/orders/<order_id>/payment-proof/file/<path:filename>")
def get_payment_proof_file(order_id: str, filename: str):
    expires = request.args.get("expires", type=int) or 0
    sig = request.args.get("sig", "")
    now = int(datetime.now(timezone.utc).timestamp())
    if expires < now or not sig or not hmac.compare_digest(sig, _proof_signature(order_id, filename, expires)):
        return jsonify({"success": False, "error": "الرابط غير صالح أو منتهي"}), 403
    return send_from_directory(_proof_dir(), Path(filename).name, conditional=True, max_age=3600)


@socketio.on("takhfid:join_order")
def join_order(data):
    from flask_socketio import join_room
    customer = _current_customer()
    if not customer:
        return
    order_id = str((data or {}).get("orderId") or "").strip()
    order = db.session.get(TakhfidOrder, order_id)
    if order and (customer.is_admin or order.customer_id == customer.uid):
        join_room(f"takhfid-order:{order_id}")


@socketio.on("takhfid:leave_order")
def leave_order(data):
    from flask_socketio import leave_room
    order_id = str((data or {}).get("orderId") or "").strip()
    if order_id:
        leave_room(f"takhfid-order:{order_id}")
