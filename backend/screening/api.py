"""HTTP bindings for synthetic workflow rehearsals."""
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from report.utils.jobs import cleanup_job_dir

from screening import repository, service, imports
from screening.models import Command, CreateCase, ImportPreview, ConfirmImport
from utils import auth
from utils import storage
from utils.errors import ApplicationError
from report import assets, service as reports

screening_router = APIRouter(prefix="/screening", tags=["screening rehearsal"])


@screening_router.get("/site")
def current_site(user: auth.CurrentUser, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    with storage.connect() as conn:
        row = conn.execute("SELECT m.organization,m.role,s.receiving_unit,s.emergency_contact,s.daily_capacity "
                           "FROM screening_members m JOIN screening_sites s USING(organization) WHERE m.user_id=?",
                           (user["id"],)).fetchone()
    return dict(row) if row else {}


@screening_router.get("/cases/{case_id}/sources/{report_id}/{kind}")
def case_image(user: auth.CurrentUser, case_id: str, report_id: str, kind: Literal["original", "overlay"],
               revision: Annotated[int, Query(ge=1)]) -> Response:
    case = repository.get_case(user["id"], case_id, revision)
    for source in case.get("analysis_sources", []):
        if source["report_id"] == report_id:
            if kind == "overlay":
                name = source["report"].get("img_name") or ""
                if name and name.replace("-", "").replace("_", "").isalnum():
                    path = reports.IMG_STORE_DIR / f"{name}.jpg"
                    if path.is_file():
                        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
                raise ApplicationError(404, "当前病例版本没有可用的叠加图")
            metadata = source["report"]["source_metadata"]
            _, content = assets.read_original(metadata)
            if content is not None:
                return Response(content, media_type="application/octet-stream", headers={
                    "Content-Disposition": 'attachment; filename="original.img"', "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff"})
    raise ApplicationError(404, "当前病例版本没有可核验的原图")


@screening_router.post("/imports/preview")
def preview_import(user: auth.CurrentUser, request: ImportPreview, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return imports.preview(user, request)


@screening_router.post("/imports/{preview_id}/confirm")
def confirm_import(user: auth.CurrentUser, preview_id: str, request: ConfirmImport, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return imports.confirm(user, preview_id, request)


@screening_router.get("/cases")
def list_cases(user: auth.CurrentUser, response: Response) -> list[dict]:
    response.headers["Cache-Control"] = "no-store"
    return repository.list_cases(user["id"])


@screening_router.post("/cases")
def create_case(user: auth.CurrentUser, request: CreateCase, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return service.create_case(user, request)


@screening_router.get("/cases/{case_id}")
def get_case(user: auth.CurrentUser, case_id: str, response: Response,
             revision: Annotated[int | None, Query(ge=1)] = None) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return repository.get_case(user["id"], case_id, revision)


@screening_router.post("/cases/{case_id}/commands")
def apply_command(user: auth.CurrentUser, case_id: str, command: Command, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return service.apply_command(user, case_id, command)


@screening_router.get("/cases/{case_id}/context")
def get_context(user: auth.CurrentUser, case_id: str, revision: Annotated[int, Query(ge=1)], response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return service.followup_context(user["id"], case_id, revision)


@screening_router.get("/cases/{case_id}/export")
def export_case(user: auth.CurrentUser, case_id: str, revision: Annotated[int, Query(ge=1)]) -> Response:
    snapshot = repository.get_case(user["id"], case_id, revision)
    return Response(repository.encode(snapshot), media_type="application/json",
                    headers={"Cache-Control": "no-store",
                             "Content-Disposition": f'attachment; filename="screening-{case_id}-v{revision}.json"'})


@screening_router.get("/cases/{case_id}/pdf")
def export_pdf(user: auth.CurrentUser, case_id: str, revision: Annotated[int, Query(ge=1)]) -> FileResponse:
    result = service.export_pdf(user["id"], case_id, revision)
    return FileResponse(str(result.path), media_type="application/pdf", filename=result.filename,
                        headers={"Cache-Control": "no-store"},
                        background=BackgroundTask(cleanup_job_dir, result.job_dir))
