"""文本定位、定点替换和修订检查。相似度仅作启发式检查，不能证明医学事实。"""
from __future__ import annotations
from typing import Callable
import re
import sys
_SKIP_CHARS = set(" \t\r\n\u3000\u00a0")

_DODGE_MARKERS = ("未涵盖", "未提及", "未涉及", "没有提及", "无相关资料", "资料不足", "未说明")

def _cjk_bigrams(text: str) -> set[str]:
    chars = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    return {chars[i:i + 2] for i in range(len(chars) - 1)}


def is_false_dodge(
    quote: str,
    new: str,
    evidence_text: str,
    sim_fn: Callable[[str, str], float] | None = None,
    sim_threshold: float = 0.8,
) -> bool:
    """拦截可能把已有依据改成“资料不足”的修订。

    中文二元字符覆盖率或可选相似度达到阈值时保留原句，交给后续复核。
    阈值是启发式参数，未达到阈值不表示修订正确。
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


def locate(text: str, quote: str) -> tuple[int, int] | None:
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


def apply_replacements(
    text: str,
    replacements: list[dict],
    evidence_text: str = '',
    sim_fn: Callable[[str, str], float] | None = None,
    evidence_map: dict[int, str] | None = None,
) -> tuple[str, list[dict], int]:
    """返回修订文本、实际应用的修改和删除数。

    无法定位或命中内容丢失检查的修改会被跳过；允许空字符串删除。
    本函数不判定最终是否通过，调用方必须复核修改后的文本。
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
