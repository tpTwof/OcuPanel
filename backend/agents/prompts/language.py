"""分析 Agent 的输出语言要求。"""
from utils import config
USE_CHINESE = config.REPORT_LANGUAGE.startswith("zh")
LANGUAGE_INSTRUCTION = (
    "\n\n请用简体中文撰写全部内容。专业术语首次出现时可在括号内保留英文缩写"
    "（如眼压 IOP、光学相干断层扫描 OCT、视网膜神经纤维层 RNFL）。"
    if USE_CHINESE
    else ""
)
