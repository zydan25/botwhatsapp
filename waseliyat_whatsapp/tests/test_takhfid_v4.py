import hashlib
import hmac
import os
import secrets
from datetime import timedelta

import pytest


@pytest.fixture()
def app(tmp_path):
    os.environ.update({
        "TESTING": "true",
        "SECRET_KEY": "ci-test-secret",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}",
        "ADMIN_USERNAME": "ciadmin",
        "ADMIN_PASSWORD": "ci-admin-password-123",
        "TAKHFIID_ADMIN_PHONES": "967700000000",
        "TAKHFIID_OTP_HASH_SECRET": "ci-otp-secret",
        "STATUS_POLL_SECONDS": "999",
    })
    from app import create_app
    application = create_app()
    application.config.update(TESTING=True)
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


def test_health(client):
    response = client.get("/takhfid/api/v4/health")
    assert response.status_code == 200
    assert response.get_json().get("success") is True


def test_public_catalog_endpoints(client):
    for path in [
        "/takhfid/api/v4/store",
        "/takhfid/api/v4/content",
        "/takhfid/api/v4/categories",
        "/takhfid/api/v4/pricing",
        "/takhfid/api/v4/products",
    ]:
        response = client.get(path)
        assert response.status_code == 200, (path, response.data[:500])
        assert response.is_json


def test_customer_token_me_and_legacy_token_survives(app, client):
    from app import db
    from app.takhfid_api import TakhfidAccessToken, TakhfidCustomer, token_hash, utcnow

    raw = secrets.token_urlsafe(32)
    with app.app_context():
        customer = TakhfidCustomer(
            uid="usr_ci_customer",
            phone="967711111111",
            first_name="اختبار",
            governorate="أمانة العاصمة",
        )
        db.session.add(customer)
        db.session.flush()
        db.session.add(TakhfidAccessToken(
            customer_id=customer.id,
            token_hash=token_hash(raw),
            expires_at=utcnow() + timedelta(days=30),
        ))
        db.session.commit()

    response = client.get("/takhfid/api/v4/auth/me", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == 200
    assert response.get_json()["customer"]["uid"] == "usr_ci_customer"


def test_admin_web_requires_login(client):
    response = client.get("/takhfid/admin/", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/login" in response.headers["Location"]


def test_admin_web_product_create_and_pwa(client):
    with client.session_transaction() as session:
        session["_user_id"] = "1"
        session["_fresh"] = True

    page = client.get("/takhfid/admin/products")
    assert page.status_code == 200
    csrf = client.get_cookie("tk_admin_csrf")
    csrf_value = csrf.value if csrf else ""
    assert csrf_value

    response = client.post(
        "/takhfid/admin/products/save",
        data={
            "csrf_token": csrf_value,
            "name": "منتج CI",
            "price": "100",
            "stock": "5",
            "currency": "YER",
            "sizes": "[]",
            "colors": "[]",
            "variants": "[]",
            "attributes": "{}",
            "tags": "[]",
            "active": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}

    manifest = client.get("/takhfid/admin/pwa/manifest.webmanifest")
    assert manifest.status_code == 200
    sw = client.get("/takhfid/admin/sw.js")
    assert sw.status_code == 200
    assert sw.headers.get("Service-Worker-Allowed") == "/takhfid/admin/"
