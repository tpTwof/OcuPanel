# OcuPanel 云服务器部署指南

从零把 OcuPanel 部署到一台 Linux 云服务器（以 **Ubuntu 22.04 / 24.04** 为例，Debian 系通用）。

整体形态：**Nginx（443/80）→ Uvicorn（127.0.0.1:8000）→ 单进程同时托管 API 与前端页面**。
前端构建产物由 FastAPI 自己托管，所以线上只需要跑一个进程，不需要 Node 常驻。

---

## 0. 先确定四件事

| 决策项 | 建议 | 原因 |
|---|---|---|
| 服务器配置 | **2 核 4G 起步**，磁盘 20G+ | 容量需在目标环境测量；旧版本内存数字不能作为当前保证，见 0.5 节 |
| GPU | **可选** | 视觉模型默认选择 CUDA → MPS → CPU；需安装对应 PyTorch 构建。CPU 版也可运行 |
| 出网 | 能访问 `huggingface.co` 或 `hf-mirror.com` | 首次启动要下 3 个模型（合计约 700MB） |
| 域名 | 想要 HTTPS 就需要；国内服务器还需**先备案**才能用 80/443 | 没备案可先用高位端口 + IP 访问，但浏览器会报不安全 |

> 单次报告生成会并发调用 7 个以上 LLM 请求（六专科 + Director + 最多 3 轮校验），
> 耗时通常 1–5 分钟。这是**同步长请求**，所以后面 Nginx 的超时必须放大，不能沿用默认 60s。

---

## 0.5 小内存部署与并发

旧版本逐次加载模型得到的 550MB 常驻、1.3GB 峰值等数字不再作为当前版本的容量指标。当前视觉模型由 `backend/vision/utils/runtime.py` 按设备缓存，加载和推理共用进程内锁，多个请求复用权重；每个 Uvicorn worker 仍各自持有一份缓存。

- 建议先运行单个 worker，在目标硬件上分别测量冷启动、首次推理、重复请求和多用户请求的内存峰值。
- 视觉锁只限制模型加载和推理，不限制整个报告任务。上传解码、知识检索、并发 LLM 调用和 PDF 仍会消耗资源。
- 在报告任务量较大时，应根据实测容量增加任务准入/队列；当前没有内置完整任务队列，不要把视觉锁当作整条报告链的限流。
- CPU 小机器可在 systemd 设置 `OMP_NUM_THREADS=2`、`MKL_NUM_THREADS=2`；分配器与 swap 是否调整应结合实际操作系统和测量结果。
- 在 2GB 机器上不能仅凭代码缓存就承诺安全运行，优先测量后再决定容量。

本地单张样本的 CPU 推理验证见 `backend/vision/README.md`；它验证执行和输出结构，不是生产容量测试或临床验证。

## 1. 服务器初始化

```bash
# 以 root 登录后
apt update && apt upgrade -y

# 建一个专用运行账号（不要用 root 跑服务）
adduser --disabled-password --gecos "" ocupanel
mkdir -p /opt/ocupanel && chown ocupanel:ocupanel /opt/ocupanel

# 基础工具 + Python + 中文字体（PDF 要用，缺了中文会变空框）
apt install -y git curl build-essential python3 python3-venv python3-pip \
               sqlite3 nginx fonts-noto-cjk fonts-wqy-microhei

# 防火墙
ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw --force enable
```

**云厂商控制台的安全组也要放行 22 / 80 / 443**，`ufw` 只管系统内部，两层都要开。

---

## 2. 把代码拉下来（私有仓库）

仓库是私有的，服务器上必须能认证。推荐 **Deploy Key（只读）**，比塞个人 Token 安全。

```bash
sudo -u ocupanel -H bash
cd /opt/ocupanel

# 生成只读部署密钥
ssh-keygen -t ed25519 -C "ocupanel-deploy" -f ~/.ssh/ocupanel_deploy -N ""
cat ~/.ssh/ocupanel_deploy.pub
```

把这行公钥贴到 GitHub：`仓库 → Settings → Deploy keys → Add deploy key`（**不要**勾选 Allow write access）。

```bash
# 告诉 ssh 用这把钥匙访问 github.com
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/ocupanel_deploy
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config

ssh -T git@github.com          # 应显示 successfully authenticated
git clone git@github.com:tpTwof/OcuPanel.git .
```

