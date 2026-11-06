# OcuPanel

> 普通聊天与眼科助手 · 影像分析、多角色报告与引用校验

默认使用普通聊天；切换为眼科助手后可进行眼科问答。提交眼底照片和临床记录会运行视觉分析、
专科 Agents、Director 综合和引用校验，结果作为回复进入当前会话，之后可继续追问。
引用校验针对外部知识陈述，不能证明影像测量或临床结论一定正确；当前影像模型仅支持青光眼相关分析。

基于 Philip Liu 等人 *Multi-Agent Diagnosis using Multimodal Large Language Models*
（MIPR 2025）改造，本项目额外实现了多用户账号体系、证据检索与引用校验。

---

## 快速开始

### 前置要求

- **Python 3.13**：当前开发与验证基线；本机项目 `.venv` 实测为 **3.13.3**。系统默认 `python` 为 3.14.4，启动时请明确使用项目虚拟环境。
- 前端本机验证环境：**Node 24.15.0 / npm 11.12.1**（React 18、Vite 6）。其他运行时版本尚未完成整体验证。
- 能访问 HuggingFace（国内需镜像，见下方「常用配置」）
- 影像分析所需内存取决于模型、图片尺寸与并发；部署前需在目标机器实测，见部署文档

### 模式一：单服务（推荐）

FastAPI 同时提供 API 和页面，只需一条命令。

```bash
# 1. 后端依赖（torch 先装 CPU 版，否则会拖进 2GB+ 的 CUDA 库）
cd backend
py -3.13 -m venv ../.venv     # 明确选择 Python 3.13；已有环境则跳过
../.venv/Scripts/python.exe -m pip install --upgrade pip
../.venv/Scripts/python.exe -m pip install torch==2.7.0 --index-url https://download.pytorch.org/whl/cpu
../.venv/Scripts/python.exe -m pip install -r requirements.txt

# 2. 前端构建
cd ../frontend
npm install
npm run build

# 3. 配置并启动
cd ../backend
cp .env.example .env          # 首次安装才复制，已有 .env 不要覆盖
../.venv/Scripts/python.exe main.py
```

浏览器打开 <http://127.0.0.1:8000> —— 页面和 API 都在这里。

> 若无 `py -3.13`，使用 Python 3.13 可执行文件的完整路径创建环境。Linux / macOS 使用 `python3.13 -m venv ../.venv`，并把虚拟环境路径换成 `../.venv/bin/python`。其他 Python 版本没有完成全套依赖与运行验证，不再笼统声明“Python 3.10+”。
>
> PowerShell 可在根目录用 `.\.venv\Scripts\python.exe --version` 确认项目版本；不要只检查系统 `python --version`。

### 模式二：前后端分离（开发用）

前端用 Vite dev server（热更新），`/api` 自动代理到后端，不需要任何配置。

```bash
# 终端 1：后端
cd backend && ../.venv/Scripts/python.exe main.py

# 终端 2：前端
cd frontend && npm run dev
```

浏览器打开 <http://127.0.0.1:5500>。若端口被占用，Vite 会尝试其他端口，以终端输出为准。

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

首次打开是登录页，同一张卡片可以切到注册。用户名 + 密码（至少 6 位）。
注册成功直接进入系统，不需要再登录一次。

会话和消息查询按账户隔离。分割图接口要求登录，但目前只校验文件名，尚未额外核对图片所属用户，不能将其描述为完整的图片权限隔离。

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
- 分析后自动切为眼科助手，可基于报告继续追问；模型仅收到受预算限制的上下文，不是完整永久记忆。

### 4. 生成报告

1. 左栏点「眼科分析」，或在眼科助手形态选择「影像与报告分析」；
2. 上传眼底照片（`.jpg` / `.jpeg` / `.png`，支持拖拽）+ 填写临床记录；
3. 点「生成报告」，等待推理、检索、LLM 生成与校验完成；耗时取决于硬件、模型服务和修订次数。

结果会追加到当前对话里，包含报告正文、杯盘比、分割图、证据包和校验结果，可下载 PDF。

**如果报告被拒答**，说明校验发现有些结论找不到出处。此时**不会生成 PDF**，
界面会展示拒答原因和可用的未通过断言；也可能因无证据或校验故障拒答。补充临床信息不能保证下次通过，应结合返回原因排查。

### 5. 退出登录

侧栏底部的退出图标，或「个人设置」里的按钮。退出只清除本机登录态，
**服务端的对话与报告一条都不动**，重新登录后还在。

---

## 常用配置

