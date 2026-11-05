"""引用核查与定点修订的提示词；不执行模型调用。"""
VERIFIER_SYSTEM = (
    "你是临床报告的引用校验员（citation verifier）。"
    "你的唯一职责是判断报告里的事实性断言是否被标注的参考资料真实支持。"
    "你不评价医学观点是否最优，不补充任何新知识，不润色文字，不写解释性散文。"
)

REWRITER_SYSTEM = (
    "你是临床报告的文字修订员。你只改写被点名的句子，"
    "改写后的内容必须严格落在给定参考资料能支持的范围之内。"
    "你从不新增资料以外的数字、剂量或结论，也从不改动未被点名的句子。"
)

def evidence_block(evidence: list[dict]) -> str:
    """参考资料清单。编号与正文 [n] 一一对应，必须沿用后端算好的 index。"""
    lines = []
    for i, item in enumerate(evidence, 1):
        number = item.get("index", i)
        lines.append(
            f"[{number}] 《{item.get('title', '')}》§{item.get('section', '')}"
            f"（来源：{item.get('source', '')}）\n{item.get('text', '')}"
        )
    return "\n\n".join(lines)


def build_verify_prompt(text: str, evidence: list[dict]) -> str:
    return (
        "请核查下面这份临床报告：每一条「引用外部知识」的断言，标注的编号资料是否真的支持它。\n\n"
        "【判断标准】\n"
        "- partial：一部分成立、一部分资料里没有。最常见的是模型自己加了绝对化措辞"
        "（必须 / 一定 / 唯一 / 立即 / 无任何禁忌），或把「可以考虑」写成「首选」。\n"
        "- unsupported：资料里没有对应内容，或句中的数字、结论与资料冲突。\n"
        "- uncited：讲的是指南、药物、阈值、随访间隔、检查规范这类外部知识，却没有任何 [n]。\n\n"
        "【不算问题，不要报告】\n"
        "- 报告标题、章节名、免责声明；\n"
        "- 本病例的影像所见与测量值（如杯盘比 0.85、眼压 26 mmHg、视盘色淡、RNFL 变薄），"
        "这些属于本例数据，本来就不需要外部出处；\n"
        "- 没有具体数值也没有指南结论的泛化建议（如「建议进一步检查」）。\n\n"
        f"【报告正文】\n<<<\n{text}\n>>>\n\n"
        f"【参考资料】\n{evidence_block(evidence)}\n\n"
        "【输出】只输出 JSON，不要代码块，不要任何额外文字：\n"
        '{"claims":[{"quote":"从正文逐字复制的原句","citations":[2],'
        '"verdict":"unsupported","reason":"不超过40字"}]}\n'
        '没有任何问题时输出 {"claims":[]}。'
    )


def build_rewrite_prompt(text: str, issues: list[dict], evidence: list[dict]) -> str:
    listed = []
    for i, it in enumerate(issues, 1):
        cite = "、".join(f"[{c}]" for c in it.get("citations") or []) or "无"
        listed.append(
            f"{i}. 原句：「{it['quote']}」\n   标注：{cite}｜问题：{it['verdict']}"
            f"（{it.get('reason') or '资料未覆盖'}）"
        )
    return (
        "下面这份报告有若干句子被判定为「资料不支撑 / 未标注依据」。请只重写这些句子。\n\n"
        f"【报告正文】\n<<<\n{text}\n>>>\n\n"
        f"【参考资料】\n{evidence_block(evidence)}\n\n"
        "【需要改写的句子】\n" + "\n".join(listed) + "\n\n"
        "【改写要求】\n"
        "1. 改写后的句子必须能被所列参考资料支持：能支持多少写多少，资料没写的细节删掉。\n"
        "2. 若正文其实是有依据的，只是漏标或标错了编号：只改 citation，正文一个字都不要动。"
        "\n"
        "3. 绝对化措辞（必须 / 一定 / 唯一 / 立即 / 完全）若资料没有对应表述，一律去掉。\n"
        "4. 不要新增资料以外的数字、剂量、分期或结论；也不要把资料里的范围写成单点。\n"
        "5. 保留原句式与语气，长度尽量接近，不要改动与其他句子的衔接。\n"
        "6. 具体建议（复查、监测、转诊）若本身有资料支持，就保留动作本身；"
        "若无依据则删掉该建议，也不要用泛泛的机制陈述去顶替它。\n"
        "7. 若该句是本例的影像所见或测量值（如杯盘比、眼压），保留数值、去掉不成立的引用即可"
        "（citation 置为空数组）。\n\n"
        "【关于删除】\n"
        "- 完全没有依据的内容必须删掉（new 设为 \"\"），不要为了让报告显得完整而保留；\n"
        "- 能改写成资料支持的说法就改写，只有整句都无从改起时才删；\n"
        "- 删掉一句后要保证上下文仍然通顺，不要留下半截话；\n"
        "- 允许一次删多句，但不得因此把正文删空——删空等于承认这份报告无法成立。\n\n"
        "【输出】只输出 JSON，不要代码块：\n"
        '{"replacements":[{"quote":"原句逐字复制","new":"改写后的句子","citation":[2]}]}'
    )
