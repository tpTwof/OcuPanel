"""应用组装：中间件、路由注册、生命周期与前端托管。

这里是唯一的「线束」层：只负责把各业务模块拼起来，不含任何业务逻辑。
业务实现分别位于 core（配置/路径/错误）、common（公共依赖）与 modules（业务功能）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from common import deps as auth
from core import config, paths
from core.exceptions import ApplicationError
from modules.user.router import router as account_router
from modules.conversation.router import router as conversation_router
from modules.chat.router import router as chat_router
from modules.report.router import router as report_router
from modules.report.utils.jobs import purge_stale_job_dirs
from modules.screening.router import screening_router
from core import storage

load_dotenv()
config.apply_hf_endpoint()

logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def setup_cache(app: FastAPI) -> AsyncIterator[None]:
    storage.init_db()
    auth.init_sessions()
    removed_sessions = storage.purge_expired_sessions()
    logger.info(
        "SQLite ready at %s（清理过期登录态 %d 条）", storage.DB_PATH, removed_sessions
    )

    # 进程被强杀时，请求级临时目录（job_* / report_* / content_*）会留在 output/ 里。
    # 启动时清一次，避免长期运行后越积越多。
    removed = purge_stale_job_dirs()
    if removed:
        logger.info("Removed %d stale temp dirs from %s", removed, paths.OUTPUT_DIR)

    # 门控阈值自检：RAG_LANG_GATE 是标定值，换 embedding 模型或语料大改后必须重标。
    # 放到线程里跑（要加载向量模型，几秒到几十秒），不挡启动；失败只告警不影响服务。
    # 副作用是好的：它会把向量模型与 Chroma 索引预热好，首个真实请求不用再等加载。
    async def run_gate_selfcheck() -> None:
        try:
            from modules.knowledge import retrieval

            report = await asyncio.to_thread(retrieval.selfcheck_gate)
            if report.get("skipped"):
                logger.info("RAG gate selfcheck skipped: %s", report.get("skipped"))
            elif report.get("ok") and not report.get("thin"):
                logger.info("RAG gate selfcheck ok: %s", report)
            else:
                logger.warning("RAG gate selfcheck needs attention: %s", report)
        except Exception as exc:  # noqa: BLE001 - 自检不能挡住服务
            logger.warning("RAG gate selfcheck crashed: %s", exc)

    # 持有引用，否则任务可能被 GC 提前回收；关停时一并取消
    gate_task = asyncio.create_task(run_gate_selfcheck()) if config.RAG_ENABLED else None

    from modules.report import assets
    from modules.report.queue import consume

    retention_days = int(os.getenv("ORIGINAL_RETENTION_DAYS") or 0)
    if retention_days < 0:
        raise ValueError("ORIGINAL_RETENTION_DAYS must be nonnegative")
    stop = asyncio.Event()

    async def enforce_retention() -> None:
        while not stop.is_set():
            try:
                removed_count = await asyncio.to_thread(
                    assets.expire_originals, storage.DB_PATH,
                    assets.ORIGINAL_STORE_DIR, retention_days, True,
                )
                logger.info("Expired %d archived originals", removed_count)
            except Exception:
                logger.exception("Original retention cleanup failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=86400)
            except TimeoutError:
                pass

    worker = asyncio.create_task(consume(stop))
    retention = asyncio.create_task(enforce_retention()) if retention_days else None
    try:
        yield
    finally:
        stop.set()
        await worker
        if retention:
            await retention

    if gate_task and not gate_task.done():
        gate_task.cancel()
    logger.info("Shutting down.")


app = FastAPI(
    title="OcuPanel API",
    description="Multi-disease fundus image analysis and ophthalmic report generation",
    version="1.0.0",
    lifespan=setup_cache,
)


@app.exception_handler(ApplicationError)
async def handle_application_error(request: Request, exc: ApplicationError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# CORS：单服务模式下页面与 API 同源，不触发跨域；
# 只有 Vite 开发服务器（默认 5500）需要放行。
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(account_router, prefix="/api")
app.include_router(report_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(conversation_router, prefix="/api")
app.include_router(screening_router, prefix="/api")


# ---------------------------------------------------------------------------
# 前端托管：存在构建产物时，FastAPI 直接提供页面，实现单服务一键启动
# ---------------------------------------------------------------------------
FRONTEND_DIST = config.FRONTEND_DIST
FRONTEND_INDEX = FRONTEND_DIST / "index.html"


def _mount_frontend() -> bool:
    if not FRONTEND_INDEX.is_file():
        logger.info(
            "Frontend build not found at %s - running in API-only mode. "
            "Run `npm run build` in frontend/ to enable single-server mode.",
            FRONTEND_DIST,
        )
        return False

    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(FRONTEND_INDEX))

    logger.info("Serving frontend build from %s", FRONTEND_DIST)
    return True


_mount_frontend()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.RELOAD,
    )