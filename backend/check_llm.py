r"""LLM 连通性自检。

用法（必须用项目的 venv 解释器）：
    cd F:\GIthub\MedChat\backend
    ..\.venv\Scripts\python.exe check_llm.py

只依赖 config + openai，不加载 torch/transformers，几秒内出结果。
退出码：0 正常，1 失败。
"""
import sys


def _fail_missing(exc):
    name = exc.name or str(exc)
    print(f"[FAIL] 当前 Python 缺少依赖：{name}")
    print(f"       解释器 = {sys.executable}")
    print("       你用的不是项目的虚拟环境。请改用：")
    print(r"       ..\.venv\Scripts\python.exe check_llm.py")
    print(r"       或先激活：..\.venv\Scripts\Activate.ps1")
    return 1


try:
    import config
except ModuleNotFoundError as exc:
    sys.exit(_fail_missing(exc))


def mask(key):
    if not key:
        return "(未设置)"
    return key[:6] + "***" + key[-4:] if len(key) > 12 else key[:3] + "***"


def main():
    base_url = config.OPENAI_BASE_URL
    model = config.OPENAI_MODEL

    print("解释器   =", sys.executable)
    print("base_url =", base_url or "https://api.openai.com (官方默认)")
    print("model    =", model)
    print("api_key  =", mask(config.OPENAI_API_KEY))

    if not config.OPENAI_API_KEY:
        print("\n[FAIL] 未读到 OPENAI_API_KEY，请检查 backend/.env")
        return 1

    try:
        import time

        import openai
    except ModuleNotFoundError as exc:
        return _fail_missing(exc)

    try:
        client = openai.OpenAI(
            api_key=config.OPENAI_API_KEY,
            base_url=base_url,
            max_retries=0,
            timeout=60,
        )
        started = time.time()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
        )
        elapsed = time.time() - started

        reply = resp.choices[0].message.content
        usage = resp.usage
        print("\n[OK] 调用成功")
        print("  延迟     = %.2fs" % elapsed)
        print("  返回模型 =", resp.model)
        print("  回复     =", repr(reply))
        print("  用量     = prompt %s / completion %s / total %s"
              % (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens))

        details = getattr(usage, "completion_tokens_details", None)
        reasoning = getattr(details, "reasoning_tokens", None)
        if reasoning:
            print("  提示     = 模型处于 thinking 模式（消耗 %s 推理 token），"
                  "本项目 report_generator 的 temperature 参数在此模式下不生效" % reasoning)
        return 0

    except Exception as exc:  # noqa: BLE001 - 自检脚本需要打印全部失败原因
        print("\n[FAIL]", type(exc).__name__, str(exc)[:300])
        cause = exc.__cause__
        while cause:
            text = str(cause)
            print("  cause:", type(cause).__name__, text[:300])
            if "CERTIFICATE_VERIFY_FAILED" in text:
                print("\n  → TLS 证书校验失败。常见原因：")
                print("    1. 本机代理/杀软做了 HTTPS 中间人，Python 不信任其根证书")
                print("    2. 解决：关闭代理直连，或把代理根证书加入信任链")
                print("       $env:SSL_CERT_FILE='C:\\path\\to\\ca-bundle.crt'")
            cause = cause.__cause__
        if "Connection error" in str(exc) or "ConnectError" in str(exc.__cause__ or ""):
            print("\n  → 排查方向：")
            print("    1. 清掉 shell 里残留的代理变量：")
            print("       Remove-Item Env:HTTPS_PROXY,Env:HTTP_PROXY,Env:https_proxy,Env:http_proxy -ErrorAction SilentlyContinue")
            print("    2. 直连测试：curl https://api.deepseek.com/models")
            print("    3. 若走代理，确认代理进程还在监听")
        return 1


if __name__ == "__main__":
    sys.exit(main())
