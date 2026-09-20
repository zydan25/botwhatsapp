import io
import os
import secrets
from datetime import timedelta

import pytest
from urllib.parse import quote


@pytest.fixture()
def app(tmp_path):
    os.environ.update(
        {
            "TESTING": "true",
            "SECRET_KEY": "ci-test-secret",
            "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}",
            "ADMIN_USERNAME": "ciadmin",
            "ADMIN_PASSWORD": "ci-admin-password-123",
            "TAKHFIID_ADMIN_PHONES": "967700000000",
            "TAKHFIID_OTP_HASH_SECRET": "ci-otp-secret",
            "STATUS_POLL_SECONDS": "999",
        }
    )
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True)
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


def _token(app, *, uid, phone, admin=False, first="عميل"):
    from app import db
    from app.takhfid_api import (
        TakhfidAccessToken,
        TakhfidCustomer,
        token_hash,
        utcnow,
    )

    raw = secrets.token_urlsafe(32)
    with app.app_context():
        customer = TakhfidCustomer(
            uid=uid,
            phone=phone,
            first_name=first,
            governorate="صنعاء",
            is_admin=admin,
            role="admin" if admin else "customer",
        )
        db.session.add(customer)
        db.session.flush()
        db.session.add(
            TakhfidAccessToken(
                customer_id=customer.id,
                token_hash=token_hash(raw),
                expires_at=utcnow() + timedelta(days=30),
            )
        )
        db.session.commit()
    return raw


def test_public_catalog_endpoints(client):
    for path in [
        "/takhfid/api/v4/health",
        "/takhfid/api/v4/store",
        "/takhfid/api/v4/content",
        "/takhfid/api/v4/categories",
        "/takhfid/api/v4/pricing",
        "/takhfid/api/v4/products?limit=1",
    ]:
        response = client.get(path)
        assert response.status_code == 200, (path, response.data[:500])
        assert response.is_json


def test_existing_customer_otp_returns_needs_profile_false(app, client):
    from app import db
    from app.takhfid_api import TakhfidCustomer, TakhfidOtp, hash_otp, utcnow

    phone = "967771111111"
    code = "123456"
    with app.app_context():
        customer = TakhfidCustomer(
            uid="usr_existing",
            phone=phone,
            first_name="محمد",
            governorate="صنعاء",
        )
        db.session.add(customer)
        db.session.add(
            TakhfidOtp(
                phone=phone,
                code_hash=hash_otp(phone, code),
                expires_at=utcnow() + timedelta(minutes=5),
                sent_at=utcnow(),
            )
        )
        db.session.commit()

    response = client.post(
        "/takhfid/api/v4/auth/verify-otp",
        json={"phoneNumber": phone, "otp": code},
    )
    data = response.get_json()
    assert response.status_code == 200
    assert data["needsProfile"] is False
    assert data["accessToken"]


def test_new_customer_otp_returns_needs_profile_true(app, client):
    from app import db
    from app.takhfid_api import TakhfidOtp, hash_otp, utcnow

    phone = "967772222222"
    code = "654321"
    with app.app_context():
        db.session.add(
            TakhfidOtp(
                phone=phone,
                code_hash=hash_otp(phone, code),
                expires_at=utcnow() + timedelta(minutes=5),
                sent_at=utcnow(),
            )
        )
        db.session.commit()

    response = client.post(
        "/takhfid/api/v4/auth/verify-otp",
        json={"phoneNumber": phone, "otp": code},
    )
    data = response.get_json()
    assert response.status_code == 200
    assert data["needsProfile"] is True
    assert data["user"]["phone"] == phone
    assert data["user"]["firstName"] == ""


