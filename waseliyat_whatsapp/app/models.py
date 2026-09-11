from datetime import datetime, timezone
import json
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash
from . import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    def set_password(self, value):
        self.password_hash = generate_password_hash(value)

    def check_password(self, value):
        return check_password_hash(self.password_hash, value)


class Contract(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(40), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    required = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class UserContract(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contract_id = db.Column(db.Integer, db.ForeignKey('contract.id'), nullable=False)
    accepted_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'contract_id', name='uq_user_contract'),)


class WhatsAppSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(120), nullable=False)
    api_base_url = db.Column(db.String(500), nullable=False)
    webhook_base_url = db.Column(db.String(500))
    active = db.Column(db.Boolean, default=True, nullable=False)
    status = db.Column(db.String(30), default='idle', nullable=False)
    qr_available = db.Column(db.Boolean, default=False, nullable=False)
    backup_phone = db.Column(db.String(32))
    last_error = db.Column(db.Text)
    info_json = db.Column(db.Text, default='{}', nullable=False)
    started_at = db.Column(db.DateTime(timezone=True))
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    last_message_at = db.Column(db.DateTime(timezone=True))
    incoming_count = db.Column(db.Integer, default=0, nullable=False)
    outgoing_count = db.Column(db.Integer, default=0, nullable=False)

    def api_url(self, action):
        return f"{self.api_base_url.rstrip('/')}/api/sessions/{self.name}/{action}"

    def update_from_status(self, data):
        self.status = data.get('status') or self.status
        self.qr_available = bool(data.get('qrAvailable'))
        self.backup_phone = data.get('backupPhone') or self.backup_phone
        self.last_error = data.get('lastError')
        self.info_json = json.dumps(data.get('info') or {}, ensure_ascii=False)
        self.last_message_at = _parse_dt(data.get('stats', {}).get('lastMessageAt'))
        self.incoming_count = int(data.get('stats', {}).get('incomingCount') or 0)
        self.outgoing_count = int(data.get('stats', {}).get('outgoingCount') or 0)
        self.started_at = _parse_dt(data.get('startedAt')) or self.started_at
        self.updated_at = utcnow()

    def to_public_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'api_base_url': self.api_base_url,
            'webhook_base_url': self.webhook_base_url,
            'active': self.active,
            'status': self.status,
            'qr_available': self.qr_available,
            'backup_phone': self.backup_phone,
            'last_error': self.last_error,
            'incoming_count': self.incoming_count,
            'outgoing_count': self.outgoing_count,
            'last_message_at': self.last_message_at.isoformat() if self.last_message_at else None,
        }


class MessageLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_name = db.Column(db.String(32), nullable=False, index=True)
    direction = db.Column(db.String(8), nullable=False)
    message_id = db.Column(db.String(200))
    sender = db.Column(db.String(100))
    recipient = db.Column(db.String(100))
    body = db.Column(db.Text, default='')
    message_type = db.Column(db.String(40), default='text')
    has_media = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_name = db.Column(db.String(32), index=True)
    level = db.Column(db.String(20), default='info', nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    read = db.Column(db.Boolean, default=False, nullable=False)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    action = db.Column(db.String(120), nullable=False)
    details = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, ValueError, TypeError):
        return None