改 `backend/.env`，配置说明见 [`backend/README.md`](backend/README.md#配置)。

| 想改什么 | 加这一行 |
|---|---|
| 国内下载模型慢 / 失败 | `HF_ENDPOINT=https://hf-mirror.com` |
| 设置默认端点与模型名称 | `OPENAI_BASE_URL=...` + `OPENAI_MODEL=...`；业务请求仍要求用户在个人设置中保存自己的 Key |
| PDF 中文变方块 | `REPORT_FONT_PATH=C:/Windows/Fonts/simhei.ttf` |
| 换端口 | `PORT=8001`（前端再配 `VITE_API_BASE_URL=http://127.0.0.1:8001`） |

---

## 文档导航

| 想看什么 | 去哪 |
|---|---|
| 整体架构、方法流程、设计取舍 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 文档状态与维护范围 | [`docs/README.md`](docs/README.md) |
| 部署到云服务器与容量验证 | [`docs/DEPLOY.md`](docs/DEPLOY.md) |
| API 端点、数据表、检索与校验细节 | [`backend/README.md`](backend/README.md) |
| 前端组件、交互约定、调试抽屉 | [`frontend/README.md`](frontend/README.md) |
| 测试样本 | [`samples/`](samples/) |

接口文档在服务启动后可访问 `/docs`（Swagger UI）与 `/redoc`。

---

## 常见问题

**Q：点了注册 / 登录，只显示 `Internal Server Error`？**
先确认后端已启动。模式二下页面在 5500、接口转发到 8000；代理失败与后端自身异常都可能导致请求失败。验证：

```bash
curl -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/account/llm-presets
```

`200` 说明后端在跑（去看它的 traceback）；连接失败就是后端没起。

**Q：第一次生成报告卡很久？**
可能正在下载视觉或检索模型。视觉权重首次分析加载，默认向量检索还会在启动后的后台自检中加载；下载量取决于缓存和模型配置。可设置 `HF_ENDPOINT` 或提前下载，缓存目录可用 `HF_HOME` 指定。

**Q：导出的 PDF 中文变成方块 / 空白？**
字体没探测到，按上面「常用配置」显式指定一个 ttf。

**Q：改了前端代码，页面没变化？**
单服务模式下页面来自构建产物，改完要重新 `npm run build`；想热更新就用 `npm run dev`。

**Q：生成一份报告要多久？**
实际耗时取决于硬件、服务商、工具调用和引用修订次数，不能保证固定时长。正文生成不渲染 PDF，点击下载 PDF 会再次执行生成流程。

**Q：报告提示「无法生成有依据的诊断报告」？**
引用校验没通过。补充临床信息（眼压、视野、用药史等）后重试，或换个说法描述。
不要为了让它出报告而关掉校验——那等于把「可追溯」这个前提去掉了。

**Q：端口被占用？**
后端设 `PORT=8001`，前端设 `VITE_API_BASE_URL=http://127.0.0.1:8001`。

更多排查、任务目录和模型缓存说明见
[`backend/README.md`](backend/README.md#验证与排查) 与 [`frontend/README.md`](frontend/README.md#已知坑)。

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

有问题或合作意向请提 Issue，或联系 <tptwo06@gmail.com>。

## 当前实现说明

当前知识库的四份 Markdown 是检索演示语料，并非已校对的权威指南全文。眼底样本带 AI 生成水印，用于功能验证，不能充当临床模型准确度基准。

当前按业务分层：user/chat/report 各自维护 api.py、service.py 和 models.py，vision/agents/knowledge/llm 分别维护分析、推理、检索和模型调用。详见 [架构说明](docs/ARCHITECTURE.md) 和 [数据对象规范](docs/DATA_MODELS.md)。

当前影像模型只输出青光眼类别概率、视杯视盘掩膜和面积等效 CDR，不提供疾病分期。视觉模型有进程级设备缓存与推理锁，支持可用的 CUDA/MPS/CPU；具体运行资源需在部署环境测量。专科 Agent 支持受限工具循环，Director 综合，Verifier 负责引用修订与复核。旧视觉管线切换配置已移除，详见 [后端说明](backend/README.md)。聊天通过 LLMClient 独立调用；眼科分析使用报告生成流程。

## 两种会话形态

初次进入与新建会话默认为普通聊天，可在欢迎页或聊天页切换为眼科助手。模式按会话保存，重新打开会话会恢复。普通聊天不注入眼科系统提示词；眼科助手使用 chat/prompts.py 的业务指令。

侧栏“眼科分析”是独立入口，眼科助手聊天页也提供“影像与报告分析”。上传图片与医疗报告/临床记录并提交后，进入当前聊天，自动切为眼科助手，显示生成状态和报告回复，随后可继续追问。未提交分析时只切换形态，不执行视觉模型、Agents 或产生报告费用。切回普通聊天保留已有消息。

后端的 PATCH /api/chat/conversations/{id}/mode 负责持久化形态；旧数据库在启动时迁移，旧报告会话保留眼科助手语义。详细规则见 [会话说明](backend/chat/README.md)。llm/ 不再包含眼科提示词，分析 Agent 与聊天各自管理指令。

## 聊天上下文限制

默认最多携带 20 条历史消息，系统指令、当前问题与选中历史共用 20,000 字符预算；眼科形态最多固定最近一份报告的 6,000 字符（还受剩余预算一半的限制），长报告会标记节选。聊天回复上限为 2,048 token。字符预算不是精确 token 数，较早内容可能不再进入本次请求。

这些是开发阶段的成本与长度控制，不是经过临床验证的长期病例记忆策略。完整记录仍在数据库中，当前没有跨会话记忆。配置见 [会话上下文说明](backend/chat/README.md#聊天上下文与回复预算)。

## 离线验证

从项目根目录执行，测试使用模拟 LLM，不使用账户的真实 Key：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests
```

当前回归覆盖会话形态与窗口、报告接口、受限工具、引用修订、视觉数值逻辑及 TypedDict schema 兼容。真实模型样本验证记录见 [vision/README.md](backend/vision/README.md)，不代替临床准确度、GPU 或生产容量验证。界面“测试连通”和 `python -m llm.check` 则会调用真实服务，可能产生费用。
