from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict, NamedTuple

@dataclass(frozen=True)
class ReportSubmission:
    image_bytes: bytes
    filename: str
    note: str = ""
    conversation_id: str | None = None

@dataclass(frozen=True)
class ReportDownload:
    path: Path
    job_dir: Path
    filename: str = "diagnostic_report.pdf"

class ReportContent(TypedDict):
    summary: str
    cup_to_disc_ratio: float | None
    img_name: str
    evidence: list[dict[str, Any]]
    verification: dict[str, Any]
    rejected: bool
    report_id: str

@dataclass(frozen=True)
class ReportLabels:
    title: str
    cdr: str
    legend: str
    summary: str
    references: str
    chat: str
    you: str
    ai: str
    footer: str

class SpecialistReports(NamedTuple):
    reports: dict[str, str]
    cup_to_disc_ratio: float | None
    image_path: str
    evidence: list[dict[str, Any]]

class ReportResult(NamedTuple):
    summary: str | None
    verification: dict[str, Any]
    cup_to_disc_ratio: float | None
    image_path: str
    evidence: list[dict[str, Any]]
