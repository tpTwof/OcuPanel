# backend — FastAPI 服务

OcuPanel 的后端：影像分析（SwinV2 分类 + SegFormer 分割）、证据检索、六专科并发生成、
Director 综合、引用校验、PDF 导出，同时托管前端构建产物。项目整体介绍与使用说明见
[根目录 README](../README.md)。

```bash
cd backend
../.venv/Scripts/python.exe main.py        # Windows
../.venv/bin/python main.py                # Linux / macOS
```

---

## 主链路

`api/report.py:generate_content` 是入口，对应下图：

<p align="center">
  <img src="../docs/diagrams/pipeline.svg" alt="OcuPanel 主链路：眼底图上传 → 影像分析 → 证据检索 → 六专科并发 → Director 综合" width="720">
</p>

1. **视觉预处理** — SwinV2 给出青光眼概率 *p*，分箱为「无青光眼 / 可能 / 较可能 / 检测到青光眼」；
   SegFormer 给出视杯与视盘掩码 → 杯盘比（CDR）。
2. **核心提示词** — 用自然语言概括 *p* 与 CDR，可附加临床医生备注。
3. **证据检索** — 本地检索知识语料，得到带出处的证据包（见下文「知识检索」）。
4. **角色化子报告** — 每个临床角色（眼科医生、验光师、药师等）拿到核心提示词 + 本专业的窄指令，
   撰写聚焦的子报告。
5. **Director 综合** — 另一个 LLM 实例合并全部子报告，消解轻微冲突，产出唯一一份报告。
6. **引用校验（第 7 个智能体）** — 逐句核对 `[n]` 是否真的支撑该句（见下文「引用校验」）。
7. **输出** — 正文、概率、CDR、证据包、校验结果返回客户端；可选渲染 PDF。

第六步既可能让流程回头（重生成），也可能让流程关门（拒答），所以没画进主链路。
六个专科互不依赖，用 `ThreadPoolExecutor` 并发——串行时整条链路要 8 分钟以上，
并发后约等于最慢的那一次。

## 模块职责

| 文件 | 职责 |
|---|---|
| `main.py` | 应用入口：路由挂载、CORS、静态托管、启动清理、RAG 门控自检 |
| `api/account.py` | 注册 / 登录 / 注销 / 当前用户 / LLM 配置 / 用量 |
| `api/chat.py` | 会话 CRUD 与问答 |
| `api/report.py` | 报告生成（JSON 与 PDF 两个入口）、取分割图 |
| `schemas/` | Pydantic 请求 / 响应模型 |
| `classifier/swinv2_classifier.py` | 青光眼概率推理 |
| `segmenter/segmenter.py` | 视杯 / 视盘分割、CDR 计算、掩膜叠加 |
| `report_generator.py` | 角色分派、Director 合成、PDF 渲染、临时目录管理 |
| `retrieval.py` | BM25 + 多语言向量 + RRF 融合、语言配额与门控、启动自检 |
| `verifier.py` | 引用校验：核查 → 打回重写 → 复核 → 拒答判定 |
| `storage.py` | SQLite 数据层与 Key 加密 |
| `auth.py` | 令牌签发 / 校验 / 注销 |
| `config.py` | 环境变量集中管理（不散落魔法值） |
| `paths.py` | `output/`、`img_store/` 路径解析 |
| `check_llm.py` | 命令行 LLM 连通性自检 |
| `knowledge/corpus/*.md` | 知识语料（**示例语料，正式使用需换权威指南**） |

---

## 数据层

没有引入 ORM，也没有额外的数据库服务，就是 `backend/medchat.db` 一个 SQLite 文件
（首次启动自动建表）。

