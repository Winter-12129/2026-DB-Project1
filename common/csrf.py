import hmac
import secrets

from flask import abort, current_app, request, session


def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf():
    if not current_app.config.get("CSRF_ENABLED", True):
        return

    expected = session.get("_csrf_token", "")
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(400, description="CSRF 校验失败，请刷新页面后重试。")
