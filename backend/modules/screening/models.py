"""Versioned contracts for synthetic, bilateral workflow rehearsals."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Key = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=100)]
Disease = Literal["glaucoma", "diabetic_retinopathy", "dme", "age_related_macular_degeneration"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Capture(Contract):
    image_ref: Text
    captured_at: datetime
    device: Text
    field: Text

    @model_validator(mode="after")
    def timezone_required(self) -> "Capture":
        if self.captured_at.utcoffset() is None:
            raise ValueError("采集时间必须包含时区")
        if not self.image_ref.startswith("synthetic:"):
            raise ValueError("演练只接受 synthetic: 开头的合成原图引用")
        return self


class ReferenceExam(Contract):
    modality: Literal["彩色眼底照", "OCT", "裂隙灯", "视野", "专科综合检查"]
    acquired_on: date
    source: Text
    interpretation: Text


class TaskAssessment(Contract):
    disease: Disease
    status: Literal["not_captured", "not_assessed", "ungradable", "gradable"]
    finding: Literal["not_assessed", "no_target_signs", "suspect"] = "not_assessed"
    visible_region: Text
    reason: str = Field(default="", max_length=1000)
    next_step: Text
    observations: str = Field(default="", max_length=2000)
    reference_exam: ReferenceExam | None = None
    source: Literal["human_rehearsal"] = "human_rehearsal"

    @model_validator(mode="after")
    def consistent_assessment(self) -> "TaskAssessment":
        if self.status != "gradable" and self.finding != "not_assessed":
            raise ValueError("未拍、未评估和不可判读均不能填阴性或可疑结论")
        if self.status == "gradable" and self.finding == "not_assessed":
            raise ValueError("可判读任务须明确可疑或未见目标征象")
        if self.status == "ungradable" and not self.reason.strip():
            raise ValueError("不可判读须说明原因及下一步")
        return self


class EyeRecord(Contract):
    laterality: Literal["right", "left"]
    captures: list[Capture] = Field(default_factory=list, max_length=20)
    tasks: list[TaskAssessment] = Field(min_length=1, max_length=4)
    analysis_refs: list[Text] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def consistent_tasks(self) -> "EyeRecord":
        if len({task.disease for task in self.tasks}) != len(self.tasks):
            raise ValueError("同眼任务不能重复")
        for task in self.tasks:
            pending_analysis = task.status == "not_assessed" and self.analysis_refs
            if not self.captures and task.status != "not_captured" and not pending_analysis:
                raise ValueError("未拍状态与原图记录不一致")
        return self


class Examination(Contract):
    synthetic: Literal[True]
    institution: Text
    encounter_id: Text
    patient_group: Text
    age: int = Field(ge=18, le=120)
    followup_owner: Text
    eyes: list[EyeRecord] = Field(min_length=2, max_length=2)
    note: str = Field(default="", max_length=4000)
    urgent_handoff: bool = False
    urgent_symptoms: list[Literal["curtain", "sudden_loss", "painful_red_eye"]] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def bilateral(self) -> "Examination":
        if self.urgent_symptoms and not self.urgent_handoff:
            raise ValueError("已记录紧急症状，须保留立即人工交接标记")
        if {eye.laterality for eye in self.eyes} != {"right", "left"}:
            raise ValueError("必须分别记录左右眼")
        return self


class ReportBinding(Contract):
    report_id: Text
    laterality: Literal["right", "left"]
    captured_at: datetime | None = None
    device: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def timezone_required(self) -> "ReportBinding":
        if self.captured_at and self.captured_at.utcoffset() is None:
            raise ValueError("采集时间必须包含时区")
        return self
