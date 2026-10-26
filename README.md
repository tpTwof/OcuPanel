# OcuPanel

> 多智能体眼科报告系统 · 每个结论可追溯，无据即拒答

上传一张眼底照片和一段临床记录，得到一份由六个临床角色分工撰写、再由 Director 智能体综合、
并逐句核对过引用的青光眼诊断报告。结论背后要么有指南出处，要么这句话不会出现在报告里。

基于 Philip Liu 等人 *Multi-Agent Diagnosis using Multimodal Large Language Models*
（MIPR 2025）改造，本项目额外实现了多用户账号体系、证据检索与引用校验。

---

## 快速开始

### 前置要求

- Python 3.10+、Node 18+
- 能访问 HuggingFace（国内需镜像，见下方「常用配置」）
- 约 2GB 内存空闲（一次报告的内存峰值约 1.3GB）

### 模式一：单服务（推荐）

FastAPI 同时提供 API 和页面，只需一条命令。

```bash
# 1. 后端依赖（torch 先装 CPU 版，否则会拖进 2GB+ 的 CUDA 库）
cd backend
python -m venv ../.venv
../.venv/Scripts/python.exe -m pip install --upgrade pip
../.venv/Scripts/python.exe -m pip install torch==2.7.0 --index-url https://download.pytorch.org/whl/cpu
../.venv/Scripts/python.exe -m pip install -r requirements.txt

# 2. 前端构建
cd ../frontend
npm install
npm run build

# 3. 配置并启动
cd ../backend
cp .env.example .env          # 服务器默认值可留空，用户自己在界面填 Key
../.venv/Scripts/python.exe main.py
```

浏览器打开 <http://127.0.0.1:8000> —— 页面和 API 都在这里。

> Linux / macOS 把 `../.venv/Scripts/python.exe` 换成 `../.venv/bin/python` 即可。

### 模式二：前后端分离（开发用）

前端用 Vite dev server（热更新），`/api` 自动代理到后端，不需要任何配置。

```bash
# 终端 1：后端
cd backend && ../.venv/Scripts/python.exe main.py

# 终端 2：前端
cd frontend && npm run dev
```

浏览器打开 <http://127.0.0.1:5500>。

> ⚠️ **两个终端都要开着。** 只起前端时页面能正常打开（纯静态），
> 但一提交表单就会报 `Internal Server Error`——Vite 代理找不到后端，直接回了 500 空响应。

### 两种模式对比

| | 单服务 | 前后端分离 |
|---|---|---|
| 访问地址 | http://127.0.0.1:8000 | http://127.0.0.1:5500 |
| 需要几个进程 | 1 | 2 |
| 前端热更新 | ❌（改完要 `npm run build`） | ✅ |
| 适用场景 | 演示、部署、给他人使用 | 日常开发 |

`frontend/dist` 不存在时，后端自动降级为纯 API 模式并打印提示，不会报错。

---

## 使用说明

### 1. 注册 / 登录

首次打开是登录页，同一张卡片可以切到注册。用户名 + 密码（至少 8 位）。
注册成功直接进入系统，不需要再登录一次。

多个账号之间**数据完全隔离**：每个人只能看到自己的会话与报告，互不可见。

### 2. 配置自己的 LLM（第一次必做）

点左下角用户名进「个人设置」：

1. 从预设里选服务商（DeepSeek / OpenAI / Moonshot / 阿里云百炼），或手动填接口地址与模型名；
2. 粘贴你自己的 API Key；
3. 点「测试连通」先验证——通了再点保存。

> 服务端**不提供公共 Key**。没配置时点生成报告会提示去设置页填写，不会偷偷用别人的额度。
> Key 在服务端加密存储，界面只显示 `sk-xxx...abcd` 这样的掩码。

### 3. 对话问答

登录后是欢迎页，点建议卡可以直接提问，也可以点左栏「新建对话」自己输入。

- 每条首消息会自动给会话起名；
- 记录存在服务端，换设备登录、重启服务都还在；
- 报告生成后也可以直接接着追问，报告正文本身就是上下文。

### 4. 生成报告

