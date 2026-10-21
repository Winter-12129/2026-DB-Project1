class AppError(Exception):
    """可预期的业务错误，由应用统一转换为页面或 JSON 响应。"""

    status_code = 400
    code = "bad_request"

    def __init__(self, message, code=None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
