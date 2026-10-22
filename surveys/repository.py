from common.db import get_db
from pymongo.errors import DuplicateKeyError


class ShareCodeAlreadyExistsError(Exception):
    pass


def create_survey(
    owner_id,
    title,
    description,
    allow_anonymous,
    allow_multiple_responses,
    share_code,
    created_at,
):
    document = {
        "ownerId": owner_id,
        "title": title,
        "description": description,
        "allowAnonymous": allow_anonymous,
        "allowMultipleResponses": allow_multiple_responses,
        "shareCode": share_code,
        "status": "draft",
        "schemaVersion": 1,
        "version": 1,
        "startQuestionId": None,
        "questions": [],
        "rules": [],
        "deadline": None,
        "publishedAt": None,
        "closedAt": None,
        "createdAt": created_at,
        "updatedAt": created_at,
    }
    try:
        result = get_db().surveys.insert_one(document)
    except DuplicateKeyError as exc:
        raise ShareCodeAlreadyExistsError() from exc
    return result.inserted_id


def list_by_owner(owner_id):
    return list(
        get_db()
        .surveys.find({"ownerId": owner_id})
        .sort("createdAt", -1)
    )


def find_by_id(survey_id):
    return get_db().surveys.find_one({"_id": survey_id})


def find_by_share_code(share_code):
    return get_db().surveys.find_one({"shareCode": share_code})

def list_by_question_bank(owner_id, bank_id):
    """返回当前用户问卷中使用了指定题目族的问卷。"""

    return list(
        get_db()
        .surveys.find(
            {
                "ownerId": owner_id,
                "questions": {
                    "$elemMatch": {"sourceBankId": str(bank_id)},
                },
            }
        )
        .sort("createdAt", -1)
    )


def update_fields(survey_id, fields):
    return get_db().surveys.update_one(
        {"_id": survey_id},
        {"$set": fields},
    )
