import secrets

from flask import Blueprint, g, jsonify, request, session

from common.csrf import validate_csrf
from common.errors import ValidationError
from responses import service as response_service

bp = Blueprint("responses", __name__)


@bp.post("/api/v1/surveys/<share_code>/responses")
def submit(share_code):
    validate_csrf()
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError("请求必须是 JSON 对象")

    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise ValidationError("answers 必须是一个对象")

    anonymous_token = session.get("respondent_token")
    if getattr(g, "user", None) is None and not anonymous_token:
        anonymous_token = secrets.token_urlsafe(24)
        session["respondent_token"] = anonymous_token

    response_id, idempotent = response_service.submit_response(
        share_code,
        answers,
        payload.get("submissionToken"),
        getattr(g, "user", None),
        anonymous_token=anonymous_token,
    )
    return (
        jsonify(
            {
                "ok": True,
                "responseId": str(response_id),
                "idempotent": idempotent,
            }
        ),
        200 if idempotent else 201,
    )
