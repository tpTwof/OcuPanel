"""Prepare immutable report imports and atomically confirm a pending case version."""
import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from report import assets
from screening import repository, service
from screening.models import ConfirmImport, Examination, ImportPreview, TaskAssessment
from user.models import User
from utils import storage
from utils.errors import ApplicationError

SUPPORTED = {"glaucoma", "diabetic_retinopathy", "age_related_macular_degeneration"}


def normalize_time(value: str | None) -> str | None:
    try:
        parsed = datetime.fromisoformat(value) if value else None
        return parsed.astimezone(timezone.utc).isoformat() if parsed and parsed.utcoffset() is not None else None
    except ValueError:
        return None


def digest(value: Any) -> str:
    return hashlib.sha256(repository.encode(value).encode()).hexdigest()


def validate_refs(examination: Examination, sources: list[dict]) -> None:
    for eye in examination.eyes:
        allowed = {source["report_id"] for source in sources if source["laterality"] == eye.laterality}
        if not set(eye.analysis_refs).issubset(allowed):
            raise ApplicationError(422, "分析引用必须通过服务端导入，不能手工伪造")


def require_reviewable(case: dict) -> None:
    for source in case.get("analysis_sources", []):
        if source["original"]["status"] != "available" or assets.inspect_original(source["report"]["source_metadata"])["status"] != "available":
            raise ApplicationError(409, "导入来源缺少完整原图，不能记录已核对原图；研究信息仍可查看")
        if not source["captured_at"] or not source["device"]:
            raise ApplicationError(409, "导入来源缺少采集时间或设备，请补齐后重新导入")


def _report(conn, user_id: str, report_id: str) -> dict:
    report = storage.read_report(conn, user_id, report_id)
    if report is None:
        raise ApplicationError(404, "报告不存在")
    return report


def preview(user: User, request: ImportPreview) -> dict:
    from screening import access
    with storage.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM screening_import_previews WHERE expires_at < ?", (storage.now(),))
        if request.case_id:
            access.scope(conn, user["id"], request.case_id, "import_analysis")
            current = repository.read(conn, user["id"], request.case_id)
            if current["revision"] != request.expected_revision:
                raise ApplicationError(409, "病例已更新，请刷新后重新预览")
            for field in ("institution", "encounter_id", "patient_group"):
                if current["examination"][field] != getattr(request.examination, field):
                    raise ApplicationError(409, "就诊或分组信息已修改，请先保存病例修订再导入")
        else:
            access.creation_scope(conn, user["id"], request.examination.institution)
            current = {"id": storage.new_id(), "revision": 0, "referrals": [], "events": [],
                       "provenance": {"software": service.SOFTWARE_VERSION, "model": "research-import",
                                      "rules": "manual-rehearsal-v1", "guidelines": [],
                                      "validation": "synthetic_only", "clinical_release": False}}
        sources = copy.deepcopy(current.get("analysis_sources", []))
        validate_refs(request.examination, sources)
        candidate = copy.deepcopy(current)
        examination = request.examination.model_dump(mode="json")
        warnings, notes, checks, added = [], [], [], []
        for binding in request.bindings:
            report = _report(conn, user["id"], binding.report_id)
            metadata = report["source_metadata"]
            if metadata.get("data_kind") in {"real", "clinical", "patient"}:
                raise ApplicationError(422, "真实病例来源尚未获准接入合成演练")
            original = assets.inspect_original(metadata)
            checks.append({"report_id": binding.report_id, "hash": digest(report), "original": original})
            if metadata.get("laterality") and metadata["laterality"] != binding.laterality:
                raise ApplicationError(422, "所选眼别与归档眼别不一致，不能自动改绑")
            previous = next((source for source in sources if source["report_id"] == binding.report_id), None)
            captured_at = binding.captured_at.isoformat() if binding.captured_at else metadata.get("captured_at")
            device = binding.device.strip() or metadata.get("device", "")
            captured_at = normalize_time(captured_at)
            if previous:
                if previous["laterality"] != binding.laterality:
                    raise ApplicationError(409, "此分析已绑定另一只眼，请核对来源")
                captured_at = captured_at or previous["captured_at"]
                device = device or previous["device"]
                if captured_at == previous["captured_at"] and device == previous["device"] and original == previous["original"]:
                    if request.note_policy == "replace" and metadata.get("clinical_note", "").strip(): notes.append(metadata["clinical_note"].strip())
                    warnings.append("此分析已导入，不会重复追加来源")
                    continue
                sources.remove(previous)
            if len(sources) >= 20:
                raise ApplicationError(422, "单病例最多保留 20 份分析来源")
            if original["status"] != "available": warnings.append("原图缺失或校验失败：仅导入研究信息，不能完成原图复核")
            if not captured_at or not device: warnings.append("采集时间或设备缺失：保留待补齐状态")
            if report["rejected"] or report["verification"].get("status") not in ("pass", "rewritten"):
                warnings.append("正文未通过引用校验：保留原状态，不作为已签发计划")
            if metadata.get("data_kind") != "synthetic_declared": warnings.append("来源未声明为合成数据，确认时须由操作者明确声明合成演练用途")
            diseases = [name for name in metadata.get("selected_diseases", report["visual_findings"].keys()) if name in SUPPORTED]
            if not diseases and report["cup_to_disc"] is not None: diseases = ["glaucoma"]
            source = {"report_id": binding.report_id, "report_hash": digest(report), "report": report,
                      "laterality": binding.laterality, "captured_at": captured_at, "device": device,
                      "original": original, "diseases": diseases, "source_kind": "model_research"}
            sources.append(source); added.append(binding.report_id)
            if metadata.get("clinical_note", "").strip() and (not previous or request.note_policy == "replace"):
                notes.append(metadata["clinical_note"].strip())
            eye = next(eye for eye in examination["eyes"] if eye["laterality"] == binding.laterality)
            refs = eye.setdefault("analysis_refs", [])
            if binding.report_id not in refs: refs.append(binding.report_id)
            has_original_capture = original["status"] == "available" and captured_at and device
            if has_original_capture:
                capture = {"image_ref": f"synthetic:report:{binding.report_id}:{original['original_id']}",
                           "captured_at": captured_at, "device": device, "field": "导入原图（视野待人工核对）"}
                previous_capture = next((item for item in eye["captures"] if item["image_ref"] == capture["image_ref"]), None)
                if previous_capture:
                    previous_capture.update(capture)
                else:
                    if len(eye["captures"]) >= 20: raise ApplicationError(422, "该眼采集记录已达上限")
                    eye["captures"].append(capture)
            existing = {task["disease"] for task in eye["tasks"]}
            for disease in diseases:
                if disease not in existing:
                    eye["tasks"].append(TaskAssessment(disease=disease, status="not_assessed", visible_region="待人工核对",
                                                       next_step="核对原图并完成人工评估").model_dump())
            # Existing human assessments remain exactly as entered.
            if not request.case_id:
                for task in eye["tasks"]:
                    if task["disease"] in diseases and task["status"] == "not_captured": task["status"] = "not_assessed"
        if notes and request.note_policy != "keep":
            imported_note = "\n\n".join(dict.fromkeys(notes))
            examination["note"] = "\n\n".join(filter(None, [examination["note"], imported_note])) if request.note_policy == "append" else imported_note
        try:
            examination = Examination.model_validate(examination).model_dump(mode="json")
        except ValueError as exc:
            raise ApplicationError(422, "合并后的病例字段超出限制，请保留原备注或减少导入内容") from exc
        unchanged = request.case_id and not added and examination == current["examination"]
        candidate.update(examination=examination, analysis_sources=sources)
        if not unchanged:
            candidate.update(schema_version=2, stage="draft", review=None, signature=None)
            candidate["provenance"]["software"] = service.SOFTWARE_VERSION
        payload = {"case_id": request.case_id, "expected_revision": request.expected_revision,
                   "new_organization": None if request.case_id else access.creation_scope(conn, user["id"], request.examination.institution),
                   "candidate": candidate, "checks": checks, "added": added, "no_changes": bool(unchanged)}
        preview_id = storage.new_id()
        expires = storage.now() + 900
        conn.execute("INSERT INTO screening_import_previews VALUES (?, ?, ?, ?)",
                     (preview_id, user["id"], repository.encode(payload), expires))
        return {"preview_id": preview_id, "expires_at": expires, "candidate": candidate,
                "warnings": list(dict.fromkeys(warnings)), "added_report_ids": added, "no_changes": bool(unchanged)}


