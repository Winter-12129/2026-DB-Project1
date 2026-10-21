from pymongo.errors import DuplicateKeyError

from common.db import get_db


class UsernameAlreadyExistsError(Exception):
    pass


def create_user(username, password_hash, created_at):
    document = {
        "username": username,
        "passwordHash": password_hash,
        "createdAt": created_at,
    }
    try:
        result = get_db().users.insert_one(document)
    except DuplicateKeyError as exc:
        raise UsernameAlreadyExistsError() from exc
    return result.inserted_id


def find_by_username(username):
    return get_db().users.find_one({"username": username})


def find_by_id(user_id):
    return get_db().users.find_one({"_id": user_id})
