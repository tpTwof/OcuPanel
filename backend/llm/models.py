from typing import Protocol, TypedDict

class LLMCall(Protocol):
    def __call__(
        self,
        prompt: str,
        /,
        *,
        reset: bool = True,
        system: str | None = None,
        temperature: float | None = None,
    ) -> str: ...


class LLMConfiguration(TypedDict):
    api_key: str
    base_url: str
    model: str
