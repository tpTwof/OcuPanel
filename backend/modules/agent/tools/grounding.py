"""检查通过内容的来源指针。片段存在性由代码检查，语义支持仍由模型评估。"""
import re
from typing import Any
from modules.agent.tools.text_revision import visible_text

SOFTWARE_BOUNDARY = (
    "视觉模型用于研究性辅助分析。分类概率、面积等效杯盘比或研究匹配分数不能单独确诊、"
    "排除疾病、判定分期或进展。面积等效杯盘比不等同于垂直杯盘比。"
    "未拍摄的眼别不能因对侧照片而得到影像评估。引用校验不等于临床验证或医生签发。"
    "本报告不对资料未涵盖的病因或关联作推断，不能为未提供的信息补值。"
    "具体检查、治疗与随访安排由接诊医生决定，软件不自行生成未获资料支持的方案。"
)
BASES = {"case_fact", "medical_knowledge", "case_inference", "general_advice", "recommendation", "software_limit", "scope_limit"}


class GroundingSupportError(ValueError):
    """格式可读，但声称通过的断言缺少有效来源。"""


def _contains(source: str, quote: str) -> bool:
    if quote.strip() and quote in source:
        return True
    content = visible_text(quote)
    return bool(content) and content in visible_text(source)


def _exists_in_evidence(quote: str, evidence_map: dict) -> bool:
    """这段引文是否逐字存在于任意一条证据里。"""
    return bool(quote.strip()) and any(_contains(text, quote) for text in evidence_map.values())


def _evidence_number_of(quote: str, evidence_map: dict) -> int:
    """返回包含该引文的证据编号；调用前须确认 _exists_in_evidence 通过。"""
    for number in sorted(evidence_map):
        if _contains(evidence_map[number], quote):
            return number
    raise ValueError("quote not found in any evidence")


def report_statements(text: str) -> list[dict[str, str]]:
    clauses = []
    for line in text.splitlines():
        if not line.strip() or re.match(r"^\s*#{1,6}\s", line):
            continue
        for match in re.finditer(r".+?(?:[。！？!?；;，]|(?<!\d),(?!\d)|\.(?=\s+[A-Z])|$)", line):
            if match[0].strip():
                clauses.append(match[0].strip())
    return [{"id": f"R{index}", "text": clause} for index, clause in enumerate(clauses, 1)]


def covers_citations(text: str, entries: list[dict]) -> bool:
    normalized = visible_text(text)
    expected = {match.start() for match in re.finditer(r"\[-?\d+\]", normalized)}
    covered = set()
    for entry in entries:
        quote = visible_text(entry["quote"])
        start = normalized.find(quote)
        while start >= 0:
            end = start + len(quote)
            trailing = re.match(r"(?:\[\d+\])+", normalized[end:])
            if trailing:
                end += len(trailing[0])
            for match in re.finditer(r"\[(-?\d+)\]", normalized[start:end]):
                if int(match[1]) in entry["citations"]:
                    covered.add(start + match.start())
            start = normalized.find(quote, start + 1)
    return expected.issubset(covered)


