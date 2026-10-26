"""引用校验智能体（CitationVerifier）——第 7 个 Agent。

为什么需要它：前面 6 个角色和 Director 都是「生成型」调用，模型天然会把
「听起来合理」的话写进报告。句末挂一个 [3] 只证明它引用了资料，**不证明
[3] 真的支持那句话**——实测首版报告有 16 处引用，其中若干处原文与结论
并不是一回事（例如资料写「每 3–6 个月复查」，报告写成「必须每 3 个月复查」；
资料只提到「前列腺素类似物为一线」，报告加上了「且无任何禁忌」）。

这里做两件事：
1. **逐句核查**：每条引用外部知识的断言，标注的 [n] 是否能推出这句话；
2. **打回重写**：没依据的句子允许直接删掉（删是正确处置，不是事故）；改不动
   就整篇重新生成；重生成之后仍有断言无法被支持，就**拒答**——返回空报告，
   由接口层给出「无法生成有依据的报告」的说明。

三条硬规则：
- 未经校验的内容一律不输出。校验服务本身出错时也不输出（status=error），
  不拿"看起来对"的报告顶上去。
- 不设删除配额。把有依据的句子改写成「资料未涵盖」是假覆盖，方向反了，
  这个要拦；把没依据的句子删掉则是本该发生的事。
- 删到正文不成文（content_len 低于阈值）时不退回原文，而是触发重生成。

判定四档：
- supported   资料原文能直接推出该句
- partial     一半成立：常见于模型自己加的绝对化措辞（必须 / 一定 / 唯一 / 立即）
- unsupported 资料无对应内容，或数字、结论与资料冲突
- uncited     讲的是指南、药物、阈值、随访规范这类外部知识，却没有任何 [n]

重要边界：**本病例的影像所见与测量值不算 uncited**。杯盘比 0.85、眼压 26 mmHg、
视盘色淡这些都是本例数据，本来就不该有外部出处。少了这条约束，校验员会把
整篇报告标红，反而没法用。

失败即降级：校验或重写任何环节出错，都保留原文继续走完流程，只在返回体里
标注 status，绝不让报告生成因为校验而 500。
"""

from __future__ import annotations

import json
import re
import sys

# 单轮最多处理多少条问题句。太多会让重写提示词过长，模型开始乱改。
MAX_ISSUES_PER_ROUND = 12

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

# 归一化匹配时忽略的字符：模型复制原句时经常吞掉空格 / 换行
_SKIP_CHARS = set(" \t\r\n\u3000\u00a0")

_VERDICTS = {"partial", "unsupported", "uncited"}

# 模型偷懒时会把有依据的句子改写成「资料未涵盖」。实测出现过：语料明写
# 「前列腺素类似物……是首选一线用药」，模型却把该句改成「具体药物选择资料未涵盖」。
# 这种改写比原来的漏标引用更糟，必须拦下。
_DODGE_MARKERS = ("未涵盖", "未提及", "未涉及", "没有提及", "无相关资料", "资料不足", "未说明")


def _cjk_bigrams(text: str) -> set[str]:
    chars = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    return {chars[i:i + 2] for i in range(len(chars) - 1)}


