from common.errors import ConflictError, ValidationError
from common.time_utils import as_utc, parse_local_datetime, utc_now
from logic import service as logic_service
from questions import service as question_service
from surveys import service as survey_service


def publish_survey(survey_id, owner_id):
    document = survey_service.get_owned_survey_doc(survey_id, owner_id)
    if document.get("status") != "draft":
        raise ConflictError("只有草稿问卷可以发布")

    deadline = as_utc(document.get("deadline"))
    now = utc_now()
    if deadline is not None and deadline <= now:
        raise ValidationError("截止时间已过，请先修改截止时间")

    question_service.validate_questions_for_publish(document)
    logic_service.validate_rules_for_publish(document)
    start_question_id = document.get("startQuestionId")
    if not start_question_id:
        ordered = sorted(
            document.get("questions", []),
            key=lambda item: item.get("order", 0),
        )
        start_question_id = ordered[0]["id"]
    survey_service.mark_published(
        document["_id"],
        now,
        start_question_id=start_question_id,
    )


def set_deadline(survey_id, owner_id, deadline_text):
    document = survey_service.get_owned_survey_doc(survey_id, owner_id)
    if document.get("status") == "closed":
        raise ConflictError("已关闭的问卷不能修改截止时间")
    if not deadline_text:
        raise ValidationError("请选择截止时间")

    try:
        deadline = parse_local_datetime(deadline_text)
    except ValueError as exc:
        raise ValidationError("截止时间格式不正确") from exc

    now = utc_now()
    if deadline <= now:
        raise ValidationError("截止时间必须晚于当前时间")

    survey_service.update_deadline(document["_id"], deadline, now)


def close_survey(survey_id, owner_id):
    document = survey_service.get_owned_survey_doc(survey_id, owner_id)
    if document.get("status") != "published":
        raise ConflictError("只有已发布问卷可以关闭")
    survey_service.mark_closed(document["_id"], utc_now())


def public_state(document):
    if document.get("status") == "closed":
        return "closed"
    deadline = as_utc(document.get("deadline"))
    if deadline is not None and deadline <= utc_now():
        return "expired"
    return "open"


def get_public_survey(share_code):
    document = survey_service.get_by_share_code(share_code)
    return (
        document,
        survey_service.to_view(document),
        public_state(document),
    )
