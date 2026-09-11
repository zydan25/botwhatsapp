import io
import json
from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from . import db
from .models import Contract, UserContract, WhatsAppSession, Notification, AuditLog
from .services.whatsapp import WhatsAppClient

main_bp = Blueprint('main', __name__)


def _contract_needed():
    contract = Contract.query.filter_by(required=True).order_by(Contract.id.desc()).first()
    if not contract:
        return None
    accepted = UserContract.query.filter_by(user_id=current_user.id, contract_id=contract.id).first()
    return None if accepted else contract


@main_bp.before_request
def require_contract():
    if request.endpoint in {'auth.login', 'auth.login_post', 'auth.logout', 'main.contracts', 'main.contracts_accept', 'static'}:
        return
    if current_user.is_authenticated:
        contract = _contract_needed()
        if contract:
            return redirect(url_for('main.contracts'))


@main_bp.get('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@main_bp.get('/dashboard')
@login_required
def dashboard():
    sessions = WhatsAppSession.query.order_by(WhatsAppSession.id.desc()).all()
    unread = Notification.query.filter_by(read=False).count()
    return render_template('dashboard.html', sessions=sessions, unread=unread)


@main_bp.route('/contracts', methods=['GET'])
def contracts():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))
    contract = Contract.query.filter_by(required=True).order_by(Contract.id.desc()).first()
    return render_template('contracts.html', contract=contract)


@main_bp.post('/contracts/accept')
@login_required
def contracts_accept():
    contract = Contract.query.filter_by(required=True).order_by(Contract.id.desc()).first()
    if not contract:
        return redirect(url_for('main.dashboard'))
    if not UserContract.query.filter_by(user_id=current_user.id, contract_id=contract.id).first():
        db.session.add(UserContract(user_id=current_user.id, contract_id=contract.id))
        db.session.add(AuditLog(user_id=current_user.id, action='contract.accepted', details=f'version={contract.version}'))
        db.session.commit()
    return redirect(url_for('main.dashboard'))


@main_bp.get('/sessions/new')
@login_required
def session_new():
    return render_template('session_form.html', session=None)


@main_bp.post('/sessions/new')
@login_required
def session_new_post():
    name = (request.form.get('name') or '').strip().lower()
    display_name = (request.form.get('display_name') or name).strip()
    api_base_url = (request.form.get('api_base_url') or '').strip().rstrip('/')
    webhook_base_url = (request.form.get('webhook_base_url') or '').strip().rstrip('/')
    if not name or not (3 <= len(name) <= 32) or not name[0].isalpha() or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_- ' for c in name):
        flash('اسم الجلسة يجب أن يبدأ بحرف إنجليزي ويكون بين 3 و32 محرفًا.', 'danger')
        return render_template('session_form.html', session=None)
    name = name.replace(' ', '')
    if WhatsAppSession.query.filter_by(name=name).first():
        flash('اسم الجلسة موجود بالفعل.', 'danger')
        return render_template('session_form.html', session=None)
    if not api_base_url.startswith(('http://', 'https://')):
        flash('رابط API يجب أن يبدأ بـ http:// أو https://.', 'danger')
        return render_template('session_form.html', session=None)
    session = WhatsAppSession(name=name, display_name=display_name, api_base_url=api_base_url, webhook_base_url=webhook_base_url, active=True)
    db.session.add(session)
    db.session.add(AuditLog(user_id=current_user.id, action='session.created', details=name))
    db.session.commit()
    flash('تمت إضافة الجلسة.', 'success')
    return redirect(url_for('main.session_detail', session_id=session.id))


@main_bp.get('/sessions/<int:session_id>')
@login_required
def session_detail(session_id):
    session = db.get_or_404(WhatsAppSession, session_id)
    return render_template('session_detail.html', session=session)


