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
    """忽略空白及成对的简单 Markdown 标记，保留可见字符到原文的映射。"""
    markers = set()
    for match in re.finditer(r"\*\*\S[^\n]*?\*\*|__\S[^\n]*?__|`[^`\n]+`", text):
        size = 1 if match[0].startswith('`') else 2
        markers.update(range(match.start(), match.start() + size))
        markers.update(range(match.end() - size, match.end()))
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if ch in _SKIP_CHARS or i in markers:
            continue
        chars.append(ch)
        index.append(i)
    return "".join(chars), index


def visible_text(text: str) -> str:
    return _norm_index(text)[0]


def locate(text: str, quote: str) -> tuple[int, int] | None:
    """在 text 里定位 quote，返回 (start, end) 或 None。

    仅接受唯一的完整匹配或去空白后的完整匹配，不按句首猜测位置。
    """
    if not quote:
        return None
    pos = text.find(quote)
    if pos >= 0:
        return (pos, pos + len(quote)) if text.count(quote) == 1 else None

    norm, index = _norm_index(text)
    target = visible_text(quote)
    if not target:
        return None

    hit = norm.find(target)
    if hit >= 0 and norm.count(target) == 1:
        end = hit + len(target)
        start, stop = index[hit], index[end - 1] + 1
        for marker in ('**', '__', '`'):
            if text[start:stop].count(marker) % 2:
                if text[:start].endswith(marker):
                    start -= len(marker)
                elif text[stop:].startswith(marker):
                    stop += len(marker)
        return start, stop

    return None


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
    allowed_quotes: list[str] | None = None,
    protected_facts: list[str] | None = None,
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
        if allowed_quotes is not None and _norm_index(quote)[0] not in {
            _norm_index(allowed)[0] for allowed in allowed_quotes
        }:
            continue
        new = rep.get("new")
        new = "" if new is None else str(new).strip()
        if any(_norm_index(fact)[0] in _norm_index(quote)[0]
               and _norm_index(fact)[0] not in _norm_index(new)[0] for fact in protected_facts or []):
            continue

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
        if _norm_index(text[start:end])[0] == _norm_index(new)[0]:
            continue
        text = f"{text[:start]}{new}{text[end:]}"
        if not new:
            deleted += 1
        applied.append({
            "quote": quote,
            "new": new,
            "citations": rep.get("citation") or rep.get("citations") or [],
        })

    # 删除整句后会留下空行和多余空格
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, applied, deleted


def omit_local_issues(text: str, issues: list[dict]) -> tuple[str, list[dict]]:
    """一次性删去可唯一精确定位的非核心问题，返回待整篇复核的文本。"""
    if not issues or any(item.get("impact", "core") != "local" for item in issues):
        return text, []
    spans: dict[tuple[int, int], dict] = {}
    for item in issues:
        quote = item["quote"]
        span = locate(text, quote)
        if span is None:
            return text, []
        start, end = span
        prefix = text[:start].rsplit("\n", 1)[-1]
        if not re.search(r"(?:^|[。！？.!?；;])\s*(?:[-*+]|\d+[.)、])?\s*$", prefix):
            return text, []
        tail = text[end:].split("\n", 1)[0]
        if tail.strip() in ("。", ".", "！", "!", "？", "?"):
            end += len(tail)
            tail = ""
        if tail.strip() and quote[-1] not in "。！？.!?；;":
            return text, []
        item = {**item, "quote": text[start:end]}
        if re.fullmatch(r"\s*(?:[-*+]|\d+[.)、])\s*", prefix):
            start -= len(prefix)
        spans[(start, end)] = item
    ordered = sorted(spans)
    if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
        return text, []
    applied = []
    for start, end in reversed(ordered):
        item = spans[(start, end)]
        text = text[:start] + text[end:]
        applied.append({
            "quote": item["quote"], "new": "", "citations": item.get("citations", []),
            "impact": "local", "reason": item.get("reason", ""), "method": "local_omission",
        })
    lines = text.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        heading = re.match(r"^\s{0,3}(#{1,6})\s+", lines[index])
        if not heading:
            continue
        end = index + 1
        while end < len(lines):
            next_heading = re.match(r"^\s{0,3}(#{1,6})\s+", lines[end])
            if next_heading and len(next_heading[1]) <= len(heading[1]):
                break
            end += 1
        if not any(line.strip() for line in lines[index + 1:end]):
            del lines[index:end]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return cleaned, list(reversed(applied))
