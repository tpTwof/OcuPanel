"""报告 HTTP 路由：绑定请求对象、委托业务、构造响应。"""
from typing import Annotated, Literal
from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, UploadFile, Query, Response
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
    laterality: Annotated[Literal["right", "left"] | None, Form()] = None,
    captured_at: Annotated[datetime | None, Form()] = None,
    device: Annotated[str, Form(max_length=500)] = "",
    synthetic: Annotated[bool, Form()] = False,
) -> ReportSubmission:
    try:
        selected = validate_diseases(DEFAULT_DISEASES if diseases is None else diseases)
    except ValueError as exc:
        raise ApplicationError(status_code=422, detail=str(exc)) from exc
    if captured_at and captured_at.utcoffset() is None:
        raise ApplicationError(422, "采集时间必须包含时区")
    return ReportSubmission(await file.read(), file.filename or "", note, conversation_id or None, selected,
                            laterality, captured_at, device.strip(), synthetic)


@report_router.get("/reports")
def list_saved_reports(user: auth.CurrentUser, response: Response, limit: Annotated[int, Query(ge=1, le=100)] = 100) -> list[dict]:
    response.headers["Cache-Control"] = "no-store"
    return service.report_catalog(user["id"], limit)


@report_router.get("/reports/{report_id}")
def get_saved_report(report_id: str, user: auth.CurrentUser, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return service.report_detail(user["id"], report_id)


@report_router.get("/reports/{report_id}/original")
def get_saved_original(report_id: str, user: auth.CurrentUser) -> Response:
    return Response(service.get_original(user["id"], report_id), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="original-{report_id}.img"',
                             "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

ReportRequest = Annotated[ReportSubmission, Depends(parse_report_submission)]

@report_router.post("/report-jobs", status_code=202)
def submit_job(user: auth.CurrentUser, request: ReportRequest,
               request_key: Annotated[str, Form(min_length=8, max_length=100)]) -> dict:
    from report.queue import submit
    return submit(user, request, request_key)


@report_router.get("/report-jobs/{job_id}")
def job_status(user: auth.CurrentUser, job_id: str, response: Response) -> dict:
    from report.queue import status
    response.headers["Cache-Control"] = "no-store"
    return status(user["id"], job_id)

@report_router.post("/generate-report/")
async def generate_report(
    user: auth.CurrentUser,
    request: ReportRequest,
) -> FileResponse:
    download = await service.generate_report(user, request)
    return FileResponse(str(download.path), media_type="application/pdf", filename=download.filename,
                        headers={"Cache-Control": "no-store"},
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
    return FileResponse(str(path), media_type="image/jpeg", headers={"Cache-Control": "no-store"})
