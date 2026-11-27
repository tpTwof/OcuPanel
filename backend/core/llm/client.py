from __future__ import annotations
import os
import sys
import threading

from core import config
from core.llm.gateway import (
    LLMUnavailable,
    build_chat_model,
    describe_llm_error,
    normalize_text,
    resolve_base_url,
    resolve_model,
    thinking_control,
    to_messages,
)

# 迁移前这些名字就在 client 里定义，外部有按 client 导入的用法；
# 统一从 gateway 再导出，避免调用方跟着搬家。
DEFAULT_MODEL = config.DEFAULT_MODEL

__all__ = [
    "DEFAULT_MODEL", "LLMClient", "LLMUnavailable", "build_chat_model",
    "describe_llm_error", "normalize_text", "resolve_base_url", "resolve_model",
    "thinking_control", "to_messages",
]


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """Initialize model parameters

        base_url: 用户自己配置的接口地址。为 None 时回落到环境变量里的全局配置，
        这样老的单用户模式（直接用 .env 里的 key）仍然跑得通。
        """
        # 用 os.getenv 而不是 config 常量：main.py 先 import 再 load_dotenv()，
        # 常量会停在 dotenv 之前的值，构造时现读才不会漏掉 .env 里的 key。
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or None
        self.model = resolve_model(model)
        self.base_url = base_url if base_url is not None else resolve_base_url()
        self.system_prompt = {"role": "system", "content": "You are a helpful assistant."}
        self.chat_history = []
        self.messages = [self.system_prompt]
        # 同一用户的综合报告与后续追问可能并发，历史列表的读改写要串行化
        self._state_lock = threading.Lock()

    def chat_with_history(
        self,
        history: list[dict],
        user_message: str,
        *,
        system: str | None = None,
    ) -> str:
        """根据调用方提供的消息和可选系统指令发起无状态请求。"""
        messages = [{"role": "system", "content": system}] if system else []
        for item in history:
            role = item.get("role")
            if role in ("user", "assistant") and item.get("content"):
                messages.append({"role": role, "content": item["content"]})
        messages.append({"role": "user", "content": user_message})
        # 失败时 _invoke 已把 SDK 异常翻成带排查提示的 LLMUnavailable，
        # 这里不再二次包装，保住原始异常链给调用方记录。
        return self._invoke(
            messages, temperature=0.7, max_tokens=config.CHAT_MAX_OUTPUT_TOKENS,
        )

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """单轮补全：失败抛 `LLMUnavailable`，绝不返回"看起来正常"的空串。

        与 `chat_with_gpt` 的区别只在错误语义：这个给报告链路用，调用方需要把
        模型故障渲染成"可操作的提示"，而不是把整条任务打成"联系管理员"。
        """
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        return self._invoke(
            messages, temperature=0.7 if temperature is None else temperature,
            max_tokens=max_tokens,
        )

    def _build_client(self):
        """每次调用新建 LangChain ChatOpenAI，避免共享连接状态。

        用户的 key 与端点可能在会话中途被改，按调用重建最省心。测试通过替换
        这个方法观察 bind/invoke 的参数。
        """
        return build_chat_model(
            api_key=self.api_key, model=self.model, base_url=self.base_url,
        )

    def _invoke(self, messages: list[dict], *, temperature: float,
                max_tokens: int | None = None) -> str:
        """统一的模型调用：dict 消息 → LangChain 消息 → 纯文本。

        这是全链路唯一的模型出口。温度、输出上限与思考开关都在这里 bind，
        调用方不必各自记住这些参数。
        """
        options: dict = {"temperature": temperature}
        if max_tokens is not None:
            options["max_tokens"] = max_tokens
        extra = thinking_control(self.base_url)
        if extra:
            options["extra_body"] = extra
        payload = to_messages(messages)
        try:
            result = self._build_client().bind(**options).invoke(payload)
        except Exception as exc:  # noqa: BLE001 - 统一转成可读的 LLMUnavailable
            raise LLMUnavailable(
                describe_llm_error(exc, self.base_url, from_user_config=True)
            ) from exc
        return normalize_text(result)

    def chat_with_gpt(
        self,
        user_message: str,
        conversation: bool = False,
        reset: bool = True,
        system: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Talk to GPT with optional context reset

        system / temperature: 供校验智能体使用。校验与重写需要独立的系统提示词
        （"你是校对员"而不是"你是医学助手"）和接近 0 的温度，否则同一个角色
        既写又判，等于自证清白。

        历史语义保留：reset=False 时把本轮问答追加进 self.messages。模型故障时
        返回以 `Error:` 开头的字符串（问答链路据此降级），报告链路请改用
        `complete()` 让异常传出去。
        """
        try:
            sys_prompt = self.system_prompt if not system else {"role": "system", "content": system}
            if reset:
                messages = [sys_prompt, {"role": "user", "content": user_message}]
            else:
                with self._state_lock:
                    self.messages.append({"role": "user", "content": user_message})
                    messages = list(self.messages)

            reply = self._invoke(
                messages, temperature=0.7 if temperature is None else temperature,
            )

            if not reset:
                with self._state_lock:
                    self.messages.append({"role": "assistant", "content": reply})

            if (conversation):
                with self._state_lock:
                    self.chat_history.append({"role": "user", "content": user_message})
                    self.chat_history.append({"role": "assistant", "content": reply})

            return reply
        except Exception as e:
            # 保留异常链，否则 UI 只能看到 "Connection error." 这类无信息量的外壳
            detail = describe_llm_error(e, self.base_url, from_user_config=True)
            print(f"[LLM ERROR] {detail}", file=sys.stderr)
            return f"Error: {detail}"

    def reset_conversation(self) -> None:
        """清空对话上下文。

        原来只清 chat_history（PDF 用的那份），self.messages 仍留着上一轮的
        问答，重置后模型其实还能"记得"之前的内容，属于隐性 bug，一并清掉。
        """
        with self._state_lock:
            self.chat_history.clear()
            self.messages = [self.system_prompt]