| 表 | 内容 | 说明 |
|---|---|---|
| `users` | 用户名、密码哈希、显示名 | PBKDF2-HMAC-SHA256，600k 迭代，每用户随机盐 |
| `sessions` | 登录令牌 | 7 天 TTL，启动时清理过期项 |
| `llm_configs` | 每人的 Base URL / 模型 / **加密后的 API Key** | Fernet 对称加密，密钥是 `.env` 的 `MEDCHAT_SECRET_KEY` |
| `conversations` | 会话标题、创建 / 更新时间 | 按 `user_id` 隔离 |
| `messages` | 对话逐条记录 | 报告消息的 `meta` 里存分割图名、证据、校验结果 |
| `reports` | 报告留痕 | 便于查「这份报告是什么时候、用哪个模型生成的」 |

几个刻意的选择：

- **每个用户用自己的 Key。** 代码里不写死 key，也不回退到服务器的 `OPENAI_API_KEY`
  ——没配就返回 409，而不是偷偷用别人的额度。
- **Key 不在界面回显明文。** 只给 `sk-xxx...abcd` 形式的掩码，保存时留空表示沿用旧值。
- **越权统一返回 404。** 访问别人的会话返回「会话不存在」而不是 403，不泄露"这个 id 存在"。
  GET / PATCH / DELETE 三者的文案也必须一致；DELETE 要检查 `rowcount`，
  不能因为"删除幂等"就一律 200，否则越权尝试会伪装成成功。
- **`.gitignore` 已排除 `*.db`。** 这个文件含账户与密文 Key，不能进版本库。

> ⚠️ `MEDCHAT_SECRET_KEY` 丢了，所有用户已存的 Key 就解不开，只能重新填写。
> 首次启动会自动生成并写回 `.env`，请自行备份。

### 临时文件

每次请求在 `backend/output/` 下新建独占目录（`job_*` / `report_*` / `content_*`），
原始图、分割图、临时 jpg、PDF 全在里面，多个并发请求互不干扰：

- `generate-report-content`：请求结束立即删目录，只留 `img_store/<uuid>.jpg` 供前端取回；
- `generate-report`：PDF 随响应体发送完毕后再删目录（`BackgroundTask`）；
- 进程被强杀留下的目录，下次启动时自动清理（超过 30 分钟的删除）。

`img_store/` 只写不清理（历史报告的分割图要长期可访问），会缓慢增长。

### 单进程假设

服务按**单个 Uvicorn 进程**设计。数据层本身支持多进程（SQLite WAL），但每个 worker
都会独立加载一遍 torch 与模型，内存占用线性叠加，小内存机器会直接 OOM。
不要加 `--workers N`。

---

## API

除注册 / 登录外，**所有接口都要求 `Authorization: Bearer <token>`**，未带或失效统一返回 `401`。

### 账户

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/account/register` | 注册并直接登录，返回 `{user, token}` |
| POST | `/api/account/login` | 登录；用户名或密码错都只回「用户名或密码错误」，防枚举 |
| POST | `/api/account/logout` | 注销当前令牌 |
| GET | `/api/account/me` | 当前用户 + 已配置的 LLM（Key 为掩码） |
| GET | `/api/account/llm-presets` | 内置服务商预设与服务器默认值 |
| PUT | `/api/account/llm` | 保存配置；`api_key` 留空表示沿用已存的 |
| POST | `/api/account/llm/test` | 测试连通，**不落库** |
| DELETE | `/api/account/llm` | 清除配置 |
| GET | `/api/account/usage` | 对话数 / 报告数 / 被拒答次数 |

### 会话与问答

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/chat/conversations` | 会话列表（只含自己的） |
| POST | `/api/chat/conversations` | 新建会话 |
| GET | `/api/chat/conversations/{id}` | 会话详情 + 全部消息 |
| PATCH | `/api/chat/conversations/{id}` | 重命名 |
| DELETE | `/api/chat/conversations/{id}` | 删除（连带消息） |
| POST | `/api/chat/conversations/{id}/messages` | 发消息，返回助手回复 |

