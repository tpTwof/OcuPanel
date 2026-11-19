# 眼部影像分析

环境安装与服务端入口见 [后端 README](../README.md)。

本目录只负责影像算法，不依赖前端、HTTP、Agents 或报告文本。

```text
vision/
  analysis.py                 公共入口，校验请求病种、读取一次图片、汇总结果
  models.py                   EyeAnalysis、DiseaseResult 数据契约
  utils/                      跨病种通用工具，不包含病种判断
    images.py                 RGB uint8 图像读取与校验
    runtime.py                设备选择、模型缓存、推理锁
  anatomy/optic_disc_cup.py    解剖结构分割、面积等效 CDR、叠加图
  diseases/glaucoma/           青光眼分类与分析组合
  diseases/retinal.py          FLAIR 糖网及 AMD 图文匹配
```

```python
from vision import analyze_fundus
result = analyze_fundus("fundus.png", diseases=("glaucoma",), device="cpu")
finding = result.diseases["glaucoma"]
print(finding.probability, finding.measurements, finding.warnings)
mask = result.masks["optic_disc_cup"]
overlay = result.overlays["optic_disc_cup"]  # RGB uint8，保存由调用方负责
```

在 backend 目录运行，或将 backend 加入 Python 模块搜索路径。

## 当前已实现的功能

青光眼使用专用分类和分割模型。糖尿病视网膜病变（DR）与年龄相关性黄斑变性（AMD）使用可选的 FLAIR 模型。

| 能力 | 实现与输出 |
|---|---|
| 青光眼二分类 | SwinV2 输出青光眼类别的 softmax 概率，保存在 `diseases["glaucoma"].probability` |
| 视杯、视盘分割 | SegFormer 输出与输入图像同高、同宽的 `uint8` 掩膜，保存在 `masks["optic_disc_cup"]`；0=背景、1=视盘环、2=视杯 |
| 面积等效 CDR | `sqrt(视杯像素数 / (视盘环像素数 + 视杯像素数))`，保存在 `measurements["area_equivalent_cdr"]`；不是直接测得的垂直 CDR |
| 分割可视化 | `overlays["optic_disc_cup"]` 为 RGB `uint8` 数组；视盘环偏红、视杯绿色，背景保持原样；保存文件由调用方负责 |
| 基础异常提示 | 未检测到视盘环时不提供 CDR；有视盘环但没有视杯时 CDR 为 0 并附提示；记录在 `warnings` |
| 模型来源 | `model_sources` 记录分类和分割使用的模型名称 |

### 概率与严重程度

当前分类模型的类别只有 `Non-glaucoma` 和 `Glaucoma`，没有早期、中期、晚期标签。因此 `severity` 当前始终为 `None`，表示未评估严重程度，不表示正常或轻度。

旧实现曾按 0.2、0.5、0.9 将分类概率分为 `none / possible / likely / definitive`，并写入名为 `severity` 的字段。这是概率分档，不是疾病分期；当前实现已移除该映射，不再输出这些标签。高分类概率不等于病情严重，面积等效 CDR 也不直接转换为分期。

青光眼结果包括模型概率、面积等效 CDR、分割位置及模型来源。`warnings=[]` 表示上述检查未触发提示。影像质量与分割准确度需要独立评估。

### 本地真实模型验证

2026-11-05，使用项目 `.venv`、PyTorch 2.7.0+cpu、Transformers 4.51.3 和本地缓存权重，对 `samples/fundus_right_eye.png` 完成一次 CPU 离线推理，耗时约 10.7 秒（包含模型加载）：

```text
probability:          0.999963641166687
severity:             None
area_equivalent_cdr:  0.8485026024761082
warnings:             []
mask:                 (1024, 1024), uint8
overlay:              (1024, 1024, 3), RGB uint8
```

掩膜中背景为 1,035,653 像素、视盘环为 3,619 像素、视杯为 9,304 像素；叠加图的背景与原图逐像素一致。原图带有“AI生成 / WORKBUDDY”标记，该次验证用于确认推理执行与返回结构，不能证明临床准确度。详细记录和数组产物位于 `backend/output/vision_validation/`，属于本地验证产物，不是版本化测试基准。

## 分层规则

- utils/ 只存放通用工具，不依赖 anatomy/、diseases/ 或报告代码；按需导入子模块，避免提前加载 PyTorch。
- 解剖结构分割可被不同病种复用，因此不放在青光眼专属目录。
- 病种分析组合实际需要的模型；不要求每个病种都具备分类器和分割器。
- 病种概率和严重程度分开；没有分级模型时 severity 为 None。
- CDR 命名为 area_equivalent_cdr，不冒充垂直 CDR。
- 未检测到视盘环时，病种分析保留分类概率和分割图，但不输出 CDR；提示位于 warnings。
- 模型技术故障直接抛出异常；当前没有静默降级和自动 OOM 重试。
- 未支持的病种直接报错，空结果不能表示检查正常。
- 青光眼模型按名称、模型类和设备缓存，最多四组，可用 `clear_model_cache()` 释放引用。FLAIR 缓存最近使用的一组权重。各模型加载和推理共用锁以限制并发显存峰值。
- 模型输入预处理由各权重的 processor 决定，不把所有模型强行统一为同一种缩放和归一化。

