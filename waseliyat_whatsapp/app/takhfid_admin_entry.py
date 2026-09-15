from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, current_app, redirect, render_template, request, url_for, flash
from flask_login import current_user, login_user, logout_user, login_required
from sqlalchemy import text

from . import db
from .models import User, Contract, UserContract

bp = Blueprint("takhfid_admin_entry", __name__, url_prefix="/store-admin")


def _safe_next(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return url_for("takhfid_admin_center.dashboard")
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/"):
        return url_for("takhfid_admin_center.dashboard")
    return value


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_safe_next(request.args.get("next")))
    next_url = request.args.get("next") or request.form.get("next") or ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            flash("اسم المستخدم أو كلمة المرور غير صحيحة.", "danger")
            return render_template("takhfid_center/login.html", next_url=next_url, username=username), 401
        login_user(user)
        contract = Contract.query.filter_by(required=True).order_by(Contract.id.desc()).first()
        if contract and not UserContract.query.filter_by(user_id=user.id, contract_id=contract.id).first():
            return redirect(url_for("main.contracts", next=_safe_next(next_url)))
        return redirect(_safe_next(next_url))
    return render_template("takhfid_center/login.html", next_url=next_url)


@bp.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("takhfid_admin_entry.login"))


@bp.get("/status")
@login_required
def status():
    db_ok = False
    db_error = ""
    try:
        db.session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # pragma: no cover - visual diagnostics only
        db_error = str(exc)
        db.session.rollback()
    sessions = []
    try:
        from .models import WhatsAppSession
        sessions = WhatsAppSession.query.order_by(WhatsAppSession.id.asc()).all()
    except Exception:
        pass
    return render_template(
        "takhfid_center/status.html",
        db_ok=db_ok,
        db_error=db_error,
        database=current_app.config.get("SQLALCHEMY_DATABASE_URI", ""),
        sessions=sessions,
    )
