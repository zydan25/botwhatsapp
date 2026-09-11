import os
import threading
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from flask import Flask
from flask_login import LoginManager
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy

load_dotenv()


db = SQLAlchemy()
login_manager = LoginManager()
socketio = SocketIO(async_mode='eventlet', cors_allowed_origins='*', manage_session=False)


def utcnow():
    return datetime.now(timezone.utc)


def _database_uri(app):
    """Return a safe database URI for the current deployment.

    Flask-SQLAlchemy resolves relative SQLite paths against Flask's instance path.
    The old value ``sqlite:///instance/waseliyat.db`` therefore points at
    ``instance/instance/waseliyat.db`` and can fail when the nested directory
    does not exist. Normalize that legacy value to the intended instance file.
    """
    uri = os.getenv('DATABASE_URL', '').strip()
    if not uri:
        return 'sqlite:///waseliyat.db'

    if uri.startswith('sqlite:///instance/'):
        filename = uri[len('sqlite:///instance/'):]
        return f'sqlite:///{filename}'

    return uri


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        SECRET_KEY=os.getenv('SECRET_KEY', 'dev-change-me'),
        SQLALCHEMY_DATABASE_URI=_database_uri(app),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        APP_NAME=os.getenv('APP_NAME', 'ربطيات واتساب'),
        APP_PORT=int(os.getenv('APP_PORT', '3333')),
        CONTRACT_VERSION=os.getenv('CONTRACT_VERSION', '1.0'),
        STATUS_POLL_SECONDS=max(2, int(os.getenv('STATUS_POLL_SECONDS', '4'))),
        WHATSAPP_API_BASE_URL=os.getenv('WHATSAPP_API_BASE_URL', 'https://whatsapp.alattab.site').rstrip('/'),
        WEBHOOK_SECRET=os.getenv('WEBHOOK_SECRET', ''),
    )

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'يرجى تسجيل الدخول أولاً.'
    socketio.init_app(app)

    from .models import User
    from .auth import auth_bp
    from .main import main_bp
    from .api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api/internal')

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    with app.app_context():
        db.create_all()
        _seed_data(app)

    _start_status_worker(app)
    return app


def _seed_data(app):
    from .models import User, Contract, WhatsAppSession
    from werkzeug.security import generate_password_hash

    username = os.getenv('ADMIN_USERNAME', 'zydan').strip()
    password = os.getenv('ADMIN_PASSWORD', '774952665')
    user = User.query.filter_by(username=username).first()
    if not user:
        user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(user)
    elif not user.password_hash:
        user.password_hash = generate_password_hash(password)

    version = app.config['CONTRACT_VERSION']
    contract = Contract.query.filter_by(version=version).first()
    if not contract:
        contract = Contract(
            version=version,
            title='عقد استخدام ربطيات واتساب',
            body=(
                'باستخدام المنصة أقر بأنني مسؤول عن أرقام واتساب والحسابات وواجهات API التي أربطها، '
                'وألتزم بالأنظمة والقوانين وشروط واتساب وبحماية مفاتيح الربط وعدم إساءة استخدام الإرسال.'
            ),
            required=True,
        )
        db.session.add(contract)
    db.session.commit()

    if not WhatsAppSession.query.first():
        session = WhatsAppSession(
            name='basheer',
            display_name='الجلسة الأولى',
            api_base_url=app.config['WHATSAPP_API_BASE_URL'],
            webhook_base_url='',
            active=True,
        )
        db.session.add(session)
        db.session.commit()


def _start_status_worker(app):
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'false':
        return
    key = f"{id(app)}-status-worker"
    if getattr(app, key, False):
        return
    setattr(app, key, True)

    def worker():
        time.sleep(2)
        from .models import WhatsAppSession
        from .services.whatsapp import WhatsAppClient
        while True:
            try:
                with app.app_context():
                    sessions = WhatsAppSession.query.filter_by(active=True).all()
                    for session in sessions:
                        client = WhatsAppClient(session)
                        result = client.status(timeout=7)
                        if result.get('ok'):
                            session.update_from_status(result['data'])
                            db.session.commit()
                            socketio.emit('session:update', session.to_public_dict())
            except Exception as exc:
                app.logger.exception('status worker error: %s', exc)
            time.sleep(app.config['STATUS_POLL_SECONDS'])

    t = threading.Thread(target=worker, name='waseliyat-status-worker', daemon=True)
    t.start()
