import os
import sys
import threading
import openai
from utils import config
from llm.prompts import LANGUAGE_INSTRUCTION, CHAT_SYSTEM_PROMPT
DEFAULT_MODEL = config.DEFAULT_MODEL
def resolve_model(model=None):
    """模型名：显式入参 > 环境变量 OPENAI_MODEL > 默认值。统一由 config 读取。"""
    return model or config.OPENAI_MODEL or DEFAULT_MODEL

def resolve_base_url():
    """OpenAI 兼容端点。None 表示官方 OpenAI API。"""
    return config.OPENAI_BASE_URL or None

def thinking_control(base_url=None):
    """DeepSeek 的 thinking 模式默认开启，会让单次生成慢 2-3 倍。

    LLM_DISABLE_THINKING=1 时通过 extra_body 关掉；其他厂商不支持该字段，
    因此只对 DeepSeek 端点生效，其余情况返回 None 不影响正常调用。
    base_url: 用户自定义端点也要照此判断，不能只看全局配置。
    """
    if not config.LLM_DISABLE_THINKING:
        return None
    base = base_url if base_url is not None else resolve_base_url()
    if "deepseek" not in (base or "").lower():
        return None
    return {"thinking": {"type": "disabled"}}

def describe_llm_error(exc, base_url=None, from_user_config=False):
    """把 SDK 抛出的嵌套异常压成一行可读信息，并附上排查提示。

    from_user_config=True 表示这次调用用的是某个用户在「个人设置」里填的 key，
    提示语必须指向那里的配置，而不是 backend/.env —— 否则用户会去改错地方。
    """
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


class LLMClient:
    def __init__(self, api_key=None, model=None, base_url=None):
        """Initialize model parameters

        base_url: 用户自己配置的接口地址。为 None 时回落到环境变量里的全局配置，
        这样老的单用户模式（直接用 .env 里的 key）仍然跑得通。
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or None
        self.model = resolve_model(model)
        self.base_url = base_url if base_url is not None else resolve_base_url()
        self.system_prompt = {
            "role": "system",
            "content": (
                "You are a medical AI assistant answering questions after reviewing diagnostic reports."
                + LANGUAGE_INSTRUCTION
            )
        }
        self.chat_history = []
        self.messages = [self.system_prompt]
        # 同一用户的综合报告与后续追问可能并发，历史列表的读改写要串行化
        self._state_lock = threading.Lock()

    def chat_with_history(self, history: list[dict], user_message: str) -> str:
        """无状态对话：外部把历史传进来，本方法不读写 self.messages。

        引入数据库后，对话历史的事实来源是 SQLite 而不是进程内存，
        这样重启不丢、多台机器也能接上。这里只负责拼消息和发起调用。

        系统消息用 CHAT_SYSTEM_PROMPT（眼科辅助诊疗定位），不用 self.system_prompt
        ——后者是给六专科子报告与 Director 综合用的，措辞与目标都不同。
        """
        messages = [CHAT_SYSTEM_PROMPT]
        for item in history:
            role = item.get("role")
            if role in ("user", "assistant") and item.get("content"):
                messages.append({"role": role, "content": item["content"]})
        messages.append({"role": "user", "content": user_message})

        client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=config.LLM_TIMEOUT,
            max_retries=config.LLM_MAX_RETRIES,
        )
        kwargs = {"model": self.model, "messages": messages, "temperature": 0.7}
        extra = thinking_control(self.base_url)
        if extra:
            kwargs["extra_body"] = extra
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001 - 让上层统一转成可读错误
            raise RuntimeError(
                describe_llm_error(exc, self.base_url, from_user_config=True)
            ) from exc

    def chat_with_gpt(self, user_message, conversation=False, reset=True,
                      system=None, temperature=None):
        """Talk to GPT with optional context reset

        system / temperature: 供校验智能体使用。校验与重写需要独立的系统提示词
        （"你是校对员"而不是"你是医学助手"）和接近 0 的温度，否则同一个角色
        既写又判，等于自证清白。
        """
        try:
            sys_prompt = self.system_prompt if not system else {"role": "system", "content": system}
            if reset:
                messages = [sys_prompt, {"role": "user", "content": user_message}]
            else:
                with self._state_lock:
                    self.messages.append({"role": "user", "content": user_message})
                    messages = list(self.messages)

            client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=config.LLM_TIMEOUT,
                max_retries=config.LLM_MAX_RETRIES,
            )
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7 if temperature is None else temperature,
            }
            extra = thinking_control(self.base_url)
            if extra:
                kwargs["extra_body"] = extra
            response = client.chat.completions.create(**kwargs)
            reply = response.choices[0].message.content

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

    def reset_conversation(self):
        """清空对话上下文。

        原来只清 chat_history（PDF 用的那份），self.messages 仍留着上一轮的
        问答，重置后模型其实还能"记得"之前的内容，属于隐性 bug，一并清掉。
        """
        with self._state_lock:
            self.chat_history.clear()
            self.messages = [self.system_prompt]
