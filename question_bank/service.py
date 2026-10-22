import copy
import hashlib
import json
import re
import secrets
import unicodedata
from decimal import Decimal, InvalidOperation

from bson import ObjectId

from auth import repository as auth_repository
from common.errors import ConflictError, NotFoundError, ValidationError
from common.ids import generate_option_id
from common.time_utils import utc_now
from question_bank import repository
from surveys import repository as survey_repository
from surveys import service as survey_service

SUPPORTED_TYPES = {"single_choice", "multiple_choice", "text", "number"}
TYPE_LABELS = {
    "single_choice": "单选",
    "multiple_choice": "多选",
    "text": "文本",
    "number": "数字",
}


def _to_object_id(value):
    if isinstance(value, ObjectId):
        return value
    if not ObjectId.is_valid(value):
        raise NotFoundError("题目库记录不存在")
    return ObjectId(value)


def normalize_text(value):
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def _parse_aliases(value):
    aliases = []
    seen = set()
    for line in (value or "").splitlines():
        alias = line.strip()
        key = normalize_text(alias)
        if alias and key not in seen:
            aliases.append(alias)
            seen.add(key)
    return aliases


def _optional_int(value, field_name, minimum=0):
    value = (value or "").strip()
    if not value:
        return None
    try:
        number = int(value)
    except ValueError as exc:
        raise ValidationError(f"{field_name}必须是整数") from exc
    if number < minimum:
        raise ValidationError(f"{field_name}不能小于 {minimum}")
    return number


def _optional_decimal(value, field_name):
    value = (value or "").strip()
    if not value:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(f"{field_name}必须是数字") from exc
    if not number.is_finite():
        raise ValidationError(f"{field_name}必须是有限数字")
    return int(number) if number == number.to_integral_value() else float(number)


def _parse_options(text, minimum):
    labels = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(labels) < minimum:
        raise ValidationError(f"该题型至少需要 {minimum} 个选项")
    return [{"id": generate_option_id(), "label": label} for label in labels]


def _build_config(question_type, form):
    if question_type == "multiple_choice":
        minimum = _optional_int(form.get("min_selections"), "最少选择数量") or 0
        maximum = _optional_int(form.get("max_selections"), "最多选择数量")
        if maximum is not None and maximum < minimum:
            raise ValidationError("最多选择数量不能小于最少选择数量")
        return {"minSelections": minimum, "maxSelections": maximum}
    if question_type == "text":
        minimum = _optional_int(form.get("min_length"), "最少字数") or 0
        maximum = _optional_int(form.get("max_length"), "最多字数")
        if maximum is not None and maximum < minimum:
            raise ValidationError("最多字数不能小于最少字数")
        return {"minLength": minimum, "maxLength": maximum}
    if question_type == "number":
        minimum = _optional_decimal(form.get("min_number"), "最小值")
        maximum = _optional_decimal(form.get("max_number"), "最大值")
        if minimum is not None and maximum is not None and maximum < minimum:
            raise ValidationError("最大值不能小于最小值")
        return {
            "min": minimum,
            "max": maximum,
            "integerOnly": form.get("integer_only") == "1",
        }
    return {}


def parse_question_form(form):
    question_type = (form.get("type") or "").strip()
    if question_type not in SUPPORTED_TYPES:
        raise ValidationError("请选择有效的题型")
    title = (form.get("title") or "").strip()
    if not title:
        raise ValidationError("题干不能为空")
    if len(title) > 300:
        raise ValidationError("题干不能超过 300 个字符")
    options = []
    if question_type == "single_choice":
        options = _parse_options(form.get("options"), 2)
    elif question_type == "multiple_choice":
        options = _parse_options(form.get("options"), 1)
    return {
        "type": question_type,
        "title": title,
        "options": options,
        "config": _build_config(question_type, form),
    }


