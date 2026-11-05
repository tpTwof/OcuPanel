"""报告生成、记录保存及图像访问的应用服务。"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Any
from user.models import User
from report.models import ReportSubmission, ReportDownload, ReportContent, ReportResult
from agents.roles import DEFAULT_ROLES

import imageio.v2 as imageio
from utils.errors import ApplicationError
from PIL import Image
from starlette.concurrency import run_in_threadpool

from utils import storage
from utils.paths import IMG_STORE_DIR
from report.generation import MedicalReportGenerator, build_generator_for_user
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
) -> ReportResult:
    """六专科并发 → Director → 引用校验。返回 (summary, verification, ratio, seg_path, evidence)。

    拒答时 summary 为 None，调用方必须自己决定怎么呈现，绝不能把原文当成功返回。
    """
    return await run_in_threadpool(
        generator.generate, io.BytesIO(contents), note, DEFAULT_ROLES, job_dir
    )


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

    contents = request.image_bytes
    try:
        imageio.imread(io.BytesIO(contents))
    except Exception:
        raise ApplicationError(status_code=400, detail="图片无法解析，请换一张") from None

    job_dir = new_job_dir("report")
    try:
        summary, verification, ratio, seg_path, evidence = await _run_report_pipeline(
            generator, contents, request.note, job_dir
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

    contents = request.image_bytes
    try:
        imageio.imread(io.BytesIO(contents))
    except Exception:
        raise ApplicationError(status_code=400, detail="图片无法解析，请换一张") from None

    job_dir = new_job_dir("content")
    try:
        summary, verification, ratio, seg_path, evidence = await _run_report_pipeline(
            generator, contents, request.note, job_dir
        )
        rejected = summary is None
        display_text = generator.reject_message(verification) if rejected else summary

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
    }


async def get_report_image(img_name: str, user: User) -> Path:
    # 只允许安全字符，防止 ../ 穿越到 img_store 之外
    if not img_name.replace("-", "").replace("_", "").isalnum():
        raise ApplicationError(status_code=400, detail="非法的图片名")
    path = IMG_STORE_DIR / f"{img_name}.jpg"
    if not path.is_file():
        raise ApplicationError(status_code=404, detail="图片不存在")
    return path
