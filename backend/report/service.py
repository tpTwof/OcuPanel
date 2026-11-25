"""报告生成、记录保存及图像访问的应用服务。"""

from __future__ import annotations

import io
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any
from user.models import User
from report.models import ReportSubmission, ReportDownload, ReportContent, ReportResult
from vision.analysis import DEFAULT_DISEASES
from vision.models import FundusImageDecodeError, FundusImageUnusable
from vision.diseases.retinal import RetinalModelUnavailable

from utils.errors import ApplicationError
from PIL import Image
from starlette.concurrency import run_in_threadpool

from utils import storage
from utils.paths import IMG_STORE_DIR
from report.generation import MedicalReportGenerator, build_generator_for_user
from report.context import format_visual_findings
from report.pdf import PDFRenderer
from report.utils.messages import reject_message
from report.utils.jobs import cleanup_job_dir, new_job_dir
from report import assets


async def _load_generator(user: User) -> MedicalReportGenerator:
    """取当前用户自己的 LLM 配置。没配就直接告诉用户去配，而不是甩一个 500。"""
    from screening.access import analysis_site
    def checked_config():
        with storage.connect() as conn:
            analysis_site(conn, user["id"])
        return storage.load_llm_config(user["id"])
    cfg = await run_in_threadpool(checked_config)
    if not cfg:
        raise ApplicationError(
            status_code=409,
            detail="尚未配置 LLM API，请先在左下角「个人设置」中填写 API Key、接口地址与模型",
        )
    return build_generator_for_user(cfg)


async def _run_report_pipeline(
    generator: MedicalReportGenerator,
    contents: bytes,
    note: str,
    job_dir: Path,
    diseases: tuple[str, ...] = DEFAULT_DISEASES,
) -> ReportResult:
    """运行所选病种的影像分析、专科报告、综合和引用校验。

    未通过的诊疗草稿不能当成功返回；limited 只保留病例输入，不能导出诊断 PDF。
    """
    try:
        return await run_in_threadpool(
            generator.generate, io.BytesIO(contents), note, job_dir, diseases=diseases,
        )
    except FundusImageDecodeError as exc:
        raise ApplicationError(status_code=400, detail="图片无法解析，请换一张") from exc
    except FundusImageUnusable as exc:
        raise ApplicationError(status_code=422, detail=str(exc)) from exc
    except RetinalModelUnavailable as exc:
        raise ApplicationError(
            status_code=503,
            detail="糖网与黄斑变性影像模型暂不可用。请检查 FLAIR 依赖和模型权重，或选择青光眼分析。",
        ) from exc


def _validate_upload(request: ReportSubmission) -> None:
    if not request.filename or not request.filename.lower().endswith((".jpg", ".jpeg", ".png")):
        raise ApplicationError(status_code=400, detail="仅支持 .jpg / .jpeg / .png 格式的眼底图像")


async def _activate_analysis_mode(user: User, conversation_id: str | None) -> None:
    if not conversation_id:
        return
    changed = await run_in_threadpool(
        storage.set_conversation_mode, user["id"], conversation_id, "ophthalmic",
    )
    if not changed:
        raise ApplicationError(status_code=404, detail="会话不存在")


async def generate_report(user: User, request: ReportSubmission) -> ReportDownload:
    content = await _generate_and_store(user, request, append_to_chat=False)
    if content["rejected"]:
        raise ApplicationError(status_code=422, detail=content["summary"])
    return await export_report(user, content["report_id"])


async def generate_content(user: User, request: ReportSubmission) -> ReportContent:
    return await _generate_and_store(user, request, append_to_chat=True)


def _archive_result(
    user_id: str, request: ReportSubmission, result: ReportResult, append_to_chat: bool,
    report_id: str | None = None,
) -> ReportContent:
    summary, verification, ratio, seg_path, evidence, findings = result
    rejected = summary is None or verification.get("status") == "limited"
    display_text = reject_message(verification) if summary is None else summary
    findings_text = format_visual_findings(findings, verification.get("missing_evidence_diseases"))
    img_name = uuid.uuid4().hex if seg_path else ""
    archive_image = IMG_STORE_DIR / f"{img_name}.jpg" if img_name else None
    source_metadata = {
        "schema_version": 1, "filename": request.filename, "clinical_note": request.note,
        "selected_diseases": list(request.diseases), "laterality": request.laterality,
        "captured_at": request.captured_at.isoformat() if request.captured_at else None,
        "device": request.device, "data_kind": "synthetic_declared" if request.synthetic else "unclassified",
        "original_id": uuid.uuid4().hex, "original_sha256": hashlib.sha256(request.image_bytes).hexdigest(),
    }
    original_file = assets.original_path(source_metadata)
    meta = {
        "kind": "report", "img_name": img_name, "evidence": evidence,
        "verification": verification, "rejected": rejected, "cup_to_disc_ratio": ratio,
        "visual_findings_text": findings_text,
    }
    chat_turn = None
    if append_to_chat and request.conversation_id:
        chat_turn = (f"眼科分析：{request.filename}\n{request.note}", meta, f"眼科分析 · {request.filename}"[:60])
    try:
        assets.ORIGINAL_STORE_DIR.mkdir(parents=True, exist_ok=True)
        original_file.write_bytes(request.image_bytes)
        if archive_image:
            with Image.open(seg_path) as image:
                image.convert("RGB").save(archive_image)
        report_id = storage.save_report(
            user_id, request.conversation_id, img_name, display_text, verification,
            evidence, rejected, cup_to_disc=ratio, visual_findings=findings, chat_turn=chat_turn,
            source_metadata=source_metadata,
            report_id=report_id,
        )
    except Exception:
        if archive_image:
            archive_image.unlink(missing_ok=True)
        original_file.unlink(missing_ok=True)
        raise

    return {
        "summary": display_text, "cup_to_disc_ratio": ratio, "img_name": img_name,
        "evidence": evidence, "verification": verification, "rejected": rejected,
        "report_id": report_id, "visual_findings": findings or {},
        "visual_findings_text": findings_text,
    }


