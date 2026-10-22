from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from auth.guards import login_required
from common.csrf import validate_csrf
from common.errors import AppError
from logic import service as logic_service
from question_bank import service as bank_service
from questions import service as question_service
from surveys import service as survey_service

bp = Blueprint("surveys", __name__)


@bp.get("/surveys")
@login_required
def index():
    surveys = survey_service.list_my_surveys(g.user["_id"])
    return render_template("surveys/list.html", surveys=surveys)


@bp.get("/surveys/<survey_id>")
@login_required
def detail(survey_id):
    document = survey_service.get_owned_survey_doc(
        survey_id,
        g.user["_id"],
    )
    survey = survey_service.to_view(document)
    questions = question_service.question_views(document)
    rules = logic_service.rule_views(document)
    for question in questions:
        question["laterQuestions"] = [
            candidate
            for candidate in questions
            if candidate["order"] > question["order"]
        ]
        question["rules"] = [
            rule
            for rule in rules
            if rule["sourceQuestionId"] == question["id"]
        ]
    return render_template(
        "surveys/detail.html",
        survey=survey,
        questions=questions,
        bank_versions=bank_service.flatten_versions(g.user["_id"]),
        can_edit=survey["status"] == "draft",
    )


@bp.route("/surveys/new", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        validate_csrf()
        try:
            survey = survey_service.create_survey(
                g.user["_id"],
                request.form.get("title", ""),
                request.form.get("description", ""),
                request.form.get("allow_anonymous") == "1",
                request.form.get("allow_multiple") == "1",
            )
        except AppError as exc:
            flash(exc.message, "error")
            return (
                render_template(
                    "surveys/create.html",
                    title=request.form.get("title", ""),
                    description=request.form.get("description", ""),
                    allow_anonymous=request.form.get("allow_anonymous") == "1",
                    allow_multiple=request.form.get("allow_multiple") == "1",
                ),
                exc.status_code,
            )

        flash("问卷已创建，请先添加题目。", "success")
        return redirect(
            url_for("surveys.detail", survey_id=survey["id"])
        )

    return render_template(
        "surveys/create.html",
        title="",
        description="",
        allow_anonymous=False,
        allow_multiple=False,
    )