def parse_grounding(data: dict, text: str, evidence: list[dict], case_context: str, *, required: bool) -> list[dict]:
    entries = data.get("grounding")
    if entries is None and not required:
        return []
    if not isinstance(entries, list):
        raise ValueError("grounding must be an array of accepted clauses and source excerpts")
    evidence_map = {item.get("index", index): item.get("text", "") for index, item in enumerate(evidence, 1)}
    accepted: list[dict[str, Any]] = []
    statements = {item['id']: item['text'] for item in report_statements(text)}
    for index, entry in enumerate(entries):
        path = f"grounding[{index}]"
        if isinstance(entry, dict) and entry.get('statement_id') is not None:
            statement_id = entry['statement_id']
            if not isinstance(statement_id, str) or statement_id not in statements:
                raise ValueError(f"{path}.statement_id must identify a current report statement")
            actual = statements[statement_id]
            # 提示词允许只给 statement_id（省 token）；此时按位置直接取正文原句。
            if not isinstance(entry.get('quote'), str) or not _contains(actual, entry['quote']):
                entry = {**entry, 'quote': actual, 'quote_resolution': 'statement_id',
                         'reported_quote': entry.get('quote')}
        if not isinstance(entry, dict) or not isinstance(entry.get("quote"), str) or not _contains(text, entry["quote"]):
            raise ValueError(f"{path}.quote must match the current report")
        basis = entry.get("basis")
        if not isinstance(basis, str) or basis not in BASES:
            raise ValueError(f"{path}.basis must classify the accepted clause")
        citations = entry.get("citations", [])
        if not isinstance(citations, list) or any(type(number) is not int or number not in evidence_map for number in citations):
            raise ValueError(f"{path}.citations must reference known evidence numbers")
        sources = entry.get("sources", [])
        if not isinstance(sources, list):
            raise ValueError(f"{path}.sources must be an array")
        sources = list(sources)
        if basis in {'case_fact', 'case_inference'} and case_context and not any(
                isinstance(source, dict) and source.get('kind') == 'case' for source in sources):
            sources.append({'kind': 'case', 'quote': case_context, 'excerpt_kind': 'source_snapshot'})
        if basis == 'software_limit' and not any(
                isinstance(source, dict) and source.get('kind') == 'policy' for source in sources):
            sources.append({'kind': 'policy', 'quote': SOFTWARE_BOUNDARY, 'excerpt_kind': 'source_snapshot'})
        kinds, supported_numbers = set(), set()
        resolved_sources = []
        evidence_sources = 0
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get("quote", ""), str):
                raise ValueError(f"{path}.sources must contain source excerpts")
            kind = source.get("kind")
            if kind == "case":
                content = case_context
            elif kind == "policy":
                content = SOFTWARE_BOUNDARY
            elif kind == "evidence" and type(source.get("index")) is int and source["index"] in citations:
                content = evidence_map[source["index"]]
                if basis == "scope_limit":
                    original = next(item for number, item in enumerate(evidence, 1)
                                    if item.get('index', number) == source['index'])
                    content += '\n' + '\n'.join(str(original[key]) for key in
                                                ('scope', 'jurisdiction', 'version', 'title', 'url') if original.get(key))
                supported_numbers.add(source["index"])
                evidence_sources += 1
            else:
                raise ValueError(f"{path}.sources must identify case, policy or cited evidence")
            if not _contains(content, source.get("quote", "")):
                if (kind in {"case", "policy"} or basis == 'scope_limit') and content:
                    source = {**source, "quote": content, "excerpt_kind": "source_snapshot",
                              "reported_quote": source.get("quote", "")}
                elif kind == "evidence" and _exists_in_evidence(source.get("quote", ""), evidence_map):
                    # 原文真实存在于某条证据、只是编号标错了：改记到实际来源上。
                    # 语义是否支持仍由校验模型判断，这里只保证引文不是编造的。
                    reported = source["index"]
                    actual = _evidence_number_of(source["quote"], evidence_map)
                    supported_numbers.discard(reported)
                    supported_numbers.add(actual)
                    citations = [actual if number == reported else number for number in citations]
                    source = {**source, "index": actual, "excerpt_kind": "renumbered",
                              "reported_index": reported}
                else:
                    raise GroundingSupportError(
                        f"{path}.sources quote must be copied verbatim from evidence "
                        f"[{source['index']}]; the reported text was not found in it")
            kinds.add(kind)
            resolved_sources.append(source)
        # 引文编号笔误已在上方改记到实际来源，此处只核对「每条引用都有原文」。
        if evidence_sources and not set(citations).issubset(supported_numbers):
            raise GroundingSupportError(f"{path} must include an original excerpt for every citation")
        if basis in {"medical_knowledge", "recommendation", "case_inference"} and not citations:
            raise GroundingSupportError(f"{path} needs evidence support; list unsupported assertions in claims")
        if basis in {"case_fact", "case_inference"} and "case" not in kinds:
            raise GroundingSupportError(f"{path} needs an original case excerpt")
        if basis == "software_limit" and "policy" not in kinds:
            raise GroundingSupportError(f"{path} needs a software boundary excerpt")
        if basis == "scope_limit" and not kinds:
            raise GroundingSupportError(f"{path} needs case or policy context for the stated limitation")
        if basis in {"case_fact", "general_advice", "software_limit"} and citations:
            raise GroundingSupportError(f"{path} must separate case data or general advice from externally cited clauses")
        advice = re.sub(r'^\s*(?:[-*+]\s*)?\d+[.)、]\s*', '', entry['quote'])
        if basis == "general_advice" and re.search(r"\d|每[日天周月年]|\b(?:mg|mcg|mmHg)\b", advice, re.I):
            raise GroundingSupportError(f"{path} cannot classify quantities or explicit schedules as general advice")
        accepted.append({**entry, "citations": citations, "sources": resolved_sources})
    return accepted


def audit_grounding(data: dict, text: str, evidence: list[dict], case_context: str, *, required: bool) -> tuple[list[dict], list[dict]]:
    entries = data.get("grounding")
    if entries is None and not required:
        return [], []
    if not isinstance(entries, list):
        raise ValueError("grounding must be an array of accepted clauses and source excerpts")
    accepted, issues = [], []
    statements = {item['id']: item['text'] for item in report_statements(text)}
    for index, entry in enumerate(entries):
        if isinstance(entry, dict) and isinstance(entry.get('statement_id'), str) and entry['statement_id'] in statements:
            actual = statements[entry['statement_id']]
            if not isinstance(entry.get('quote'), str) or not _contains(actual, entry['quote']):
                entry = {**entry, 'quote': actual, 'quote_resolution': 'statement_id',
                         'reported_quote': entry.get('quote')}
        try:
            accepted.extend(parse_grounding({'grounding': [entry]}, text, evidence, case_context, required=True))
        except GroundingSupportError as exc:
            issues.append({
                "quote": entry["quote"], "basis": entry["basis"], "impact": "core",
                "citations": entry.get("citations", []),
                "verdict": "unsupported" if entry.get("citations") else "uncited",
                "reason": "来源对照未证实支持：" + str(exc).replace('grounding[0]', f'grounding[{index}]') +
                "；病例复述或不作推断的声明应核对归类，新增医学关联则补充依据或删除。",
                "origin": "source_audit",
            })
    return accepted, issues
