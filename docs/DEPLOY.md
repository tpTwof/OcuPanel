# OcuPanel 云服务器部署指南

本指南给出 Linux 单进程部署步骤。当前实际验证环境是 Windows 项目 Python 3.13.3、Node 24.15.0 / npm 11.12.1；Linux 的 Python 3.13 安装与依赖仍需在目标机器验证，不应直接采用发行版默认 Python 并假定兼容。

整体形态：**Nginx（443/80）→ Uvicorn（127.0.0.1:8000）→ 单进程同时托管 API 与前端页面**。
前端构建产物由 FastAPI 自己托管，所以线上只需要跑一个进程，不需要 Node 常驻。

---

## 0. 先确定四件事

| 决策项 | 建议 | 原因 |
|---|---|---|
| 服务器配置 | **2 核 4G 起步**，磁盘 20G+ | 容量需在目标环境测量；旧版本内存数字不能作为当前保证，见 0.5 节 |
| GPU | **可选** | 视觉模型默认选择 CUDA → MPS → CPU；需安装对应 PyTorch 构建。CPU 版也可运行 |
| 出网 | 能访问 `huggingface.co` 或 `hf-mirror.com` | 默认配置涉及两个视觉模型和一个向量模型；下载大小与缓存、版本有关 |
| 域名 | 想要 HTTPS 就需要；国内服务器还需**先备案**才能用 80/443 | 没备案可先用高位端口 + IP 访问，但浏览器会报不安全 |

> 专科阶段六角色并发，之后 Director 与 Verifier 顺序执行；专科工具循环、校验修订和重生成会增加模型调用。当前是同步长请求，没有内置任务队列；代理超时应结合目标环境耗时配置，不能承诺固定时长。

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

公开仓库可以使用 HTTPS 克隆；私有仓库或使用 SSH 地址时需配置认证。下面给出只读 Deploy Key 示例，按实际仓库权限选择。

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

先通过目标系统认可的安装方式准备 Python 3.13 和对应 venv 支持，确认 `python3.13` 可用。下方 apt 的默认 python3 包不能保证提供 3.13。

**CPU 部署先单独装 CPU 版 torch**。`requirements.txt` 里是 `torch==2.7.0`，直接从 PyPI 装会顺带拉进
较大的 CUDA 运行库（仅在计划使用 NVIDIA GPU 时需要）。先装 CPU 版，pip 会认为该版本已满足，跳过重复安装。

```bash
cd /opt/ocupanel
python3.13 --version
python3.13 -m venv .venv
source .venv/bin/activate

pip install -U pip wheel
pip install torch==2.7.0 --index-url https://download.pytorch.org/whl/cpu   # 约 200MB

cd backend
pip install -r requirements.txt
```

装完自检：

```bash
python -c "import sys, torch, transformers, cv2, fpdf, fastapi; print(sys.version); print(torch.__version__)"
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
OPENAI_MODEL=填写该端点实际可用的模型ID
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

> `backend/utils/config.py` 会自己加载 `backend/.env`，不依赖启动目录，所以 **systemd 里不需要 EnvironmentFile**
> ——那样反而容易被带空格的值弄出语法错误。

---

## 5. 预下载模型（强烈建议）

视觉模型首次分析时加载；默认向量检索模型可能在启动后的后台自检中加载。下载或预热较慢时查看后端日志，前端分析页会显示生成状态。
手动先拉一遍：

```bash
cd /opt/ocupanel/backend
source /opt/ocupanel/.venv/bin/activate
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/opt/ocupanel/.cache/huggingface

python - <<'PY'
from transformers import AutoModel, AutoTokenizer, AutoModelForImageClassification, SegformerForSemanticSegmentation, AutoImageProcessor
print("segformer...")
SegformerForSemanticSegmentation.from_pretrained("pamixsun/segformer_for_optic_disc_cup_segmentation")
print("swinv2...")
AutoModelForImageClassification.from_pretrained("pamixsun/swinv2_tiny_for_glaucoma_classification")
print("e5...")
AutoModel.from_pretrained("intfloat/multilingual-e5-small")
for name in ("pamixsun/segformer_for_optic_disc_cup_segmentation", "pamixsun/swinv2_tiny_for_glaucoma_classification"):
    AutoImageProcessor.from_pretrained(name, use_fast=False)
