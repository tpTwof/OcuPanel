"""Synthetic reading/referral state machine. No model or clinical signature is implied."""
import hashlib
from typing import Any

from screening import access, repository
from screening.models import Command, CreateCase, Followup, Handoff, Receipt, Refer, Review, Revise, Revoke, Sign
from screening.presentation import describe
from report.models import ReportDownload
from user.models import User
from utils import storage
from utils.errors import ApplicationError

SOFTWARE_VERSION = "screening-rehearsal-v3"


def _fingerprint(scope: str, payload: dict) -> str:
    return hashlib.sha256(repository.encode({"scope": scope, "payload": payload}).encode()).hexdigest()


def _audit(case: dict, user: User, action: str, detail: dict[str, Any]) -> None:
    case["updated_at"] = storage.now()
    case["provenance"]["software"] = SOFTWARE_VERSION
    case["events"].append({"revision": case["revision"], "actor_id": user["id"],
                           "actor_name": user["display_name"], "action": action,
                           "at": case["updated_at"], "software": SOFTWARE_VERSION, "detail": detail})


def create_case(user: User, request: CreateCase) -> dict:
    from screening.imports import validate_refs
    validate_refs(request.examination, [])
    fingerprint = _fingerprint("create", request.model_dump(mode="json"))
    with storage.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cached = repository.replay(conn, user["id"], request.idempotency_key, fingerprint)
        if cached is not None:
            access.scope(conn, user["id"], cached["id"], "create")
            return cached
        case = {"schema_version": 1, "id": storage.new_id(), "revision": 1,
                "stage": "draft", "examination": request.examination.model_dump(mode="json"),
                "review": None, "signature": None, "referrals": [], "events": [],
                "provenance": {"software": SOFTWARE_VERSION, "model": "none-human-rehearsal",
                               "rules": "manual-rehearsal-v1", "guidelines": [],
                               "validation": "synthetic_only", "clinical_release": False}}
        _audit(case, user, "create", {})
        repository.save(conn, user["id"], case, request.idempotency_key, fingerprint)
        return case


