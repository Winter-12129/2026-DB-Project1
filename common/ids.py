import secrets


SHARE_CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def generate_share_code(length=10):
    """生成适合放进 URL、便于口头转述的随机分享码。"""

    return "".join(
        secrets.choice(SHARE_CODE_ALPHABET)
        for _ in range(length)
    )


def generate_question_id():
    return "q_" + secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:10]


def generate_option_id():
    return "o_" + secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:8]


def generate_rule_id():
    return "r_" + secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:10]
