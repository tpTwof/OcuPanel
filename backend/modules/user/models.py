"""账户相关的领域模型。"""

from typing_extensions import TypedDict


class User(TypedDict):
    """已认证用户的最小身份信息。"""

    id: str
    username: str
    display_name: str