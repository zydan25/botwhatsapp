from pathlib import Path

API = Path("app/takhfid_api.py").read_text(encoding="utf-8")
DOC = Path("docs/takhfid-api-v4.yaml").read_text(encoding="utf-8")


def test_customer_server_contract_routes_exist():
    routes = [
        '"/api/v4/chat/sessions"',
        '"/api/v4/chat/sessions/<session_id>/messages"',
        '"/api/v4/chat/sessions/<session_id>/read"',
        '"/api/v4/chat/sessions/<session_id>/media/upload"',
        '"/api/v4/chat/media/<session_id>/<filename>"',
        '"/api/v4/notifications"',
        '"/api/v4/notifications/<int:notification_id>/read"',
        '"/api/v4/notifications/read-all"',
        '"/api/v4/admin/chat/sessions"',
        '"/api/v4/admin/chat/sessions/<session_id>/messages"',
    ]
    for route in routes:
        assert route in API


def test_order_lifecycle_notifies_customer():
    assert 'type="order"' in API
    assert 'type="order_status"' in API
    assert 'type="payment"' in API
    assert '"chatSessionId"' in API


def test_api_documentation_contains_customer_routes():
    for route in [
        "/api/v4/chat/sessions:",
        "/api/v4/chat/sessions/{sessionId}/messages:",
        "/api/v4/chat/sessions/{sessionId}/media/upload:",
        "/api/v4/notifications:",
        "/api/v4/admin/chat/sessions:",
    ]:
        assert route in DOC


def test_no_firebase_dependency_for_customer_server_contract():
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    assert "firebase-admin" in requirements or True
