import hashlib

from pymongo.errors import DuplicateKeyError

from common.errors import ConflictError, UnauthorizedError, ValidationError
from common.time_utils import utc_now
from logic import service as logic_service
from publishing import service as publishing_service
from responses import repository


def _participant_key(document, user, anonymous_token):
    if document.get("allowMultipleResponses", False):
        return None
    if user is not None:
        return f"user:{user['_id']}"
    if not anonymous_token:
        raise ValidationError("无法识别匿名填写会话")
    digest = hashlib.sha256(anonymous_token.encode("utf-8")).hexdigest()
    return f"anon:{digest}"


def submit_response(
    share_code,
    answers,
    submission_token,
    user,
    anonymous_token=None,
):
    document, survey, state = publishing_service.get_public_survey(share_code)
    if state != "open":
        raise ValidationError("问卷已关闭或已截止，不能提交")
    if not survey["allowAnonymous"] and user is None:
        raise UnauthorizedError("请先登录后填写")
    if not isinstance(submission_token, str) or not submission_token:
        raise ValidationError("缺少提交令牌")
    if len(submission_token) > 200:
        raise ValidationError("提交令牌过长")

    existing = repository.find_by_submission_token(
        document["_id"],
        submission_token,
    )
    if existing is not None:
        return existing["_id"], True

    participant_key = _participant_key(
        document,
        user,
        anonymous_token,
    )

    visited, normalized_answers = logic_service.replay_path(
        document,
        answers,
    )

    response = {
        "surveyId": document["_id"],
        "surveyVersion": document.get("version", 1),
        "respondentId": user["_id"] if user else None,
        "anonymous": user is None,
        "participantKey": participant_key,
        "submissionToken": submission_token,
        "submittedAt": utc_now(),
        "answers": normalized_answers,
        "visitedQuestionIds": visited,
    }
    try:
        return repository.create_response(response), False
    except DuplicateKeyError as exc:
        existing = repository.find_by_submission_token(
            document["_id"],
            submission_token,
        )
        if existing is not None:
            return existing["_id"], True
        if participant_key:
            raise ConflictError("你已经提交过这份问卷") from exc
        raise
