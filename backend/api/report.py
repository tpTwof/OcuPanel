"""报告生成与取图接口。

与旧版的区别：
- 身份来自登录 token（`auth.CurrentUser`），不再由前端随手传一个 user_uuid；
- LLM 配置来自该用户在 SQLite 里的配置（`build_generator_for_user`），
  代码里不再有任何写死的厂商/模型/密钥；
- 每次生成结果落到 `reports` 表，包括被拒答的那次（"曾经拒答过"本身要留痕）。
"""

from __future__ import annotations

import io
import uuid
from typing import Optional

import imageio.v2 as imageio
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

import auth
import storage
from paths import IMG_STORE_DIR
from report_generator import build_generator_for_user, cleanup_job_dir, new_job_dir

report_router = APIRouter()

ROLES = [
    "Ophthalmologist",
    "Optometrist",
    "Glaucoma Specialist",
    "Primary Care Physician",
    "Ophthalmic Technician",
    "Pharmacist",
]


async def _load_generator(user: dict):
    """取当前用户自己的 LLM 配置。没配就直接告诉用户去配，而不是甩一个 500。"""
    cfg = await run_in_threadpool(storage.load_llm_config, user["id"])
    if not cfg:
        raise HTTPException(
            status_code=409,
            detail="尚未配置 LLM API，请先在左下角「个人设置」中填写 API Key、接口地址与模型",
        )
    return build_generator_for_user(cfg)


async def _run_report_pipeline(generator, contents: bytes, note: str, job_dir):
    """六专科并发 → Director → 引用校验。返回 (summary, verification, ratio, seg_path, evidence)。

    拒答时 summary 为 None，调用方必须自己决定怎么呈现，绝不能把原文当成功返回。
    """
    reports, ratio, segmented_image_path, evidence = await run_in_threadpool(
        generator.generate_reports, io.BytesIO(contents), note, ROLES, job_dir
    )
    summary = await run_in_threadpool(generator.generate_synthesis, reports, evidence)
    summary, verification = await run_in_threadpool(
        generator.verify_synthesis,
        summary,
        evidence,
        lambda issues: generator.generate_synthesis(reports, evidence, avoid=issues),
    )
    print(f"[VERIFY] {verification.get('status')}")
    return summary, verification, ratio, segmented_image_path, evidence


def _validate_upload(file: UploadFile) -> None:
    if not file.filename or not file.filename.lower().endswith((".jpg", ".jpeg", ".png")):
        raise HTTPException(status_code=400, detail="仅支持 .jpg / .jpeg / .png 格式的眼底图像")


@report_router.post("/generate-report/")
async def generate_report(
    user: auth.CurrentUser,
    file: UploadFile = File(...),
    note: Optional[str] = Form(""),
    conversation_id: Optional[str] = Form(""),
):
    """生成 PDF。校验未通过时返回 422，不产出任何文件。"""
    _validate_upload(file)
    generator = await _load_generator(user)

    contents = await file.read()
    try:
        imageio.imread(io.BytesIO(contents))
    except Exception:
        raise HTTPException(status_code=400, detail="图片无法解析，请换一张") from None

    job_dir = new_job_dir("report")
    try:
        summary, verification, ratio, seg_path, evidence = await _run_report_pipeline(
            generator, contents, note or "", job_dir
        )

        await run_in_threadpool(
            storage.save_report,
            user["id"],
            conversation_id or None,
            "",
            summary or "",
            verification,
            evidence,
            summary is None,
            ratio,
            None,
        )

        if summary is None:
            raise HTTPException(status_code=422, detail=generator.reject_message(verification))

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
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename="diagnostic_report.pdf",
        background=BackgroundTask(cleanup_job_dir, job_dir),
    )


@report_router.post("/generate-report-content/")
async def generate_content(
    user: auth.CurrentUser,
    file: UploadFile = File(...),
    note: Optional[str] = Form(""),
    conversation_id: Optional[str] = Form(""),
):
    """生成报告正文（不产出 PDF），并把这一轮对话写进数据库。"""
    _validate_upload(file)
    generator = await _load_generator(user)

    contents = await file.read()
    try:
        imageio.imread(io.BytesIO(contents))
    except Exception:
        raise HTTPException(status_code=400, detail="图片无法解析，请换一张") from None

    job_dir = new_job_dir("content")
    try:
        summary, verification, ratio, seg_path, evidence = await _run_report_pipeline(
            generator, contents, note or "", job_dir
        )
        rejected = summary is None
        display_text = generator.reject_message(verification) if rejected else summary

        # 分割图要长期可访问（前端按 img_name 取回），存进 img_store
        im = Image.open(seg_path)
        img_name = uuid.uuid4().hex
        im.convert("RGB").save(str(IMG_STORE_DIR / f"{img_name}.jpg"))

        report_id = await run_in_threadpool(
            storage.save_report,
            user["id"],
            conversation_id or None,
            img_name,
            display_text or "",
            verification,
            evidence,
            rejected,
            ratio,
            None,
        )

        # 落一条 assistant 消息，这样刷新页面后这段报告还在对话里
        if conversation_id:
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
                conversation_id,
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


@report_router.get("/get-report-image/{img_name}")
async def get_report_image(img_name: str, user: auth.CurrentUser):
    # 只允许安全字符，防止 ../ 穿越到 img_store 之外
    if not img_name.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="非法的图片名")
    path = IMG_STORE_DIR / f"{img_name}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path=str(path), media_type="image/jpeg")
