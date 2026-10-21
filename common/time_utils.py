from datetime import datetime, timezone
from zoneinfo import ZoneInfo


APP_TIMEZONE = ZoneInfo("Asia/Shanghai")


def utc_now():
    return datetime.now(timezone.utc)


def as_utc(value):
    if value and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def format_local_datetime(value):
    """把 UTC 时间转成本机时区显示；无时区信息时按 UTC 处理。"""

    if not value:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(APP_TIMEZONE).strftime("%Y-%m-%d %H:%M")


def parse_local_datetime(value):
    """把 datetime-local 输入按上海时区解析，再转成 UTC。"""

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=APP_TIMEZONE)
    return parsed.astimezone(timezone.utc)


def to_local_input(value):
    """把 UTC 时间转成 datetime-local 输入框需要的格式。"""

    if not value:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(APP_TIMEZONE).strftime("%Y-%m-%dT%H:%M")
