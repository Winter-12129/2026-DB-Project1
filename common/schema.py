from pymongo.errors import OperationFailure, PyMongoError


USERS_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["username", "passwordHash", "createdAt"],
        "properties": {
            "username": {
                "bsonType": "string",
                "minLength": 3,
                "maxLength": 32,
            },
            "passwordHash": {
                "bsonType": "string",
                "minLength": 8,
            },
            "createdAt": {
                "bsonType": "date",
            },
        },
    }
}


SURVEYS_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "ownerId",
            "title",
            "shareCode",
            "status",
            "allowAnonymous",
            "questions",
            "rules",
            "createdAt",
            "updatedAt",
        ],
        "properties": {
            "ownerId": {
                "bsonType": "objectId",
            },
            "title": {
                "bsonType": "string",
                "minLength": 1,
            },
            "description": {
                "bsonType": "string",
            },
            "allowAnonymous": {
                "bsonType": "bool",
            },
            "allowMultipleResponses": {
                "bsonType": "bool",
            },
            "shareCode": {
                "bsonType": "string",
                "minLength": 6,
            },
            "status": {
                "enum": ["draft", "published", "closed"],
            },
            "version": {
                "bsonType": "int",
                "minimum": 1,
            },
            "schemaVersion": {
                "bsonType": "int",
                "minimum": 1,
            },
            "startQuestionId": {
                "bsonType": ["string", "null"],
            },
            "questions": {
                "bsonType": "array",
            },
            "rules": {
                "bsonType": "array",
            },
            "deadline": {
                "bsonType": ["date", "null"],
            },
            "publishedAt": {
                "bsonType": ["date", "null"],
            },
            "closedAt": {
                "bsonType": ["date", "null"],
            },
            "createdAt": {
                "bsonType": "date",
            },
            "updatedAt": {
                "bsonType": "date",
            },
        },
    }
}


RESPONSES_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "surveyId",
            "surveyVersion",
            "anonymous",
            "submissionToken",
            "submittedAt",
            "answers",
            "visitedQuestionIds",
        ],
        "properties": {
            "surveyId": {
                "bsonType": "objectId",
            },
            "surveyVersion": {
                "bsonType": "int",
                "minimum": 1,
            },
            "respondentId": {
                "bsonType": ["objectId", "null"],
            },
            "anonymous": {
                "bsonType": "bool",
            },
            "participantKey": {
                "bsonType": ["string", "null"],
            },
            "submissionToken": {
                "bsonType": "string",
                "minLength": 1,
            },
            "submittedAt": {
                "bsonType": "date",
            },
            "answers": {
                "bsonType": "array",
                "items": {
                    "bsonType": "object",
                    "required": ["questionId", "type"],
                    "properties": {
                        "questionId": {"bsonType": "string"},
                        "type": {"bsonType": "string"},
                    },
                },
            },
            "visitedQuestionIds": {
                "bsonType": "array",
                "items": {"bsonType": "string"},
            },
        },
    }
}


QUESTION_BANK_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "ownerId",
            "familyKey",
            "title",
            "aliases",
            "aliasKeys",
            "sharedWith",
            "currentVersionId",
            "versions",
            "createdAt",
            "updatedAt",
        ],
        "properties": {
            "ownerId": {"bsonType": "objectId"},
            "familyKey": {"bsonType": "string", "minLength": 1},
            "title": {"bsonType": "string", "minLength": 1},
            "aliases": {"bsonType": "array", "items": {"bsonType": "string"}},
            "aliasKeys": {"bsonType": "array", "items": {"bsonType": "string"}},
            "sharedWith": {
                "bsonType": "array",
                "items": {"bsonType": "objectId"},
            },
            "currentVersionId": {"bsonType": "string", "minLength": 1},
            "versions": {
                "bsonType": "array",
                "minItems": 1,
                "items": {
                    "bsonType": "object",
                    "required": [
                        "id",
                        "number",
                        "fingerprint",
                        "title",
                        "type",
                        "options",
                        "config",
                        "parentVersionId",
                        "createdAt",
                    ],
                    "properties": {
                        "id": {"bsonType": "string"},
                        "number": {"bsonType": "int"},
                        "fingerprint": {"bsonType": "string"},
                        "title": {"bsonType": "string"},
                        "type": {"bsonType": "string"},
                        "options": {"bsonType": "array"},
                        "config": {"bsonType": "object"},
                        "parentVersionId": {"bsonType": ["string", "null"]},
                        "createdAt": {"bsonType": "date"},
                    },
                },
            },
            "variants": {
                "bsonType": "array",
                "items": {"bsonType": "object"},
            },
            "createdAt": {"bsonType": "date"},
            "updatedAt": {"bsonType": "date"},
        },
    }
}


COLLECTION_VALIDATORS = {
    "users": USERS_VALIDATOR,
    "surveys": SURVEYS_VALIDATOR,
    "responses": RESPONSES_VALIDATOR,
    "question_bank": QUESTION_BANK_VALIDATOR,
}


def apply_schema_validators(db):
    """为已有或新建集合添加 MongoDB 数据库级结构校验。

    使用 moderate，让已有历史文档保留，但新的插入和合法文档更新必须符合结构。
    """

    existing = set(db.list_collection_names())
    for name, validator in COLLECTION_VALIDATORS.items():
        options = {
            "validator": validator,
            "validationLevel": "moderate",
            "validationAction": "error",
        }
        try:
            if name in existing:
                db.command("collMod", name, **options)
            else:
                db.create_collection(name, **options)
        except PyMongoError as exc:
            raise RuntimeError(
                f"无法为集合 {name} 应用 MongoDB Schema Validator"
            ) from exc
