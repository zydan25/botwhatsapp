from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from . import db
from .models import User, Contract, UserContract, AuditLog


auth_bp = Blueprint('auth', __name__)


@auth_bp.get('/login')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('login.html')


@auth_bp.post('/login')
def login_post():
    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        flash('اسم المستخدم أو كلمة المرور غير صحيحة.', 'danger')
        return render_template('login.html', username=username), 401
    login_user(user)
    contract = Contract.query.filter_by(required=True).order_by(Contract.id.desc()).first()
    if contract and not UserContract.query.filter_by(user_id=user.id, contract_id=contract.id).first():
        return redirect(url_for('main.contracts'))
    return redirect(url_for('main.dashboard'))


@auth_bp.get('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@auth_bp.get('/settings/account')
@login_required
def account_settings():
    return render_template('account_settings.html')


@auth_bp.post('/settings/account')
@login_required
def account_settings_post():
    new_username = (request.form.get('username') or '').strip()
    current_password = request.form.get('current_password') or ''
    new_password = request.form.get('new_password') or ''
    if not current_user.check_password(current_password):
        flash('كلمة المرور الحالية غير صحيحة.', 'danger')
        return redirect(url_for('auth.account_settings'))
    if not new_username or len(new_username) < 3:
        flash('اسم المستخدم يجب أن يكون 3 أحرف على الأقل.', 'danger')
        return redirect(url_for('auth.account_settings'))
    exists = User.query.filter(User.username == new_username, User.id != current_user.id).first()
    if exists:
        flash('اسم المستخدم مستخدم بالفعل.', 'danger')
        return redirect(url_for('auth.account_settings'))
    current_user.username = new_username
    if new_password:
        if len(new_password) < 8:
            flash('كلمة المرور الجديدة يجب أن تكون 8 محارف على الأقل.', 'danger')
            return redirect(url_for('auth.account_settings'))
        current_user.set_password(new_password)
    db.session.add(AuditLog(user_id=current_user.id, action='account.updated', details='تم تحديث بيانات الدخول'))
    db.session.commit()
    flash('تم تحديث بيانات الحساب.', 'success')
    return redirect(url_for('main.dashboard'))