### 报告

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/generate-report/` | 上传图像 + 备注，直接返回 PDF（校验未通过返回 `422`） |
| POST | `/api/generate-report-content/` | 上传图像 + 备注，返回 JSON |
| GET | `/api/get-report-image/{img_name}` | 取回叠加了分割掩膜的眼底图（文件名白名单校验，防路径穿越） |

两个报告接口的公共表单字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | File | 眼底图像（`.jpg` / `.jpeg` / `.png`） |
| `note` | Text | 临床备注（可选） |
| `conversation_id` | Text | 关联到哪个会话（可选，缺省则新建） |

未配置 LLM 时这两个接口返回 `409`，提示去个人设置填写。
`generate-report-content` 的响应字段：`summary` / `cup_to_disc_ratio` / `img_name` /
`evidence` / `verification` / `rejected` / `report_id`。

接口文档：`/docs`（Swagger UI）、`/redoc`（ReDoc）。

示例：

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/account/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"doctor01","password":"pass1234"}' | jq -r .token)

curl -X POST http://127.0.0.1:8000/api/generate-report/ \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@fundus.jpg" \
  -F "note=IOP 24 mmHg OU" \
  -o diagnostic_report.pdf
```

> 报告接口是**同步长请求**（1–5 分钟）。放在 Nginx 后面时 `proxy_read_timeout`
> 必须放大，默认 60s 会在模型还在生成时切断连接。见 [`docs/DEPLOY.md`](../docs/DEPLOY.md)。

---

## 知识检索（证据包）

报告不只靠模型参数。每次生成前会做一次本地检索，把带出处的指南片段注入提示词：

```
病历 + 影像结论 → 各角色用自己的专业关键词检索 → 证据包（编号 + 出处）
                 → 注入提示词（要求句末标注 [n]）→ 报告正文带引用
                 → PDF 末尾附「参考资料」→ 前端展示证据卡片
```

<p align="center">
  <img src="../docs/diagrams/rag-hybrid.svg" alt="混合检索：BM25 与多语言向量双路召回，RRF 按名次融合，经每源上限、语言配额、查询门控过滤后输出证据包" width="720">
</p>

- **实现**：`retrieval.py`，BM25（中文 2-gram）+ 多语言向量 + RRF 融合；语料按「小节 → 段落」两级切分。
- **按角色差异化**：`report_generator.ROLE_QUERY_HINTS` 给药师「禁忌 / 相互作用」、
  给技师「眼压测量 / 视野检查」等关键词加权，避免六个角色拿到同一批证据。
- **全局编号**：一条资料在所有角色提示词与最终报告里编号一致，Director 汇总不会串号。
- **开关**：`RAG_ENABLED=0` 退回纯模型生成，便于 A/B 对比——但**没有证据包时引用校验会把结论判为无据**，
  所以关掉 RAG 等于关掉「可追溯」这个卖点，只适合做对比实验。

### 中英语料混存（`RAG_MODE`）

语料可中英混排，但**词面检索救不了跨语言**：中文查询在英文块里没有任何 token，实测零命中；
只能靠缩写（OCT/RNFL）和数字漏网，而数字还会造成 1.0 的假命中。所以默认走多语言向量：

| 模式 | 中文查询 → 英文块 | 说明 |
|---|---|---|
| `bm25` | 永不命中 | 零依赖，只适合同一语料 |
| `vector` | 命中（余弦 0.82–0.84） | `intfloat/multilingual-e5-small`，AutoModel + mean pooling，不装 sentence-transformers |
| `hybrid`（默认） | 命中，且中文块排前 | 两路各宽召回，RRF 排名融合 |

三个容易被忽略的细节：

1. **光有语义对齐不够，还要语言配额**（`RAG_LANG_QUOTA`）。中文块的相似度天然更高
   （0.93 vs 跨语言 0.85），top-4 会被中文块占满，英文块一个都排不上。配额给每种语言留
   `k/语言数` 个位置。
