# 眼科诊疗 Copilot 文献、数据与测试准备

核对日期为 2026-11-16。首轮范围为彩色眼底照片（CFP）、糖尿病视网膜病变（DR）、糖尿病黄斑水肿（DME）相关证据问答，以及青光眼辅助筛查。OcuPanel 已有青光眼分类、视盘和视杯分割与专科并行报告。首批条款已接入可选的图文档混合检索，DR 视觉任务和病例驱动的智能体协作仍是研究设计。见[GraphRAG 启用方式](../../backend/README.md#graphrag)和[报告智能体说明](../../backend/agents/README.md)。

## 1. 视觉模型与图文对齐

| 路线 | 模型与对齐方式 | 在本课题中验证的能力 |
| --- | --- | --- |
| 视觉自监督 | **RETFound**（Nature，2023）以遮挡图像块重建（MAE）学习视觉表示，论文分别训练 CFP 与 OCT 权重，共用约 164 万张视网膜图像。 | 在 CFP 权重上训练任务头，测 DR 五级分级或青光眼二分类。原模型提供视觉特征，配合任务头产生结构化输出供检索与问答使用。[论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC10550819/) |
| 图文对比学习 | **FLAIR** 把眼底标签扩写为专家术语和形态描述，与照片做对比学习。**RetiZero** 将冻结的 RETFound 视觉编码器与文本侧对齐，论文使用 341,896 对眼底图文。 | 用固定中英文术语提示测试零样本分类、图像到短语检索。分数反映匹配程度，若要解释为风险概率须单独评估校准。[FLAIR 论文](https://www.sciencedirect.com/science/article/pii/S1361841524002822) · [FLAIR 代码和权重入口](https://github.com/jusiro/FLAIR) · [RetiZero 论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC12214743/) |
| 跨检查与报告对齐 | **EyeCLIP** 使用约 278 万张、覆盖 11 种模态的眼科图像，结合图像重建、同人跨检查对比学习以及图像和层级报告关键词的对比学习。 | 为后续 CFP、OCT 联合研究提供方法参考。按输入模态报告结果，区分 CFP 单输入与加入 OCT 后的收益。[EyeCLIP 论文](https://www.nature.com/articles/s41746-025-01772-2) |
| 图像投影与指令微调 | **LLaVA-Med** 原论文先用约 60 万对 PubMed Central 图文调视觉到语言的投影层，再用基于图注生成的指令调语言模型与投影层，视觉编码器在两阶段均冻结。v1.5 发布版的语言骨干为 Mistral-7B-Instruct v0.2。 | 作为通用医学 VQA 对照。原论文的三项 VQA 基准为 VQA-RAD、SLAKE 和 PathVQA，眼底问答表现需单独测量。[NeurIPS 论文](https://proceedings.neurips.cc/paper_files/paper/2023/file/5abcdf8ecdcacba028c6662789194572-Paper-Datasets_and_Benchmarks.pdf) · [微软模型卡](https://ai.azure.com/catalog/models/microsoft-llava-med-v1.5-mistral-7b?task=image-text-to-text) · [研究用途说明](https://github.com/microsoft/LLaVA-Med) |
| 眼科生成式问答 | **VisionUnite** 报告使用 124 万图文对预训练，并以 MMFundus 图文和模拟医患对话微调。 | 作为眼科问答候选。对中英文输出分别检查图像事实错误、病灶位置、缺失信息提示和引用支持。[作者论文](https://arxiv.org/abs/2408.02865) |
| 图像区域定位 | **EVLF-FM**（Nature Medicine，2026）结合疾病级与像素级编码器，并使用监督微调和强化微调，覆盖眼底照片和 OCT。 | 参考其视觉定位任务设计，单独验证文本所述病灶与影像区域的对应关系。[EVLF-FM 论文](https://www.nature.com/articles/s41591-026-04655-5) |

病灶与术语的对齐可用 IDRiD 掩膜验证，建议配对测试原图与换图、仅图与仅文本。图像侧至少记录眼别、模态、质量、模型版本和可追溯的测量或病灶位置。指南适用性取决于患者和就诊场景，独立通过原文条款检索和匹配。生成式语言中提到的位置需要对应标注或经过评估的定位输出，才适合显示为病灶叠图。[IDRiD 标注说明](https://idrid.grand-challenge.org/Data/) · [项目影像结果结构](../../backend/vision/models.py)

## 2. 指南、分级与药品说明书

| 来源 | 首轮抽取对象与适用范围 |
| --- | --- |
| 中国 DR | 《我国糖尿病视网膜病变临床诊疗指南（2022年）》刊载于 2023 年。用于中文 DR 分级、随访、DME 与治疗证据，记录版本名与发表年份。[中山眼科中心发布入口](https://www.gzzoc.org.cn/node/13780) |
| 中国青光眼 | 《中国青光眼指南（2020年）》覆盖筛查、开角及闭角相关疾病、治疗和管理。抽取时保留亚型、阶段与检查前提。[《中华眼科杂志》原文](https://master.yiigle.com/uploads/guide_html/%E4%B8%AD%E5%9B%BD%E9%9D%92%E5%85%89%E7%9C%BC%E6%8C%87%E5%8D%97%EF%BC%882020%E5%B9%B4%EF%BC%89.html) |
| 美国 DR | AAO PPP 2025 版用于眼科诊疗，ADA 2026 年标准第 12 章的 Retinopathy 部分用于糖尿病人群筛查、转诊和治疗条款。分别保留条款适用人群与就诊环节。[AAO DR PPP](https://pubmed.ncbi.nlm.nih.gov/39918521/) · [ADA 第 12 章](https://diabetesjournals.org/care/article-lookup/doi/10.2337/dc26-S012) |
| 美国青光眼 | AAO 2026 年的 POAG、POAG Suspect、Primary Angle-Closure Disease 各有独立 PPP。用于考察疑似、确诊与房角关闭分类的证据切换。[AAO PPP 指南集合](https://www.aaojournal.org/content/preferred-practice-pattern) · [POAG 论文记录](https://pubmed.ncbi.nlm.nih.gov/41665583/) |
| 英国 NICE | NG242 面向医院眼科服务中的 DR 与 DME 管理，适合抽取 OCT 和治疗条件。NG81 用于慢性开角型青光眼和高眼压症的发现、诊断和管理。[NG242](https://www.nice.org.uk/guidance/ng242/chapter/Recommendations) · [NG81](https://www.nice.org.uk/guidance/ng81/chapter/recommendations) |
| 欧洲青光眼与 DR 分级标准 | EGS 第 6 版用于青光眼术语和分级推荐的交叉核对。Wilkinson 等的国际临床分级用于建立 DR 等级及 DME 临床术语字典，并记录各数据集采用的定义。[EGS 第 6 版](https://www.eugs.org/guidelines) · [国际临床分级原文记录](https://pubmed.ncbi.nlm.nih.gov/13129861/) |

| 产品与来源 | 首轮抽取对象 |
| --- | --- |
| 中国适利达（拉坦前列素滴眼液 0.005%） | 晖致公开说明书列有 2026-03-12 修改日期。按适应症、禁忌、注意事项和相互作用分节索引。黄斑水肿相关提示保留在注意事项及其适用条件内。[中文说明书](https://www.viatris.cn/-/media/project/viatris-sites/product-document/19xalatan.pdf) |
| 美国 EYLEA（阿柏西普眼内注射剂，2 mg 规格） | 标注修订日期 2024-10。§1.3 与 §1.4 分列 DME 和 DR 适应症，§4 为禁忌，§5 为警告和注意事项。中国有拜耳 2023 年医保申报公示，可用于定位当时的资料。中国上市适应症、禁忌和规格仍需核对对应产品现行完整说明书。[美国 DailyMed](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=f96cfd69-da34-41ee-90a9-610a4655cd1c) · [中国申报公示](https://www.nhsa.gov.cn/attach/Ypsn2023/YPSN202300127/YPSN202300127-N1.pdf) · [国家药监局数据查询说明](https://datasearch.nmpa.gov.cn/datasearch/search-help.html) |
| 美国 TIMOPTIC in OCUDOSE（马来酸噻吗洛尔滴眼液） | 可作禁忌检索的对照样例，明确产品与美国说明书范围，按 Contraindications 索引哮喘和相关病史。[美国 DailyMed](https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=16323b0e-78ae-40e5-be93-04f698dd672b) |

将指南建议、产品批准适应症、说明书安全条款和医保支付规则分别建模，并记录司法辖区。公开可读资料先登记标题、出处和章节，全文索引及拷贝按来源授权决定。中文转述保留原语种和条款定位，临床条款经审核后进入正式索引。

## 3. 图像数据登记

| 数据集 | 标签与首轮用途 | 获取与权限 |
| --- | --- | --- |
| **IDRiD** | 516 张 CFP 提供 DR 和 DME 图像级分级，81 张子集提供微血管瘤、出血、软性及硬性渗出等掩膜。适合测 DR 分级及病灶定位。DME 标签基于黄斑附近硬性渗出分级，应用作眼底照片代理标签。 | CC BY 4.0，保留署名。按挑战任务划分保持分级和分割的测试集，并检查两个任务间的图像交叉。[挑战说明与下载入口](https://idrid.grand-challenge.org/Data/) · [IEEE 数据 DOI](https://doi.org/10.21227/H25W98) |
| **DDR** | 13,673 张 CFP 含图像级标注，757 张有像素级及边界框标注。可分测可分级图像的 DR 五级识别、不可分级识别和病灶定位。 | 作者仓库提供分卷下载。图像、标注与标签适用 CC BY-NC-SA 4.0，仓库代码许可为 MIT。[作者下载及条款](https://github.com/nkicsl/DDR-dataset) · [原始论文](https://www.sciencedirect.com/science/article/abs/pii/S0020025519305377) |
| **REFUGE（2018）** | 1,200 张 CFP，训练、离线验证、现场测试各 400 张。青光眼参考诊断综合病历、OCT、视野等信息，另有视盘和视杯掩膜。适合项目现有分类和分割的回归。 | 官方站说明注册、下载和署名要求，镜像和再分发权限需按实际取得的条款确认。REFUGE2 按独立版本登记。[2018 挑战入口](https://refuge.grand-challenge.org/Home2018/) · [标签与划分](https://refuge.grand-challenge.org/Details/) · [参赛规则](https://refuge.grand-challenge.org/Rules/) |

**预训练重叠影响测试解释。** RetiZero 附表 18 列有 IDRiD（516 张）、DDR（13,673 张）和 REFUGE（800 张），FLAIR 也将三者列为预训练来源。这些公开集合可用于指定权重的流程回归。独立泛化结论需要核实具体 checkpoint 与测试病例的交集，或使用可确认独立来源的评估集。RETFound 原论文曾将 IDRiD 用作下游评估，复用其下游权重时也需要核对训练和测试划分。[RetiZero 附表 18](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41467-025-60577-9/MediaObjects/41467_2025_60577_MOESM1_ESM.pdf#page=40) · [FLAIR 预训练来源](https://github.com/jusiro/FLAIR#-foundation-model-pre-training) · [RETFound 论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC10550819/)

本次登记了原始入口与条款，原始压缩包及图像尚未下载。取得数据后记录数据版本、来源、许可、文件校验和、标签字典、缺失值和划分；有病例标识时按患者分组，标识缺失时记录局限并做图像级去重和近重复检查。测试集冻结后再调整阈值、提示或术语映射，任何此类调整使用验证集。

## 4. 知识图谱、向量索引与智能体的实验接口

1. **证据索引。** 一条 `Recommendation` 对应一条指南建议或一项说明书条款。记录 `source_id`、版本、地区、章节或页码、适用场景、纳入条件、例外、原始推荐等级和来源链接。为每条审核过的依据分配稳定的 `chunk_id`，供向量索引和图谱共同引用。现有 `Chunk` 按 Markdown 段落切分，入库时需保证表格脚注、限制条件和主条款共同可检索。见[当前检索实现](../../backend/knowledge/retrieval.py)。
2. **图检索。** 从疾病、分期、体征、检查、药品或人群条件定位节点，沿 `requires_test`、`applies_to`、`supported_by`、`has_warning`、`has_contraindication` 等关系取回支持条款，保留路径、证据编号及未满足条件。限定眼别、地区、场景和版本后与 BM25/向量结果融合。图谱缺失时使用现有混合检索，证据为空或条件不足时返回缺失项。见[图检索接口](../../backend/graphrag/retriever.py)。
3. **协作。** 影像入口 `vision.analyze_fundus` 提供当前眼分析结果，未来的视觉模块由此交付可核查发现和质量。由专科 Agent 提出证据查询，Director 汇总，Verifier 核验引用和条款条件。以现有并行模式为基线，单独测试由 DR、青光眼、用药冲突或信息缺失触发的复核。用相同模型和工具预算比较，并记录额外调用、用时和冲突处理结果。见[当前影像接口](../../backend/vision/README.md)和[报告智能体说明](../../backend/agents/README.md)。
4. **可视化。** 在结果页展示同一眼别的原图、已验证的掩膜及测量值。答案内的推荐可点至原文条款，图路径可点至对应证据和适用条件。图像不可判读、证据存在冲突或需要 OCT 等检查时，显示原因及缺失字段。现有[证据列表组件](../../frontend/src/components/EvidenceList.jsx)可作为原文定位的展示入口。

## 5. 首轮可复现测试

在同一问题集、同一权重和同一证据条数下比较 **BM25/向量 RRF** 与 **增加图检索**。固定检索结果后比较单 Agent、现有并行报告、条件触发复核。影像实验分开报告 DR 五级分级（QWK、各级召回）、筛查（AUROC、固定阈值的灵敏度和特异度）、分割（视杯/视盘 Dice、垂直杯盘比误差或病灶级召回），并记录不可判读率、相机或站点分层和置信区间。问答评估记录证据 Recall@k、正确引用率、无依据陈述率、条件缺失时的正确拒答率和用时。保留完整上下文与成对的换图、去图或去除关键检查值的输入，检查答案是否随证据变化。

| 样例输入 | 预期检索与可判定断言 |
| --- | --- |
| 单张眼底照有黄斑附近硬性渗出，没有 OCT 和视力结果 | 检索路径为眼底体征 → 待评估的 DME → 所需检查 → NG242 §1.6.11，并关联 §1.6.4–1.6.6。说明图像所见，标记中心受累及视力分层证据不足，抑制具体治疗建议。[NG242 §1.6](https://www.nice.org.uk/guidance/ng242/chapter/Recommendations#diabetic-macular-oedema) |
| 报告仅包含较大杯盘比，用户询问是否可确诊慢性开角型青光眼 | 命中 NG81 §1.2.1，回答须考虑视野、眼压、房角等检查，保留“待进一步评估”。[NG81 §1.2](https://www.nice.org.uk/guidance/ng81/chapter/recommendations#diagnosis) |
| 中国适利达疑问，给出后囊撕裂的人工晶体眼信息 | 引用中国产品说明书第 5 页的黄斑水肿注意事项，保留风险条件及“慎用”措辞。[适利达中文说明书](https://www.viatris.cn/-/media/project/viatris-sites/product-document/19xalatan.pdf#page=5) |
| 提问指定美国 EYLEA 2 mg，病例另有活动性眼内炎症 | 来源应为该产品的 §4.2，引用应标明禁忌及情境，避免只凭 DME 适应症生成治疗路径。[EYLEA §4](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=f96cfd69-da34-41ee-90a9-610a4655cd1c) |
| 相同 DR 关键词分别询问美国糖尿病人群常规筛查与英国医院眼科随访 | 前者应命中 ADA 2026 筛查依据，后者命中 NG242 对应阶段的医院管理条款。单独评分场景匹配以及引用版本。[ADA 第 12 章](https://diabetesjournals.org/care/article-lookup/doi/10.2337/dc26-S012) · [NICE NG242 适用范围](https://www.nice.org.uk/guidance/ng242) |

首轮执行顺序为证据问答回归、IDRiD 与 REFUGE 视觉流程验证、图检索增益评估、按条件触发的智能体复核。模型、图谱和多智能体的增益分别记录，以上样例为待执行草案。