def is_false_dodge(quote: str, new: str, evidence_text: str,
                   sim_fn=None, sim_threshold: float = 0.80) -> bool:
    """改写结果声称「资料未涵盖」，但资料里明显有对应内容。

    三种判据，任一命中即拦下这条改写、保留原句：
    1. 中文 2-gram 覆盖率 ≥0.4 —— 同语言语料下便宜且准；
    2. 语义相似度 ≥0.80 —— 语料混进英文后，中文引文与英文证据没有任何共享
       bigram，判据 1 恒为 0，这道守卫原本会**静默失效**（不报错，只是不再拦截）。
       实测跨语言相关块余弦 0.82–0.84，同语言无关块 0.867，所以阈值取 0.80；
    3. 都判不出来时放过 —— 下游还有复核，真不支撑会触发重写/重生成/拒答。

    sim_fn: (quote, evidence_text) -> float。不传就只跑判据 1，
    对应「没加载向量模型」的场景（RAG_MODE=bm25）。
    """
    if not any(marker in new for marker in _DODGE_MARKERS):
        return False

    grams = _cjk_bigrams(quote)
    if grams:
        covered = sum(1 for g in grams if g in evidence_text)
        if covered / len(grams) >= 0.4:
            return True

    if sim_fn is not None:
        try:
            if sim_fn(quote, evidence_text) >= sim_threshold:
                return True
        except Exception as exc:  # noqa: BLE001 - 相似度算不出来就退回判据 1 的结论
            print(f"[VERIFY] 假覆盖语义判据失败，忽略：{exc}", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# 证据 & 提示词
# ---------------------------------------------------------------------------
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
        "（实测踩过：模型会把「目标眼压降低 25%–30%」里正确的数字删掉，只因该句漏了编号。）\n"
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


# ---------------------------------------------------------------------------
# JSON 解析 & 定点替换
# ---------------------------------------------------------------------------
def parse_json(raw: str | None):
    """容错解析：模型常套 ```json 代码块或前后带一句客套话。"""
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start:end + 1])
        except (ValueError, TypeError):
            return None
    return None


def _norm_index(text: str) -> tuple[str, list[int]]:
    """去掉空白后的文本 + 每个字符在原文中的下标，用于宽松定位原句。"""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if ch in _SKIP_CHARS:
            continue
        chars.append(ch)
        index.append(i)
    return "".join(chars), index


def locate(text: str, quote: str):
    """在 text 里定位 quote，返回 (start, end) 或 None。

    先按原样找，找不到再去空白后找；还找不到就用前 12 个非空白字符定位
    （模型常把句末的 [n] 或句号抄漏 / 抄多）。
    """
    if not quote:
        return None
    pos = text.find(quote)
    if pos >= 0:
        return pos, pos + len(quote)

    norm, index = _norm_index(text)
    target = "".join(ch for ch in quote if ch not in _SKIP_CHARS)
    if not target:
        return None

    hit = norm.find(target)
    if hit >= 0:
        end = hit + len(target)
        return index[hit], index[end - 1] + 1

    head = target[:12]
    if len(head) < 8:
        return None
    hit = norm.find(head)
    if hit < 0:
        return None
    tail = min(hit + len(target), len(norm)) - 1
    return index[hit], index[tail] + 1


def content_len(text: str) -> int:
    """正文的有效字数：去掉 Markdown 标记、引用编号、空白后的长度。

    用它判断「是不是被删得不足以成文」。注意这不是用来"保底留内容"的阈值——
    只用来触发重生成 / 拒答，绝不拿它当保留无依据内容的理由。
    """
    text = re.sub(r"\[\d+\]", "", text or "")
    text = re.sub(r"[#*>`\s\-—·•|]", "", text)
    return len(text)


def apply_replacements(text: str, replacements: list[dict],
                       evidence_text: str = "", sim_fn=None,
                       evidence_map: dict[int, str] | None = None) -> tuple[str, list[dict], int]:
    """逐条定点替换，返回 (新文本, 实际生效的替换, 删除句数)。

    删除是合法处置：没有依据的句子就该被删掉，不设配额。
    唯一保留的拦截是「假覆盖」——把有依据的句子改写成「资料未涵盖」，
    那是把真实内容抹掉，方向反了（见 is_false_dodge）。
    删多了的后果不在这里兜：上层会据 content_len 判定「删到不成文」，
    然后触发重生成，重生成仍不合格就拒答。
    """
    applied: list[dict] = []
    deleted = 0

    for rep in replacements:
        quote = str(rep.get("quote") or "").strip()
        if not quote:
            continue
        new = rep.get("new")
        new = "" if new is None else str(new).strip()

        if new and (evidence_text or evidence_map):
            # 优先用该句引用的那一条证据比对：拿全部证据拼起来算相似度会虚高，
            # 把本该删掉的句子也拦下来，最后变成误拒答。
            target = ""
            for cite in rep.get("citation") or rep.get("citations") or []:
                try:
                    key = int(cite)
                except (TypeError, ValueError):
                    continue
                if evidence_map and key in evidence_map:
                    target = evidence_map[key]
                    break
            if not target:
                target = evidence_text
            if target and is_false_dodge(quote, new, target, sim_fn=sim_fn):
                print(
                    f"[VERIFY] 判为假覆盖（资料其实有对应内容），保留原句：{quote[:40]}",
                    file=sys.stderr,
                )
                continue

        span = locate(text, quote)
        if not span:
            print(f"[VERIFY] 原句定位失败，跳过：{quote[:40]}", file=sys.stderr)
            continue

        start, end = span
        text = f"{text[:start]}{new}{text[end:]}"
        if not new:
            deleted += 1
        applied.append({
            "quote": quote[:200],
            "new": new[:200],
            "citations": rep.get("citation") or rep.get("citations") or [],
        })

    # 删除整句后会留下空行和多余空格
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, applied, deleted


