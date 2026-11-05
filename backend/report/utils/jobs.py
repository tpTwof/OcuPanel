import shutil
import tempfile
from pathlib import Path
from utils.paths import OUTPUT_DIR
JOB_DIR_PREFIXES = ("job_", "report_", "content_")

def new_job_dir(prefix="job"):
    """为单次请求创建独占的临时工作目录。

    之前所有请求共用 output/temp_slo_fundus.png、output/segmented_image.png
    这类固定文件名，两个人同时上传就会互相覆盖，后到的请求可能拿到别人的
    分割图和杯盘比。改成每次请求一个目录后彻底隔离。
    """
    return Path(tempfile.mkdtemp(prefix=f"{prefix}_", dir=str(OUTPUT_DIR)))


def cleanup_job_dir(path):
    """删除本次请求的工作目录（幂等，失败不抛）。"""
    if not path:
        return
    shutil.rmtree(str(path), ignore_errors=True)


def purge_stale_job_dirs(max_age_seconds=1800):
    """清掉进程被强杀后遗留的请求级临时目录，返回删除数量。"""
    import time

    now = time.time()
    removed = 0
    try:
        entries = list(OUTPUT_DIR.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.is_dir() or not entry.name.startswith(JOB_DIR_PREFIXES):
            continue
        try:
            if now - entry.stat().st_mtime < max_age_seconds:
                continue
        except OSError:
            continue
        shutil.rmtree(str(entry), ignore_errors=True)
        removed += 1
    return removed
