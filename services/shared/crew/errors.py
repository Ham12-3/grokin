"""Application errors. The API turns these into `{"error": {"code", "message"}}`."""


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def unauthorized(code: str = "unauthorized", message: str = "Sign in again.") -> AppError:
    return AppError(401, code, message)