AutoTokenizer.from_pretrained("intfloat/multilingual-e5-small")
print("done")
PY
```

默认缓存根目录为 `~/.cache/huggingface`，权重通常在其 hub 子目录。可在预下载前和服务环境中统一设置 HF_HOME，避免下载与运行使用不同缓存目录：

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
# 先安装 Node 24 与 npm（本机验证基线），具体安装方式按目标系统选择
node --version
npm --version

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
# 1) 先停掉本地后端，确保没有写入；推荐用 SQLite backup 生成一致性快照

# 2) 拷数据库（本地 Git Bash 执行）
scp backend/ocupanel.db ocupanel@<服务器IP>:/opt/ocupanel/backend/

# 3) 直接复制文件时必须停写并考虑 WAL；不要复制运行中的单个 db 文件
#    推荐传输 backup 生成的数据库快照，同时迁移 img_store 和原加密密钥
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

先使用单 worker，每个 worker 会独立加载模型缓存；是否增加 worker 需实测内存、并发和延迟。当前没有完整任务队列，不能仅凭 SQLite 支持并发就判断整条分析链容量足够。

启动日志正常长这样：

```
SQLite ready at /opt/ocupanel/backend/ocupanel.db（清理过期登录态 0 条）
Serving frontend build from /opt/ocupanel/frontend/dist
RAG gate selfcheck ok: {...}
```

启动后的后台 RAG 自检可能触发向量模型下载与预热，耗时和资源占用取决于缓存与硬件；自检失败会写日志告警。

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

        # 同步分析可能耗时较长；根据实测调整超时
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
4. 「生成报告」→ 传 `samples/fundus_right_eye.png` + 一段临床记录 → 检查报告或明确拒答原因（耗时随模型服务和硬件变化）
5. 点下载 PDF → 中文正常显示（若变空框，回第 4 节设 `REPORT_FONT_PATH`）
6. 退出登录 → 回到登录页；刷新页面仍是登录页（未回退）

最后跑一遍多用户隔离自检（会注册两个临时账号、跑 24 项检查、跑完自动删号）：

```bash
cd /opt/ocupanel/backend
/opt/ocupanel/.venv/bin/python ../tools/check_isolation.py --base http://127.0.0.1:8000 --cleanup
```

通过时退出码为 0，以脚本实际检查总数为准；这不覆盖分割图所属用户校验，也不代表完整权限审计。

---

## 12. 日常运维

```bash
# 日志
journalctl -u ocupanel -f
journalctl -u ocupanel --since "1 hour ago" | grep -i error

# 重启 / 停止
sudo systemctl restart ocupanel

# 看内存占用（常驻和峰值需在目标环境实测；跑完不回落到启动值属正常，
# 因为 glibc 不急着把内存还给系统；单一绝对数值不能判断泄漏，应比较同等负载下的长期趋势）
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

## 当前行为与备份范围

普通聊天与眼科追问只调用 LLM，提交影像分析才运行 vision、Agents 与 report。聊天默认上下文与输出限制见 [chat/README](../backend/chat/README.md)。PDF 下载会重新生成并可能额外计费，刷新后暂不能直接导出已存报告。

备份不仅包括 SQLite，还包括 backend/.env 中的 OCUPANEL_SECRET_KEY 与 backend/img_store/。迁移数据库优先使用 SQLite backup 得到一致性快照，再停写并完成图片及密钥迁移，不把运行中的单个 db 文件复制当成完整备份。

分割图接口目前只要求登录并校验文件名，未检查图像所属用户。部署容量、GPU 和临床准确度需要另行验证，演示语料与 AI 生成样本不能作为临床验收依据。
