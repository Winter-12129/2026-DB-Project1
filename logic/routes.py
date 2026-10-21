from flask import Blueprint, flash, g, redirect, request, url_for

from auth.guards import login_required
from common.csrf import validate_csrf
from common.errors import AppError
from logic import service as logic_service

bp = Blueprint("logic", __name__)


@bp.post("/surveys/<survey_id>/questions/<question_id>/rules")
@login_required
def add_rule(survey_id, question_id):
    validate_csrf()
    try:
        logic_service.add_rule(
            survey_id,
            g.user["_id"],
            question_id,
            request.form,
        )
    except AppError as exc:
        flash(exc.message, "error")
    else:
        flash("跳转规则已添加。", "success")
    return redirect(url_for("surveys.detail", survey_id=survey_id))


@bp.post("/surveys/<survey_id>/rules/<rule_id>/delete")
@login_required
def delete_rule(survey_id, rule_id):
    validate_csrf()
    try:
        logic_service.delete_rule(
            survey_id,
            g.user["_id"],
            rule_id,
        )
    except AppError as exc:
        flash(exc.message, "error")
    else:
        flash("跳转规则已删除。", "success")
    return redirect(url_for("surveys.detail", survey_id=survey_id))
