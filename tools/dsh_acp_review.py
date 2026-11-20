"""Run one read-only OcuPanel review through DSH's ACP stdio profile."""

import json
import os
import subprocess
import sys
import threading
import time


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DSH = r"C:\Users\Administrator\AppData\Roaming\npm\dsh.cmd"
process = subprocess.Popen(
    [DSH, "--profile", "acp"], cwd=ROOT,
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, encoding="utf-8", errors="replace", bufsize=1,
)
pending = {}
next_id = 1
session_id = None


def send(message):
    process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
    process.stdin.flush()


def reader():
    global session_id
    for line in process.stdout:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print("NON_JSON_STDOUT", line[:500], flush=True)
            continue
        if "id" in msg and ("result" in msg or "error" in msg):
            pending[msg["id"]] = msg
        elif msg.get("method") == "session/request_permission":
            options = msg.get("params", {}).get("options", [])
            reject = next((x for x in options if "reject" in str(x).lower() or "deny" in str(x).lower()), None)
            if reject:
                send({"jsonrpc": "2.0", "id": msg["id"], "result": {"outcome": {"outcome": "selected", "optionId": reject.get("optionId")}}})
            else:
                print("PERMISSION_REQUIRES_USER", json.dumps(msg, ensure_ascii=False), flush=True)
        elif msg.get("method") == "session/update":
            update = msg.get("params", {}).get("update", {})
            kind = update.get("sessionUpdate", "")
            if kind in ("agent_message_chunk", "agent_thought_chunk"):
                if kind == "agent_message_chunk":
                    print(update.get("content", {}).get("text", ""), end="", flush=True)
            elif kind == "tool_call":
                print("\nTOOL", update.get("title", ""), json.dumps(update.get("rawInput", {}), ensure_ascii=False)[:200], flush=True)
            elif kind == "tool_call_update":
                pass
            else:
                pass
        else:
            print("OTHER", json.dumps(msg, ensure_ascii=False)[:1000], flush=True)


def stderr_reader():
    for line in process.stderr:
        print("STDERR", line.rstrip()[:1000], flush=True)


threading.Thread(target=reader, daemon=True).start()
threading.Thread(target=stderr_reader, daemon=True).start()


def call(method, params, timeout=60):
    global next_id
    request_id = next_id
    next_id += 1
    send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if request_id in pending:
            response = pending.pop(request_id)
            print("\nRESPONSE", method, json.dumps(response, ensure_ascii=False)[:8000], flush=True)
            if "error" in response:
                raise RuntimeError(response["error"])
            return response["result"]
        if process.poll() is not None:
            raise RuntimeError(f"DSH exited: {process.returncode}")
        time.sleep(0.05)
    raise TimeoutError(method)


try:
    call("initialize", {"protocolVersion": 1, "clientInfo": {"name": "ocupanels-review-client", "version": "0.1"}, "clientCapabilities": {}})
    session = call("session/new", {"cwd": ROOT, "mcpServers": []})
    session_id = session["sessionId"]
    print("SESSION_ID", session_id, flush=True)
    prompt = (
        "在 OcuPanel 项目中完成一个简短的只读评估任务。"
        "只检查 README.md、backend/main.py、backend/report/generation.py、"
        "frontend/src/App.jsx 和 frontend/package.json。"
        "用中文列出最多 3 项最值得改进的问题和下一步行动，每项引用文件路径和行号。"
        "当前有未提交改动；不要修改文件、运行测试或访问密钥。请直接给出最终答复。"
    )
    call("session/prompt", {"sessionId": session_id, "prompt": [{"type": "text", "text": prompt}]}, timeout=900)
finally:
    if session_id:
        try:
            call("session/close", {"sessionId": session_id}, timeout=10)
        except Exception as exc:
            print("CLOSE_ERROR", str(exc), flush=True)
    process.terminate()
