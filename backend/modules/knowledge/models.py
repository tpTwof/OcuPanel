"""知识检索的数据结构。

``Chunk`` 是 Markdown/PDF 切分出的基础片段；``SourcedChunk`` 是语料 JSON 里
登记了出处的条款。两者都携带材料类型与审核状态等可选元数据，缺失时保持空串，
由 `modules.knowledge.metadata` 统一解释为未登记，不在此处赋默认值。
"""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Chunk:
    id: str
    source: str
    title: str
    section: str
    text: str
    lang: str = ""
    # 可选元数据：旧语料与切分片段可以留空。
    topic: str = ""
    material_type: str = ""
    review_status: str = ""
    content_hash: str = ""
    # 条款级病种范围（逗号分隔）；空串表示沿用来源登记。
    disease: str = ""


@dataclass
class SourcedChunk(Chunk):
    url: str = ""
    version: str = ""
    jurisdiction: str = ""
    scope: str = ""
    applicability: dict[str, str] = field(default_factory=dict)
    chinese_summary: str = ""
    context: str = ""
    supersedes: str = ""
    superseded_by: str = ""


RetrieveEvidence = Callable[..., list[dict[str, Any]]]
