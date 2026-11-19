"""报告 HTTP 路由：绑定请求对象、委托业务、构造响应。"""
from typing import Annotated
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from utils import auth
from report.models import ReportSubmission, ReportContent
from . import service
from .utils.jobs import cleanup_job_dir
from utils.errors import ApplicationError
from vision.analysis import DEFAULT_DISEASES, validate_diseases

report_router = APIRouter()

async def parse_report_submission(
    file: Annotated[UploadFile, File()],
    note: Annotated[str, Form()] = "",
    conversation_id: Annotated[str, Form()] = "",
    diseases: Annotated[list[str] | None, Form()] = None,
) -> ReportSubmission:
    try:
        selected = validate_diseases(DEFAULT_DISEASES if diseases is None else diseases)
    except ValueError as exc:
        raise ApplicationError(status_code=422, detail=str(exc)) from exc
    return ReportSubmission(await file.read(), file.filename or "", note, conversation_id or None, selected)

ReportRequest = Annotated[ReportSubmission, Depends(parse_report_submission)]

@report_router.post("/generate-report/")
async def generate_report(
    user: auth.CurrentUser,
    request: ReportRequest,
) -> FileResponse:
    download = await service.generate_report(user, request)
    return FileResponse(str(download.path), media_type="application/pdf", filename=download.filename,
                        background=BackgroundTask(cleanup_job_dir, download.job_dir))

@report_router.post("/generate-report-content/")
async def generate_content(
    user: auth.CurrentUser,
    request: ReportRequest,
) -> ReportContent:
    return await service.generate_content(user, request)


@report_router.get("/reports/{report_id}/pdf")
async def export_report(report_id: str, user: auth.CurrentUser) -> FileResponse:
    download = await service.export_report(user, report_id)
    return FileResponse(str(download.path), media_type="application/pdf", filename=download.filename,
                        headers={"Cache-Control": "no-store"},
                        background=BackgroundTask(cleanup_job_dir, download.job_dir))

@report_router.get("/get-report-image/{img_name}")
async def get_report_image(img_name: str, user: auth.CurrentUser) -> FileResponse:
    path = await service.get_report_image(img_name, user)
    return FileResponse(str(path), media_type="image/jpeg")
