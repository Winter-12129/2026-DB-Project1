from common.db import get_db


def create_response(document):
    result = get_db().responses.insert_one(document)
    return result.inserted_id


def find_by_submission_token(survey_id, submission_token):
    return get_db().responses.find_one(
        {
            "surveyId": survey_id,
            "submissionToken": submission_token,
        }
    )
