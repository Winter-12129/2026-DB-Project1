from functools import wraps

from flask import g, jsonify, redirect, request, session, url_for

from auth.service import get_user_by_id


def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = get_user_by_id(user_id) if user_id else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "user", None) is None:
            if request.path.startswith("/api/"):
                return (
                    jsonify(
                        {"error": {"code": "unauthorized", "message": "请先登录"}}
                    ),
                    401,
                )
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped
