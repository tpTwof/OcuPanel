# 知识检索

`retrieval.py` 为 [corpus/](../../knowledge/corpus/) 下的文章、主图谱中的条款和独立指南建立同一份基础语料索引。问答可按会话选择图谱开关，启用后增加概念路径召回。后端通过 `RAG_MODE` 选择 BM25 关键词检索、向量检索或混合检索。默认 `hybrid` 使用 Reciprocal Rank Fusion 合并排名，再应用来源上限与语言配额等筛选规则。

- `service.py` 提供报告与眼科聊天使用的固定主题检索入口、图谱融合和证据格式化。
- `question_retrieval.py` 执行检索计划：按问题查询、覆盖判断、一次补检、预算与故障记录。报告 v2 流程使用它，入口受 `modules/report/generation.py` 编排。
- `metadata.py` 解释条款级材料类型、审核状态、主题与适用条件，并被检索、格式化和校验记录共用。
- `models.py` 定义证据相关的数据结构。
- 通过向量通道时，默认使用 `intfloat/multilingual-e5-small`，首次运行可能下载权重。配置 `RAG_MODE=bm25` 可单独调试关键词召回。

影像报告的固定主题入口由 `report_focus.py` 提供；这不是新增诊断。

- `REPORT_TOPICS` 把 `legacy` 流程必须回答的内容拆成四个方面（诊断评估、结构与功能判读、治疗与处置、随访），每方面单独检索，再用 `service.retrieve_report_evidence` 按轮次合并（先取各方面第 1 名，再取第 2 名）。单条长查询只会让诊断类条款占满结果：病例全文里反复出现的「眼压、视野、RNFL」会盖过主题词，实测「弓形暗点」条款排第 16、「目标眼压」排第 21，报告便写不出可引用的判读与治疗目标依据，校验只能判为无依据。
- `TOPIC_QUERIES` 为 v2 的七个问题主题（诊断、判读、检查、鉴别、处置、随访、教育）提供检索词。主题由病例的检索计划决定，不再预设每份报告都要覆盖全部主题；未登记主题回退到旧四方面检索词。
- `SOURCE_DISEASES` 登记来源的病种归属。登记为某一病种的来源只在该病种报告中入选，登记为空集的来源（白内障相关）任何病种都不入选，未登记的来源视为通用条款。条款级 `disease` 优先于来源登记，便于把适用范围逐步落到条款层面。
- BM25 对已经出现在病例中的病种词仍正确加权。检索分数、条款适用性和临床有效性仍分别核对，不因病种匹配就视为可以直接适用。

## 条款元数据

语料 JSON 兼容旧文件：没有下列字段时按「未登记」处理，不自动提升为已审核。新增或更新条款时建议显式登记。

| 层级 | 字段 | 说明 |
| --- | --- | --- |
| 来源 | `material_type` | `guideline` / `consensus` / `expert_consensus` / `systematic_review` / `case_report` / `patient_education` / `reference_text` |
| 来源 | `review_status` | `verified` / `pending` / `draft`；缺失为 unknown |
| 来源或条款 | `disease` | 字符串或列表；空表示沿用来源登记 |
| 条款 | `topic` | 七个问题主题之一；缺失时按小节名推断，仅用于覆盖统计 |
| 条款 | `applicability` | `population` / `region` / `care_stage` / `preconditions` / `exclusions` |
| 条款 | `chinese_summary` / `context` | 可选的中文摘要与必要上下文 |

`corpus.py` 在加载时校验这些字段并计算正文 `content_hash`；非法取值会使该文件被跳过并记录日志。检索结果带 `material_type`、`review_status`、`applicability_unknown` 与 `content_hash`，证据格式化会标注材料类型、审核状态和适用条件。

材料类型决定它能支撑哪类问题：`TOPIC_MATERIAL_TYPES` 要求诊疗主题使用指南、共识或综述，患者教育材料只能支撑通俗解释，草稿示例不参与 v2 的诊疗主题证据包。只有**明确矛盾**时才排除条款（人群、阶段或地区与检索筛选冲突）；条款写明的前提与例外、以及无法在筛选里核实的适用条件，记为 `applicability_unknown` 随证据保留，由证据格式化标为「未核实（不能默认满足）」，报告引用该条款时必须把前提写出来。采纳规则集中在 `metadata.clause_fit`，检索筛选与覆盖矩阵共用同一套判断，避免两处口径不一致。

`backend/tools/corpus_coverage.py` 按「病种 × 方面」生成[语料覆盖矩阵](../../../docs/语料覆盖矩阵.md)，并读取评估病例集标注对应问题。「可用于该方面」复用 `clause_fit`，按 v2 实际采纳规则统计，不能仅凭文件名或条数判断完整。

草稿语料（标题带「示例语料」的 `glaucoma-*.md`）参与检索，命中时带 `draft: true` 标记与 `review_status=draft`，不冒充权威原文。正式条款此前只覆盖诊断与分级，缺随访、目标眼压和视野判读；整体剔除这些文件会让全库只剩 2 条青光眼条款，报告因此无据可写。`legacy` 流程仍使用它们；v2 只把它们当作参考资料，不作为诊疗主题的依据。有正式条款替代的副本仍须退出索引（NEI 的 AMD 主题已由 `guidelines/nei-amd.json` 收录，故排除 `macular-degeneration-nei.md`）。

语料用于演示证据召回与引用。检索分数表示所用通道的相关性，医学判断需另行验证。更换语料或向量模型后，应重新检查阈值与启动自检。 [后端配置](../../README.md#配置) · [报告流程](../report/README.md)

图谱条款的来源和维护规则见 [图检索](#增加指南)。

知识库还收录了美国国家眼科研究所（NEI）的 34 个公众教育主题，覆盖视网膜与玻璃体疾病、眼表与眼睑疾病、儿童与遗传性眼病、屈光和双眼视功能等。可用病名、检查名或日常描述检索，例如“孩子拍照瞳孔发白”“睫毛根部结痂”。每条中文摘要保留原文章节、页面更新日期和美国公众教育适用范围，临床专家复核状态为待复核。这些主题扩充问答与报告的参考知识，影像模型支持的病种仍以项目 README 为准。 [NEI 眼病原文目录](https://www.nei.nih.gov/eye-health-information/eye-conditions-and-diseases)

## 增加指南

在 [guidelines](../../knowledge/corpus/guidelines/) 下按来源保存 JSON 文件。`corpus.py` 校验并读取正文与出处，基础检索直接索引这些条款。`concepts`、`relations` 和每条证据的 `anchors` 均可省略。增加图谱信息时，锚点引用概念 ID，关系引用概念对。概念 ID 在主图谱（[ophthalmology-graph.json](../../knowledge/corpus/ophthalmology-graph.json)）中已存在时不要重新定义，否则图谱加载会因概念重复而失败，此时只用 `anchors` 引用既有 ID。条款 ID 必须全库唯一，保持稳定。相同 ID 的条款可同时被多个通道召回，最终合并为一份引用。新增来源需在 `report_focus.SOURCE_DISEASES` 登记病种归属，或在条款级写 `disease`，否则会被当作通用条款进入所有病种报告。

最小基础指南示例，可保存为新的 JSON 文件。

```json
{
  "schema_version": 1,
  "sources": {
    "source-id": {
      "title": "指南标题",
      "version": "版本或发布日期",
      "jurisdiction": "CN",
      "url": "https://example.org/original",
      "material_type": "guideline",
      "review_status": "pending",
      "disease": ["glaucoma"]
    }
  },
  "evidence": [{
    "id": "source-id-section-1",
    "source": "source-id",
    "section": "第一章第 1 条",
    "scope": "适用地区、人群和临床情境",
    "topic": "treatment",
    "applicability": {
      "population": "已确诊开角型青光眼患者",
      "care_stage": "treatment",
      "preconditions": "已建立结构与功能基线"
    },
    "text": "经原文核对的条款摘要"
  }]
}
```

示例地址需替换为真实原文。更新条款时核对原文并保留出处。现有文件是针对所列章节的研究用摘要，临床专家复核状态为待复核。图谱关系错误会使图谱加载失败，正文仍进入基础检索；正文或出处不合法时跳过该文件并记录日志。全库重复条款 ID 会阻止索引初始化，避免引用发生歧义。

重启后端后，新条款会随语料进入 BM25 和启用的 E5 索引；开启图谱时，有锚点的条款还可以通过概念路径召回。无锚点的条款继续参与文本检索。两种模式使用相同的条款集合，已收录正式条款时排除对应演示材料。

BM25 使用内存倒排索引。E5 按需加载模型，按 32 条分批编码。SQLite 缓存默认保存在 `knowledge/.cache/vectors.db`，按模型名、模型实际提交版本（本地模型使用配置版本）、编码方法和输入正文的内容哈希复用向量。修改条款只重算变化的输入，删除条款后下次启动会从当前索引移除；旧缓存记录保留供复用。查询仍在内存中计算向量相似度。

`RAG_VECTOR_CACHE_PATH` 可指定缓存文件的绝对路径，设置为空字符串可禁用缓存。缓存读写失败时使用本轮内存编码。模型权重及查询向量仍需模型加载。`RAG_VECTOR_REVISION` 默认 `main`，可固定为模型提交版本；替换本地模型权重时应更改这个值。语料更新后需重启后端，当前没有自动热更新。

按问题检索时，条款登记或章节推断的主题缺失、错配或适用条件未核实的命中记录在排除清单中，并触发受预算限制的补检。自由文本前提和排除条件目前保守地记为未核实。
