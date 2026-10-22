from flask import Blueprint, flash, g, redirect, request, url_for

from auth.guards import login_required
from common.csrf import validate_csrf
from common.errors import AppError
from question_bank import service as bank_service
from questions import service as question_service

bp = Blueprint("questions", __name__)


@bp.post("/surveys/<survey_id>/questions")
@login_required
def add(survey_id):
    validate_csrf()
    try:
        question = question_service.add_question(
            survey_id,
            g.user["_id"],
            request.form,
        )
        if request.form.get("save_to_bank") == "1":
            family, version, _created = bank_service.save_question(
                g.user["_id"],
                question,
                request.form.get("bank_aliases", ""),
            )
            bank_service.link_survey_question(
                g.user["_id"],
                survey_id,
                question["id"],
                family,
                version,
            )
            flash("题目已添加，并保存到题目库。", "success")
        else:
            flash("题目已添加。", "success")
    except AppError as exc:
        flash(exc.message, "error")
    return redirect(url_for("surveys.detail", survey_id=survey_id))


@bp.post("/surveys/<survey_id>/questions/from-bank")
@login_required
def add_from_bank(survey_id):
    validate_csrf()
    try:
        question_service.add_from_bank(
            survey_id,
            g.user["_id"],
            request.form.get("bank_version_id")
            or request.form.get("bank_variant_id", ""),
            request.form.get("required") == "1",
        )
    except AppError as exc:
        flash(exc.message, "error")
    else:
        flash("已从题目库添加题目。", "success")
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
