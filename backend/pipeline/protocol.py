"""AnalysisPipeline 协议 —— 可替换的视觉分析后端。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .types import FundusAnalysis


@runtime_checkable
class AnalysisPipeline(Protocol):
    """所有视觉分析后端必须实现的接口。

    analyze() 接收眼底图路径和工作目录，返回统一的 FundusAnalysis。
    调用方不关心具体用了什么模型，只消费返回值。
    """

    def analyze(self, image_path: str, job_dir: Path) -> FundusAnalysis: ...
