from pymongo.errors import DuplicateKeyError

from common.db import get_db


class FamilyKeyAlreadyExistsError(Exception):
    pass


def list_by_owner(owner_id):
    return list(get_db().question_bank.find({"ownerId": owner_id}).sort("updatedAt", -1))


def list_shared_with(user_id):
    return list(get_db().question_bank.find({"sharedWith": user_id}).sort("updatedAt", -1))


def find_by_id(family_id, owner_id):
    return get_db().question_bank.find_one({"_id": family_id, "ownerId": owner_id})


def insert_family(document):
    try:
        return get_db().question_bank.insert_one(document)
    except DuplicateKeyError as exc:
        raise FamilyKeyAlreadyExistsError() from exc


def update_fields(family_id, owner_id, fields):
    return get_db().question_bank.update_one(
        {"_id": family_id, "ownerId": owner_id},
        {"$set": fields},
    )


def add_shared_user(family_id, owner_id, user_id):
    return get_db().question_bank.update_one(
        {"_id": family_id, "ownerId": owner_id},
        {"$addToSet": {"sharedWith": user_id}},
    )


def remove_shared_user(family_id, owner_id, user_id):
    return get_db().question_bank.update_one(
        {"_id": family_id, "ownerId": owner_id},
        {"$pull": {"sharedWith": user_id}},
    )


def delete_family(family_id, owner_id):
    return get_db().question_bank.delete_one({"_id": family_id, "ownerId": owner_id})