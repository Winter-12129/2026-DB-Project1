from flask import (
    Blueprint,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from analytics import cross_survey_service
from auth.guards import login_required
from common.csrf import validate_csrf
from common.errors import AppError
from question_bank import service as bank_service

bp = Blueprint("question_bank", __name__)


@bp.get("/question-bank")
@login_required
def index():
    return render_template(
        "question_bank/list.html",
        families=bank_service.family_views(g.user["_id"]),
        shared_families=bank_service.shared_family_views(g.user["_id"]),
    )


@bp.get("/question-bank/lookup")
@login_required
def lookup():
    reference = (request.args.get("question_id") or "").strip()
    if not reference:
        return render_template("question_bank/lookup.html")
    return redirect(
        url_for("question_bank.insights", reference=reference)
    )


@bp.get("/question-bank/insights/<path:reference>")
@login_required
def insights(reference):
    stats = cross_survey_service.get_cross_survey_stats(
        g.user["_id"],
        reference,
    )
    return render_template("question_bank/insights.html", **stats)


@bp.get("/api/v1/question-bank/insights/<path:reference>")
@login_required
def insights_api(reference):
    stats = cross_survey_service.get_cross_survey_stats(
        g.user["_id"],
        reference,
    )
    return jsonify(stats)


@bp.route("/question-bank/new", methods=["GET", "POST"])
@login_required
def new_family():
    if request.method == "POST":
        validate_csrf()
        try:
            question = bank_service.parse_question_form(request.form)
            _family, _version, created = bank_service.save_question(
                g.user["_id"],
                question,
                request.form.get("aliases", ""),
            )
        except AppError as exc:
            flash(exc.message, "error")
            return (
                render_template("question_bank/form.html", form=request.form),
                exc.status_code,
            )

        if created:
            flash("常用题目已保存。", "success")
        else:
            flash("相同内容已在题目库中，未重复创建。", "info")
        return redirect(url_for("question_bank.index"))

    return render_template("question_bank/form.html", form={})


@bp.post("/question-bank/<family_id>/share")
@login_required
def share(family_id):
    validate_csrf()
    try:
        target = bank_service.share_family(
            g.user["_id"],
            family_id,
            request.form.get("username", ""),
        )
    except AppError as exc:
        flash(exc.message, "error")
    else:
        flash(f"已共享给 {target.get('username', '用户')}。", "success")
    return redirect(url_for("question_bank.index"))


@bp.post("/question-bank/<family_id>/unshare")
@login_required
def unshare(family_id):
    validate_csrf()
    try:
        target = bank_service.unshare_family(
            g.user["_id"],
            family_id,
            request.form.get("username", ""),
        )
    except AppError as exc:
        flash(exc.message, "error")
    else:
        flash(f"已取消共享给 {target.get('username', '用户')}。", "success")
    return redirect(url_for("question_bank.index"))


@bp.post("/question-bank/<family_id>/aliases")
@login_required
def add_aliases(family_id):
    validate_csrf()
    try:
        bank_service.add_aliases(
            g.user["_id"],
            family_id,
            request.form.get("aliases", ""),
        )
    except AppError as exc:
        flash(exc.message, "error")
    else:
        flash("题目别名已更新。", "success")
    return redirect(url_for("question_bank.index"))


@bp.post("/question-bank/<family_id>/delete")
@login_required
def delete(family_id):
    validate_csrf()
    try:
        bank_service.delete_family(g.user["_id"], family_id)
    except AppError as exc:
        flash(exc.message, "error")
    else:
        flash("题目库记录已删除。", "success")
    return redirect(url_for("question_bank.index"))


@bp.route("/question-bank/<family_id>/versions/new", methods=["GET", "POST"])
@login_required
def new_version(family_id):
    family = bank_service.get_owned_family(g.user["_id"], family_id)
    base_id = request.args.get("base") or request.form.get("base_version_id")
    save_mode = (
        request.args.get("mode")
        or request.form.get("save_mode")
        or "new"
    )
    base = bank_service.find_family_version(family, base_id) if base_id else None
    if base is None:
        base = bank_service.family_current_version(family)
    if base is None:
        flash("题目族还没有版本。", "error")
        return redirect(url_for("question_bank.index"))

    if request.method == "POST":
        validate_csrf()
        try:
            _family, _version, created = bank_service.save_version(
                g.user["_id"],
                family_id,
                base["id"],
                request.form,
                save_mode=request.form.get("save_mode", "new"),
            )
        except AppError as exc:
            flash(exc.message, "error")
            return render_template(
                "question_bank/version_form.html",
                family_id=family_id,
                base=base,
                save_mode=save_mode,
            ), exc.status_code
        flash(
            "新版本已保存。" if created else "当前版本内容已更新。",
            "success",
        )
        return redirect(url_for("question_bank.index"))

    return render_template(
        "question_bank/version_form.html",
        family_id=family_id,
        base=base,
        save_mode=save_mode,
    )


@bp.post("/question-bank/<family_id>/versions/<version_id>/restore")
@login_required
def restore_version(family_id, version_id):
    validate_csrf()
    try:
        bank_service.restore_version(g.user["_id"], family_id, version_id)
    except AppError as exc:
        flash(exc.message, "error")
    else:
        flash("已切换当前版本。", "success")
    return redirect(url_for("question_bank.index"))