def confirm(user: User, preview_id: str, request: ConfirmImport) -> dict:
    from screening import access
    fingerprint = digest({"preview_id": preview_id, "request": request.model_dump()})
    with storage.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        replay = repository.replay(conn, user["id"], request.idempotency_key, fingerprint)
        if replay is not None:
            access.scope(conn, user["id"], replay["id"], "import_analysis")
            return replay
        row = conn.execute("SELECT payload, expires_at FROM screening_import_previews WHERE id=? AND user_id=?", (preview_id, user["id"])).fetchone()
        if row is None: raise ApplicationError(404, "导入预览不存在")
        if row["expires_at"] < storage.now(): raise ApplicationError(409, "导入预览已过期，请重新预览")
        payload = json.loads(row["payload"])
        if "confirmed_result" in payload:
            access.scope(conn, user["id"], payload["confirmed_result"]["id"], "import_analysis")
            repository.remember(conn, user["id"], request.idempotency_key, fingerprint, payload["confirmed_result"])
            return payload["confirmed_result"]
        if payload["case_id"]:
            access.scope(conn, user["id"], payload["case_id"], "import_analysis")
            current = repository.read(conn, user["id"], payload["case_id"])
            if current["revision"] != payload["expected_revision"]: raise ApplicationError(409, "病例已更新，请重新预览导入")
        for check in payload["checks"]:
            report = _report(conn, user["id"], check["report_id"])
            if digest(report) != check["hash"] or assets.inspect_original(report["source_metadata"]) != check["original"]:
                raise ApplicationError(409, "分析来源或原图状态已变化，请重新预览")
        candidate = payload["candidate"]
        if not payload["case_id"] and access.creation_scope(conn, user["id"], candidate["examination"]["institution"]) != payload.get("new_organization"):
            raise ApplicationError(409, "工作区已变更，请重新预览导入")
        if payload["no_changes"]:
            repository.remember(conn, user["id"], request.idempotency_key, fingerprint, current)
            payload["confirmed_result"] = current
            conn.execute("UPDATE screening_import_previews SET payload=? WHERE id=?", (repository.encode(payload), preview_id))
            return current
        candidate["revision"] += 1
        for source in candidate["analysis_sources"]:
            if source["report_id"] in payload["added"]:
                source.update(imported_at=storage.now(), imported_by=user["id"],
                              use_declaration="operator_confirmed_synthetic_rehearsal")
        service._audit(candidate, user, "import_analysis", {"report_ids": payload["added"], "preview_id": preview_id})
        repository.save(conn, user["id"], candidate, request.idempotency_key, fingerprint)
        payload["confirmed_result"] = candidate
        conn.execute("UPDATE screening_import_previews SET payload=? WHERE id=?", (repository.encode(payload), preview_id))
        return candidate
