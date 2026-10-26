"""最小可用的证据检索（知识检索增强的第一步）。

刻意不引入向量库与图数据库：先用「中文 2-gram + IDF 加权」把整条链路跑通
——语料 → 检索 → 证据包（带出处）→ 注入提示词 → 接口返回 → 前端展示。

后续把 `Retriever.search()` 换成向量检索或图谱多跳即可，**接口与数据结构不变**，
上层的 report_generator 与前端都不用改。

语料目录：backend/knowledge/corpus/*.md（示例语料，正式使用需替换为权威指南原文）
"""

from __future__ import annotations

import math
import re
import sys
import threading
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

import config

CORPUS_DIR = Path(__file__).resolve().parent / "knowledge" / "corpus"

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+\-.]*|\d+(?:\.\d+)?")
_H2 = re.compile(r"^##\s+(.*)$", re.M)


@dataclass
class Chunk:
    id: str
    source: str
    title: str
    section: str
    text: str
    lang: str = ""


def detect_lang(text: str) -> str:
    """粗判语种：中文占比够高就算 zh，其余算 en。

    只为展示与阈值分组用，不参与打分——真正跨语言的能力来自向量。
    """
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return "zh" if cjk >= max(4, len(text) * 0.05) else "en"


def _tokenize(text: str) -> list[str]:
    """中文按 2-gram，英文/数字按词。够用且零依赖。"""
    tokens: list[str] = []
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    tokens.extend(w.lower() for w in _ASCII_WORD.findall(text))
    return tokens


def load_chunks(corpus_dir: Path = CORPUS_DIR) -> list[Chunk]:
    """按 `## 小节` → 段落 两级切分。

    只按小节切时，一个块里塞满 3–4 段，长块在 BM25 里被长度归一化惩罚，
    真正对口的短段落会被埋掉。按段落切更细，召回更准，出处也更具体。
    """
    chunks: list[Chunk] = []
    for path in sorted(corpus_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.*)$", raw, re.M)
        title = title_match.group(1).strip() if title_match else path.stem

        positions = [(m.start(), m.group(1).strip()) for m in _H2.finditer(raw)]
        for idx, (start, section) in enumerate(positions):
            end = positions[idx + 1][0] if idx + 1 < len(positions) else len(raw)
            body = raw[start:end].split("\n", 1)[-1].strip()
            if not body:
                continue

            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
            merged: list[str] = []
            for para in paragraphs:
                # 过短的段落（标题行、单句提示）并入下一段，避免噪声块
                if merged and len(merged[-1]) < 60:
                    merged[-1] = f"{merged[-1]}\n{para}"
                else:
                    merged.append(para)

            for p_idx, para in enumerate(merged):
                chunks.append(
                    Chunk(
                        id=f"{path.stem}#{idx + 1}-{p_idx + 1}",
                        source=path.name,
                        title=title,
                        section=section,
                        text=para,
                        lang=detect_lang(f"{title} {section} {para}"),
                    )
                )
    return chunks


