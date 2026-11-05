from dataclasses import dataclass

@dataclass(frozen=True)
class SpecialistRole:
    name: str
    query_hint: str
