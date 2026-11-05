from dataclasses import dataclass

@dataclass
class Chunk:
    id: str
    source: str
    title: str
    section: str
    text: str
    lang: str = ""


from typing import Any, Callable

RetrieveEvidence = Callable[..., list[dict[str, Any]]]
