#!/usr/bin/env python3
"""Initialize the Waseliyat/Takhfid PostgreSQL database safely.

The script uses the same SQLAlchemy models as the application, so schema and
runtime models cannot silently drift apart. It is idempotent: existing rows
are preserved and only missing defaults are inserted.

Required environment variables in production:
  DATABASE_URL=postgresql+psycopg://...
  SECRET_KEY=...
  ADMIN_USERNAME=...
  ADMIN_PASSWORD=...
  TAKHFIID_ADMIN_PHONES=9677xxxxxxxx
  TAKHFIID_OTP_HASH_SECRET=...

Optional:
  WHATSAPP_API_BASE_URL=https://whatsapp.alattab.site
  TAKHFIID_WHATSAPP_SESSION=basheer
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app, db  # noqa: E402
from app.models import User, WhatsAppSession  # noqa: E402
from app.takhfid_api import (  # noqa: E402
    GOVERNORATES,
    PUBLIC_SETTING_DEFAULTS,
    TakhfidCustomer,
    TakhfidSetting,
    save_json_setting,
    save_setting,
)
from sqlalchemy import text  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402


def require_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("DATABASE_URL غير مضبوط؛ ارفض تشغيل التهيئة بدون قاعدة محددة.")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise SystemExit("هذه التهيئة مخصصة لـ PostgreSQL. اضبط DATABASE_URL بصيغة postgresql+psycopg://...")
    return url


def normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = "967" + digits[1:]
    if len(digits) == 9 and digits.startswith("7"):
        digits = "967" + digits
    return digits


def upsert_json_setting(key: str, value) -> None:
    row = TakhfidSetting.query.filter_by(key=key).first()
    if row is None:
        save_json_setting(key, value)


def seed() -> dict[str, int]:
    require_database_url()
    app = create_app()

    with app.app_context():
        # Hard connectivity check before reporting success.
        db.session.execute(text("SELECT 1"))

        # Global application defaults already created by create_app(); persist
        # every governorate pricing record so admin edits survive deployments.
        for key, value in PUBLIC_SETTING_DEFAULTS.items():
            upsert_json_setting(key, value)

        for governorate, pricing in GOVERNORATES.items():
            upsert_json_setting(f"pricing:{governorate}", pricing)

        admin_phones_raw = os.getenv("TAKHFIID_ADMIN_PHONES", "")
        if not TakhfidSetting.query.filter_by(key="admin_phones").first():
            save_setting(
                "admin_phones",
                ",".join(filter(None, (normalize_phone(x) for x in admin_phones_raw.split(",")))),
            )

        otp_secret = os.getenv("TAKHFIID_OTP_HASH_SECRET") or os.getenv("OTP_HASH_SECRET")
        if otp_secret and not TakhfidSetting.query.filter_by(key="otp_hash_secret").first():
            save_setting("otp_hash_secret", otp_secret, secret=True)

        # Ensure the Flask admin account exists. Password comes only from the
        # environment and is never written to this repository.
        username = os.getenv("ADMIN_USERNAME", "zydan").strip()
        password = os.getenv("ADMIN_PASSWORD", "").strip()
        if username and password:
            user = User.query.filter_by(username=username).first()
            if user is None:
                user = User(username=username, password_hash=generate_password_hash(password))
                db.session.add(user)
            elif not user.password_hash:
                user.password_hash = generate_password_hash(password)

        # Ensure the configured WhatsApp session exists for OTP delivery.
        session_name = os.getenv("TAKHFIID_WHATSAPP_SESSION", "basheer").strip() or "basheer"
        if WhatsAppSession.query.filter_by(name=session_name).first() is None:
            session = WhatsAppSession(
                name=session_name,
                display_name="جلسة التخفيض",
                api_base_url=os.getenv("WHATSAPP_API_BASE_URL", "https://whatsapp.alattab.site").rstrip("/"),
                webhook_base_url="",
                active=True,
            )
            db.session.add(session)

        # Create the phone-based Takhfid admin record when a phone was
        # explicitly configured. This keeps API admin auth independent from
        # the Flask dashboard account while allowing one operator to use both.
        admin_phone = next((normalize_phone(x) for x in admin_phones_raw.split(",") if normalize_phone(x)), "")
        customer_count = 0
        if admin_phone:
            customer = TakhfidCustomer.query.filter_by(phone=admin_phone).first()
            if customer is None:
                customer = TakhfidCustomer(
                    uid=f"usr_{admin_phone}",
                    phone=admin_phone,
                    first_name="مدير المتجر",
                    governorate="أمانة العاصمة",
                    role="admin",
                    is_admin=True,
                )
                db.session.add(customer)
            else:
                customer.role = "admin"
                customer.is_admin = True
                customer.first_name = customer.first_name or "مدير المتجر"
            customer_count = 1

        db.session.commit()

        counts = {
            "users": User.query.count(),
            "whatsapp_sessions": WhatsAppSession.query.count(),
            "settings": TakhfidSetting.query.count(),
            "customers": TakhfidCustomer.query.count(),
            "admin_customers": customer_count or TakhfidCustomer.query.filter_by(is_admin=True).count(),
            "products": __import__("app.takhfid_api", fromlist=["TakhfidProduct"]).TakhfidProduct.query.count(),
            "orders": __import__("app.takhfid_api", fromlist=["TakhfidOrder"]).TakhfidOrder.query.count(),
        }
        return counts


if __name__ == "__main__":
    try:
        result = seed()
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"DATABASE INITIALIZATION FAILED: {exc}", file=sys.stderr)
        raise
    print("Takhfid PostgreSQL initialization completed successfully.")
    for key, value in result.items():
        print(f"{key}={value}")
