"""应用错误。业务模块抛 ApplicationError，由入口统一转换为 HTTP 响应。"""

from __future__ import annotations


class ApplicationError(Exception):
    """可预期的业务错误；status_code 决定响应的 HTTP 状态。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail