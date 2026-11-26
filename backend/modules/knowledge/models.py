from dataclasses import dataclass

@dataclass
class Chunk:
    id: str
    source: str
    title: str
    section: str
    text: str
    lang: str = ""


@dataclass
class SourcedChunk(Chunk):
    url: str = ""
    version: str = ""
    jurisdiction: str = ""
    scope: str = ""


from typing import Any, Callable

RetrieveEvidence = Callable[..., list[dict[str, Any]]]
