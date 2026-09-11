import os
import tempfile
from flask import Blueprint, jsonify, request, send_file
from flask_login import current_user, login_required
from . import db, socketio
from .models import WhatsAppSession, MessageLog, Notification, AuditLog
from .services.whatsapp import WhatsAppClient

api_bp = Blueprint('api', __name__)


def get_session(session_id):
    session = db.get_or_404(WhatsAppSession, session_id)
    return session


def _webhook_guard():
    secret = __import__('flask').current_app.config.get('WEBHOOK_SECRET', '')
    if secret and request.headers.get('X-Waseliyat-Webhook-Secret') != secret:
        return jsonify({'success': False, 'error': 'invalid webhook secret'}), 401
    return None


def _notify(session, level, title, body):
    n = Notification(session_name=session.name, level=level, title=title, body=body)
    db.session.add(n)
    db.session.commit()
    socketio.emit('session:notification', {
        'session': session.name, 'level': level, 'title': title, 'body': body,
    })


@api_bp.post('/sessions/<int:session_id>/action/<action>')
@login_required
def session_action(session_id, action):
    session = get_session(session_id)
    client = WhatsAppClient(session)
    methods = {'connect': client.connect, 'disconnect': client.disconnect, 'logout': client.logout}
    if action not in methods:
        return jsonify({'success': False, 'error': 'إجراء غير مدعوم'}), 400
    result = methods[action]()
    if result.get('ok'):
        db.session.add(AuditLog(user_id=current_user.id, action=f'session.{action}', details=session.name))
        db.session.commit()
        status = client.status(timeout=7)
        if status.get('ok'):
            session.update_from_status(status['data']); db.session.commit()
        _notify(session, 'success', 'تم تنفيذ العملية', f'{action}: {session.name}')
        return jsonify({'success': True, 'result': result, 'session': session.to_public_dict()})
    return jsonify(result), 502


@api_bp.get('/sessions/<int:session_id>/qr-image')
@login_required
def qr_image(session_id):
    session = get_session(session_id)
    result = WhatsAppClient(session).qr_image()
    if not result.get('ok'):
        return jsonify(result), 502
    return send_file(__import__('io').BytesIO(result['bytes']), mimetype=result.get('content_type', 'image/png'))


@api_bp.post('/sessions/<int:session_id>/send')
@login_required
def send_message(session_id):
    session = get_session(session_id)
    if session.status != 'connected':
        return jsonify({'success': False, 'error': 'الجلسة غير متصلة. يجب أن تكون connected.'}), 409
    phone = (request.form.get('phoneNumber') or '').strip()
    message = request.form.get('message') or ''
    media = request.files.get('media')
    path = None
    try:
        if media and media.filename:
            fd, path = tempfile.mkstemp(prefix='waseliyat_', suffix='_' + os.path.basename(media.filename))
            os.close(fd)
            media.save(path)
        result = WhatsAppClient(session).send(phone, message, path)
    finally:
        if path:
            try: os.remove(path)
            except OSError: pass
    if not result.get('ok'):
        return jsonify(result), 502
    payload = result.get('data') or {}
    msg = MessageLog(session_name=session.name, direction='out', message_id=payload.get('messageId'),
                     recipient=phone, body=message, message_type='media' if media and media.filename else 'text',
                     has_media=bool(media and media.filename))
    db.session.add(msg)
    db.session.add(AuditLog(user_id=current_user.id, action='message.sent', details=f'{session.name}:{phone}'))
    session.outgoing_count += 1
    db.session.commit()
    socketio.emit('session:notification', {'session': session.name, 'level': 'success', 'title': 'تم الإرسال', 'body': f'إلى {phone}'})
    return jsonify({'success': True, 'result': result, 'message_id': payload.get('messageId')})


@api_bp.get('/sessions/<int:session_id>/messages')
@login_required
def messages(session_id):
    session = get_session(session_id)
    result = WhatsAppClient(session).messages(request.args.get('limit', 50), request.args.get('offset', 0))
    return jsonify(result), 200 if result.get('ok') else 502


@api_bp.get('/sessions/<int:session_id>/errors')
@login_required
def errors(session_id):
    session = get_session(session_id)
    result = WhatsAppClient(session).errors(request.args.get('limit', 25))
    return jsonify(result), 200 if result.get('ok') else 502


@api_bp.get('/sessions/<int:session_id>/notifications')
@login_required
def session_notifications(session_id):
    session = get_session(session_id)
    result = WhatsAppClient(session).notifications(request.args.get('limit', 50))
    return jsonify(result), 200 if result.get('ok') else 502


@api_bp.post('/webhook/whatsapp')
def webhook_whatsapp():
    guard = _webhook_guard()
    if guard: return guard
    data = request.get_json(silent=True) or {}
    name = data.get('session') or data.get('botId')
    session = WhatsAppSession.query.filter_by(name=name).first() if name else None
    if not session:
        return jsonify({'success': False, 'error': 'session not found'}), 404
    db.session.add(MessageLog(
        session_name=name, direction=data.get('direction', 'in'), message_id=data.get('messageId'),
        sender=data.get('from'), recipient=data.get('to'), body=data.get('body') or '',
        message_type=data.get('type') or 'chat', has_media=bool(data.get('hasMedia')),
    ))
    if data.get('direction') == 'in':
        session.incoming_count += 1
        session.last_message_at = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
    db.session.commit()
    socketio.emit('session:update', session.to_public_dict())
    socketio.emit('message:new', data)
    return jsonify({'success': True})


@api_bp.post('/webhook/session-status')
def webhook_status():
    guard = _webhook_guard()
    if guard: return guard
    data = request.get_json(silent=True) or {}
    name = data.get('session') or data.get('botId')
    session = WhatsAppSession.query.filter_by(name=name).first() if name else None
    if not session:
        return jsonify({'success': False, 'error': 'session not found'}), 404
    session.status = data.get('status') or session.status
    db.session.add(Notification(session_name=name, level='info', title='تحديث حالة الجلسة', body=str(session.status)))
    db.session.commit()
    socketio.emit('session:update', session.to_public_dict())
    return jsonify({'success': True})


@api_bp.post('/webhook/qr')
def webhook_qr():
    guard = _webhook_guard()
    if guard: return guard
    data = request.get_json(silent=True) or {}
    name = data.get('session') or data.get('botId')
    session = WhatsAppSession.query.filter_by(name=name).first() if name else None
    if not session:
        return jsonify({'success': False, 'error': 'session not found'}), 404
    session.status = 'qr'
    session.qr_available = bool(data.get('qrCode'))
    db.session.add(Notification(session_name=name, level='info', title='رمز QR جديد', body='الجلسة تنتظر المسح من واتساب.'))
    db.session.commit()
    socketio.emit('session:update', session.to_public_dict())
    return jsonify({'success': True})
