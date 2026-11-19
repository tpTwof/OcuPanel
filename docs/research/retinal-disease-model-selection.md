# OcuPanel 彩色眼底照多病种模型选型

调研日期为 2026-11-16。选型面向现有单张彩色眼底照入口，优先比较是否能直接运行公开权重、是否有眼底任务证据，以及结果能否表达为有明确含义的逐病种信号。各论文的队列、标签、指标和微调设置不同。下面的数值用于说明证据覆盖范围，同一数据集内的对照才用于比较表现。

## 候选模型

| 模型 | 任务证据 | 代码、权重和接入条件 |
| --- | --- | --- |
| FLAIR | 面向彩色眼底照的图文相似度模型，在 288,307 张图像和最多 101 类条件上预训练。作者采用专家提示做零样本推理时，在 MESSIDOR 糖网分级中报告平均类准确率 0.604、κ 0.772，在涵盖糖网、青光眼及 AMD 的 FIVES 四分类中报告平均类准确率 0.735，在 REFUGE 青光眼任务中报告 AUC 0.920。 | 作者提供 Apache-2.0 代码及公开 Safetensors 权重，单张 RGB 图像即可与固定提示词做相似度推理。 [论文表 3](https://arxiv.org/html/2308.07898#S5.T3) · [官方代码](https://github.com/jusiro/FLAIR) · [官方权重](https://huggingface.co/jusiro2/FLAIR/tree/5f6bdd0a068353dc41a896ba3abdd7c0f6d35938) |
| RetiZero | 眼底图文模型，通过同一组对照直接比较零样本候选排序。在 Eye-52，RetiZero 的 Top-1 / Top-5 准确率为 0.360 / 0.756，FLAIR 为 0.092 / 0.340。该研究的微调实验也报告了跨队列表现。 | 作者提供零样本脚本和 Google Drive 预训练权重，公开仓库中未找到明确的软件及权重许可，接入前需厘清许可。适合优先评估罕见病候选排序。 [论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC12214743/) · [官方代码与权重链接](https://github.com/LooKing9218/RetiZero) |
| VisionFM | 覆盖八种眼科影像模态。论文在彩色眼底照糖网外部验证中报告 AUROC 0.945，在 OCT 的 AMD 外部验证中报告 AUROC 0.974。 | 提供按模态区分的编码器，以及 IDRiD、MESSIDOR2、APTOS-2019 等任务微调权重。可用于后续糖网专用分级对照，须按检查点匹配输入处理和类别定义。代码仓库采用 CC BY-NC 4.0。 [论文](https://ai.nejm.org/doi/10.1056/AIoa2300221) · [微调权重与推理脚本](https://github.com/ABILab-CUHK/VisionFM/blob/main/Fine-tuning/README.md) · [许可](https://github.com/ABILab-CUHK/VisionFM/blob/main/LICENSE) |
| RETFound | Nature 原始论文验证了糖网、青光眼等任务。分别预训练彩照和 OCT 编码器，按任务标签适配。 | 原始 MAE 预训练权重需要下游分类头。作者已发布 APTOS2019、MESSIDOR2、IDRiD 等可用于复现实验的微调权重。代码仓库采用 CC BY-NC 4.0。 [Nature 论文](https://www.nature.com/articles/s41586-023-06555-x) · [官方检查点](https://github.com/rmaphoh/RETFound/blob/main/BENCHMARK.md) · [许可](https://github.com/rmaphoh/RETFound/blob/main/LICENSE) |
| RETFound-Green / BE DINORET | 较新的彩照编码器。RETFound-Green 的论文报告，在该研究的匹配比较中，119 项对照的 68 项得分最高，发布的编码器约 84 MB。BE DINORET 论文在糖网分级和青光眼识别任务中报告了有竞争力的微调结果。 | 可作为标注数据就绪后的监督模型基线。RETFound-Green 官方快速用法输出图像特征，软件许可限非商业研究。 [RETFound-Green 论文](https://www.nature.com/articles/s41467-025-62123-z) · [代码和权重](https://github.com/justinengelmann/RETFound_Green) · [BE DINORET 论文](https://arxiv.org/abs/2409.17332) |
| EyeCLIP | 眼科图文模型，以 11 种模态的 277 万张眼科图像训练，在多个眼科数据集开展零样本分类、检索和微调实验。 | 作者发布代码和 Google Drive 权重，2026 年 2 月更新了此前损坏的文本编码器权重。若扩展到 OCT 等模态，可用最新检查点独立验证，公开仓库中未找到明确的软件及权重许可。 [论文](https://www.nature.com/articles/s41746-025-01772-2) · [官方代码与权重链接](https://github.com/Michi-3000/EyeCLIP) |
| LLaVA-Med | 通用生物医学图文问答模型。官方评估聚焦对话与视觉问答，这些评估无法衡量本项目的逐病种眼底筛查性能。 | 官方发布条款限研究，明确禁止用于临床决策。 [官方代码与用途说明](https://github.com/microsoft/LLaVA-Med) |
| MedSAM | 输入图像和目标框后输出区域掩膜，论文以分割任务评估。可为有定位标注的病灶分割实验提供基线。 | 官方提供权重和交互式分割示例。新增病种筛查仍需独立的病种识别模型。 [论文](https://www.nature.com/articles/s41467-024-44824-z) · [官方推理示例](https://github.com/bowang-lab/MedSAM) |

## 本轮选型

采用 FLAIR 作为可选的彩色眼底照多病种研究模型，保留青光眼专用分析。FLAIR 的公开权重、明确的许可和单图推理接口满足本轮要求。RetiZero 在同一研究中的罕见眼底病排序明显优于 FLAIR，VisionFM 则已发表糖网外部验证结果，适合在获得对应权重使用条件和本地验证数据后按任务比较。 [FLAIR 官方发布](https://github.com/jusiro/FLAIR) · [RetiZero 同队列比较](https://pmc.ncbi.nlm.nih.gov/articles/PMC12214743/) · [VisionFM 外部验证](https://ai.nejm.org/doi/10.1056/AIoa2300221)

FLAIR 的上游接口接受 uint8 RGB 图像及英文提示词列表，内部缩放并填充到 512 × 512，再返回每条提示词的图文相似度及候选集合内的 softmax 分数。每个病种可通过独立的成对提示计算相对相似度，使不同病种无需竞争同一概率总量。提示词可参考作者发布的糖网、AMD 和静脉阻塞表型词典。模型接口计算的是文本与图像匹配程度，分数没有经过本项目的疾病概率校准，病灶位置、糖网分级和转诊阈值也需要各自的标注与验证。模型首次装载时还会读取 Bio_ClinicalBERT 资产，默认配置启用了 ResNet-50 的 ImageNet 初始化。 [推理实现](https://github.com/jusiro/FLAIR/blob/main/flair/modeling/model.py) · [专家提示词典](https://github.com/jusiro/FLAIR/blob/main/flair/modeling/dictionary.py) · [权重配置](https://huggingface.co/jusiro2/FLAIR/blob/main/config.json)

## 当前实现的缺陷

- **分数无法解释为患病概率。** OcuPanel 对每个病种只比较两段固定提示词，输出相似度差值。零点只表示两段提示词的匹配程度相等。项目缺少按目标人群校准的概率、经验证的转诊阈值，以及用于估计漏诊率的独立病例数据。对差值做 softmax 或直接分档，无法得到经验证的概率或病情等级。 [评分实现](../../backend/vision/diseases/retinal.py)
- **输入与输出不足以完成临床评估。** 当前只接收单张彩色眼底照，缺少图像清晰度、视野覆盖和不可判读判断。系统也没有定位或量化用于分期的病灶。低分遇到模糊照片或关键区域缺失时，无法支持排除疾病。糖尿病黄斑水肿及疑似活动性新生血管性 AMD 需要按对应任务补充参考检查。 [糖网 AI 试验的参考标准](https://doi.org/10.1038/s41746-018-0040-6) · [NICE AMD 诊断建议](https://www.nice.org.uk/guidance/ng82/chapter/recommendations#diagnosis)
- **本项目尚无临床性能结论。** 已使用官方权重和仓库示例图完成离线 CPU 推理，并使用真实分数与模拟文本 LLM 验证报告和 PDF。论文中的性能对应各自的数据、任务和处理流程。本项目的固定提示词、目标人群、相机和上传流程均需验证。 [本地验证记录](../../backend/vision/README.md#当前缺陷)

## 补齐临床能力所需的工作

**优先验证糖网转诊筛查。** 先明确目标人群、拍摄规范、转诊终点及不可判读时的处理流程。例如，可把中度及以上糖网设为转诊目标，并单独评估糖尿病黄斑水肿。收集由眼科专家逐眼分级、带图像质量标签的照片，纳入无病、各严重度、共病和不可判读病例。在同一批病例上比较当前 FLAIR 分数与专用糖网模型。验证完成后，输出可包括「建议转诊」「未达转诊阈值」「不可判读」。 [ADA 2026 糖网筛查与转诊建议](https://doi.org/10.2337/dc26-s012) · [糖网 AI 前瞻性试验](https://doi.org/10.1038/s41746-018-0040-6)

**分级需要单独的任务和标签。** DR 需要各级非增殖期及增殖期的参考标签，糖尿病黄斑水肿需要单独标注，参考检查可包括 OCT。AMD 早期和中期需要玻璃膜疣大小和色素异常等标注，疑似活动性新生血管性 AMD 需要接入 OCT，并在有相应参考检查的病例中验证。 [ADA 2026 指南](https://doi.org/10.2337/dc26-s012) · [Beckman AMD 分期](https://pmc.ncbi.nlm.nih.gov/articles/PMC11551519/) · [NICE AMD 诊断建议](https://www.nice.org.uk/guidance/ng82/chapter/recommendations#diagnosis)

**锁定阈值后再做外部测试。** 按患者划分开发、验证和测试数据。在验证集上选择阈值，有概率输出时在验证集上拟合校准，再用患者互不重叠、来自其他机构或相机的数据做外部测试。报告敏感度、特异度、阴性预测值、不可判读率及置信区间，并说明测试人群的患病率。分级任务还需报告各级混淆和关键漏分级。概率输出应检验各预测概率区间内的实际患病比例是否与预测一致。
