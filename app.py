from flask import (
    Flask,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from analytics.routes import bp as analytics_bp
from auth.guards import load_logged_in_user
from auth.routes import bp as auth_bp
from common.csrf import csrf_token
from common.db import init_db
from common.errors import AppError, NotFoundError
from common.time_utils import format_local_datetime
from config import Config
from logic.routes import bp as logic_bp
from publishing.routes import bp as publishing_bp
from questions.routes import bp as questions_bp
from responses.routes import bp as responses_bp
from surveys.routes import bp as surveys_bp


def create_app(config_object=Config, database=None):
    app = Flask(__name__)
    app.config.from_object(config_object)

    init_db(app, database=database)

    app.register_blueprint(auth_bp)
    app.register_blueprint(surveys_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(publishing_bp)
    app.register_blueprint(questions_bp)
    app.register_blueprint(logic_bp)
    app.register_blueprint(responses_bp)

    app.before_request(load_logged_in_user)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.filters["localdt"] = format_local_datetime

    @app.context_processor
    def inject_current_user():
        return {"current_user": getattr(g, "user", None)}

    @app.get("/")
    def index():
        if getattr(g, "user", None) is None:
            return redirect(url_for("auth.login"))
        return redirect(url_for("surveys.index"))

    @app.errorhandler(AppError)
    def handle_app_error(exc):
        if request.path.startswith("/api/"):
            return (
                jsonify(
                    {"error": {"code": exc.code, "message": exc.message}}
                ),
                exc.status_code,
            )
        return render_template("error.html", error=exc), exc.status_code

    @app.errorhandler(400)
    def handle_bad_request(exc):
        message = getattr(exc, "description", "请求无效")
        return (
            render_template(
                "error.html",
                error=AppError(message, "bad_request"),
            ),
            400,
        )

    @app.errorhandler(404)
    def handle_not_found(exc):
        return (
            render_template(
                "error.html",
                error=NotFoundError("页面不存在"),
            ),
            404,
        )

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