def test_customer_order_creates_order_chat_and_notification(app, client):
    from app import db
    from app.takhfid_api import TakhfidProduct

    token = _token(
        app,
        uid="usr_order",
        phone="967773333333",
        first="مشتري",
    )

    with app.app_context():
        db.session.add(
            TakhfidProduct(
                id="p-ci",
                payload={
                    "name": "منتج اختبار",
                    "price": 100,
                    "currency": "YER",
                    "stock": 10,
                    "active": True,
                    "allowBackorder": False,
                },
            )
        )
        db.session.commit()

    headers = {"Authorization": f"Bearer {token}"}
    order_response = client.post(
        "/takhfid/api/v4/orders",
        headers=headers,
        json={
            "customerName": "مشتري",
            "customerPhone": "967773333333",
            "governorate": "صنعاء",
            "address": "صنعاء",
            "currency": "YER",
            "paymentMethod": "cash_on_delivery",
            "items": [
                {
                    "productId": "p-ci",
                    "quantity": 2,
                    "size": "M",
                    "color": "أسود",
                }
            ],
        },
    )
    data = order_response.get_json()
    assert order_response.status_code == 201
    assert data["chatSessionId"]
    order_id = data["orderId"]

    sessions = client.get(
        "/takhfid/api/v4/chat/sessions",
        headers=headers,
    )
    assert sessions.status_code == 200
    assert any(x["orderId"] == order_id for x in sessions.get_json()["sessions"])

    chat_id = data["chatSessionId"]
    upload = client.post(
        f"/takhfid/api/v4/chat/sessions/{chat_id}/media/upload",
        headers=headers,
        data={"file": (io.BytesIO(b"fake-jpeg"), "payment.jpg")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 201
    media = upload.get_json()["relativeUrl"]

    message = client.post(
        f"/takhfid/api/v4/chat/sessions/{chat_id}/messages",
        headers=headers,
        json={
            "text": "هذا سند الدفع",
            "mediaUrl": media,
            "mediaType": "image/jpeg",
            "fileName": "payment.jpg",
            "isPaymentProof": True,
        },
    )
    assert message.status_code == 201
    assert message.get_json()["message"]["isPaymentProof"] is True

    notifications = client.get(
        "/takhfid/api/v4/notifications",
        headers=headers,
    )
    assert notifications.status_code == 200
    assert any(
        x["orderId"] == order_id
        for x in notifications.get_json()["notifications"]
    )


def test_admin_order_status_and_chat_notify_customer(app, client):
    from app import db
    from app.takhfid_api import TakhfidProduct

    customer_token = _token(
        app,
        uid="usr_status",
        phone="967774444444",
        first="عميل الحالة",
    )
    admin_token = _token(
        app,
        uid="usr_admin",
        phone="967700000000",
        first="مدير",
        admin=True,
    )

    with app.app_context():
        db.session.add(
            TakhfidProduct(
                id="p-status",
                payload={
                    "name": "منتج حالة",
                    "price": 50,
                    "currency": "YER",
                    "stock": 5,
                    "active": True,
                },
            )
        )
        db.session.commit()

    customer_headers = {"Authorization": f"Bearer {customer_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    response = client.post(
        "/takhfid/api/v4/orders",
        headers=customer_headers,
        json={
            "customerName": "عميل الحالة",
            "customerPhone": "967774444444",
            "governorate": "صنعاء",
            "address": "صنعاء",
            "currency": "YER",
            "paymentMethod": "cash_on_delivery",
            "items": [{"productId": "p-status", "quantity": 1}],
        },
    )
    assert response.status_code == 201
    order_id = response.get_json()["orderId"]
    chat_id = response.get_json()["chatSessionId"]

    status = client.patch(
        f"/takhfid/api/v4/orders/{quote(order_id, safe='')}/status",
        headers=admin_headers,
        json={"status": "in_shipping"},
    )
    assert status.status_code == 200

    admin_message = client.post(
        f"/takhfid/api/v4/admin/chat/sessions/{chat_id}/messages",
        headers=admin_headers,
        json={"text": "طلبك خرج للشحن"},
    )
    assert admin_message.status_code == 201

    notifications = client.get(
        "/takhfid/api/v4/notifications",
        headers=customer_headers,
    )
    payload = notifications.get_json()
    assert notifications.status_code == 200
    assert any(x["type"] == "order_status" for x in payload["notifications"])
    assert any(x["type"] == "chat" for x in payload["notifications"])

    messages = client.get(
        f"/takhfid/api/v4/chat/sessions/{chat_id}/messages",
        headers=customer_headers,
    )
    assert messages.status_code == 200
    assert any(
        x["sender"] == "admin" for x in messages.get_json()["messages"]
    )


def test_customer_cannot_access_another_customer_chat(app, client):
    owner_token = _token(
        app,
        uid="usr_owner",
        phone="967775555555",
        first="صاحب",
    )
    intruder_token = _token(
        app,
        uid="usr_intruder",
        phone="967776666666",
        first="متطفل",
    )

    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    intruder_headers = {"Authorization": f"Bearer {intruder_token}"}

    create = client.post(
        "/takhfid/api/v4/chat/sessions",
        headers=owner_headers,
        json={},
    )
    assert create.status_code == 201
    chat_id = create.get_json()["session"]["id"]

    owner_read = client.get(
        f"/takhfid/api/v4/chat/sessions/{chat_id}/messages",
        headers=owner_headers,
    )
    assert owner_read.status_code == 200

    denied = client.get(
        f"/takhfid/api/v4/chat/sessions/{chat_id}/messages",
        headers=intruder_headers,
    )
    assert denied.status_code == 403
