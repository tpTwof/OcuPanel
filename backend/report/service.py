"""报告生成、记录保存及图像访问的应用服务。"""

from __future__ import annotations

import io
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
from report.utils.jobs import cleanup_job_dir, new_job_dir




async def _load_generator(user: User) -> MedicalReportGenerator:
    """取当前用户自己的 LLM 配置。没配就直接告诉用户去配，而不是甩一个 500。"""
    cfg = await run_in_threadpool(storage.load_llm_config, user["id"])
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

    拒答时 summary 为 None，调用方必须自己决定怎么呈现，绝不能把原文当成功返回。
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
    """生成 PDF。校验未通过时返回 422，不产出任何文件。"""
    _validate_upload(request)
    await _activate_analysis_mode(user, request.conversation_id)
    generator = await _load_generator(user)

    job_dir = new_job_dir("report")
    try:
        summary, verification, ratio, seg_path, evidence, findings = await _run_report_pipeline(
            generator, request.image_bytes, request.note, job_dir, request.diseases,
        )

        await run_in_threadpool(
            storage.save_report,
            user["id"],
            request.conversation_id,
            "",
            summary or "",
            verification,
            evidence,
            summary is None,
            ratio,
            None,
            findings,
        )

        if summary is None:
            raise ApplicationError(status_code=422, detail=generator.reject_message(verification))

        pdf_path = job_dir / "diagnostic_report.pdf"
        await run_in_threadpool(
            generator.generate_pdf_report,
            image_path=seg_path,
            cup_to_disc_ratio=ratio,
            synthesis_text=summary,
            output_path=str(pdf_path),
            evidence=evidence,
            visual_findings_text=format_visual_findings(
                findings, verification.get("missing_evidence_diseases"),
            ),
        )
    except Exception:
        cleanup_job_dir(job_dir)
        raise

    # 目录要等响应体发完才能删，否则 FileResponse 会读不到文件
    return ReportDownload(path=pdf_path, job_dir=job_dir)



async def generate_content(user: User, request: ReportSubmission) -> ReportContent:
    """生成报告正文（不产出 PDF），并把这一轮对话写进数据库。"""
    _validate_upload(request)
    await _activate_analysis_mode(user, request.conversation_id)
    generator = await _load_generator(user)

    job_dir = new_job_dir("content")
    try:
        summary, verification, ratio, seg_path, evidence, findings = await _run_report_pipeline(
            generator, request.image_bytes, request.note, job_dir, request.diseases,
        )
        rejected = summary is None
        display_text = generator.reject_message(verification) if rejected else summary
        findings_text = format_visual_findings(findings, verification.get("missing_evidence_diseases"))

        # 分割图要长期可访问（前端按 img_name 取回），存进 img_store。
        # 分析结果没有叠加图时仍可展示文字，img_name 保持为空。
        if seg_path and Path(seg_path).is_file():
            im = Image.open(seg_path)
            img_name = uuid.uuid4().hex
            im.convert("RGB").save(str(IMG_STORE_DIR / f"{img_name}.jpg"))
        else:
            img_name = ""

        report_id = await run_in_threadpool(
            storage.save_report,
            user["id"],
            request.conversation_id,
            img_name,
            display_text or "",
            verification,
            evidence,
            rejected,
            ratio,
            None,
            findings,
        )

        # 落一条 assistant 消息，这样刷新页面后这段报告还在对话里
        if request.conversation_id:
            await run_in_threadpool(
                storage.add_message, user["id"], request.conversation_id, "user",
                f"眼科分析：{request.filename}\n{request.note}",
                {"kind": "analysis_request"},
            )
            conversation = await run_in_threadpool(
                storage.get_conversation, user["id"], request.conversation_id,
            )
            if conversation and conversation["title"] in ("新对话", "", None):
                await run_in_threadpool(
                    storage.rename_conversation, user["id"], request.conversation_id,
                    f"眼科分析 · {request.filename}"[:60],
                )
            meta = {
                "kind": "report",
                "img_name": img_name,
                "evidence": evidence,
                "verification": verification,
                "rejected": rejected,
                "cup_to_disc_ratio": ratio,
                "report_id": report_id,
                "visual_findings_text": findings_text,
            }
            await run_in_threadpool(
                storage.add_message,
                user["id"],
                request.conversation_id,
                "assistant",
                display_text,
                meta,
            )
    finally:
        cleanup_job_dir(job_dir)

    return {
        "summary": display_text,
        "cup_to_disc_ratio": ratio,
        "img_name": img_name,
        "evidence": evidence,
        "verification": verification,
        "rejected": rejected,
        "report_id": report_id,
        "visual_findings": findings or {},
        "visual_findings_text": findings_text,
    }


async def get_report_image(img_name: str, user: User) -> Path:
    # 只允许安全字符，防止 ../ 穿越到 img_store 之外
    if not img_name.replace("-", "").replace("_", "").isalnum():
        raise ApplicationError(status_code=400, detail="非法的图片名")
    path = IMG_STORE_DIR / f"{img_name}.jpg"
    if not path.is_file():
        raise ApplicationError(status_code=404, detail="图片不存在")
    return path


async def export_report(user: User, report_id: str) -> ReportDownload:
    report = await run_in_threadpool(storage.get_report, user["id"], report_id)
    if report is None:
        raise ApplicationError(status_code=404, detail="报告不存在")
    if report["rejected"] or not report["summary"].strip():
        raise ApplicationError(status_code=422, detail="当前报告没有可导出的正文")

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
            visual_findings_text=format_visual_findings(
                report["visual_findings"], report["verification"].get("missing_evidence_diseases"),
            ),
        )
    except Exception:
        cleanup_job_dir(job_dir)
        raise
    return download
