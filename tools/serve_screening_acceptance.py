"""Serve the real application on loopback with disposable synthetic acceptance data.

No models, API keys or production database are used. Build frontend before running.
"""
import argparse
from datetime import datetime, timezone
from io import BytesIO
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["RAG_ENABLED"] = "0"
os.environ["GRAPH_RAG_ENABLED"] = "0"

from PIL import Image
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRoute
import uvicorn
import main
from report import assets, service as reports
from report.models import ReportResult, ReportSubmission
from report.utils import jobs
from screening import service as screening
from screening.models import CreateCase, Review
from utils import auth, storage


def seed_case(owner: dict, name: str) -> dict:
    task = {"disease": "glaucoma", "visible_region": "视盘区域", "next_step": "人工复核并安排去向"}
    captured = {"image_ref": "synthetic:fixture", "captured_at": "2026-11-25T08:00:00+00:00", "device": "合成设备", "field": "合成视野"}
    examination = {"synthetic": True, "institution": "合成验收机构", "encounter_id": name, "patient_group": name,
                   "age": 55, "followup_owner": "验收员", "eyes": [
                       {"laterality": "right", "captures": [captured], "tasks": [{**task, "status": "gradable", "finding": "suspect"}]},
                       {"laterality": "left", "captures": [captured, {**captured, "image_ref": "synthetic:retake"}],
                        "tasks": [{**task, "status": "ungradable", "reason": "补拍后仍不可判读"}]}]}
    return screening.create_case(owner, CreateCase(idempotency_key=f"fixture-create-{name}", examination=examination))


def serve(port: int) -> None:
    temp_root = ROOT / "tmp"
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="screening-acceptance-", dir=temp_root) as directory:
        folder = Path(directory)
        storage.DB_PATH = folder / "fixture.db"
        assets.ORIGINAL_STORE_DIR = folder / "originals"
        reports.IMG_STORE_DIR = folder / "overlays"
        reports.IMG_STORE_DIR.mkdir()
        jobs.OUTPUT_DIR = folder / "output"
        jobs.OUTPUT_DIR.mkdir()
        storage.init_db(); auth.init_sessions()
        owner = storage.create_user("acceptance", "synthetic-local-only", "验收员")
        token = auth.issue_token(owner["id"])
        seed_case(owner, "AUDIT-1")
        second = seed_case(owner, "AUDIT-2")
        screening.apply_command(owner, second["id"], Review(action="review", expected_revision=1,
            idempotency_key="fixture-review-case2", original_images_checked=True, case_checked=True, comment="合成复核"))
        storage.create_user("another-account", "synthetic-local-only", "另一账号")
        conversation = storage.create_conversation(owner["id"], "合成验收 · 眼科分析", "ophthalmic")
        image = Image.new("RGB", (64, 64), "#446644")
        image.paste("#99bb88", (8, 8, 40, 40))
        encoded = BytesIO(); image.save(encoded, format="PNG")
        for eye in ("right", "left"):
            findings = {'glaucoma': {'probability': .82, 'measurements': {'area_equivalent_cdr': .61}, 'model_sources': {'classifier': 'synthetic-fixture@v1'}},
                        'diabetic_retinopathy': {'prompt_similarity_margin': -4.2, 'model_sources': {'image_text_model': 'synthetic-FLAIR'}}}
            request = ReportSubmission(encoded.getvalue(), f"合成{eye}-fundus.png", f"{eye} 合成病例记录", conversation['id'], tuple(findings),
                                       eye, datetime(2026, 11, 25, 8, tzinfo=timezone.utc), "合成相机 A", True)
            reports._archive_result(owner['id'], request, ReportResult('合成验收报告，不代表真实诊断。', {'status': 'pass'}, .61, '', [], findings), eye == 'right')
        storage.save_report(owner['id'], None, '', '旧合成报告：原图未归档', {'status': 'disabled'}, [], False,
                            cup_to_disc=.5, visual_findings={'glaucoma': {'measurements': {'area_equivalent_cdr': .5}}})
        storage.save_report(owner['id'], None, '', '合成拒答记录', {'status': 'rejected'}, [], True)

        def home():
            html = main.FRONTEND_INDEX.read_text(encoding='utf-8')
            return HTMLResponse(html.replace('<head>', '<head><script>localStorage.setItem("ocupanel.token", ' + repr(token) + ')</script>'))

        main.app.router.routes.insert(0, APIRoute('/', endpoint=home))

        @main.app.middleware('http')
        async def simulate_one_read_failure(request, call_next):
            flag = folder / 'fail-next-case-read'
            if request.method == 'GET' and request.url.path.startswith('/api/screening/cases/') and request.url.path.count('/') == 4 and flag.exists():
                flag.unlink()
                return JSONResponse(status_code=503, content={'detail': '合成验收：模拟同步读取失败'})
            return await call_next(request)

        print(f"Synthetic acceptance fixture: {folder}", flush=True)
        uvicorn.run(main.app, host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8127)
    serve(parser.parse_args().port)
