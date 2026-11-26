"""Persistent local inference jobs, with one active consumer per database."""
import asyncio
from dataclasses import fields
from datetime import datetime
import hashlib
import json
import logging

from filelock import FileLock, Timeout
from modules.report import service
from modules.report.context import format_visual_findings
from modules.report.models import ReportSubmission
from core import storage
from core.errors import ApplicationError
from modules.screening.access import analysis_site


def submit(user: dict, request: ReportSubmission, key: str) -> dict:
    service._validate_upload(request)
    metadata = {f.name: getattr(request, f.name) for f in fields(request) if f.name != "image_bytes"}
    if request.captured_at:
        metadata["captured_at"] = request.captured_at.isoformat()
    encoded = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(encoded.encode() + b"\0" + request.image_bytes).hexdigest()
    with storage.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute("SELECT id,fingerprint,state FROM report_jobs WHERE user_id=? AND request_key=?",
                           (user["id"], key)).fetchone()
        if old:
            if old["fingerprint"] != digest:
                raise ApplicationError(409, "提交标识已用于其他分析")
            return {"id": old["id"], "state": old["state"]}
        if request.conversation_id and not conn.execute(
            "SELECT 1 FROM conversations WHERE id=? AND user_id=?", (request.conversation_id, user["id"])
        ).fetchone():
            raise ApplicationError(404, "会话不存在")
        job_id = storage.new_id()
        metadata["job_site"] = analysis_site(conn, user["id"])
        encoded = json.dumps(metadata, ensure_ascii=False)
        conn.execute("INSERT INTO report_jobs(id,user_id,request_key,fingerprint,metadata,image,created_at,organization) "
                     "VALUES(?,?,?,?,?,?,?,?)", (job_id, user["id"], key, digest, encoded, request.image_bytes, storage.now(), metadata["job_site"]))
    return {"id": job_id, "state": "queued"}


def set_progress(job_id: str, stage: str, detail: str = "") -> None:
    """记录任务当前阶段，供前端显示进度。

    报告生成需要数分钟，且核查可能中途判定不可交付。这里只暴露「进行到哪一步」，
    不推送正文片段：流式输出正文后若最终核查不通过，用户已经读到的内容会被撤回，
    反而更难处理。阶段进度既能缓解等待焦虑，也不会给出错误的完成暗示。
    """
    try:
        with storage.connect() as conn:
            conn.execute("UPDATE report_jobs SET progress=? WHERE id=?",
                         (f"{stage}|{detail}" if detail else stage, job_id))
    except Exception:  # noqa: BLE001 - 进度上报失败不应影响主流程
        pass


def status(user_id: str, job_id: str) -> dict:
    with storage.connect() as conn:
        row = conn.execute(
            "SELECT id,state,error,progress FROM report_jobs WHERE user_id=? AND id=?",
            (user_id, job_id)).fetchone()
        if row is None:
            raise ApplicationError(404, "任务不存在")
        result = dict(row)
        if row["state"] == "completed":
            report = storage.read_report(conn, user_id, job_id)
            if report is None:
                raise ApplicationError(404, "报告不存在")
            findings = report["visual_findings"]
            result["content"] = {**report, "report_id": job_id, "cup_to_disc_ratio": report["cup_to_disc"],
                                 "visual_findings_text": format_visual_findings(findings, report["verification"].get("missing_evidence_diseases"))}
        return result


def run_one() -> bool:
    lock = FileLock(str(storage.DB_PATH) + ".worker.lock")
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return False
    try:
        with storage.connect() as conn:
            row = conn.execute("SELECT * FROM report_jobs WHERE state IN ('queued','running') ORDER BY created_at,id LIMIT 1").fetchone()
            if row is None:
                return False
            conn.execute("UPDATE report_jobs SET state='running',started_at=COALESCE(started_at,?) WHERE id=?", (storage.now(), row["id"]))
        error = ""
        try:
            # A crash after the archive transaction can leave a completed report awaiting its receipt.
            if not storage.get_report(row["user_id"], row["id"]):
                metadata = json.loads(row["metadata"])
                with storage.connect() as conn:
                    if analysis_site(conn, row["user_id"]) != metadata.pop("job_site", None):
                        raise ApplicationError(409, "任务所属机构已变更，请重新提交")
                if metadata["captured_at"]:
                    metadata["captured_at"] = datetime.fromisoformat(metadata["captured_at"])
                metadata["diseases"] = tuple(metadata["diseases"])
                request = ReportSubmission(image_bytes=row["image"], **metadata)
                asyncio.run(service._generate_and_store(storage.get_user(row["user_id"]), request,
                                                       append_to_chat=True, report_id=row["id"]))
        except ApplicationError as exc:
            error = exc.detail
        except Exception:
            logging.getLogger(__name__).exception("Report job failed: %s", row["id"])
            error = "报告生成失败，请联系管理员核查任务"
        with storage.connect() as conn:
            conn.execute("UPDATE report_jobs SET state=?,error=?,image=NULL,metadata='{}',finished_at=? WHERE id=?",
                         ("failed" if error else "completed", error, storage.now(), row["id"]))
        return True
    finally:
        lock.release()


async def consume(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            if await asyncio.to_thread(run_one):
                continue
        except Exception:
            logging.getLogger(__name__).exception("Unable to process report queue")
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except TimeoutError:
            pass
