"""Persistent local inference jobs, with one active consumer per database."""
import asyncio
from dataclasses import fields
from datetime import datetime
import hashlib
import json
import logging

from filelock import FileLock, Timeout
from report import service
from report.context import format_visual_findings
from report.models import ReportSubmission
from utils import storage
from utils.errors import ApplicationError
from screening.access import analysis_site


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


def status(user_id: str, job_id: str) -> dict:
    with storage.connect() as conn:
        row = conn.execute("SELECT id,state,error FROM report_jobs WHERE user_id=? AND id=?", (user_id, job_id)).fetchone()
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