1. 左栏点「生成报告」；
2. 上传眼底照片（`.jpg` / `.jpeg` / `.png`，支持拖拽）+ 填写临床记录；
3. 点「生成报告」，等 40 秒到几分钟（取决于服务商速度）。

结果会追加到当前对话里，包含报告正文、杯盘比、分割图、证据包和校验结果，可下载 PDF。

**如果报告被拒答**，说明校验发现有些结论找不到出处。此时**不会生成 PDF**，
界面会列出哪些句子没通过——这是设计上的保护，不是故障。补充一点临床信息重新生成即可。

### 5. 退出登录

侧栏底部的退出图标，或「个人设置」里的按钮。退出只清除本机登录态，
**服务端的对话与报告一条都不动**，重新登录后还在。

---

## 常用配置

改 `backend/.env`，全部变量见 [`backend/README.md`](backend/README.md#环境变量)。

| 想改什么 | 加这一行 |
|---|---|
| 国内下载模型慢 / 失败 | `HF_ENDPOINT=https://hf-mirror.com` |
| 用 DeepSeek | `OPENAI_BASE_URL=https://api.deepseek.com` + `OPENAI_MODEL=deepseek-flash` |
| PDF 中文变方块 | `REPORT_FONT_PATH=C:/Windows/Fonts/simhei.ttf` |
| 换端口 | `PORT=8001`（前端再配 `VITE_API_BASE_URL=http://127.0.0.1:8001`） |

---

## 文档导航

| 想看什么 | 去哪 |
|---|---|
| 整体架构、方法流程、设计取舍 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 部署到云服务器（含 2C2G 调优） | [`docs/DEPLOY.md`](docs/DEPLOY.md) |
| API 端点、数据表、检索与校验细节 | [`backend/README.md`](backend/README.md) |
| 前端组件、交互约定、调试抽屉 | [`frontend/README.md`](frontend/README.md) |
| 测试样本 | [`samples/`](samples/) |

接口文档在服务启动后可访问 `/docs`（Swagger UI）与 `/redoc`。

---

## 常见问题

**Q：点了注册 / 登录，只显示 `Internal Server Error`？**
后端没启动。模式二下页面在 5500、接口要转发到 8000，只起前端时任何提交都会失败。验证：

```bash
curl -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/account/llm-presets
```

`200` 说明后端在跑（去看它的 traceback）；连接失败就是后端没起。

**Q：第一次生成报告卡很久？**
正在从 HuggingFace 下载模型权重（约 700MB）。加 `HF_ENDPOINT=https://hf-mirror.com` 后重启。

**Q：导出的 PDF 中文变成方块 / 空白？**
字体没探测到，按上面「常用配置」显式指定一个 ttf。

**Q：改了前端代码，页面没变化？**
单服务模式下页面来自构建产物，改完要重新 `npm run build`；想热更新就用 `npm run dev`。

**Q：生成一份报告要多久？**
默认配置约 40–50 秒（六个角色并发 + Director + PDF）。走引用校验的重生成再加约 20 秒。

**Q：报告提示「无法生成有依据的诊断报告」？**
引用校验没通过。补充临床信息（眼压、视野、用药史等）后重试，或换个说法描述。
不要为了让它出报告而关掉校验——那等于把「可追溯」这个前提去掉了。

**Q：端口被占用？**
后端设 `PORT=8001`，前端设 `VITE_API_BASE_URL=http://127.0.0.1:8001`。

更多排查（500 的三种成因、并发目录隔离、模型缓存问题）见
[`backend/README.md`](backend/README.md#排查) 与 [`frontend/README.md`](frontend/README.md#已知坑)。

---

## 引用

```bibtex
@inproceedings{liu2025multiagent,
  title     = {Multi-Agent Diagnosis using Multimodal Large Language Models},
  author    = {Liu, Philip and Bansal, Sparsh and Dinh, Jimmy and Pawar, Aditya and Satishkumar, Ramani and Gupta, Neeraj and Wang, Xin and Hu, Shu},
  booktitle = {IEEE Int'l Conf. on Multimedia Information Processing and Retrieval (MIPR)},
  year      = {2025}
}
```

## 许可

MIT License，详见 `LICENSE`。

## 联系方式

有问题或合作意向请提 Issue，或联系 m2lab.purdue@gmail.com。
