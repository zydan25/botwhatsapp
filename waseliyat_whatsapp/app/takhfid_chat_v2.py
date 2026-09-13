from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request
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
    return {"id": str(row.id), "orderId": row.order_id, "senderId": row.sender_id, "senderRole": row.sender_role, "type": row.type, "text": row.text, "imageUrl": row.image_url, "createdAt": row.created_at.isoformat()}


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
    message_type = str(payload.get("type") or "text").strip() or "text"
    text = str(payload.get("text") or "").strip()
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
    if not file or not file.filename:
        return jsonify({"success": False, "error": "لم يتم إرسال صورة"}), 400
    if not (file.mimetype or "").startswith("image/"):
        return jsonify({"success": False, "error": "يسمح بالصور فقط"}), 400
    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > 5 * 1024 * 1024:
        return jsonify({"success": False, "error": "حجم الصورة أكبر من 5MB"}), 400
    root = Path(current_app.instance_path) / "takhfid_uploads" / "payment-proofs" / order.id
    root.mkdir(parents=True, exist_ok=True)
    original = secure_filename(file.filename) or "proof.jpg"
    name = f"{int(datetime.now(timezone.utc).timestamp() * 1000)}-{secrets.token_hex(4)}-{original}"
    path = root / name
    file.save(path)
    url = f"/takhfid/uploads/payment-proofs/{order.id}/{name}"
    note = str(request.form.get("note") or "إشعار تحويل من العميل").strip()
    now = datetime.now(timezone.utc)
    data = dict(order.payload or {})
    data.update({"status": "payment_submitted", "paymentProofUrl": url, "paymentNote": note, "updatedAt": now.isoformat()})
    order.payload = data
    order.status = "payment_submitted"
    order.updated_at = now
    row = TakhfidChatMessage(order_id=order.id, sender_id=customer.uid, sender_role="customer", type="payment_proof", text=note, image_url=url, created_at=now)
    db.session.add(row)
    db.session.commit()
    message = _public_message(row)
    public_order = data | {"id": order.id, "customerId": order.customer_id}
    socketio.emit("takhfid:order_updated", {"order": public_order}, room=f"takhfid-order:{order.id}")
    socketio.emit("takhfid:chat_message", message, room=f"takhfid-order:{order.id}")
    return jsonify({"success": True, "order": public_order, "message": message, "url": url})


@socketio.on("takhfid:join_order")
def join_order(data):
    from flask_socketio import join_room
    customer = _current_customer()
    if not customer:
        return
    order_id = str((data or {}).get("orderId") or "").strip()
    order = db.session.get(TakhfidOrder, order_id)
    if not order or (not customer.is_admin and order.customer_id != customer.uid):
        return
    join_room(f"takhfid-order:{order_id}")


@socketio.on("takhfid:leave_order")
def leave_order(data):
    from flask_socketio import leave_room
    order_id = str((data or {}).get("orderId") or "").strip()
    if order_id:
        leave_room(f"takhfid-order:{order_id}")
