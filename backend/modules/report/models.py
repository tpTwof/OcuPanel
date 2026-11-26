from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple
from typing_extensions import TypedDict, NotRequired
from modules.vision.analysis import DEFAULT_DISEASES

@dataclass(frozen=True)
class ReportSubmission:
    image_bytes: bytes
    filename: str
    note: str = ""
    conversation_id: str | None = None
    diseases: tuple[str, ...] = DEFAULT_DISEASES
    laterality: str | None = None
    captured_at: datetime | None = None
    device: str = ""
    synthetic: bool = False

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
    visual_findings: NotRequired[dict[str, dict[str, Any]]]
    visual_findings_text: NotRequired[str]

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

class ReportResult(NamedTuple):
    summary: str | None
    verification: dict[str, Any]
    cup_to_disc_ratio: float | None
    image_path: str
    evidence: list[dict[str, Any]]
    visual_findings: dict[str, dict[str, Any]] | None = None
