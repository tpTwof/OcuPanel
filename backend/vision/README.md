# 眼部影像分析

本目录只负责影像算法，不依赖前端、HTTP、Agents 或报告文本。

```text
vision/
  analysis.py                 公共入口，校验请求病种、读取一次图片、汇总结果
  # 数据对象统一位于 ../vision/models.py
  utils/                      跨病种通用工具，不包含病种判断
    images.py                 RGB uint8 图像读取与校验
    runtime.py                设备选择、模型缓存、推理锁
  anatomy/optic_disc_cup.py    解剖结构分割、面积等效 CDR、叠加图
  diseases/glaucoma/           青光眼分类与分析组合
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

目前只实现青光眼相关分析，多病种结构不表示已经支持其他疾病。

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

当前结果可以支持后续回答模型概率、面积等效 CDR、分割位置及模型来源。它不能提供青光眼分期、糖网分级或其他尚未检测的病灶结论；不应把未检查的病种当作阴性。`warnings=[]` 仅表示上述有限检查没有触发，不代表图像质量或分割准确度已经通过验证。

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
- 模型按名称、模型类和设备缓存，最多四组；加载和推理共用锁以限制并发显存峰值。clear_model_cache 可释放缓存引用。
- 模型输入预处理由各权重的 processor 决定，不把所有模型强行统一为同一种缩放和归一化。

## 扩展糖网

选择并验证实际模型后创建 diseases/diabetic_retinopathy/，实现接收 RGB 数组、返回 EyeAnalysis 的 analyze 函数，再在 analysis.py 注册。保存该模型实际输出的分级、概率和来源；不要复制青光眼阈值。可视化和掩膜采用有含义的唯一键，避免覆盖其他模型结果。多个病种需要同一解剖结构时，应在入口中共享该次请求的分割结果，避免重复推理。

## 兼容和限制

分析模块唯一输出是 EyeAnalysis，各病种结果统一存放在 diseases 字典中。病种名只保存在字典键中，不在 DiseaseResult 再次保存。概率、严重程度和数值指标分别存放，不增加青光眼或糖网专属顶层字段。

旧 FundusAnalysis、report_adapter.py、report_types.py 和 interpretation.py 已移除。报告侧直接读取新结果并自行保存图片、组织文字。PDF 现有的 CDR 展示仍由报告侧单独提取，不属于通用分析结构。

单独测试分割（在 backend 目录）：

```powershell
python -m vision ../samples/fundus_right_eye.png --output overlay.png
```

当前分割权重沿用类别 0=背景、1=视盘环、2=视杯，分类权重沿用索引 1=青光眼；更换模型必须重新确认语义。输出维度检查不能替代模型标签验证。未增加未经验证的连通域过滤或病灶后处理。

已完成上述单张样本的真实 CPU 推理；模型准确度、GPU 运行与临床阈值仍需另行验证。单元测试只覆盖数值逻辑和接口组织。
