import os
from datetime import timedelta


class Config:
    """应用配置。生产环境请通过环境变量覆盖默认值。"""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
    MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "survey_system")
    MONGO_ENSURE_INDEXES = True

    CSRF_ENABLED = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
