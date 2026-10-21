import secrets

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

from auth.guards import login_required
from common.csrf import csrf_token, validate_csrf
from common.errors import AppError
from logic import service as logic_service
from publishing import service as publishing_service
from questions import service as question_service

bp = Blueprint("publishing", __name__)


@bp.post("/surveys/<survey_id>/publish")
@login_required
def publish(survey_id):
    validate_csrf()
    try:
        publishing_service.publish_survey(survey_id, g.user["_id"])
    except AppError as exc:
        flash(exc.message, "error")
    else:
        flash("问卷已发布，可以分享链接了。", "success")
    return redirect(url_for("surveys.detail", survey_id=survey_id))


@bp.post("/surveys/<survey_id>/deadline")
@login_required
def set_deadline(survey_id):
    validate_csrf()
    try:
        publishing_service.set_deadline(
            survey_id,
            g.user["_id"],
            request.form.get("deadline", ""),
        )
    except AppError as exc:
        flash(exc.message, "error")
    else:
        flash("截止时间已更新。", "success")
    return redirect(url_for("surveys.detail", survey_id=survey_id))


@bp.post("/surveys/<survey_id>/close")
@login_required
def close(survey_id):
    validate_csrf()
    try:
        publishing_service.close_survey(survey_id, g.user["_id"])
    except AppError as exc:
        flash(exc.message, "error")
    else:
        flash("问卷已关闭。", "success")
    return redirect(url_for("surveys.detail", survey_id=survey_id))


@bp.get("/survey/<share_code>")
def public_survey(share_code):
    document, survey, state = publishing_service.get_public_survey(share_code)

    if (
        state == "open"
        and not survey["allowAnonymous"]
        and getattr(g, "user", None) is None
    ):
        return redirect(url_for("auth.login", next=request.path))

    if getattr(g, "user", None) is None and not session.get("respondent_token"):
        session["respondent_token"] = secrets.token_urlsafe(24)

    ordered_questions = question_service.public_questions(document)
    survey_data = {
        "startQuestionId": document.get("startQuestionId")
        or (ordered_questions[0]["id"] if ordered_questions else None),
        "questions": ordered_questions,
        "rules": logic_service.public_rules(document),
    }

    return render_template(
        "publishing/public.html",
        survey=survey,
        state=state,
        survey_data=survey_data,
        submit_url=url_for(
            "responses.submit",
            share_code=share_code,
        ),
        csrf_value=csrf_token(),
    )