class VectorIndex:
    """多语言向量索引：中文查询也能命中英文片段。

    刻意不引入 sentence-transformers —— 项目已装 transformers + torch，
    自己算 mean pooling 就够，少一个依赖、少一层版本冲突。
    e5 系列要求 query:/passage: 前缀，缺了会让相似度整体偏移几个点。

    首次检索才加载权重（约 470MB），之后矩阵常驻；查询侧只编码一次，CPU 上几十毫秒。
    """

    QUERY_PREFIX = "query: "
    PASSAGE_PREFIX = "passage: "

    def __init__(self, chunks: list[Chunk], model_name: str | None = None):
        self.chunks = chunks
        self.model_name = model_name or config.RAG_VECTOR_MODEL
        self._tokenizer = None
        self._model = None
        self._matrix: np.ndarray | None = None
        self._lock = threading.Lock()

    def _load(self):
        from transformers import AutoModel, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModel.from_pretrained(self.model_name)
        self._model.eval()

    def _encode(self, texts: list[str]) -> np.ndarray:
        import torch

        batch = self._tokenizer(
            texts, padding=True, truncation=True, max_length=512, return_tensors="pt"
        )
        with torch.no_grad():
            hidden = self._model(**batch).last_hidden_state
        mask = batch["attention_mask"].unsqueeze(-1).float()
        pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return pooled.cpu().numpy()

    def ensure(self):
        if self._matrix is not None:
            return
        with self._lock:
            if self._matrix is not None:
                return
            self._load()
            texts = [
                f"{self.PASSAGE_PREFIX}{c.title} §{c.section}\n{c.text}" for c in self.chunks
            ]
            self._matrix = self._encode(texts)

    def search(self, query: str, k: int, min_score: float = 0.0) -> list[dict]:
        self.ensure()
        vector = self._encode([f"{self.QUERY_PREFIX}{query}"])[0]
        sims = self._matrix @ vector
        results: list[dict] = []
        for idx in sims.argsort()[::-1]:
            score = float(sims[idx])
            if score < min_score:
                break
            item = asdict(self.chunks[idx])
            item["score"] = round(score, 3)
            item["vector"] = round(score, 3)
            results.append(item)
            if len(results) >= k:
                break
        return results