@main_bp.post('/sessions/<int:session_id>/settings')
@login_required
def session_settings(session_id):
    session = db.get_or_404(WhatsAppSession, session_id)
    display_name = (request.form.get('display_name') or '').strip()
    api_base_url = (request.form.get('api_base_url') or '').strip().rstrip('/')
    webhook_base_url = (request.form.get('webhook_base_url') or '').strip().rstrip('/')
    if not display_name:
        flash('اسم العرض مطلوب.', 'danger')
        return redirect(url_for('main.session_detail', session_id=session.id))
    if not api_base_url.startswith(('http://', 'https://')):
        flash('رابط بوابة WhatsApp API غير صالح.', 'danger')
        return redirect(url_for('main.session_detail', session_id=session.id))
    if webhook_base_url and not webhook_base_url.startswith(('http://', 'https://')):
        flash('رابط API الخارجي غير صالح.', 'danger')
        return redirect(url_for('main.session_detail', session_id=session.id))
    session.display_name = display_name
    session.api_base_url = api_base_url
    session.webhook_base_url = webhook_base_url
    db.session.commit()
    remote = WhatsAppClient(session).set_api_url(webhook_base_url) if webhook_base_url else {'ok': True}
    db.session.add(AuditLog(user_id=current_user.id, action='session.updated', details=session.name))
    db.session.commit()
    if webhook_base_url and not remote.get('ok'):
        flash('تم حفظ الإعدادات محليًا، لكن تعذر تحديث api-url في خادم واتساب.', 'danger')
    else:
        flash('تم حفظ إعدادات الجلسة وتحديث API الخارجي.', 'success')
    return redirect(url_for('main.session_detail', session_id=session.id))


@main_bp.get('/api-guide')
@login_required
def api_guide():
    session = WhatsAppSession.query.order_by(WhatsAppSession.id.asc()).first()
    return render_template('api_guide.html', session=session)


@main_bp.get('/api-guide.pdf')
@login_required
def api_guide_pdf():
    session = WhatsAppSession.query.order_by(WhatsAppSession.id.asc()).first()
    base = session.api_base_url if session else 'https://whatsapp.alattab.site'
    name = session.name if session else 'basheer'
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    if not __import__('os').path.exists(font_path):
        font_path = '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'
    try:
        pdfmetrics.registerFont(TTFont('AppFont', font_path))
        pdf.setFont('AppFont', 16)
    except Exception:
        pdf.setFont('Helvetica', 14)
    pdf.drawString(50, 800, 'Waseliyat WhatsApp - API Guide')
    lines = [
        f'Base URL: {base}',
        f'Session: {name}',
        '',
        'Status: GET /api/sessions/{session}/status',
        'QR: GET /api/sessions/{session}/qr-image',
        'Connect: POST /api/sessions/{session}/connect',
        'Disconnect: POST /api/sessions/{session}/disconnect',
        'Logout: POST /api/sessions/{session}/logout',
        'Send: POST /api/sessions/{session}/send (multipart/form-data)',
        'API URL: POST /api/sessions/{session}/api-url',
        'Messages: GET /api/sessions/{session}/messages',
        'Errors: GET /api/sessions/{session}/errors',
        'Notifications: GET /api/sessions/{session}/notifications',
        '',
        'Send fields: phoneNumber, message, media(optional)',
        'Webhook: POST https://YOUR-BACKEND/webhook/whatsapp',
        'Webhook status: POST https://YOUR-BACKEND/webhook/session-status',
        'Webhook QR: POST https://YOUR-BACKEND/webhook/qr',
    ]
    y = 770
    pdf.setFont('AppFont' if 'AppFont' in pdf._fontname else 'Helvetica', 10)
    for line in lines:
        if y < 50:
            pdf.showPage(); y = 800
        pdf.drawString(50, y, line)
        y -= 19
    pdf.save(); buffer.seek(0)
    return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name='waseliyat-whatsapp-api-guide.pdf')


@main_bp.get('/notifications')
@login_required
def notifications():
    items = Notification.query.order_by(Notification.id.desc()).limit(100).all()
    for item in items:
        item.read = True
    db.session.commit()
    return render_template('notifications.html', notifications=items)
