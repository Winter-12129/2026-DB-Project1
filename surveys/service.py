from bson import ObjectId

from common.errors import NotFoundError, ValidationError
from common.ids import generate_share_code
from common.time_utils import (
    as_utc,
    format_local_datetime,
    to_local_input,
    utc_now,
)
from surveys import repository

STATUS_LABELS = {
    "draft": "草稿",
    "published": "已发布",
    "closed": "已关闭",
}


def _to_object_id(value):
    if isinstance(value, ObjectId):
        return value
    if not ObjectId.is_valid(value):
        raise NotFoundError("问卷不存在")
    return ObjectId(value)


def to_view(document):
    status = document.get("status", "draft")
    deadline = document.get("deadline")
    normalized_deadline = as_utc(deadline)
    return {
        "id": str(document["_id"]),
        "title": document["title"],
        "description": document.get("description", ""),
        "allowAnonymous": bool(document.get("allowAnonymous", False)),
        "allowMultipleResponses": bool(
            document.get("allowMultipleResponses", False)
        ),
        "shareCode": document.get("shareCode", ""),
        "status": status,
        "statusLabel": STATUS_LABELS.get(status, status),
        "createdAt": document.get("createdAt"),
        "createdAtText": format_local_datetime(document.get("createdAt")),
        "deadline": deadline,
        "deadlineText": format_local_datetime(deadline),
        "deadlineInput": to_local_input(deadline),
        "isExpired": bool(
            normalized_deadline is not None
            and normalized_deadline <= utc_now()
        ),
        "publishedAtText": format_local_datetime(document.get("publishedAt")),
        "closedAtText": format_local_datetime(document.get("closedAt")),
        "questionCount": len(document.get("questions", [])),
        "ruleCount": len(document.get("rules", [])),
        "canPublish": status == "draft",
        "canClose": status == "published",
        "canSetDeadline": status in {"draft", "published"},
    }


def create_survey(
    owner_id,
    title,
    description="",
    allow_anonymous=False,
    allow_multiple_responses=False,
):
    title = (title or "").strip()
    if not title:
        raise ValidationError("问卷标题不能为空")
    if len(title) > 120:
        raise ValidationError("问卷标题不能超过 120 个字符")

    description = (description or "").strip()
    if len(description) > 1000:
        raise ValidationError("问卷说明不能超过 1000 个字符")

    now = utc_now()
    for _ in range(5):
        share_code = generate_share_code()
        try:
            survey_id = repository.create_survey(
                owner_id,
                title,
                description,
                bool(allow_anonymous),
                bool(allow_multiple_responses),
                share_code,
                now,
            )
            break
        except repository.ShareCodeAlreadyExistsError:
            continue
    else:
        raise RuntimeError("无法生成唯一的问卷分享码，请重试")

    return to_view(repository.find_by_id(survey_id))


def list_my_surveys(owner_id):
    return [to_view(document) for document in repository.list_by_owner(owner_id)]


def get_owned_survey_doc(survey_id, owner_id):
    document = repository.find_by_id(_to_object_id(survey_id))
    if document is None or document.get("ownerId") != owner_id:
        raise NotFoundError("问卷不存在")
    return document


def get_owned_survey(survey_id, owner_id):
    return to_view(get_owned_survey_doc(survey_id, owner_id))


def get_by_share_code(share_code):
    document = repository.find_by_share_code(share_code)
    if document is None or document.get("status") == "draft":
        raise NotFoundError("问卷不存在")
    return document


def mark_published(survey_id, published_at, start_question_id=None):
    fields = {
        "status": "published",
        "publishedAt": published_at,
        "updatedAt": published_at,
    }
    if start_question_id:
        fields["startQuestionId"] = start_question_id
    repository.update_fields(
        survey_id,
        fields,
    )


def update_deadline(survey_id, deadline, updated_at):
    repository.update_fields(
        survey_id,
        {
            "deadline": deadline,
            "updatedAt": updated_at,
        },
    )


def mark_closed(survey_id, closed_at):
    repository.update_fields(
        survey_id,
        {
            "status": "closed",
            "closedAt": closed_at,
            "updatedAt": closed_at,
        },
    )