2. **配额必须门控**（`RAG_LANG_GATE=0.89`）。否则「门诊预约流程」这种无关查询也会被硬塞两条英文块。
   不能逐项卡阈值——跨语言相关块（0.82–0.84）比同语言无关块（0.867）还低；看「最佳命中」才干净：
   相关查询 ≥0.918，无关查询 ≤0.867。
3. **每源最多 2 条**（`_diversify`）。同一文档的相邻段落本来就重复，随访主题 6 段全在 0.91–0.94，
   会把名额吃光。

融合用 RRF（`score = Σ 1/(60+rank)`）而不是分数加权：中英 BM25 的分数量纲不可比，
向量分又是另一种，比名次最省事。

**关于 `score`**：hybrid 下它是融合相对分，不是余弦，直接当「相关度」显示会误导
（实测某条真实余弦 0.81 却显示 0.37）。所以前端证据卡片只标命中方式（`词面` / `语义` / `混合`），
三个原始分（`bm25` / `vector` / `rrf`）放在展开后的明细里。

**门控阈值是标定值，会让服务自己复核**：`0.89` 是在「当前语料 + e5-small」上量的
（相关 0.918–0.939，无关 0.852–0.867，取两组的中性点）。换 `RAG_VECTOR_MODEL` 或语料大改后
分布会漂移，否则门控要么常关（跨语言召回失效）、要么常开（无关查询被塞英文块）。

因此启动时会跑 `retrieval.selfcheck_gate()`：拿一条相关探针（语料首块的标题 + 小节，
跟着语料自适应）和一条跨领域无关探针（挂号 / 停车费）各取最佳余弦，检查 gate 是否被夹在
两者之间、余量够不够。余量判定不能用固定绝对值——探针间隔本身只有 0.03 量级时要求 0.05 余量
等于永远判不过；实际取 `min(0.05, 间隔/4)`，即 gate 只需落在两簇中间那一半区间。
失配或余量不足都写日志告警并给出建议值，**不自动改配置、也不挡启动**
（自检跑在后台线程，顺带预热向量模型，首个请求不用再等加载）。

实测三种阈值下的行为：`0.89` → 通过；`0.95` → 判「跨语言配额永不触发」；
`0.85` → 判「无关查询也会被塞英文块」。

升级路径：区分度不够时可换 `intfloat/multilingual-e5-base`（需 `pip install protobuf`）
或 `bge-m3`，改 `RAG_VECTOR_MODEL` 即可。

`evidence` 字段结构：

```json
[{ "index": 1, "id": "glaucoma-diagnosis#3-1", "title": "青光眼诊断要点",
   "section": "分型与鉴别", "source": "glaucoma-diagnosis.md", "score": 1.0, "text": "…" }]
```

实测（样本病例）：命中 8 条证据，报告正文出现 16 处引用标记
（如「双眼均高于正常参考上限 21 mmHg [4]」），PDF 从 4 页增至 5 页并多出「参考资料」章节。

---

## 引用校验（第 7 个智能体）

挂一个 `[3]` 只说明「引用了资料」，**不说明 `[3]` 支持这句话**。所以 Director 写完后再过一道闸门：

<p align="center">
  <img src="../docs/diagrams/citation-verifier.svg" alt="第 7 个智能体：逐句核查 → 删除或改写 → 复核；合格则通过，不合格则整篇重生成并重跑，轮次用尽则拒答且不交报告" width="720">
</p>

三个出口只有一个是「通过」。重生成走的是回到核查的循环，不是重新走一遍六个专科
——影像结论和证据包都没变，变的只是写法。

- **拒答不是失败兜底**：`status=rejected` 时**不返回报告、不生成 PDF**，只给出
  「无法生成有依据的诊断报告」和未通过的断言清单。宁可没有报告，也不给一份看起来对的报告。
  前端据此隐藏下载按钮，PDF 接口返回 422。
