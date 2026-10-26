"""最小 CDP 客户端：用标准库驱动无头 Chrome 截图。

为什么不用 Playwright：项目不想为一个截图脚本引入 300MB 依赖，
而 Chrome 的 --remote-debugging-port 已经够了。这里只用
urllib + socket 手写 WebSocket 帧（Chrome 的 CDP 只收文本帧）。

用法：python tools/shot.py <url> <out.png> [--width 1440] [--height 900]
                          [--token <token>] [--click "<css selector>"]
                          [--click-text "<按钮文字>"] [--type "<selector>|<text>"]
                          [--wait <ms>] [--auto-confirm] [--eval "<js 表达式>"]

--click / --click-text / --type 按命令行出现的先后顺序执行，
所以「先填值再点提交」写成 --type ... --click ...。

--auto-confirm 把 confirm()/alert() 换成自动通过。页面里带确认框的操作
（删会话、退出登录）不加它会一直卡住，因为弹窗阻塞渲染、evaluate 拿不到返回。
"""

import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9333


class WS:
    """够用的 WebSocket 客户端：只处理文本帧与分片。"""

    def __init__(self, url):
        u = urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + (("?" + u.query) if u.query else "")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {u.hostname}:{u.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            self.buf += self.sock.recv(4096)
        self.buf = self.buf.split(b"\r\n\r\n", 1)[1]

    def _recv(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("socket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, payload):
        data = json.dumps(payload).encode()
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def recv(self):
        chunks = []
        while True:
            b1, b2 = self._recv(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv(8))[0]
            payload = self._recv(length)
            if opcode == 0x8:
                raise ConnectionError("close frame")
            if opcode == 0x9:  # ping -> pong
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            chunks.append(payload)
            if fin:
                return json.loads(b"".join(chunks).decode())


class Page:
    def __init__(self, ws):
        self.ws = ws
        self._id = 0
        self.events = []

    def call(self, method, **params):
        self._id += 1
        mid = self._id
        self.ws.send({"id": mid, "method": method, "params": params})
        while True:
            msg = self.ws.recv()
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self.events.append(msg)

    def js(self, expr, await_promise=False):
        r = self.call(
            "Runtime.evaluate",
            expression=expr,
            returnByValue=True,
            awaitPromise=await_promise,
        )
        return r.get("result", {}).get("value")


def wait_ready(page, timeout=20):
    """等到 React 挂载出 #root 的内容为止（网络慢时比固定 sleep 稳）。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if page.js("(document.querySelector('#root')||{}).childElementCount"):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 1
    url, out = args[0], args[1]

    opts = {"width": 1440, "height": 900, "token": None, "wait": 1200,
            "auto_confirm": False, "eval": None, "actions": []}
    i = 2
    while i < len(args):
        k = args[i]
        v = args[i + 1] if i + 1 < len(args) else ""
        step = 2
        if k == "--width":
            opts["width"] = int(v)
        elif k == "--height":
            opts["height"] = int(v)
        elif k == "--token":
            opts["token"] = v
        elif k == "--wait":
            opts["wait"] = int(v)
        elif k == "--eval":
            opts["eval"] = v
        elif k == "--auto-confirm":
            opts["auto_confirm"] = True
            step = 1  # 不带值
        elif k in ("--click", "--click-text", "--type"):
            # 按命令行出现顺序执行：填值必须能排在点击之前，
            # 否则会出现"还没输入就点了提交"这种假失败。
            opts["actions"].append((k, v))
        i += step

    proc = subprocess.Popen(
        [
            CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-first-run", "--no-default-browser-check",
            f"--remote-debugging-port={PORT}",
            f"--user-data-dir={os.path.join(os.path.dirname(out) or '.', 'cdp-profile')}",
            f"--window-size={opts['width']},{opts['height']}",
            "--force-device-scale-factor=1.5",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as r:
                    tabs = json.load(r)
                pages = [t for t in tabs if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.3)
        if not ws_url:
            print("无法连接到 Chrome 调试端口")
            return 2

        page = Page(WS(ws_url))
        page.call("Page.enable")
        page.call("Runtime.enable")

        if opts["token"]:
            # 在文档创建前注入 localStorage，而不是「先跳一个页面再写」。
            # 后者依赖跳转完成时机，常出现 token 还没写进去页面就已经初始化完，
            # 表现为"注入了 token 却仍是登录页"。addScriptToEvaluateOnNewDocument
            # 对之后每个新文档都在应用脚本之前执行，稳定得多。
            page.call(
                "Page.addScriptToEvaluateOnNewDocument",
                source="try{localStorage.setItem('medchat.token', %s)}catch(e){}"
                % json.dumps(opts["token"]),
            )

        if opts["auto_confirm"]:
            # confirm()/alert() 会阻塞页面渲染，CDP 的 Runtime.evaluate 会一直
            # 等不到返回，整个脚本卡死。截图场景直接把它们换成 no-op。
            page.call(
                "Page.addScriptToEvaluateOnNewDocument",
                source="try{window.confirm=()=>true;window.alert=()=>{}}catch(e){}",
            )

        page.call("Page.navigate", url=url)
        wait_ready(page)
        # React 挂载完成后接口才回来，会话列表等元素要额外等一下
        time.sleep(opts["wait"] / 1000)

        for kind, value in opts["actions"]:
            if kind == "--click":
                ok = page.js(
                    "(()=>{const e=document.querySelector(%s);if(!e)return false;e.click();return true})()"
                    % json.dumps(value)
                )
                print(f"  click {value}: {ok}")
            elif kind == "--click-text":
                ok = page.js(
                    """(()=>{const t=%s;
                    const els=[...document.querySelectorAll('button,a,[role=button]')];
                    const e=els.find(x=>(x.textContent||'').includes(t));
                    if(e){e.click();return true}return false})()"""
                    % json.dumps(value)
                )
                print(f"  click-text {value}: {ok}")
            else:  # --type
                sel, _, val = value.partition("|")
                ok = page.js(
                    """(()=>{const e=document.querySelector(%s);
                    if(!e)return false;
                    const setter=Object.getOwnPropertyDescriptor(
                      e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set;
                    setter.call(e,%s);
                    e.dispatchEvent(new Event('input',{bubbles:true}));
                    return true})()"""
                    % (json.dumps(sel), json.dumps(val))
                )
                print(f"  type {sel}: {ok}")
            time.sleep(0.6)

        time.sleep(opts["wait"] / 1000)

        # 可选：截图前在页面里求值一次，用来断言状态（比如登录态是否真被清掉）
        if opts["eval"]:
            try:
                print(f"  eval → {page.js(opts['eval'])!r}")
            except Exception as exc:
                print(f"  eval 失败 → {exc}")

        shot = page.call("Page.captureScreenshot", format="png", captureBeyondViewport=False)
        with open(out, "wb") as f:
            f.write(base64.b64decode(shot["data"]))
        print(f"已保存 {out}")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
