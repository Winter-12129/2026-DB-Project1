from datetime import datetime, timezone

from bson import ObjectId
from werkzeug.security import check_password_hash, generate_password_hash

from auth import repository
from common.errors import ConflictError, ValidationError

USERNAME_MIN = 3
USERNAME_MAX = 32
PASSWORD_MIN = 8
PASSWORD_MAX = 128


def _clean_username(username):
    value = (username or "").strip()
    if not USERNAME_MIN <= len(value) <= USERNAME_MAX:
        raise ValidationError(
            f"用户名长度需为 {USERNAME_MIN}-{USERNAME_MAX} 个字符"
        )
    if any(character.isspace() for character in value):
        raise ValidationError("用户名不能包含空白字符")
    return value


def register_user(username, password, confirm_password=None):
    username = _clean_username(username)
    password = password or ""

    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise ValidationError(
            f"密码长度需为 {PASSWORD_MIN}-{PASSWORD_MAX} 个字符"
        )
    if confirm_password is not None and password != confirm_password:
        raise ValidationError("两次输入的密码不一致")

    try:
        user_id = repository.create_user(
            username,
            generate_password_hash(password),
            datetime.now(timezone.utc),
        )
    except repository.UsernameAlreadyExistsError as exc:
        raise ConflictError("用户名已被使用") from exc

    return repository.find_by_id(user_id)


def authenticate(username, password):
    user = repository.find_by_username((username or "").strip())
    if user is None:
        return None
    if not check_password_hash(user["passwordHash"], password or ""):
        return None
    return user


def get_user_by_id(user_id):
    if not user_id:
        return None
    if isinstance(user_id, str):
        if not ObjectId.is_valid(user_id):
            return None
        user_id = ObjectId(user_id)
    return repository.find_by_id(user_id)
