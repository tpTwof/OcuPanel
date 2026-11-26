"""合成病例接口的创建、操作及导入请求。"""
from datetime import date, datetime
from typing import Annotated, Literal
from pydantic import Field, model_validator
from modules.screening.models import Contract, Examination, Key, ReportBinding, Text


class CreateCase(Contract):
    idempotency_key: Key
    examination: Examination


class Mutation(Contract):
    idempotency_key: Key
    expected_revision: int = Field(ge=1)


class Revise(Mutation):
    action: Literal["revise"]
    examination: Examination
    reason: Text


class Review(Mutation):
    action: Literal["review"]
    original_images_checked: Literal[True]
    case_checked: Literal[True]
    comment: Text


class Sign(Mutation):
    action: Literal["sign"]
    plan: Text


class Refer(Mutation):
    action: Literal["refer"]
    destination: Text
    followup_owner: Text
    due_at: datetime
    eyes: list[Literal["right", "left"]] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def valid_referral(self) -> "Refer":
        if self.due_at.utcoffset() is None:
            raise ValueError("跟进期限必须包含时区")
        if len(set(self.eyes)) != len(self.eyes):
            raise ValueError("转诊眼别不能重复")
        return self


class Receipt(Mutation):
    action: Literal["receipt"]
    referral_id: Text
    status: Literal["accepted", "arrived", "lost"]
    note: Text


class Handoff(Mutation):
    action: Literal["handoff"]
    followup_owner: Text
    reason: Text


class Revoke(Mutation):
    action: Literal["revoke"]
    reason: Text


class Followup(Mutation):
    action: Literal["followup"]
    adherence: Text
    symptoms: Text
    next_visit: date | None = None


Command = Annotated[Revise | Review | Sign | Refer | Receipt | Handoff | Revoke | Followup, Field(discriminator="action")]


class ImportPreview(Contract):
    case_id: Text | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    examination: Examination
    bindings: list[ReportBinding] = Field(min_length=1, max_length=2)
    note_policy: Literal["keep", "append", "replace"] = "keep"

    @model_validator(mode="after")
    def valid_target(self) -> "ImportPreview":
        if bool(self.case_id) != bool(self.expected_revision):
            raise ValueError("补充病例必须同时指定病例和当前版本")
        if len({binding.report_id for binding in self.bindings}) != len(self.bindings):
            raise ValueError("同一分析不能同时绑定两只眼")
        if len({binding.laterality for binding in self.bindings}) != len(self.bindings):
            raise ValueError("每次导入每只眼只能选择一份分析")
        return self


class ConfirmImport(Contract):
    idempotency_key: Key
    synthetic_rehearsal_confirmed: Literal[True]
    laterality_confirmed: Literal[True]