def apply_command(user: User, case_id: str, command: Command) -> dict:
    fingerprint = _fingerprint(case_id, command.model_dump(mode="json"))
    with storage.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        access.scope(conn, user["id"], case_id, command.action)
        cached = repository.replay(conn, user["id"], command.idempotency_key, fingerprint)
        if cached is not None:
            return cached
        case = repository.read(conn, user["id"], case_id)
        if case["revision"] != command.expected_revision:
            raise ApplicationError(409, "病例已更新，请刷新后基于最新版本操作")
        case["revision"] += 1
        detail = command.model_dump(mode="json", exclude={"idempotency_key", "expected_revision", "action"})
        if isinstance(command, Revise):
            from screening.imports import validate_refs
            validate_refs(command.examination, case.get("analysis_sources", []))
            organization = conn.execute("SELECT organization FROM screening_cases WHERE id=?", (case_id,)).fetchone()[0]
            if organization and command.examination.institution != organization:
                raise ApplicationError(409, "已共享病例的机构不能修改")
            case.update(examination=command.examination.model_dump(mode="json"),
                        stage="draft", review=None, signature=None)
        elif isinstance(command, Review):
            from screening.imports import require_reviewable
            require_reviewable(case)
            if case["stage"] != "draft":
                raise ApplicationError(409, "只有草稿可复核；修改已签发内容须创建新版本")
            case["review"] = {**detail, "actor_id": user["id"], "revision": case["revision"]}
            case["stage"] = "reviewed"
        elif isinstance(command, Sign):
            if case["stage"] != "reviewed":
                raise ApplicationError(409, "须先完成人工原图与病例复核")
            if any(task["status"] == "not_assessed" for eye in case["examination"]["eyes"] for task in eye["tasks"]):
                raise ApplicationError(409, "仍有未评估任务，请先补充评估或明确不可判读及安排")
            for eye in case["examination"]["eyes"]:
                for task in eye["tasks"]:
                    if task["disease"] == "dme" and task["status"] == "gradable":
                        if (task.get("reference_exam") or {}).get("modality") != "OCT":
                            raise ApplicationError(409, "DME 可判读结论须附同眼 OCT 日期、来源及人工解读")
            case["signature"] = {"kind": "simulated", "actor_id": user["id"],
                                 "actor_name": user["display_name"], "plan": command.plan,
                                 "signed_revision": case["revision"], "at": storage.now()}
            case["stage"] = "signed"
        elif isinstance(command, Revoke):
            if case["signature"] is None:
                raise ApplicationError(409, "当前版本没有可撤销的模拟签发")
            detail["signed_revision"] = case["signature"]["signed_revision"]
            case.update(stage="draft", signature=None, review=None)
        elif isinstance(command, Refer):
            if case["signature"] is None:
                raise ApplicationError(409, "转诊须引用已模拟签发的报告版本")
            signed_revision = case["signature"]["signed_revision"]
            if any(ref["signed_revision"] == signed_revision for ref in case["referrals"]):
                raise ApplicationError(409, "此签发版本已有转诊单，请跟进原转诊单")
            case["referrals"].append({**detail, "id": storage.new_id(), "signed_revision": signed_revision,
                                      "status": "waiting", "created_at": storage.now(), "receipts": []})
        elif isinstance(command, Receipt):
            referral = next((ref for ref in case["referrals"] if ref["id"] == command.referral_id), None)
            if referral is None:
                raise ApplicationError(404, "转诊单不存在")
            transitions = {"waiting": {"accepted", "arrived", "lost"}, "accepted": {"arrived", "lost"},
                           "lost": {"accepted", "arrived"}, "arrived": set()}
            if command.status not in transitions[referral["status"]]:
                raise ApplicationError(409, "回执状态不允许此变更")
            referral["status"] = command.status
            referral["receipts"].append({**detail, "actor_id": user["id"], "at": storage.now()})
        elif isinstance(command, Followup):
            if case["signature"] is None:
                raise ApplicationError(409, "登记随访需要当前有效的模拟签发计划")
            detail["signed_revision"] = case["signature"]["signed_revision"]
        elif isinstance(command, Handoff):
            case["examination"]["followup_owner"] = command.followup_owner
            for referral in case["referrals"]:
                if referral["status"] != "arrived":
                    referral["followup_owner"] = command.followup_owner
        _audit(case, user, command.action, detail)
        repository.save(conn, user["id"], case, command.idempotency_key, fingerprint)
        return case


def followup_context(user_id: str, case_id: str, revision: int) -> dict:
    """Deterministic context; callers must select the exact report revision."""
    case = repository.get_case(user_id, case_id, revision)
    signed = case["signature"]
    return {"case_id": case_id, "revision": revision, "synthetic": True,
            "explanation": describe(case),
            "eyes": case["examination"]["eyes"],
            "analysis_sources": case.get("analysis_sources", []),
            "signed_plan": signed["plan"] if signed else None,
            "signature_kind": "simulated" if signed else "unsigned",
            "scope": "仅当前检查、眼别、任务和版本；缺失结果不代表阴性；治疗变更交接诊医生",
            "provenance": case["provenance"]}


def export_pdf(user_id: str, case_id: str, revision: int) -> ReportDownload:
    from report.pdf import PDFRenderer
    from report.utils.jobs import cleanup_job_dir, new_job_dir

    case = repository.get_case(user_id, case_id, revision)
    if case["signature"] is None:
        raise ApplicationError(422, "尚未模拟签发；草稿可导出 JSON 快照")
    folder = new_job_dir("report")
    result = ReportDownload(folder / "synthetic-screening.pdf", folder, f"synthetic-screening-v{revision}.pdf")
    try:
        PDFRenderer().generate_pdf_report("", None, describe(case), output_path=str(result.path))
    except Exception:
        cleanup_job_dir(folder)
        raise
    return result
