from flask import Blueprint, flash, g, redirect, request, url_for

from auth.guards import login_required
from common.csrf import validate_csrf
from common.errors import AppError
from questions import service as question_service

bp = Blueprint("questions", __name__)


@bp.post("/surveys/<survey_id>/questions")
@login_required
def add(survey_id):
    validate_csrf()
    try:
        question_service.add_question(
            survey_id,
            g.user["_id"],
            request.form,
        )
    except AppError as exc:
        flash(exc.message, "error")
    else:
        flash("题目已添加。", "success")
    return redirect(url_for("surveys.detail", survey_id=survey_id))


@bp.post("/surveys/<survey_id>/questions/<question_id>/delete")
@login_required
def delete(survey_id, question_id):
    validate_csrf()
    try:
        question_service.delete_question(
            survey_id,
            g.user["_id"],
            question_id,
        )
    except AppError as exc:
        flash(exc.message, "error")
    else:
        flash("题目已删除。", "success")
    return redirect(url_for("surveys.detail", survey_id=survey_id))
