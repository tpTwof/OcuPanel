"""多用户数据隔离验收脚本。

用两个临时账号（带时间戳后缀，可反复运行）把越权路径全试一遍，重点不是
"能不能读到自己的"，而是"能不能碰到别人的"——尤其是删除和写入：
读越权顶多泄露，写越权会毁数据。

用法：
    python tools/check_isolation.py                     # 跑全部检查
    python tools/check_isolation.py --base http://127.0.0.1:8010
    python tools/check_isolation.py --cleanup           # 跑完删掉测试账号

退出码 0 表示全部通过，1 表示有失败项。
"""

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "backend" / "ocupanel.db"

passed = 0
failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  \033[32mPASS\033[0m  {name}")
    else:
        failed += 1
        print(f"  \033[31mFAIL\033[0m  {name}" + (f"  → {detail}" if detail else ""))


class Client:
    """一个带令牌的极简 HTTP 客户端。token=None 即未登录。"""

    def __init__(self, base, token=None):
        self.base = base.rstrip("/")
        self.token = token

    def call(self, method, path, body=None):
        headers = {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                return e.code, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return e.code, raw


def register(base, username):
    status, data = Client(base).call(
        "POST",
        "/api/account/register",
        {"username": username, "password": "isolation-test-1234", "display_name": username},
    )
    if status != 200:
        print(f"注册 {username} 失败：{status} {data}")
        sys.exit(2)
    return data["token"], data["user"]["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000", help="后端地址")
    ap.add_argument("--cleanup", action="store_true", help="跑完删除测试账号")
    args = ap.parse_args()

    suffix = str(int(time.time()))[-8:]
    name_a, name_b = f"isoA{suffix}", f"isoB{suffix}"
    print(f"\n目标 {args.base}")
    print(f"临时账号 {name_a} / {name_b}\n")

    token_a, uid_a = register(args.base, name_a)
    token_b, uid_b = register(args.base, name_b)
    A, B = Client(args.base, token_a), Client(args.base, token_b)
    anon = Client(args.base)

    # ---------- 1. 认证层 ----------
    print("[1] 认证层")
    status, _ = anon.call("GET", "/api/account/me")
    check("未登录访问 /account/me 被拒（401）", status == 401, f"实际 {status}")
    status, _ = Client(args.base, "not-a-real-token").call("GET", "/api/chat/conversations")
    check("伪造令牌被拒（401）", status == 401, f"实际 {status}")

    # ---------- 2. A 自己的数据能正常读写 ----------
    print("\n[2] 正常路径（确认隔离没把合法操作也挡掉）")
    status, conv = A.call("POST", "/api/chat/conversations", {"title": "A 的私有会话"})
    check("A 能建会话", status == 200 and conv.get("id"), f"{status} {conv}")
    conv_id = conv["id"]

    status, data = A.call("GET", "/api/chat/conversations")
    ids = [c["id"] for c in (data or {}).get("items", [])]
    check("A 的列表里有自己的会话", conv_id in ids, f"列表 {ids}")

    status, _ = A.call("PATCH", f"/api/chat/conversations/{conv_id}", {"title": "A 改过标题"})
    check("A 能重命名自己的会话", status == 200, f"实际 {status}")

    # ---------- 3. B 读 A 的数据 ----------
    print("\n[3] 读越权")
    status, data = B.call("GET", "/api/chat/conversations")
    b_ids = [c["id"] for c in (data or {}).get("items", [])]
    check("B 的列表不含 A 的会话", conv_id not in b_ids, f"B 列表 {b_ids}")
    check("B 的列表本身为空", b_ids == [], f"实际 {b_ids}")

    status, data = B.call("GET", f"/api/chat/conversations/{conv_id}")
    check("B 读 A 的会话返回 404", status == 404, f"实际 {status} {data}")

    # 不泄露存在性的严格验证：越权访问「真实存在的 id」与访问「瞎编的 id」，
    # 状态码和文案必须一模一样，否则攻击者能靠响应差异探测哪些 id 是真的。
    status_fake, data_fake = B.call("GET", "/api/chat/conversations/0000000000000000000000000000dead")
    check(
        "越权访问与访问不存在的 id，响应完全一致",
        status == status_fake == 404 and data == data_fake,
        f"越权 {status}/{data} vs 不存在 {status_fake}/{data_fake}",
    )

    # ---------- 4. B 写 A 的数据（最危险） ----------
    print("\n[4] 写越权（最危险，写成功等于毁数据）")
    status, _ = B.call("PATCH", f"/api/chat/conversations/{conv_id}", {"title": "B 篡改"})
    check("B 改 A 的会话被拒（404）", status == 404, f"实际 {status}")

    status, data = A.call("GET", f"/api/chat/conversations/{conv_id}")
    # 详情接口返回 {"conversation": {...}, "messages": [...]}，标题在 conversation 里
    title_now = ((data or {}).get("conversation") or {}).get("title")
    check("A 的标题没有被改掉", title_now == "A 改过标题", f"实际标题 {title_now}")

    status, _ = B.call(
        "POST", f"/api/chat/conversations/{conv_id}/messages", {"message": "越权提问"}
    )
    check("B 往 A 的会话发消息被拒（404）", status == 404, f"实际 {status}")

    status, _ = B.call("DELETE", f"/api/chat/conversations/{conv_id}")
    check("B 删 A 的会话被拒（404）", status == 404, f"实际 {status}")

    status, data = A.call("GET", f"/api/chat/conversations/{conv_id}")
    check("越权删除后 A 的会话仍然存在", status == 200, f"实际 {status} {data}")

    # ---------- 5. LLM 配置隔离 ----------
    print("\n[5] LLM 配置隔离")
    fake_key = "sk-isolation-probe-abcd1234"
    status, _ = A.call(
        "PUT",
        "/api/account/llm",
        {"api_key": fake_key, "base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
    )
    check("A 能保存自己的 LLM 配置", status == 200, f"实际 {status}")

    status, me_a = A.call("GET", "/api/account/me")
    llm_a = (me_a or {}).get("llm") or {}
    check("A 的 /me 显示已配置", llm_a.get("has_key") is True, f"实际 {llm_a}")

    status, me_b = B.call("GET", "/api/account/me")
    llm_b = (me_b or {}).get("llm") or {}
    check("B 的 /me 显示未配置", not llm_b.get("has_key"), f"实际 {llm_b}")

    masked_b = str(llm_b.get("api_key_masked") or "")
    check("B 看不到 A 的 key 任何片段", "abcd1234" not in masked_b and not masked_b, f"实际 {masked_b}")

    # B 直接删自己的配置不该影响 A
    B.call("DELETE", "/api/account/llm")
    status, me_a2 = A.call("GET", "/api/account/me")
    check(
        "B 清除配置不影响 A",
        ((me_a2 or {}).get("llm") or {}).get("has_key") is True,
        f"实际 {(me_a2 or {}).get('llm')}",
    )

    # ---------- 6. 用量统计按人算 ----------
    print("\n[6] 统计口径")
    status, usage_a = A.call("GET", "/api/account/usage")
    check(
        "A 的 usage 只统计自己的会话",
        (usage_a or {}).get("conversations") == 1,
        f"实际 {usage_a}",
    )
    status, usage_b = B.call("GET", "/api/account/usage")
    check(
        "B 的 usage 为 0（没建过会话）",
        (usage_b or {}).get("conversations") == 0,
        f"实际 {usage_b}",
    )

    # ---------- 7. 数据库层面复核 ----------
    print("\n[7] 数据库层复核（绕过 API 直接看行）")
    if DB_PATH.is_file():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conv_owner = conn.execute(
            "SELECT user_id FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
        check(
            "会话行归属 A（user_id 对得上）",
            bool(conv_owner) and conv_owner["user_id"] == uid_a,
            f"实际 {dict(conv_owner) if conv_owner else None}",
        )

        a_convs = conn.execute(
            "SELECT COUNT(*) c FROM conversations WHERE user_id = ?", (uid_a,)
        ).fetchone()["c"]
        b_convs = conn.execute(
            "SELECT COUNT(*) c FROM conversations WHERE user_id = ?", (uid_b,)
        ).fetchone()["c"]
        check("A 名下 1 个会话、B 名下 0 个", a_convs == 1 and b_convs == 0, f"A={a_convs} B={b_convs}")

        leaked = conn.execute(
            "SELECT COUNT(*) c FROM llm_configs WHERE user_id = ?", (uid_b,)
        ).fetchone()["c"]
        check("B 名下没有 LLM 配置行", leaked == 0, f"实际 {leaked} 行")

        conn.close()
    else:
        print(f"  \033[33mSKIP\033[0m  找不到 {DB_PATH}，跳过数据库层复核")

    # ---------- 汇总 ----------
    print(f"\n{'=' * 52}")
    total = passed + failed
    if failed == 0:
        print(f"\033[32m全部通过：{passed}/{total}\033[0m")
    else:
        print(f"\033[31m{passed}/{total} 通过，{failed} 项失败\033[0m")

    if args.cleanup:
        cleanup([uid_a, uid_b])
    else:
        print(f"\n测试账号已留在库里（{name_a} / {name_b}）。")
        print("要清掉请重跑并加 --cleanup，或停了服务直接删 backend/ocupanel.db。")

    return 0 if failed == 0 else 1


def cleanup(user_ids):
    """删掉测试账号。外键是 ON DELETE CASCADE，删 user 会带走配置/会话/消息/报告。"""
    if not DB_PATH.is_file():
        print("找不到数据库，跳过清理")
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    for uid in user_ids:
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    conn.commit()
    left = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE id IN (?, ?)", tuple(user_ids)
    ).fetchone()[0]
    conn.close()
    print(f"\n已清理测试账号（残留 {left} 个）")


if __name__ == "__main__":
    sys.exit(main())
