from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from auth import service as auth_service
from auth.guards import login_required
from common.csrf import validate_csrf
from common.errors import AppError

bp = Blueprint("auth", __name__)


def _safe_next_url(value):
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return None


@bp.route("/register", methods=["GET", "POST"])
def register():
    if getattr(g, "user", None) is not None:
        return redirect(url_for("surveys.index"))

    if request.method == "POST":
        validate_csrf()
        try:
            auth_service.register_user(
                request.form.get("username", ""),
                request.form.get("password", ""),
                request.form.get("confirm_password", ""),
            )
        except AppError as exc:
            flash(exc.message, "error")
            return (
                render_template(
                    "auth/register.html",
                    username=request.form.get("username", ""),
                ),
                exc.status_code,
            )

        flash("注册成功，请登录。", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", username="")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if getattr(g, "user", None) is not None:
        return redirect(url_for("surveys.index"))

    next_url = _safe_next_url(
        request.form.get("next") or request.args.get("next")
    )

    if request.method == "POST":
        validate_csrf()
        user = auth_service.authenticate(
            request.form.get("username", ""),
            request.form.get("password", ""),
        )
        if user is None:
            flash("用户名或密码错误。", "error")
            return (
                render_template(
                    "auth/login.html",
                    username=request.form.get("username", ""),
                    next_url=next_url,
                ),
                401,
            )

        session.clear()
        session["user_id"] = str(user["_id"])
        session.permanent = True
        flash("登录成功。", "success")
        return redirect(next_url or url_for("surveys.index"))

    return render_template(
        "auth/login.html",
        username="",
        next_url=next_url,
    )


@bp.post("/logout")
@login_required
def logout():
    validate_csrf()
    session.clear()
    flash("已退出登录。", "success")
    return redirect(url_for("auth.login"))