- **删除是正确处置**：没有依据的句子直接删，不设配额。删到正文不成文（低于 `VERIFY_MIN_CHARS`
  或原稿 40%）时不退回原文，而是触发整篇重生成。
- **重生成带禁止清单**：把上一版被判无依据的断言列给 Director，要求换写法而不是换个说法
  把同一结论写回来。
- **校验故障也不交稿**：校验调用本身出错时 `status=error`，同样不输出——未经核查的内容一律不放行。
- **判定四档**：`supported` / `partial`（多为模型自加「必须 / 一定 / 唯一」）/ `unsupported` / `uncited`。
- **不算问题**：本病例的影像所见与测量值（杯盘比 0.85、眼压 26 mmHg）本来就不需要外部出处，
  否则整篇会被标红。
- **唯一被拦下的改写**是「假覆盖」：语料明写「前列腺素类似物是首选一线用药」，模型却把该句
  改成「资料未涵盖」——那是把真实内容抹掉，方向反了（`verifier.is_false_dodge`）。
  判据有两条：中文 2-gram 覆盖率 ≥0.4，或语义相似度 ≥0.80（中英混排时词面判据恒为 0，
  只能靠后者，否则这道守卫会静默失效）。
- **开关**：`VERIFY_ENABLED=0` 关闭；`VERIFY_MAX_ROUNDS=2`（最多 2 轮改写 + 1 次重生成）；
  `VERIFY_MIN_CHARS=300`。实测正常病例增加 8–12 秒，走重生成约 +20 秒。

`verification` 字段结构：

```json
{ "status": "rewritten", "rounds": 2, "initial_issues": 5, "deleted": 2, "regenerated": false,
  "fixed": [{ "quote": "建议每 3 个月复查…唯一推荐方案 [2]。", "new": "", "citations": [] }],
  "remaining_issues": [] }
```

`status` 取值：`pass` / `rewritten` / `rejected`（拒答，无报告）/ `error`（校验故障，无报告）/
`disabled` / `skipped`（无证据包可校验）。

---

## 环境变量

`backend/.env`（模板见 `.env.example`）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `OPENAI_API_KEY` | 无 | 服务器默认 Key。留空则跳过 LLM 调用，视觉流水线仍可运行；用户自己的 Key 优先 |
| `OPENAI_MODEL` | `gpt-4.1` | 模型 ID，可换成任何 OpenAI 兼容模型（DeepSeek 用 `deepseek-flash`，旧的 `deepseek-chat` 已下线） |
| `OPENAI_BASE_URL` | 官方 OpenAI | 设为第三方 / 本地端点即可接入，如 `https://api.deepseek.com` |
| `MEDCHAT_SECRET_KEY` | 自动生成 | Fernet 密钥，加密用户 Key。**丢失即无法解密，务必备份** |
| `REPORT_LANGUAGE` | `zh` | 报告语言，`zh` / `en`；只影响 LLM 输出与 PDF 文案 |
| `REPORT_FONT_PATH` | 自动探测 | 中文 PDF 字体；按 `simhei.ttf` → `Deng.ttf` → `msyh.ttc` → `simsun.ttc` → Noto CJK → wqy 顺序找 |
| `LLM_TIMEOUT` | `120` | 单次 LLM 请求超时（秒） |
| `LLM_MAX_RETRIES` | `1` | LLM 请求失败重试次数 |
| `LLM_DISABLE_THINKING` | `1` | 对 DeepSeek 端点关闭 thinking，单请求从 ~15s 降到 ~2s；设 `0` 恢复 |
| `HOST` | `127.0.0.1` | 监听地址。生产环境保持回环，由 Nginx 反代 |
| `PORT` | `8000` | 监听端口 |
| `RELOAD` | `0` | 热重载。开发设 `1`；**改文件名 / 移目录时务必关掉**，reloader 中间态会 import 失败 |
| `CORS_ORIGINS` | `http://127.0.0.1:5500,http://localhost:5500` | 跨域白名单；单服务模式同源，不需要 |
| `FRONTEND_DIST` | `../frontend/dist` | 前端构建产物目录；不存在则进入纯 API 模式 |
| `HF_ENDPOINT` | 无 | HuggingFace 镜像，`huggingface.co` 不通时设 `https://hf-mirror.com` |
| `RAG_ENABLED` | `1` | 是否注入证据包 |
| `RAG_TOP_K` / `RAG_MIN_SCORE` | `4` / `0.35` | 召回数量 / 相对阈值 |
| `RAG_MODE` | `hybrid` | `bm25` / `vector` / `hybrid` |
| `RAG_VECTOR_MODEL` | `intfloat/multilingual-e5-small` | 向量模型 |
| `RAG_VECTOR_MIN_SCORE` | `0.78` | 向量路绝对阈值 |
| `RAG_RRF_K` | `60` | RRF 常数 |
| `RAG_LANG_QUOTA` / `RAG_LANG_GATE` | `1` / `0.89` | 语言配额开关 / 门控阈值（标定值，见上文） |
| `RAG_MAX_PER_SOURCE` | `2` | 单文档最多入选条数，`0` 不限 |
| `VERIFY_ENABLED` | `1` | 引用校验开关 |
| `VERIFY_MAX_ROUNDS` / `VERIFY_MIN_CHARS` | `2` / `300` | 改写轮数 / 不成文判定字数 |
| `EXPIRY_SECONDS` / `CLEANUP_INTERVAL` | `300` / `300` | 临时目录清理间隔 |