async def _generate_and_store(
    user: User, request: ReportSubmission, *, append_to_chat: bool, report_id: str | None = None,
) -> ReportContent:
    _validate_upload(request)
    await _activate_analysis_mode(user, request.conversation_id)
    generator = await _load_generator(user)

    job_dir = new_job_dir("content")
    try:
        result = await _run_report_pipeline(
            generator, request.image_bytes, request.note, job_dir, request.diseases,
        )
        return await run_in_threadpool(_archive_result, user["id"], request, result, append_to_chat, report_id)
    finally:
        cleanup_job_dir(job_dir)


async def get_report_image(img_name: str, user: User) -> Path:
    # 只允许安全字符，防止 ../ 穿越到 img_store 之外
    if not img_name.replace("-", "").replace("_", "").isalnum():
        raise ApplicationError(status_code=400, detail="非法的图片名")
    path = IMG_STORE_DIR / f"{img_name}.jpg"
    if not await run_in_threadpool(storage.owns_report_image, user["id"], img_name) or not path.is_file():
        raise ApplicationError(status_code=404, detail="图片不存在")
    return path


async def export_report(user: User, report_id: str) -> ReportDownload:
    report = await run_in_threadpool(storage.get_report, user["id"], report_id)
    if report is None:
        raise ApplicationError(status_code=404, detail="报告不存在")
    if report["verification"].get("status") == "limited":
        raise ApplicationError(status_code=422, detail="当前仅提供病例资料摘要，诊疗结论未通过核查，不能导出诊断报告 PDF")
    if report["rejected"] or not report["summary"].strip():
        raise ApplicationError(status_code=422, detail="当前报告没有可导出的正文")

    status = report["verification"].get("status")
    if status not in ("pass", "rewritten"):
        raise ApplicationError(status_code=422, detail="此报告没有通过引用校验的记录，无法导出 PDF")

    image_path = ""
    img_name = report["img_name"]
    if img_name and img_name.replace("-", "").replace("_", "").isalnum():
        image = IMG_STORE_DIR / f"{img_name}.jpg"
        if image.is_file():
            image_path = str(image)

    job_dir = new_job_dir("report")
    download = ReportDownload(path=job_dir / "diagnostic_report.pdf", job_dir=job_dir)
    try:
        await run_in_threadpool(
            PDFRenderer().generate_pdf_report,
            image_path=image_path,
            cup_to_disc_ratio=report["cup_to_disc"],
            synthesis_text=report["summary"],
            output_path=str(download.path),
            evidence=report["evidence"],
            verification_status=status,
            visual_findings_text=format_visual_findings(
                report["visual_findings"], report["verification"].get("missing_evidence_diseases"),
            ),
        )
    except Exception:
        cleanup_job_dir(job_dir)
        raise
    return download


def report_detail(user_id: str, report_id: str) -> dict[str, Any]:
    report = storage.get_report(user_id, report_id)
    if report is None:
        raise ApplicationError(404, "报告不存在")
    report["original"] = assets.inspect_original(report["source_metadata"])
    return report


def report_catalog(user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    with storage.connect() as conn:
        rows = conn.execute("SELECT id, created_at, rejected, verification, source_metadata FROM reports WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit)).fetchall()
    return [{"id": row["id"], "created_at": row["created_at"], "rejected": bool(row["rejected"]),
             "verification": json.loads(row["verification"]), "source_metadata": json.loads(row["source_metadata"])} for row in rows]


def get_original(user_id: str, report_id: str) -> bytes:
    report = storage.get_report(user_id, report_id)
    if report is None:
        raise ApplicationError(404, "报告不存在")
    _, content = assets.read_original(report["source_metadata"])
    if content is None:
        raise ApplicationError(404, "原图缺失或完整性校验失败")
    return content
