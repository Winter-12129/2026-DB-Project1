from flask import Blueprint, g, render_template, request

from analytics import service as analytics_service
from auth.guards import login_required

bp = Blueprint("analytics", __name__)


@bp.get("/surveys/<survey_id>/stats")
@login_required
def survey_stats(survey_id):
    stats = analytics_service.get_survey_stats(
        survey_id,
        g.user["_id"],
        question_id=request.args.get("questionId"),
    )
    return render_template("analytics/stats.html", **stats)