克隆完成后目录应是 `/opt/ocupanel/backend`、`/opt/ocupanel/frontend`、`/opt/ocupanel/tools`。

---

## 3. Python 环境与依赖

**关键：先单独装 CPU 版 torch**。`requirements.txt` 里是 `torch==2.7.0`，直接从 PyPI 装会顺带拉进
较大的 CUDA 运行库（仅在计划使用 NVIDIA GPU 时需要）。先装 CPU 版，pip 会认为该版本已满足，跳过重复安装。

```bash
cd /opt/ocupanel
python3 -m venv .venv
source .venv/bin/activate

pip install -U pip wheel
pip install torch==2.7.0 --index-url https://download.pytorch.org/whl/cpu   # 约 200MB

cd backend
pip install -r requirements.txt
```

装完自检：

```bash
python -c "import torch, transformers, cv2, fpdf2, fastapi; print(torch.__version__)"
```

> 若公司/校园网访问 PyPI 慢，临时加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`，
> 但 **torch 那一行必须留在官方 CPU 源**，镜像站常常没有 `+cpu` 轮子。

---

## 4. 写 `backend/.env`

```bash
cd /opt/ocupanel/backend
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

把上面输出的密钥填进 `.env` 的 `OCUPANEL_SECRET_KEY=`，然后按下面这份生产配置改：

```ini
# ---- 监听 ----
HOST=127.0.0.1
PORT=8000
RELOAD=0

# ---- LLM ----
# 留空即可：每个用户在自己「个人设置」里填自己的 Key，未配置时接口返 409
OPENAI_API_KEY=
# 只要不是 OpenAI 官方，就把接口地址写上（DeepSeek 示例）
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-flash
LLM_TIMEOUT=120
LLM_MAX_RETRIES=1
LLM_DISABLE_THINKING=1

# ---- 这个必须配，否则重启后所有用户已存的 Key 全部解不开 ----
OCUPANEL_SECRET_KEY=粘贴刚才生成的密钥

# ---- 报告 ----
REPORT_LANGUAGE=zh
# 字体已由 fonts-noto-cjk 提供，通常能自动探测到；
# 若 PDF 中文变空框，取消下面这行注释
# REPORT_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc

# ---- 检索 ----
RAG_ENABLED=1
RAG_MODE=hybrid
HF_ENDPOINT=https://hf-mirror.com

# ---- 跨域 ----
# 同源部署不需要 CORS，留空这行即可（保持注释状态）
# CORS_ORIGINS=
```

```bash
chmod 600 .env            # 含密钥，收紧权限
```

> `config.py` 会自己加载 `backend/.env`，不依赖启动目录，所以 **systemd 里不需要 EnvironmentFile**
> ——那样反而容易被带空格的值弄出语法错误。

---

## 5. 预下载模型（强烈建议）

模型懒加载，第一次生成报告时才去下载；一旦下载慢，前端就是一个几分钟的白屏，很容易被当成服务挂了。
手动先拉一遍：

```bash
cd /opt/ocupanel/backend
source /opt/ocupanel/.venv/bin/activate
export HF_ENDPOINT=https://hf-mirror.com

python - <<'PY'
from transformers import AutoModel, AutoModelForImageClassification, SegformerForSemanticSegmentation, AutoImageProcessor
print("segformer...")
SegformerForSemanticSegmentation.from_pretrained("pamixsun/segformer_for_optic_disc_cup_segmentation")
print("swinv2...")
AutoModelForImageClassification.from_pretrained("pamixsun/swinv2_tiny_for_glaucoma_classification")
print("e5...")
AutoModel.from_pretrained("intfloat/multilingual-e5-small")
print("done")
PY
```

下载落在 `~/.cache/huggingface`（约 700MB）。生产环境建议固定到项目盘，避免 `~` 满了：

```bash
# 在 .env 里加一行，或写进 systemd 的 Environment
HF_HOME=/opt/ocupanel/.cache/huggingface
```

---

## 6. 前端构建产物

两个方案，选一个。

**方案 A（推荐）：本地构建后上传**，服务器完全不需要 Node。

```bash
# 在你自己的 Windows 机器上，项目根目录
cd frontend && npm run build && cd ..
scp -r frontend/dist ocupanel@<服务器IP>:/opt/ocupanel/frontend/
```

**方案 B：服务器上装 Node 构建**