---

## 排查

**请求返回 500** — 先看运行 `main.py` 的终端，FastAPI 会把完整 traceback 打在那里。常见三种：

- 服务已经挂了（浏览器显示拒绝连接 / 502）→ 重新 `python main.py`；
- 刚改过文件名 / 目录名 → 关掉 `RELOAD` 再启动，reloader 的中间态会 import 失败；
- LLM 相关报错**不会**返回 500（会以 `Error: ...` 写进报告正文），所以 500 基本都出在影像或 PDF 环节。

**分类器 / 分割器首次推理卡很久** — 正在从 HuggingFace 拉权重
（`pamixsun/swinv2_tiny_for_glaucoma_classification`、
`pamixsun/segformer_for_optic_disc_cup_segmentation`）。
国内网络在 `.env` 加 `HF_ENDPOINT=https://hf-mirror.com`；生产环境建议提前手动下载预热。

**PDF 中文变方块 / 空白** — `REPORT_FONT_PATH` 没探测到中文字体，显式指向一个 ttf / ttc：

```env
REPORT_FONT_PATH=C:/Windows/Fonts/simhei.ttf
```

**生成一份报告要多久** — 默认配置约 40–50 秒（6 角色并发 + Director + PDF）。
把 `LLM_DISABLE_THINKING` 设为 `0` 会退回 3 分钟以上。校验走重生成时再加约 20 秒。

**只想跑 API 不跑页面** — 把 `FRONTEND_DIST` 指向不存在的目录，自动进入纯 API 模式。

---

## 已知问题

**两个视觉模型没有进程级缓存。** `segmenter/segmenter.py` 与
`classifier/swinv2_classifier.py` 在函数内部调用 `from_pretrained`，
每次生成报告都会重新读一遍权重（约 300MB，白等几秒），且**并发请求的内存会线性叠加**。
在小内存机器（2C2G）上两个请求同时进行就可能被 OOM Killer 杀掉，日志里不留痕迹。
缓解办法见 [`docs/DEPLOY.md`](../docs/DEPLOY.md) 的「只有 2 核 2G 怎么办」一节。
彻底解决需要把模型提成模块级单例（改动很小，但会动到上游代码，需评估后再做）。
