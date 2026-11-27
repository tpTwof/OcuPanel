"""模型调用网关：LangChain 消息链、配置解析与错误归类。

迁移边界（见 `docs/adr/0001-agent-runtime-langchain.md`）：

- **模型调用与消息构造**走这里：`build_chat_model` 产出未绑定参数的 ChatOpenAI，
  `to_messages` / `normalize_text` 负责消息与响应形态的转换。全链路只有一条调用
  路径（`LLMClient._invoke`），不为了"更 LangChain"再造第二条；测试注入点因此
  固定为 `LLMClient._build_client`；
- **引用核查的控制流**走 LangGraph（`modules/agent/graphs/verify.py`）；
- **grounding / 标注 / 定位**这些确定性工具不进链。它们要能单独跑单测、要在
  失败时给出可复现的判断依据，包进 Runnable 只会让审计变难。

错误语义：模型不可用一律抛 `LLMUnavailable`（消息已转成可读文案）。调用方要么
把它翻成 HTTP 502 交给用户看，要么显式降级——不允许变成"报告成功"。
"""

from __future__ import annotations

from typing import Any, Sequence

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core import config


class LLMUnavailable(RuntimeError):
    """模型端点不可用：鉴权失败、余额不足、超时、连接异常等。

    继承 RuntimeError 是为了兼容既有 `except RuntimeError` 的调用点；
    `str(exc)` 已经是 `describe_llm_error` 生成的可读文案。
    """


def resolve_model(model: str | None = None) -> str:
    """模型名：显式入参 > 环境变量 OPENAI_MODEL > 默认值。统一由 config 读取。"""
    return model or config.OPENAI_MODEL or config.DEFAULT_MODEL


def resolve_base_url() -> str | None:
    """OpenAI 兼容端点。None 表示官方 OpenAI API。"""
    return config.OPENAI_BASE_URL or None


def thinking_control(base_url: str | None = None) -> dict[str, dict[str, str]] | None:
    """关闭推理（thinking）模式，单次调用可快 2-3 倍。

    实测同一道核查题：开启思考 1.6s / 128 输出 token（其中 96 个是 reasoning），
    关闭后 0.7s / 34 token，判断结论完全一致。报告生成要做 8-10 次调用，
    累计下来就是几分钟的差距。

    以前只对 URL 里带 deepseek 的端点下发该参数，而项目实际走的是
    maas.qianwenaiapi.com 这类 OpenAI 兼容网关，判断永远不成立，
    LLM_DISABLE_THINKING 形同虚设。现在默认对所有兼容端点下发；
    若某厂商不认这个字段并报错，把 LLM_DISABLE_THINKING 设为 0 即可。
    """
    if not config.LLM_DISABLE_THINKING:
        return None
    base = base_url if base_url is not None else resolve_base_url()
    if not base:
        return None
    return {"thinking": {"type": "disabled"}}


def describe_llm_error(
    exc: BaseException,
    base_url: str | None = None,
    from_user_config: bool = False,
) -> str:
    """把 SDK 抛出的嵌套异常压成一行可读信息，并附上排查提示。

    from_user_config=True 表示这次调用用的是某个用户在「个人设置」里填的 key，
    提示语必须指向那里的配置，而不是 backend/.env —— 否则用户会去改错地方。
    """
    if isinstance(exc, LLMUnavailable):
        # 已经翻译过，再包一层会变成「LLMUnavailable: RuntimeError: ...」的套娃。
        return str(exc)
    chain = []
    cur = exc
    while cur is not None and len(chain) < 4:
        text = str(cur).strip()
        name = type(cur).__name__
        if text:
            chain.append(f"{name}: {text}")
        else:
            chain.append(name)
        cur = cur.__cause__ or cur.__context__
        if cur is chain:
            break

    detail = " | ".join(chain) if chain else type(exc).__name__
    joined = detail.lower()

    # 提示语里的「去哪儿改配置」随调用来源变化
    where = "「个人设置 → LLM API 配置」中填写的" if from_user_config else "backend/.env 中的"
    endpoint = base_url or resolve_base_url()

    hints = []
    if "certificate_verify_failed" in joined or "self-signed certificate" in joined:
        hints.append(
            "TLS 证书校验失败：本机代理/杀软可能在做 HTTPS 中间人。"
            "可先关闭代理直连，或设置 SSL_CERT_FILE 指向代理根证书。"
        )
    if "connection error" in joined or "connect" in joined:
        hints.append(
            f"无法建立连接：确认接口地址 {endpoint} 可访问；"
            "若 shell 里残留 HTTPS_PROXY/HTTP_PROXY，请先清空（Remove-Item Env:HTTPS_PROXY）。"
        )
    if "401" in joined or "authentication" in joined or "invalid_api_key" in joined:
        hints.append(f"鉴权失败：检查{where} API Key 是否正确、是否已过期。")
    if "404" in joined or ("model" in joined and "not exist" in joined):
        hints.append(
            f"模型名或接口地址可能不对：当前模型在 {endpoint} 上不存在，"
            "核对「接口地址 + 模型」是否为同一家服务商。"
        )
    if "402" in joined or "insufficient balance" in joined:
        hints.append("账户余额不足，请到服务商控制台充值。")

    if hints:
        detail += "  → " + " ".join(hints)
    return detail


def normalize_text(message: Any) -> str:
    """把模型返回统一成纯文本。

    部分兼容网关把内容拆成 content 分片列表返回；这里保持一致的空值/分片处理，
    不把 list 直接抛给下游的 JSON 解析。
    """
    content = getattr(message, "content", message)
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return (content or "").strip()


def to_messages(messages: Sequence[dict]) -> list[Any]:
    """把 `{"role", "content"}` 字典映射成 LangChain 消息对象。

    只保留 system / user / assistant 三种角色，空内容丢弃——与迁移前的行为一致。
    """
    mapping = {"system": SystemMessage, "user": HumanMessage, "assistant": AIMessage}
    return [
        mapping[item["role"]](content=item["content"])
        for item in messages
        if item.get("role") in mapping and item.get("content")
    ]


def build_chat_model(
    *,
    api_key: str | None,
    model: str | None = None,
    base_url: str | None = None,
) -> Any:
    """构造未绑定参数的 ChatOpenAI。

    每次调用新建客户端：用户的 key 与端点可能在会话中途被改，按调用重建最省心。
    温度、输出上限与思考开关由调用方 `bind(...)`，这样测试能直接观察到参数。
    """
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=resolve_model(model),
        timeout=config.LLM_TIMEOUT,
        max_retries=config.LLM_MAX_RETRIES,
    )