```bash
# 注意 Ubuntu 自带的 nodejs 只有 12，Vite 6 需要 18+
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

cd /opt/ocupanel/frontend
npm ci
npm run build          # 产出 frontend/dist
```

构建完成后确认 `/opt/ocupanel/frontend/dist/index.html` 存在。
**没有这个文件时后端会自动降级成"纯 API 模式"，页面打不开但接口正常**——这是最容易误判的一步。

---

## 7. 迁移现有数据（可选）

想把本地已有的账号、会话、报告一起搬过去：

```bash
# 1) 先停掉本地后端进程（Windows 下 sqlite 文件被占用时拷出来是残的）

# 2) 拷数据库（本地 Git Bash 执行）
scp backend/ocupanel.db ocupanel@<服务器IP>:/opt/ocupanel/backend/

# 3) 若本地存在 ocupanel.db-wal / ocupanel.db-shm，一并拷过去，否则可能丢最近几条写入
```

**还有一件容易漏的事**：本地 `backend/.env` 里的 `OCUPANEL_SECRET_KEY` 必须和服务器上的一致，
否则库里那些加密的 API Key 全部解不开，用户得重新填一遍。

```bash
# 服务器上确认属主
chown ocupanel:ocupanel /opt/ocupanel/backend/ocupanel.db
```

不想搬数据就跳过这步，首次启动会自动建表。

---

## 8. 用 systemd 托管

```bash
sudo nano /etc/systemd/system/ocupanel.service
```

```ini
[Unit]
Description=OcuPanel - multi-agent ophthalmic report service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ocupanel
Group=ocupanel
WorkingDirectory=/opt/ocupanel/backend
Environment=PYTHONUNBUFFERED=1
Environment=HF_HOME=/opt/ocupanel/.cache/huggingface
ExecStart=/opt/ocupanel/.venv/bin/python main.py
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ocupanel
sudo systemctl status ocupanel
journalctl -u ocupanel -f          # 看启动日志
```

**不要加 `--workers N`。** 每个 worker 都会独立加载一遍 torch 和三个模型，
2 核 4G 的机器开到第二个就会 OOM。会话和对话都在 SQLite 里，单进程完全够用。

启动日志正常长这样：

```
SQLite ready at /opt/ocupanel/backend/ocupanel.db（清理过期登录态 0 条）
Serving frontend build from /opt/ocupanel/frontend/dist
RAG gate selfcheck ok: {...}
```

启动后 10–60 秒 CPU 会飙高，那是 RAG 自检在预热向量模型，属正常。

---

## 9. Nginx 反向代理

```bash
sudo nano /etc/nginx/sites-available/ocupanel
```

```nginx
server {
    listen 80;
    server_name your-domain.com;      # 没有域名就写服务器公网 IP

    # 眼底图上传，默认 1m 会直接 413
    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 报告生成要 1–5 分钟，这三行是重点
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_buffering off;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/ocupanel /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

三个参数的作用：

- `client_max_body_size 25m` → 不然上传稍大的图就 **413**，而前端只会显示一个失败。
- `proxy_read_timeout 600s` → 默认 60s 会在 LLM 还在思考时切断连接，浏览器看到 **504**，
  但后端其实还在跑（白烧一遍 token）。
- `proxy_buffering off` → 让 PDF 下载和长响应及时吐出。

> 用 **CentOS / RHEL / Alma** 的话多一步：`setsebool -P httpd_can_network_connect 1`，
> 否则 Nginx 连不上 `127.0.0.1:8000`（表现为 502），而且日志里看不出原因。

---

## 10. HTTPS

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
sudo systemctl status certbot.timer     # 自动续期
```

证书搞定后，把 `.env` 里的 `HOST` 继续保持 `127.0.0.1` 即可——对外走 Nginx，不要直接暴露 8000。

---

## 11. 验收清单

按顺序打勾，任何一步失败都别急着往下走。

```bash
# 1) 进程活着
systemctl is-active ocupanel

# 2) 后端本机可达（401 = 服务正常、只是没登录态，这是对的）
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/account/me

# 3) 前端页面由后端托管（应为 200 且 content-type 是 text/html）
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:8000/

# 4) 经过 Nginx 也正常
curl -s -o /dev/null -w "%{http_code}\n" http://<服务器IP>/
```

浏览器里再走一遍：

