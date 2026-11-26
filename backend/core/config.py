"""全局配置。

所有配置项都在 `core.config_impl` 中从环境变量读取并校验，这里原样导出，
让业务代码统一写 `from core import config`，将来调整读取方式只需改一处。
"""

from core.config_impl import *  # noqa: F401,F403
from core.config_impl import (  # noqa: F401
    CHAT_CONTEXT_MAX_CHARS,
    CHAT_HISTORY_MAX_MESSAGES,
    CHAT_MAX_OUTPUT_TOKENS,
    CHAT_REPORT_MAX_CHARS,
    CORS_ORIGINS,
    DEFAULT_MODEL,
    FRONTEND_DIST,
    GRAPH_RAG_ENABLED,
    GRAPH_STORE,
    HF_ENDPOINT,
    HOST,
    LLM_DISABLE_THINKING,
    LLM_MAX_RETRIES,
    LLM_TIMEOUT,
    MULTI_AGENT_MODE,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    PORT,
    RAG_ENABLED,
    RAG_LANG_GATE,
    RAG_LANG_QUOTA,
    RAG_MAX_PER_SOURCE,
    RAG_MIN_SCORE,
    RAG_MODE,
    RAG_RRF_K,
    RAG_TOP_K,
    RAG_VECTOR_MIN_SCORE,
    RAG_VECTOR_MODEL,
    RAG_VECTOR_REVISION,
    RAG_VECTOR_STORE_PATH,
    RELOAD,
    REPORT_FONT_PATH,
    REPORT_LANGUAGE,
    VERIFY_ENABLED,
    VERIFY_MAX_ROUNDS,
    VERIFY_MIN_CHARS,
    apply_hf_endpoint,
)