def _version_fingerprint(question):
    payload = {
        "type": question.get("type"),
        "options": [
            normalize_text(option.get("label", ""))
            for option in question.get("options", [])
        ],
        "config": question.get("config", {}),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _version_entry(question, number, parent_version_id=None):
    return {
        "id": "ver_" + secrets.token_hex(6),
        "number": number,
        "fingerprint": _version_fingerprint(question),
        "title": question["title"],
        "type": question["type"],
        "options": copy.deepcopy(question.get("options", [])),
        "config": copy.deepcopy(question.get("config", {})),
        "parentVersionId": parent_version_id,
        "createdAt": utc_now(),
    }


def _versions(family):
    entries = list(family.get("versions", family.get("variants", [])))
    for index, entry in enumerate(entries, start=1):
        entry.setdefault("number", index)
        entry.setdefault("createdAt", family.get("updatedAt") or utc_now())
        entry.setdefault("parentVersionId", None)
    return entries


def _current_version(family):
    entries = _versions(family)
    current_id = family.get("currentVersionId")
    return next(
        (entry for entry in entries if entry.get("id") == current_id),
        entries[-1] if entries else None,
    )


def _next_number(family):
    return max([entry.get("number", 0) for entry in _versions(family)] or [0]) + 1


def _user_view(user_id):
    user = auth_repository.find_by_id(user_id)
    return {
        "id": str(user_id),
        "username": user.get("username") if user else str(user_id),
    }


def _family_view(family, viewer_id):
    is_owner = family.get("ownerId") == viewer_id
    entries = _versions(family)
    current = _current_version(family)
    versions = version_views(family)
    return {
        "id": str(family["_id"]),
        "title": family.get("title", ""),
        "aliases": family.get("aliases", []),
        "versions": versions,
        "versionCount": len(entries),
        "currentVersionId": current.get("id") if current else None,
        "updatedAt": family.get("updatedAt"),
        "isOwner": is_owner,
        "ownerName": _user_view(family["ownerId"])["username"],
        "sharedUsers": (
            [_user_view(user_id) for user_id in family.get("sharedWith", [])]
            if is_owner
            else []
        ),
    }


def _find_family(owner_id, title, aliases=None):
    wanted = {normalize_text(title)}
    wanted.update(normalize_text(alias) for alias in (aliases or []))
    for family in repository.list_by_owner(owner_id):
        keys = {family.get("familyKey", "")}
        keys.update(family.get("aliasKeys", []))
        if wanted & keys:
            return family
    return None


def _ensure_alias_available(owner_id, family_id, alias):
    key = normalize_text(alias)
    if not key:
        return None
    for family in repository.list_by_owner(owner_id):
        if family["_id"] == family_id:
            continue
        if family.get("familyKey") == key or key in family.get("aliasKeys", []):
            raise ConflictError(f"别名“{alias}”已被其他题目使用")
    return key


def save_question(owner_id, question, aliases_text=""):
    if question.get("type") not in SUPPORTED_TYPES:
        raise ValidationError("不支持的题库题型")
    title = (question.get("title") or "").strip()
    if not title:
        raise ValidationError("题干不能为空")
    if not normalize_text(title):
        raise ValidationError("题干不能只包含空白或标点")

    aliases = _parse_aliases(aliases_text)
    family = _find_family(owner_id, title, aliases)
    if family is None:
        family_key = normalize_text(title)
        alias_keys = [
            key
            for key in (normalize_text(alias) for alias in aliases)
            if key and key != family_key
        ]
        entry = _version_entry(question, 1)
        document = {
            "ownerId": owner_id,
            "familyKey": family_key,
            "title": title,
            "aliases": aliases,
            "aliasKeys": alias_keys,
            "sharedWith": [],
            "versions": [entry],
            "currentVersionId": entry["id"],
            "createdAt": utc_now(),
            "updatedAt": utc_now(),
        }
        try:
            result = repository.insert_family(document)
        except repository.FamilyKeyAlreadyExistsError:
            family = _find_family(owner_id, title, aliases)
            if family is None:
                raise
        else:
            document["_id"] = result.inserted_id
            return document, entry, True

    entries = _versions(family)
    fingerprint = _version_fingerprint(question)
    for existing in entries:
        if existing.get("fingerprint") == fingerprint:
            return family, existing, False

    current = _current_version(family)
    entry = _version_entry(
        question,
        _next_number(family),
        parent_version_id=current.get("id") if current else None,
    )
    entries.append(entry)
    merged_aliases = list(dict.fromkeys(family.get("aliases", []) + aliases))
    alias_keys = list(dict.fromkeys(
        family.get("aliasKeys", [])
        + [normalize_text(alias) for alias in aliases]
    ))
    repository.update_fields(
        family["_id"],
        owner_id,
        {
            "versions": entries,
            "currentVersionId": entry["id"],
            "aliases": merged_aliases,
            "aliasKeys": alias_keys,
            "updatedAt": utc_now(),
        },
    )
    family["versions"] = entries
    family["currentVersionId"] = entry["id"]
    return family, entry, False


def save_version(owner_id, family_id, base_version_id, form, save_mode="new"):
    """保存题库编辑，可选择追加版本或覆盖指定版本。"""

    family = repository.find_by_id(_to_object_id(family_id), owner_id)
    if family is None:
        raise NotFoundError("题目库记录不存在")
    if save_mode not in {"new", "replace"}:
        raise ValidationError("请选择有效的保存方式")
    entries = _versions(family)
    base = next(
        (entry for entry in entries if entry.get("id") == base_version_id),
        _current_version(family),
    )
    if base is None:
        raise NotFoundError("基础版本不存在")
    question = parse_question_form(form)
    now = utc_now()

    if save_mode == "replace":
        updated = copy.deepcopy(base)
        updated.update(
            {
                "fingerprint": _version_fingerprint(question),
                "title": question["title"],
                "type": question["type"],
                "options": copy.deepcopy(question.get("options", [])),
                "config": copy.deepcopy(question.get("config", {})),
            }
        )
        entries = [
            updated if entry.get("id") == base["id"] else entry
            for entry in entries
        ]
        repository.update_fields(
            family["_id"],
            owner_id,
            {
                "versions": entries,
                "updatedAt": now,
            },
        )
        family["versions"] = entries
        return family, updated, False

    entry = _version_entry(
        question,
        _next_number(family),
        parent_version_id=base["id"],
    )
    entries.append(entry)
    repository.update_fields(
        family["_id"],
        owner_id,
        {
            "versions": entries,
            "currentVersionId": entry["id"],
            "updatedAt": now,
        },
    )
    family["versions"] = entries
    family["currentVersionId"] = entry["id"]
    return family, entry, True


def create_version(owner_id, family_id, base_version_id, form):
    family, entry, _created = save_version(
        owner_id,
        family_id,
        base_version_id,
        form,
        save_mode="new",
    )
    return family, entry


def restore_version(owner_id, family_id, version_id):
    family = repository.find_by_id(_to_object_id(family_id), owner_id)
    if family is None:
        raise NotFoundError("题目库记录不存在")
    target = next(
        (entry for entry in _versions(family) if entry.get("id") == version_id),
        None,
    )
    if target is None:
        raise NotFoundError("版本不存在")
    repository.update_fields(
        family["_id"],
        owner_id,
        {"currentVersionId": target["id"], "updatedAt": utc_now()},
    )
    return family, target


def link_survey_question(owner_id, survey_id, question_id, family, version):
    """把题库来源写回原问卷中的题目快照。"""

    document = survey_service.get_owned_survey_doc(survey_id, owner_id)
    questions = list(document.get("questions", []))
    question = next(
        (item for item in questions if item.get("id") == question_id),
        None,
    )
    if question is None:
        raise NotFoundError("题目不存在")
    question["sourceBankId"] = str(family["_id"])
    question["sourceVersionId"] = version["id"]
    question["sourceVariantId"] = version["id"]
    survey_repository.update_fields(
        document["_id"],
        {"questions": questions, "updatedAt": utc_now()},
    )
    return question


def save_from_survey(owner_id, survey_id, question_id, aliases_text=""):
    document = survey_service.get_owned_survey_doc(survey_id, owner_id)
    question = next(
        (item for item in document.get("questions", []) if item.get("id") == question_id),
        None,
    )
    if question is None:
        raise NotFoundError("题目不存在")
    return save_question(owner_id, question, aliases_text)


def version_views(family):
    entries = _versions(family)
    current = _current_version(family)
    current_id = current.get("id") if current else family.get("currentVersionId")
    by_id = {entry.get("id"): entry for entry in entries}
    result = []
    for entry in sorted(entries, key=lambda item: item.get("number", 0), reverse=True):
        parent = by_id.get(entry.get("parentVersionId"))
        result.append(
            {
                "id": entry["id"],
                "number": entry.get("number"),
                "title": entry.get("title", family.get("title", "")),
                "type": entry.get("type"),
                "typeLabel": TYPE_LABELS.get(entry.get("type"), entry.get("type")),
                "options": entry.get("options", []),
                "config": entry.get("config", {}),
                "createdAt": entry.get("createdAt"),
                "parentVersionId": entry.get("parentVersionId"),
                "parentVersionNumber": parent.get("number") if parent else None,
                "isCurrent": entry.get("id") == current_id,
            }
        )
    return result



def _accessible_family_by_id(viewer_id, family_id):
    for family in accessible_families(viewer_id):
        if str(family["_id"]) == str(family_id):
            return family
    return None


def resolve_question_reference(viewer_id, reference):
    """解析题目族 ID、版本 ID，或问卷内题目 ID。"""

    value = (reference or "").strip()
    if not value:
        raise ValidationError("请输入题目族 ID、版本 ID 或题目 ID")

    if value.startswith("ver_"):
        for family in accessible_families(viewer_id):
            version = next(
                (
                    entry
                    for entry in _versions(family)
                    if entry.get("id") == value
                ),
                None,
            )
            if version is not None:
                return family, version, "version"
        raise NotFoundError("版本不存在或无权访问")

    if value.startswith("q_"):
        for survey in survey_repository.list_by_owner(viewer_id):
            question = next(
                (
                    item
                    for item in survey.get("questions", [])
                    if item.get("id") == value
                ),
                None,
            )
            if question is None:
                continue
            bank_id = question.get("sourceBankId")
            family = _accessible_family_by_id(viewer_id, bank_id)
            if family is None:
                raise NotFoundError("该题目未关联可访问的题库题目")
            version_id = (
                question.get("sourceVersionId")
                or question.get("sourceVariantId")
            )
            version = next(
                (
                    entry
                    for entry in _versions(family)
                    if entry.get("id") == version_id
                ),
                None,
            )
            return family, version, "survey_question"
        raise NotFoundError("题目不存在或无权访问")

    if ObjectId.is_valid(value):
        family = _accessible_family_by_id(viewer_id, value)
        if family is not None:
            return family, None, "family"
    raise NotFoundError("题目 ID 不存在或无权访问")


def question_usages(viewer_id, family, selected_version=None):
    """返回当前用户自己的问卷中，使用该题目族或版本的记录。"""

    family_id = str(family["_id"])
    versions = {entry["id"]: entry for entry in _versions(family)}
    usages = []
    surveys = survey_repository.list_by_question_bank(
        viewer_id,
        family_id,
    )
    for survey in surveys:
        for question in survey.get("questions", []):
            if str(question.get("sourceBankId")) != family_id:
                continue
            version_id = (
                question.get("sourceVersionId")
                or question.get("sourceVariantId")
            )
            if selected_version and version_id != selected_version.get("id"):
                continue
            version = versions.get(version_id)
            usages.append(
                {
                    "survey": survey,
                    "question": question,
                    "surveyId": str(survey["_id"]),
                    "surveyTitle": survey.get("title", ""),
                    "surveyStatus": survey.get("status", "draft"),
                    "surveyStatusLabel": survey_service.STATUS_LABELS.get(
                        survey.get("status", "draft"),
                        survey.get("status", "draft"),
                    ),
                    "localQuestionId": question.get("id"),
                    "sourceVersionId": version_id,
                    "sourceVersionNumber": (
                        version.get("number") if version else None
                    ),
                }
            )
    return usages


def family_views(owner_id):
    return [_family_view(family, owner_id) for family in repository.list_by_owner(owner_id)]


def shared_family_views(user_id):
    return [_family_view(family, user_id) for family in repository.list_shared_with(user_id)]


def accessible_families(user_id):
    families = repository.list_by_owner(user_id) + repository.list_shared_with(user_id)
    unique = {}
    for family in families:
        unique[family["_id"]] = family
    return list(unique.values())


def flatten_versions(user_id):
    result = []
    for family in accessible_families(user_id):
        family_view = _family_view(family, user_id)
        for version in family_view["versions"]:
            result.append(
                {
                    **version,
                    "familyId": family_view["id"],
                    "familyTitle": family_view["title"],
                    "aliases": family_view["aliases"],
                    "isOwner": family_view["isOwner"],
                    "ownerName": family_view["ownerName"],
                }
            )
    return result


def get_accessible_version(viewer_id, version_id):
    for family in accessible_families(viewer_id):
        for entry in _versions(family):
            if entry.get("id") == version_id:
                return family, entry
    raise NotFoundError("题库题目不存在")


def add_aliases(owner_id, family_id, aliases_text):
    family = repository.find_by_id(_to_object_id(family_id), owner_id)
    if family is None:
        raise NotFoundError("题目库记录不存在")
    aliases = _parse_aliases(aliases_text)
    alias_keys = []
    for alias in aliases:
        key = _ensure_alias_available(owner_id, family["_id"], alias)
        if key and key != family.get("familyKey"):
            alias_keys.append(key)
    merged = list(dict.fromkeys(family.get("aliases", []) + aliases))
    merged_keys = list(dict.fromkeys(family.get("aliasKeys", []) + alias_keys))
    repository.update_fields(
        family["_id"],
        owner_id,
        {"aliases": merged, "aliasKeys": merged_keys, "updatedAt": utc_now()},
    )


def share_family(owner_id, family_id, username):
    family = repository.find_by_id(_to_object_id(family_id), owner_id)
    if family is None:
        raise NotFoundError("题目库记录不存在")
    username = (username or "").strip()
    if not username:
        raise ValidationError("请输入要共享的用户名")
    target = auth_repository.find_by_username(username)
    if target is None:
        raise NotFoundError("用户不存在")
    if target["_id"] == owner_id:
        raise ValidationError("不能共享给自己")
    if target["_id"] not in family.get("sharedWith", []):
        repository.add_shared_user(family["_id"], owner_id, target["_id"])
        repository.update_fields(family["_id"], owner_id, {"updatedAt": utc_now()})
    return target


def unshare_family(owner_id, family_id, username):
    family = repository.find_by_id(_to_object_id(family_id), owner_id)
    if family is None:
        raise NotFoundError("题目库记录不存在")
    target = auth_repository.find_by_username((username or "").strip())
    if target is None:
        raise NotFoundError("用户不存在")
    if target["_id"] in family.get("sharedWith", []):
        repository.remove_shared_user(family["_id"], owner_id, target["_id"])
        repository.update_fields(family["_id"], owner_id, {"updatedAt": utc_now()})
    return target


def delete_family(owner_id, family_id):
    result = repository.delete_family(_to_object_id(family_id), owner_id)
    if result.deleted_count == 0:
        raise NotFoundError("题目库记录不存在")


def get_owned_family(owner_id, family_id):
    family = repository.find_by_id(_to_object_id(family_id), owner_id)
    if family is None:
        raise NotFoundError("题目库记录不存在")
    return family


def family_versions(family):
    return _versions(family)


def family_current_version(family):
    return _current_version(family)


def find_family_version(family, version_id):
    return next(
        (entry for entry in _versions(family) if entry.get("id") == version_id),
        None,
    )