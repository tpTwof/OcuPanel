"""集中管理后端配置。所有项都可通过环境变量覆盖，代码里不出现魔法值。"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
# 显式指向 backend/.env：不依赖进程工作目录，从任何目录启动都能读到配置
load_dotenv(BASE_DIR / ".env")

# 服务监听
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
# 热重载。开发时设 RELOAD=1；默认关闭 —— 改文件名的过程中 reloader 会在
# 中间状态重启 worker（import 找不到旧模块名），直接把请求打成 500。
RELOAD = (os.getenv("RELOAD", "0") == "1")

# LLM（详见 .env.example）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or None
DEFAULT_MODEL = "gpt-4.1"
# 可选：OpenAI 兼容端点（DeepSeek / 通义 / vLLM 等）。留空走官方 OpenAI。
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/") or None
OPENAI_MODEL = (os.getenv("OPENAI_MODEL") or "").strip() or DEFAULT_MODEL
# 报告语言：zh（默认，简体中文）/ en。同时影响 LLM 输出与 PDF 文案。
REPORT_LANGUAGE = (os.getenv("REPORT_LANGUAGE") or "zh").strip().lower()
# 中文字体文件路径。留空则自动在系统字体目录里找（Windows 一般命中 simhei.ttf）。
REPORT_FONT_PATH = os.getenv("REPORT_FONT_PATH") or None

# 单次 LLM 调用超时（秒）与重试次数。不设上限时一个卡住的请求能拖死整条链路。
# 报告核查与改写提示词约 6k 字符，deepseek-v4.1-flash 实测单次 150–227 秒，
# 120 会让核查稳定超时并扣留正文。取 300 留出余量；较快的模型不受影响。
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "300"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "1"))
# 关闭 DeepSeek 的 thinking 模式以显著提速（1=关闭，默认关闭 thinking）
LLM_DISABLE_THINKING = (os.getenv("LLM_DISABLE_THINKING", "1") != "0")

# 聊天上下文：数据库保留全量记录，只有发给模型的消息受这些预算限制。
CHAT_HISTORY_MAX_MESSAGES = int(os.getenv("CHAT_HISTORY_MAX_MESSAGES", "20"))
CHAT_CONTEXT_MAX_CHARS = int(os.getenv("CHAT_CONTEXT_MAX_CHARS", "20000"))
CHAT_REPORT_MAX_CHARS = int(os.getenv("CHAT_REPORT_MAX_CHARS", "6000"))
CHAT_MAX_OUTPUT_TOKENS = int(os.getenv("CHAT_MAX_OUTPUT_TOKENS", "2048"))
for _setting in (
    "CHAT_HISTORY_MAX_MESSAGES", "CHAT_CONTEXT_MAX_CHARS",
    "CHAT_REPORT_MAX_CHARS", "CHAT_MAX_OUTPUT_TOKENS",
):
    if globals()[_setting] <= 0:
        raise ValueError(f"{_setting} must be positive")

# 知识检索（证据包）。RAG_ENABLED=0 可退回纯模型生成，便于 A/B 对比。
RAG_ENABLED = (os.getenv("RAG_ENABLED", "1") != "0")
# 证据条数。报告要同时覆盖诊断评估、结构与功能判读、治疗目标和随访四个方面，
# 取 4 条时后两类条款会被长病例文本挤出候选池（实测「目标眼压」排在第 14 名），
# 撰稿只能写无依据的处置句，校验随即判为不受支持，最终退化为病例摘要。
# 12 是实测能覆盖四类的下限，继续增大会推高提示词长度与校验成本。
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "12"))
# 相对阈值：只保留得分不低于最佳命中该比例的片段（0–1）
RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.35"))
# 检索模式：
#   bm25   纯关键词（零依赖，中文查询查不到英文块）
#   vector 纯多语言向量（中文查询能命中英文块）
#   hybrid 两路召回 + RRF 排名融合（默认）
RAG_MODE = (os.getenv("RAG_MODE") or "hybrid").strip().lower()
# 多语言向量模型。用 transformers 直接加载（AutoModel + mean pooling），
# 不引入 sentence-transformers。换模型只改这里。
RAG_VECTOR_MODEL = (os.getenv("RAG_VECTOR_MODEL") or "intfloat/multilingual-e5-small").strip()
RAG_VECTOR_REVISION = os.getenv("RAG_VECTOR_REVISION", "main")
# Chroma 持久化目录。留空表示不使用向量库，退回每次启动在内存里编码。
# Chroma 库中每条记录同时保存向量、原文与出处元数据，语料更新时按 id 增量同步。
RAG_VECTOR_STORE_PATH = os.getenv(
    "RAG_VECTOR_STORE_PATH",
    str(Path(__file__).resolve().parents[1] / "knowledge" / ".cache" / "chroma"),
)
# 向量相似度的绝对阈值（cosine）。e5 系列的分数整体偏高，0.78 相当于"确实相关"。
RAG_VECTOR_MIN_SCORE = float(os.getenv("RAG_VECTOR_MIN_SCORE", "0.78"))
# RRF 融合常数：score = Σ 1/(k + rank)，k 越大越平缓
RAG_RRF_K = int(os.getenv("RAG_RRF_K", "60"))
# 语言配额：为每种出现的语言保留至少 k/语言数 个位置。
# 不加这条，跨语言内容就算被向量拉到 0.85，也会被同语言的 0.93 挤出 top-k ——
# 实测中文查询的 top-4 全是中文块，英文块一个都进不来。1=开启，0=纯按分数。
RAG_LANG_QUOTA = (os.getenv("RAG_LANG_QUOTA", "1") != "0")
# 配额门控：只有最佳命中的余弦 ≥ 该值时才启用语言配额。
# 实测数据（e5-small）：相关查询 best 0.918–0.939，无关查询 best 0.852–0.867，
# 但跨语言相关块只有 0.82–0.84（比同语言无关块还低），逐项阈值必然误杀。
# 用「查询整体是否强相关」来门控，才能既召回跨语言内容、又不往无关查询里硬塞。
# 0.89 = 上述两组数的中性点：距无关上界 0.867 有 0.023、距相关下界 0.918 有 0.028。
# 原来取 0.90，相关侧只剩 0.008 余量，查询稍弱就掉回"英文块永不入选"。
# 启动时 retrieval.selfcheck_gate() 会拿探针复核这个值，失配或余量过小都会告警。
RAG_LANG_GATE = float(os.getenv("RAG_LANG_GATE", "0.89"))
# 同一份文档最多入选几条。防止同一主题的相邻段落把 top-k 占满，
# 也顺带给跨语言内容腾位置。0=不限。
RAG_MAX_PER_SOURCE = int(os.getenv("RAG_MAX_PER_SOURCE", "2"))

# 报告生成流程：
#   v2     病例事实整理 → 检索规划 → 按问题检索（含一次补检）→ 统一提示词撰稿 → 核查
#   legacy 影像分析后逐病种固定主题检索，保留用于新旧对比与回退
REPORT_PIPELINE = (os.getenv("REPORT_PIPELINE") or "v2").strip().lower()
if REPORT_PIPELINE not in ("v2", "legacy"):
    raise ValueError("REPORT_PIPELINE must be 'v2' or 'legacy'")

# 检索规划与执行的预算。数值是可评估后调整的上限，不是推荐配置。
RETRIEVAL_PLAN_MAX_QUESTIONS = int(os.getenv("RETRIEVAL_PLAN_MAX_QUESTIONS", "6"))
RETRIEVAL_MAX_QUERIES = int(os.getenv("RETRIEVAL_MAX_QUERIES", "10"))
RETRIEVAL_MAX_SECONDS = float(os.getenv("RETRIEVAL_MAX_SECONDS", "20"))
RETRIEVAL_MAX_EVIDENCE = int(os.getenv("RETRIEVAL_MAX_EVIDENCE", "12"))
RETRIEVAL_SUPPLEMENTAL_ROUNDS = int(os.getenv("RETRIEVAL_SUPPLEMENTAL_ROUNDS", "1"))
for _setting in (
    "RETRIEVAL_PLAN_MAX_QUESTIONS", "RETRIEVAL_MAX_QUERIES", "RETRIEVAL_MAX_SECONDS",
    "RETRIEVAL_MAX_EVIDENCE",
):
    if globals()[_setting] <= 0:
        raise ValueError(f"{_setting} must be positive")
if RETRIEVAL_SUPPLEMENTAL_ROUNDS < 0:
    raise ValueError("RETRIEVAL_SUPPLEMENTAL_ROUNDS must not be negative")

# 引用校验智能体（第 7 个 Agent）。VERIFY_ENABLED=0 可整体关掉，
# 用于对比「有校验 / 无校验」的报告差异，或在校验模型不稳定时快速退回。
VERIFY_ENABLED = (os.getenv("VERIFY_ENABLED", "1") != "0")
# 打回重写的轮数上限。每轮 = 核查 + 重写，最坏每轮 2 次 LLM 调用。
VERIFY_MAX_ROUNDS = int(os.getenv("VERIFY_MAX_ROUNDS", "2"))
# 修订轮数用尽后，把「资料未覆盖」的断言就地标注后交付，而不是整份扣留。
# 数值或表述与资料冲突这类可修正的问题仍必须改对，改不对才拒答。
# 标注文字为「〔未获资料支持〕」，页面与 PDF 另行列出，不冒充已核实结论。
VERIFY_SOFT_DELIVERY = (os.getenv("VERIFY_SOFT_DELIVERY", "1") != "0")
# 正文被删到低于此字数（或原稿的 40%，取较大者）判定为「不成文」，
# 触发整篇重新生成；重生成后仍不合格就拒答，不输出报告。
VERIFY_MIN_CHARS = int(os.getenv("VERIFY_MIN_CHARS", "300"))

# HuggingFace 模型源，国内可设为 https://hf-mirror.com
HF_ENDPOINT = os.getenv("HF_ENDPOINT") or None

# 跨域白名单。默认放行 Vite 开发服务器（5500）与同源访问；
# 生产/单服务模式下页面与 API 同源，不需要 CORS。
_cors_raw = os.getenv("CORS_ORIGINS", "http://127.0.0.1:5500,http://localhost:5500")
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

# 前端构建产物目录。存在则 FastAPI 直接托管页面（单服务模式）；
# 不存在时自动降级为纯 API 模式。
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST") or (Path(__file__).resolve().parents[1].parent / "frontend" / "dist"))

# ---------------------------------------------------------------------------
# 升级功能开关（套壳阶段默认值指向现有行为，启用时只改变量值）
# ---------------------------------------------------------------------------

# 迁移检查：不再提供旧视觉管线开关，拒绝旧非默认取值以避免静默换模型。
if os.getenv("ANALYSIS_PIPELINE", "legacy").strip().lower() not in ("", "legacy"):
    raise ValueError(
        "ANALYSIS_PIPELINE was removed. "
        "Remove the obsolete setting before starting the application."
    )

# GraphRAG 知识引擎。0=关闭（默认，退化为纯 BM25/vector），1=开启图检索路。
GRAPH_RAG_ENABLED = (os.getenv("GRAPH_RAG_ENABLED", "0") != "0")

# 图存储后端：networkx（内存图）。
GRAPH_STORE = (os.getenv("GRAPH_STORE") or "networkx").strip().lower()

# 多病种专科并行撰稿。
MULTI_AGENT_MODE = (os.getenv("MULTI_AGENT_MODE") or "parallel").strip().lower()


def apply_hf_endpoint() -> None:
    """把 HF_ENDPOINT 写回环境变量，供 huggingface_hub 读取。"""
    if HF_ENDPOINT:
        os.environ["HF_ENDPOINT"] = HF_ENDPOINT
    # transformers/hub 在部分版本下仍会尝试 Xet 传输，直连官方源时容易卡住
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
