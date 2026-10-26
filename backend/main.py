import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import auth
import config
import paths
import storage
from api import account_router, chat_router, report_router
from report_generator import purge_stale_job_dirs

load_dotenv()
config.apply_hf_endpoint()

logger = logging.getLogger("uvicorn")

DEFAULT_MODEL = config.DEFAULT_MODEL


@asynccontextmanager
async def setup_cache(app: FastAPI):
    # 持久化层：建表（幂等）+ 清理过期登录态。
    # 会话、对话历史、LLM 配置都在 SQLite 里，不再依赖进程内字典——
    # 这样重启不丢会话，也能安全地起多个 worker。
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
    # 另有一个副作用是好的：它会把向量模型预热好，首个真实请求不用再等加载。
    async def run_gate_selfcheck():
        try:
            import retrieval

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

    # 旧版的"按 uuid 缓存 generator 并定期过期"已经删掉：
    # generator 现在是每请求按用户配置新建的轻量对象（只存配置，不存对话状态），
    # 对话历史在 SQLite 里。缓存它没有收益，反而会和数据库里的状态打架。

    yield

    if gate_task and not gate_task.done():
        gate_task.cancel()
    logger.info("Shutting down.")


app = FastAPI(
    title="OcuPanel API",
    description="Multi-agent glaucoma diagnostic report generation from fundus images",
    version="1.0.0",
    lifespan=setup_cache,
)

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
    async def serve_spa(full_path: str):
        # API 路由已在上面注册，未命中的 /api/* 一律返回 JSON 404，
        # 避免被 SPA 的 index.html 吞掉。
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
