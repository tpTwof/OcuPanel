"""项目内关键路径。基于本文件位置解析，避免依赖进程的工作目录。"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent          # .../MedChat/backend
PROJECT_ROOT = BASE_DIR.parent                      # .../MedChat

OUTPUT_DIR = BASE_DIR / "output"                    # 报告 PDF、分割图、临时文件
IMG_STORE_DIR = BASE_DIR / "img_store"              # 供前端取回的分割结果图

for _d in (OUTPUT_DIR, IMG_STORE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