## 糖网与年龄相关性黄斑变性

安装后端基础依赖后，从仓库根目录用启动后端的同一个 `.venv` 安装。安装 FLAIR 需要 Git。以下命令适用于 PyTorch CPU 版。CUDA 环境请从与 PyTorch 构建匹配的源安装 torchvision 0.22.0。

```powershell
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cpu
& $python -m pip install -r .\backend\requirements-retinal.txt
& $python -m pip check
& $python -c 'import flair, torchvision; print(torchvision.__version__)'
```

重启后端后，在「眼科分析」选择 DR、AMD 或与青光眼组合。首次使用会下载 FLAIR 权重（约 533 MB）及 Bio_ClinicalBERT 的权重和词表，已有缓存会被复用。Python 包安装在 `.venv`，模型权重由 Hugging Face 单独缓存。FLAIR 在后端本地推理，报告仍使用已配置的文本 LLM。

```python
from vision import analyze_fundus

result = analyze_fundus(
    "fundus.png",
    diseases=("diabetic_retinopathy", "age_related_macular_degeneration"),
    device="cpu",
)
for name, finding in result.diseases.items():
    print(name, finding.prompt_similarity_margin, finding.model_sources)
```

两项眼底任务共用同一次 FLAIR 图像编码。`prompt_similarity_margin` 是病变提示的相似度 logit 减去无该病变提示的 logit，`probability` 与 `severity` 为空。报告和 PDF 会显示原始分数及其含义。

### 当前缺陷

- **评分未经临床校准。** 正负号分别表示两段提示词匹配程度的方向。项目暂无经过验证的转诊阈值、漏诊率或阴性预测值，分数无法用于判断是否转诊、确诊或排除疾病。
- **图像质量检查仅处理明显的输入故障。** 统一分析入口会在推理前拦截任一边不足 32 像素或整张图为纯色的图片，报告 API 返回 422 并提示重拍或上传原图。自动化测试覆盖这两类失败及仓库样例。32 像素是技术门槛，临床清晰度、曝光、视野覆盖和是否为眼底照片仍需单独验证。DR 分级、糖尿病黄斑水肿评估和 AMD 分期均缺少对应输出。
- **临床可判读性仍待验证。** 可用 DeepDRiD 的质量标签作为候选基线，按患者划分图像并在独立设备或机构的样本上评估清晰度、视野范围和伪影。应同时统计不可判读图像被放行和可判读图像被拒绝的比例。验证结果需按目标病种和采集协议分别核对。 [DeepDRiD 图像质量研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC9214346/)
- **验证仅覆盖技术链路。** 2026-11-16 使用官方权重对 `samples/fundus_right_eye.png` 完成离线 CPU 推理，DR 单选和联选的分数一致。使用真实影像分数和模拟文本 LLM 验证了报告与 PDF。项目尚未使用独立标注病例验证临床性能。 [临床能力所需的数据和验证](../../docs/research/retinal-disease-model-selection.md#补齐临床能力所需的工作)

## 兼容和限制

分析模块唯一输出是 EyeAnalysis，各病种结果统一存放在 diseases 字典中。病种名只保存在字典键中，不在 DiseaseResult 再次保存。概率、严重程度和数值指标分别存放，不增加青光眼或糖网专属顶层字段。

旧 FundusAnalysis、report_adapter.py、report_types.py 和 interpretation.py 已移除。报告侧直接读取新结果并自行保存图片、组织文字。PDF 现有的 CDR 展示仍由报告侧单独提取，不属于通用分析结构。

单独测试分割（在 backend 目录）：

```powershell
../.venv/Scripts/python.exe -m vision ../samples/fundus_right_eye.png --output overlay.png --device cpu
```

当前分割权重沿用类别 0=背景、1=视盘环、2=视杯，分类权重沿用索引 1=青光眼；更换模型必须重新确认语义。输出维度检查不能替代模型标签验证。未增加未经验证的连通域过滤或病灶后处理。

已完成上述单张样本的真实 CPU 推理；模型准确度、GPU 运行与临床阈值仍需另行验证。单元测试只覆盖数值逻辑和接口组织。

## 环境与模型缓存

开发基线为 Python 3.13。首次调用对应算法时自动下载权重与预处理配置。默认 Hub 缓存在用户目录的 `.cache/huggingface/hub`。`HF_HOME` 设置 Hugging Face 缓存根目录，`HF_HUB_CACHE` 可直接指定包含 `models--…` 子目录的 Hub 缓存。后端从 `backend/.env` 读取这两项，独立运行影像模块时可在启动 Python 前设置环境变量。

磁盘缓存由 Hugging Face 管理，新进程会从磁盘加载权重。默认设备选择 CUDA → MPS → CPU，显式请求不可用设备会报错。青光眼模型使用权重所保存的处理器（`use_fast=False`），FLAIR 使用上游的图像和文本预处理。

CLI 只测试分割和叠加图，不运行分类器、Agents 或 PDF。完整病种结果请调用 analyze_fundus；独立分割未检测到视盘时会抛出异常。
