# vision

analysis.py 是眼底分析入口，models.py 保存结构化输出；diseases/ 放病种实现，anatomy/ 放视盘视杯分割，utils/ 放影像与运行时工具。青光眼输出概率、分割和面积等效 CDR；来源与验证程度随结构化结果保留。

## 糖网与年龄相关性黄斑变性

DR 与 AMD 使用 FLAIR 研究性图文匹配。可选依赖见 [requirements-retinal.txt](../../requirements-retinal.txt)，配置见 [后端说明](../../README.md)。模型匹配分数没有临床阈值，缺少独立病例与质量验证，仅供研究和开发参考。

[后端说明](../../README.md) · [离线测试](../../tests/README.md)
