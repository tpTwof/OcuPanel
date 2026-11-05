"""应用错误，由 HTTP 入口转换为响应，业务模块不依赖 FastAPI 异常。"""
class ApplicationError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