# ---------------------------------------------------------------------------
# 校验器
# ---------------------------------------------------------------------------
class CitationVerifier:
    """把「核查 → 定点重写 → 再核查」做成闭环。

    llm_call 的签名统一为 (prompt, system=None, temperature=None) -> str。
    """

    def __init__(self, llm_call, min_chars: int = 300, min_ratio: float = 0.4, sim_fn=None):
        self._llm = llm_call
        # 「删到不成文」的判定线：低于此长度说明这一版报告已经被删空，该重新生成
        self.min_chars = min_chars
        self.min_ratio = min_ratio
        # 语义相似度回调，用于跨语言判断「假覆盖」；不传则只用词面判据
        self.sim_fn = sim_fn

    # -- 单步 ---------------------------------------------------------------
    def verify(self, text: str, evidence: list[dict]):
        """返回问题句列表；调用或解析失败返回 None（调用方据此降级）。"""
        raw = self._llm(
            build_verify_prompt(text, evidence),
            system=VERIFIER_SYSTEM,
            temperature=0.0,
        )
        if not raw or raw.startswith("Error:"):
            print(f"[VERIFY] 校验调用失败：{(raw or '空响应')[:200]}", file=sys.stderr)
            return None

        data = parse_json(raw)
        if not isinstance(data, dict):
            print(f"[VERIFY] 校验结果不是 JSON，本轮跳过：{raw[:200]}", file=sys.stderr)
            return None

        issues: list[dict] = []
        for item in data.get("claims") or []:
            if not isinstance(item, dict):
                continue
            quote = str(item.get("quote") or "").strip()
            verdict = str(item.get("verdict") or "").strip().lower()
            if not quote or verdict not in _VERDICTS:
                continue
            issues.append({
                "quote": quote[:200],
                "verdict": verdict,
                "citations": item.get("citations") or [],
                "reason": str(item.get("reason") or "")[:120],
            })
        return issues

    def rewrite(self, text: str, issues: list[dict], evidence: list[dict]) -> list[dict]:
        raw = self._llm(
            build_rewrite_prompt(text, issues, evidence),
            system=REWRITER_SYSTEM,
            temperature=0.2,
        )
        if not raw or raw.startswith("Error:"):
            print(f"[VERIFY] 重写调用失败：{(raw or '空响应')[:200]}", file=sys.stderr)
            return []
        data = parse_json(raw)
        if not isinstance(data, dict):
            print(f"[VERIFY] 重写结果不是 JSON，跳过：{raw[:200]}", file=sys.stderr)
            return []
        return [r for r in (data.get("replacements") or []) if isinstance(r, dict)]

    # -- 主流程 -------------------------------------------------------------
    def verify_and_rewrite(self, text: str, evidence: list[dict], max_rounds: int = 2,
                           regenerate=None):
        """核查 → 打回重写（含删除）→ 复核；改不动就整篇重生成；再不行就拒答。

        regenerate: 可选回调，签名 (issues) -> 新文本。重生成时会把残留的无依据
        断言当作「禁止写入清单」交给它，让它换一种写法而不是原样重来。

        返回 (text, report)：
        - 合格：text 是正文，status ∈ {pass, rewritten}
        - 拒答：**text 为 None**，status == "rejected"，remaining_issues 说明
          哪些断言始终无法被资料支持。上层必须据此不输出报告。
        - 系统故障：同样 text 为 None（status == "error"）。未经校验的内容
          一律不输出——宁可没有报告，也不给一份"看起来对"的报告。

        为什么不设删除配额、也不在改坏时退回原文：删掉无依据的句子是正确处置；
        删到不成文说明这一版报告本身站不住，该做的是重生成，重生成还不行就拒答。
        "保留幻觉让人看见"不是安全冗余，是把风险转嫁给读者。
        """
        report = {
            "status": "skipped",
            "rounds": 0,
            "initial_issues": 0,
            "remaining_issues": [],
            "fixed": [],
            "deleted": 0,
        }
        if not text or not text.strip():
            report["status"] = "rejected"
            report["reason"] = "empty_text"
            return None, report
        if not evidence:
            # 没有证据包就无法校验（RAG 关闭时的合法配置），如实标注而不是假装通过
            report["reason"] = "no_evidence"
            return text, report

        ev_text = "\n".join(item.get("text", "") for item in evidence)
        ev_map = {
            int(item.get("index", pos)): str(item.get("text", ""))
            for pos, item in enumerate(evidence, 1)
        }
        min_len = max(self.min_chars, int(content_len(text) * self.min_ratio))

        issues = self.verify(text, evidence)
        report["rounds"] = 1
        if issues is None:
            report["status"] = "error"
            report["reason"] = "verify_call_failed"
            return None, report

        report["initial_issues"] = len(issues)
        if not issues:
            report["status"] = "pass"
            return text, report

        current = text
        regen_used = False

        for round_no in range(1, max(0, max_rounds) + 1):
            replacements = self.rewrite(current, issues[:MAX_ISSUES_PER_ROUND], evidence)
            if replacements:
                current, applied, deleted = apply_replacements(
                    current, replacements, ev_text, sim_fn=self.sim_fn, evidence_map=ev_map
                )
                report["fixed"].extend(applied)
                report["deleted"] += deleted
                print(
                    f"[VERIFY] 第 {round_no} 轮：{len(issues)} 处问题 → "
                    f"改写 {len(applied)} 句（其中删除 {deleted} 句）",
                    file=sys.stderr,
                )

            issues = self.verify(current, evidence)
            report["rounds"] = round_no + 1
            if issues is None:
                report["status"] = "error"
                report["reason"] = "recheck_call_failed"
                return None, report
            if not issues:
                break

            too_thin = content_len(current) < min_len
            if regenerate and not regen_used and (too_thin or round_no == max_rounds):
                regen_used = True
                print(
                    "[VERIFY] 改写无法收敛（{}），重新生成整篇报告".format(
                        "正文已删至不成文" if too_thin else "轮数用尽仍有余留"
                    ),
                    file=sys.stderr,
                )
                regenerated = regenerate(issues)
                if regenerated and not str(regenerated).startswith("Error:"):
                    current = regenerated
                    report["regenerated"] = True
                    issues = self.verify(current, evidence)
                    report["rounds"] += 1
                    if issues is None:
                        report["status"] = "error"
                        report["reason"] = "recheck_call_failed"
                        return None, report
                    if not issues:
                        break
                else:
                    print("[VERIFY] 重新生成失败", file=sys.stderr)

        if not issues:
            report["status"] = "rewritten" if (report["fixed"] or report.get("regenerated")) else "pass"
            print(
                f"[VERIFY] 通过：首轮 {report['initial_issues']} 处问题，"
                f"改写 {len(report['fixed'])} 句（删 {report['deleted']}），"
                f"重生成={'是' if report.get('regenerated') else '否'}",
                file=sys.stderr,
            )
            return current, report

        report["remaining_issues"] = issues
        report["status"] = "rejected"
        report["reason"] = "unverified_claims_remain"
        print(
            f"[VERIFY] 拒答：仍有 {len(issues)} 处断言无法被资料支持，不输出报告",
            file=sys.stderr,
        )
        return None, report
