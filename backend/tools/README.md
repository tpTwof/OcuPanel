# backend/tools

后端本地数据工具。均在 `backend/` 目录或仓库根目录使用项目虚拟环境运行，不需要真实模型或网络。

## 语料覆盖矩阵

按「病种 × 方面」统计条款覆盖、可支撑该方面的材料类型、审核状态与对应评估病例，并列出缺口。数据来自 `modules/knowledge` 的语料加载与元数据解释，只读，不修改语料。

```powershell
# 在仓库根目录运行
.\.venv\Scripts\python.exe backend\tools\corpus_coverage.py --write docs\语料覆盖矩阵.md
```

不带 `--write` 时输出 Markdown；`--json` 输出机器可读统计。覆盖数只反映条款级元数据，不能替代原文核对与专业复核。新增或更新条款后应重新生成，并运行检索回归。