1. 打开站点 → 出现登录页（不是白屏、不是 Internal Server Error）
2. 注册新账号 → 成功进入欢迎页
3. 左下角「个人设置」→ 填 API Key / 接口地址 / 模型 → 点「测试连通」→ 有回复
4. 「生成报告」→ 传 `samples/fundus_right_eye.png` + 一段临床记录 → 等 1–5 分钟出报告
5. 点下载 PDF → 中文正常显示（若变空框，回第 4 节设 `REPORT_FONT_PATH`）
6. 退出登录 → 回到登录页；刷新页面仍是登录页（未回退）

最后跑一遍多用户隔离自检（会注册两个临时账号、跑 24 项检查、跑完自动删号）：

```bash
cd /opt/ocupanel/backend
/opt/ocupanel/.venv/bin/python ../tools/check_isolation.py --base http://127.0.0.1:8000 --cleanup
```

全部通过会打印 `24/24`，退出码 0。

---

## 12. 日常运维

```bash
# 日志
journalctl -u ocupanel -f
journalctl -u ocupanel --since "1 hour ago" | grep -i error

# 重启 / 停止
sudo systemctl restart ocupanel

# 看内存占用（常驻和峰值需在目标环境实测；跑完不回落到启动值属正常，
# 因为 glibc 不急着把内存还给系统；但要是一直涨到 1.8G 以上就说明有泄漏）
systemctl status ocupanel | grep Memory

# 排查 OOM（被系统杀掉时进程会莫名重启）
dmesg -T | grep -i "out of memory"
```

**备份**（至少每天一次，数据库里有账号和密文 Key）：

```bash
sudo mkdir -p /var/backups/ocupanel
sudo sqlite3 /opt/ocupanel/backend/ocupanel.db \
  ".backup '/var/backups/ocupanel/ocupanel-$(date +%F).db'"
# 保留 14 天
sudo find /var/backups/ocupanel -name "*.db" -mtime +14 -delete
```

写成 crontab（`sudo crontab -e`）：

```
20 3 * * * sqlite3 /opt/ocupanel/backend/ocupanel.db ".backup '/var/backups/ocupanel/ocupanel-$(date +\%F).db'"
30 3 * * * find /var/backups/ocupanel -name "*.db" -mtime +14 -delete
```

**更新版本**：

```bash
sudo -u ocupanel -H bash -c "cd /opt/ocupanel && git pull"
/opt/ocupanel/.venv/bin/pip install -r /opt/ocupanel/backend/requirements.txt
# 前端有改动时：本地 npm run build 后重新 scp dist（或服务器 npm ci && npm run build）
sudo systemctl restart ocupanel
```

`backend/img_store/` 只增不删（存分割图），长期会慢慢变大，偶尔清理一下
——但清了历史报告里的分割图就失效，自己权衡。

---

## 13. 常见故障对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| 页面白屏 / 接口 404 | `frontend/dist` 没上传，后端跑在纯 API 模式 | 补传 dist，或看日志有没有 `running in API-only mode` |
| `Internal Server Error`、响应体为空 | 直连了 5500 开发端口，或 Uvicorn 没起 | 生产别用 Vite 开发服务器；`systemctl status ocupanel` |
| 上传图片 413 | Nginx 默认 body 只有 1MB | `client_max_body_size 25m` |
| 504 Gateway Timeout，但后端日志显示报告其实生成完了 | `proxy_read_timeout` 太短 | 调到 600s |
| 502 Bad Gateway | Uvicorn 没监听 8000，或 SELinux 拦了 Nginx 出网 | 先 `curl 127.0.0.1:8000`；CentOS 设 `httpd_can_network_connect` |
| PDF 中文是空框 | 服务器缺中文字体 | `apt install fonts-noto-cjk`，必要时设 `REPORT_FONT_PATH` |
| 首次生成报告卡很久 | 正在下载模型 | 按第 5 节预下载；或换 `HF_ENDPOINT` |
| 进程反复重启、日志无报错 | 被 OOM Killer 杀掉 | 加内存 / 换 8G 机器；确认没有开多 worker |
| 用户填过的 Key 全部失效 | `OCUPANEL_SECRET_KEY` 变了 | 恢复原来的密钥，或让用户重填 |
| 报告里提示"无据可依"并拒答 | 引用校验没通过（正常防护，不是 bug） | 换个临床描述或补充信息重试；别去关 `VERIFY_ENABLED` |
| 登录后过一段时间要重新登录 | 会话 7 天过期 | 正常行为 |