class Retriever:
    """BM25 / 多语言向量 / 两路 RRF 融合，三种模式共用同一个接口。

    - bm25   零依赖，中文查询查不到英文块（词面无交集）
    - vector 中文查询能命中英文块（语义空间对齐）
    - hybrid 两路各取宽召回，再用 RRF 合并（默认）

    为什么融合用 RRF 而不是分数加权：中英 BM25 的分数不可比（英文 token 密度
    只有中文的 1/3，长度归一后系统性偏高），向量分又是另一种量纲。排名融合只
    比名次，跨语种、跨检索器都不用调权重。
    """

    K1 = 1.5
    B = 0.75
    RELATIVE_FLOOR = 0.35

    def __init__(self, chunks: list[Chunk], mode: str | None = None):
        self.chunks = chunks
        self._tokens = [_tokenize(f"{c.title} {c.section} {c.text}") for c in chunks]

        self._tfs: list[dict[str, int]] = []
        for tokens in self._tokens:
            tf: dict[str, int] = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1
            self._tfs.append(tf)

        self._lens = [len(tokens) for tokens in self._tokens]
        self._avgdl = (sum(self._lens) / len(self._lens)) if self._lens else 0.0

        df: dict[str, int] = {}
        for tokens in self._tokens:
            for token in set(tokens):
                df[token] = df.get(token, 0) + 1

        total = max(len(chunks), 1)
        # 平滑 IDF：出现在越少块里的词越有区分度
        self._idf = {t: math.log((total + 1) / (n + 1)) + 1.0 for t, n in df.items()}
        self._default_idf = math.log(total + 1) + 1.0

        self.mode = (mode or config.RAG_MODE).lower()
        self._vector_index: VectorIndex | None = None
        self._vector_failed = False
        self._vector_lock = threading.Lock()

    @classmethod
    def from_corpus(cls, corpus_dir: Path = CORPUS_DIR, mode: str | None = None) -> "Retriever":
        return cls(load_chunks(corpus_dir), mode=mode)

    @property
    def size(self) -> int:
        return len(self.chunks)

    def _get_vector(self) -> VectorIndex | None:
        if self._vector_failed:
            return None
        if self._vector_index is None:
            with self._vector_lock:
                if self._vector_index is None and not self._vector_failed:
                    self._vector_index = VectorIndex(self.chunks)
        return self._vector_index

    def _search_vector(self, query: str, k: int, boost: str = "") -> list[dict]:
        index = self._get_vector()
        if index is None:
            return []
        # 角色关键词拼进查询，保证六个角色拿到的证据仍有差异
        q = f"{query} {boost}".strip() if boost else query
        try:
            return index.search(q, k=k, min_score=config.RAG_VECTOR_MIN_SCORE)
        except Exception as exc:  # noqa: BLE001 - 向量不可用时退回 BM25，不让整条链路挂掉
            print(f"[RAG] 向量检索失败，本次退回 BM25：{exc}", file=__import__("sys").stderr)
            self._vector_failed = True
            return []

    def _search_bm25(self, query: str, k: int = 4, min_score: float = 0.35,
                     boost: str = "", boost_weight: float = 1.8) -> list[dict]:
        """返回按相关度排序的证据条目（dict，可直接进 JSON 响应）。

        boost: 该角色最关心的关键词（如药师的「禁忌 相互作用」）。命中这些词的
        片段得分乘以 boost_weight —— 否则病历里的通用词会把所有角色都拉向同一段。
        """
        query_tokens = set(_tokenize(query))
        boost_tokens = set(_tokenize(boost)) - query_tokens if boost else set()
        if not query_tokens or not self.chunks:
            return []

        scored: list[tuple[float, int]] = []
        for idx, tf in enumerate(self._tfs):
            total = 0.0
            norm = 1 - self.B + self.B * self._lens[idx] / (self._avgdl or 1.0)
            for token in query_tokens | boost_tokens:
                freq = tf.get(token, 0)
                if not freq:
                    continue
                idf = self._idf.get(token, self._default_idf)
                if token in boost_tokens:
                    idf *= boost_weight
                total += idf * freq * (self.K1 + 1) / (freq + self.K1 * norm)
            if total > 0:
                scored.append((total, idx))

        if not scored:
            return []

        scored.sort(reverse=True)
        best = scored[0][0]
        floor = max(min_score, self.RELATIVE_FLOOR)

        results: list[dict] = []
        for raw, idx in scored[: max(k * 3, k)]:
            relative = raw / best if best else 0.0
            if relative < floor:
                continue
            item = asdict(self.chunks[idx])
            item["score"] = round(relative, 3)
            item["bm25"] = round(raw, 2)
            results.append(item)
            if len(results) >= k:
                break
        return results

    def _rrf(self, ranked: list[tuple[str, list[dict]]], k: int) -> list[dict]:
        """Reciprocal Rank Fusion：只比名次，不比分数量纲。"""
        merged: dict[str, dict] = {}
        for source, items in ranked:
            for rank, item in enumerate(items, 1):
                entry = merged.get(item["id"])
                if entry is None:
                    entry = {**item, "_rrf": 0.0, "sources": []}
                    merged[item["id"]] = entry
                else:
                    # 两路都命中时要保留各自的原始分数，否则前端只能看到先出现那一路的
                    for key in ("bm25", "vector"):
                        if key in item and key not in entry:
                            entry[key] = item[key]
                entry["_rrf"] += 1.0 / (config.RAG_RRF_K + rank)
                if source not in entry["sources"]:
                    entry["sources"].append(source)
        if not merged:
            return []

        ordered = sorted(merged.values(), key=lambda x: x["_rrf"], reverse=True)[:k]
        best = ordered[0]["_rrf"] or 1.0
        results: list[dict] = []
        for entry in ordered:
            item = dict(entry)
            item["rrf"] = round(entry["_rrf"], 5)
            item["score"] = round(entry["_rrf"] / best, 3)
            item["sources"] = ",".join(sorted(entry["sources"]))
            results.append(item)
        return results

    def _balance_by_lang(self, items: list[dict], k: int, gate: bool = True) -> list[dict]:
        """按语言配额挑前 k 条，保证"两种语言同时进结果"。

        实测问题：中文查询下，中文块相似度 0.93、同主题英文块 0.85，
        多语言向量确实把两者拉近了，但 top-4 会被中文块占满，英文块一个都排不上。
        只做语义对齐不够，还得给每种语言留位置。

        门控 gate：只有该查询在语料里存在强相关命中（best cosine ≥ RAG_LANG_GATE）
        时才分位。否则无关查询会被硬塞进跨语言内容——实测"门诊预约流程"这类查询
        明明没有相关内容，best 只有 0.867，却因为配额把英文块塞到了第 3、4 位。

        规则：
        - 语料只有一种语言时直接返回（不浪费配额）；
        - 每种语言至少保留 k/语言数 个位置，剩下的按原始分数补齐；
        - 进入本函数前已过相似度阈值，所以不会把极不相关的块硬塞进来。
        """
        if not config.RAG_LANG_QUOTA or not gate or len(items) <= k:
            # 不分位也要守住每源上限（之前这里直接 return，导致同源 3 条漏网）
            return self._diversify(items, k, config.RAG_MAX_PER_SOURCE)

        groups: dict[str, list[dict]] = {}
        for item in items:
            groups.setdefault(item.get("lang") or "zh", []).append(item)
        if len(groups) < 2:
            return self._diversify(items, k, config.RAG_MAX_PER_SOURCE)

        per_lang = max(1, k // len(groups))
        per_source = config.RAG_MAX_PER_SOURCE
        picked: list[dict] = []
        seen: set[str] = set()
        counts: dict[str, int] = {}

        def take(item: dict) -> bool:
            src = item.get("source") or item.get("id")
            if per_source > 0 and counts.get(src, 0) >= per_source:
                return False
            counts[src] = counts.get(src, 0) + 1
            picked.append(item)
            seen.add(item["id"])
            return True

        # 第一轮：每种语言按配额各取 n 个
        for queue in groups.values():
            taken = 0
            for item in queue:
                if taken >= per_lang:
                    break
                if item["id"] in seen:
                    continue
                if take(item):
                    taken += 1

        # 第二轮：按分数补位，仍守每源上限
        for item in items:
            if len(picked) >= k:
                break
            if item["id"] not in seen:
                take(item)

        # 第三轮：语料太小、上限太紧导致凑不满 k 时，放宽上限补齐
        for item in items:
            if len(picked) >= k:
                break
            if item["id"] not in seen:
                picked.append(item)
                seen.add(item["id"])

        picked.sort(key=lambda x: x["score"], reverse=True)
        return picked[:k]

    def _gate_ok(self, vector_hits: list[dict]) -> bool:
        """查询级门控：语料里到底有没有强相关内容。

        不能逐项卡阈值——跨语言相关块（0.82–0.84）的分数比同语言无关块（0.867）
        还低，卡高会误杀跨语言内容，卡低会让无关查询也拿到配额。
        看最佳命中就干净了：相关查询 ≥0.918，无关查询 ≤0.867。
        """
        if not vector_hits:
            return False
        best = float(vector_hits[0].get("vector") or vector_hits[0].get("score") or 0.0)
        return best >= config.RAG_LANG_GATE

    def similarity(self, text_a: str, text_b: str) -> float:
        """两段文本的语义相似度（0–1）。

        给引用校验用作「假覆盖」判据：中文引文与英文证据没有共享 bigram，
        词面判据恒为 0，只能靠语义。bm25 模式下不加载向量模型，直接返回 0，
        此时守卫退化为词面判据（同语言语料仍然有效）。
        """
        if self.mode == "bm25":
            return 0.0
        index = self._get_vector()
        if index is None:
            return 0.0
        try:
            index.ensure()
            va, vb = index._encode([f"query: {text_a}", f"passage: {text_b}"])
            return float(va @ vb)
        except Exception as exc:  # noqa: BLE001 - 相似度算不出来不该影响校验主流程
            print(f"[RAG] 相似度计算失败：{exc}", file=__import__("sys").stderr)
            return 0.0

    def _diversify(self, items: list[dict], k: int, per_source: int | None = None) -> list[dict]:
        """限制同一份文档最多入选 per_source 条。

        病因：中文语料的随访主题有 6 个段落，分数全在 0.91–0.94，把 top-k 占满，
        英文块即使语义相关（0.85）也排到 12 名开外。同一文档的相邻段落本来就
        高度重复，限制每源条数既提高证据多样性，也给跨语言内容腾出位置。
        """
        if per_source is None:
            per_source = config.RAG_MAX_PER_SOURCE
        if per_source <= 0:
            return items
        kept: list[dict] = []
        dropped: list[dict] = []
        counts: dict[str, int] = {}
        for item in items:
            src = item.get("source") or item.get("id")
            if counts.get(src, 0) < per_source:
                counts[src] = counts.get(src, 0) + 1
                kept.append(item)
            else:
                dropped.append(item)
        if len(kept) < k:
            kept.extend(dropped[: k - len(kept)])
            kept.sort(key=lambda x: x["score"], reverse=True)
        # 必须截断：diversify 是过滤器，不截断会把 8 条塞给只要 4 条的调用方
        return kept[:k]

    def search(self, query: str, k: int = 4, min_score: float = 0.35,
               boost: str = "", boost_weight: float = 1.8) -> list[dict]:
        """统一入口。模式由 RAG_MODE 控制，调用方无需关心。"""
        # 向量那路要宽召回：跨语言内容天然排在同语言内容之后，取窄了根本进不了候选池
        wide = max(k * 6, 20)

        if self.mode == "vector":
            vector_hits = self._search_vector(query, wide, boost)
            gate = self._gate_ok(vector_hits)
            pool = self._diversify(vector_hits, wide)
            return self._balance_by_lang(pool, k, gate=gate)

        if self.mode == "hybrid":
            bm25_hits = self._search_bm25(
                query, k=max(k * 3, 12), min_score=min_score, boost=boost, boost_weight=boost_weight
            )
            vector_hits = self._search_vector(query, wide, boost)
            gate = self._gate_ok(vector_hits)
            if not vector_hits:
                return bm25_hits[:k]
            if not bm25_hits:
                pool = self._diversify(vector_hits, wide)
                return self._balance_by_lang(pool, k, gate=gate)
            merged = self._rrf([("bm25", bm25_hits), ("vector", vector_hits)], wide)
            merged = self._diversify(merged, wide)
            return self._balance_by_lang(merged, k, gate=gate)

        return self._search_bm25(
            query, k=k, min_score=min_score, boost=boost, boost_weight=boost_weight
        )


def format_evidence_block(evidence: list[dict], numbers: dict[str, int] | None = None) -> str:
    """把证据条目拼成提示词里的一段，要求模型按编号引用。

    numbers: 全局编号表（id → 序号）。多个角色各自检索时，用同一套编号，
    这样 Director 汇总时 [3] 指的永远是同一条资料。
    """
    if not evidence:
        return ""
    lines = ["\n\n【参考资料】以下片段来自本地知识库，是本病例唯一被允许引用的外部依据："]
    for i, item in enumerate(evidence, 1):
        number = numbers.get(item["id"], i) if numbers else i
        lines.append(
            f"[{number}] 《{item['title']}》§{item['section']}（来源：{item['source']}）\n{item['text']}"
        )
    lines.append(
        "【引用要求】1) 凡结论依赖上述资料的，句末必须标注编号，例如「建议每 3–4 个月复查眼压 [2]」；"
        "2) 资料未覆盖的内容不要编造，直接写「资料未涵盖」；3) 不要在报告正文里复述资料原文。"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 门控自检
# ---------------------------------------------------------------------------
# 跨领域固定探针：挂号、停车费。与医学语料天然无关，用来测"门控会不会放错"。
_IRRELEVANT_PROBE = "患者姓名 联系方式 门诊预约流程 挂号窗口 停车收费标准"


def selfcheck_gate(retriever: "Retriever | None" = None, margin: float = 0.05) -> dict:
    """检查 RAG_LANG_GATE 是否仍适配当前模型与语料。

    这个阈值是标定值：换 embedding 模型、或语料大幅改动后，分数分布会漂移，
    门控会变成"常关"（跨语言配额永不触发，英文块进不来）或"常开"
    （无关查询也被塞跨语言内容）。所以启动时自己拿两条探针试一次，失配就告警。

    related 探针从语料自身取（第一个片段标题+小节），换语料也能自适应；
    irrelevant 用跨领域固定串。

    除了判断把 gate 夹在中间，还要看余量：夹住了但只差 0.01，等于没夹住——
    真实查询的分数会波动，margin 太薄时门控会随机开关。所以余量不足也告警。

    默认复用全局检索器单例（report_generator.get_retriever），免得为了自检
    再建一个 VectorIndex，白白多加载一份约 470MB 的模型权重。
    """
    result: dict = {"ok": True, "mode": config.RAG_MODE}

    if config.RAG_MODE == "bm25":
        result["skipped"] = "bm25 模式不使用语言配额"
        return result

    if retriever is None:
        # 延迟导入：report_generator 反向依赖 retrieval，模块级导入会成环
        from report_generator import get_retriever

        retriever = get_retriever()
    index = retriever._get_vector()
    if index is None:
        result.update(ok=False, skipped="向量索引不可用")
        print("[RAG] 门控自检跳过：向量索引不可用", file=sys.stderr)
        return result
    try:
        index.ensure()
    except Exception as exc:  # noqa: BLE001 - 自检失败不该挡住启动
        result.update(ok=False, skipped=f"向量模型加载失败：{exc}")
        print(f"[RAG] 门控自检跳过：向量模型加载失败 {exc}", file=sys.stderr)
        return result

    gate = config.RAG_LANG_GATE
    first = retriever.chunks[0] if retriever.chunks else None
    related_probe = f"{first.title} {first.section}" if first else "青光眼 随访 视野"

    def best_cosine(text: str) -> float:
        vec = index._encode([f"query: {text}"])[0]
        return float((index._matrix @ vec).max())

    related_best = best_cosine(related_probe)
    irrelevant_best = best_cosine(_IRRELEVANT_PROBE)
    # 两条探针里离 gate 最近的那一侧，就是门控最脆弱的方向
    headroom = round(min(gate - irrelevant_best, related_best - gate), 3)
    # 余量够不够不能用一个固定绝对值衡量：探针本身的间隔就只有 0.03 上下时，
    # 要求 0.05 余量等于永远判不过。所以取「绝对下限」与「间隔 1/4」中更宽松的那个
    # ——即 gate 只要落在两簇中间那一半区间里就算合格。
    spread = max(related_best - irrelevant_best, 0.0)
    tol = round(min(margin, spread / 4), 3)
    result.update(
        related_best=round(related_best, 3),
        irrelevant_best=round(irrelevant_best, 3),
        gate=gate,
        headroom=headroom,
        tol=tol,
        langs=sorted({c.lang for c in retriever.chunks if c.lang}),
    )

    if related_best <= gate:
        suggested = (
            round((related_best + irrelevant_best) / 2, 3)
            if related_best > irrelevant_best
            else None
        )
        result.update(ok=False, suggested_gate=suggested)
        print(
            f"[RAG] 门控失配：相关探针只有 {related_best:.3f} ≤ gate {gate}，"
            f"跨语言配额永远不会触发（英文块进不来）。"
            + (f" 建议 RAG_LANG_GATE={suggested}" if suggested else ""),
            file=sys.stderr,
        )
        return result

    if irrelevant_best >= gate:
        suggested = round((related_best + irrelevant_best) / 2, 3)
        result.update(ok=False, suggested_gate=suggested)
        print(
            f"[RAG] 门控失配：无关探针高达 {irrelevant_best:.3f} ≥ gate {gate}，"
            f"无关查询也会被塞进跨语言内容。建议 RAG_LANG_GATE={suggested}",
            file=sys.stderr,
        )
        return result

    if headroom < tol:
        result["thin"] = True
        print(
            f"[RAG] 门控余量偏小：无关 {irrelevant_best:.3f} / gate {gate} / 相关 {related_best:.3f}，"
            f"最窄一侧只有 {headroom:.3f}（这里要求 ≥{tol}）。暂时可用，"
            f"但语料或模型一变就可能翻车，建议重标：RAG_LANG_GATE≈{round((related_best + irrelevant_best) / 2, 3)}",
            file=sys.stderr,
        )
        return result

    print(
        f"[RAG] 门控自检通过：无关 {irrelevant_best:.3f} < gate {gate} < 相关 {related_best:.3f}"
        f"（余量 {headroom:.3f} ≥ {tol}）",
        file=sys.stderr,
    )
    return result
