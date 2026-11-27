"""把病例输入整理为可回溯的事实条目。

报告流程需要先分清「用户提供了什么」「影像模型输出了什么」「缺什么」「哪里有
冲突」，再决定要检索哪些问题。本模块只做整理，不做医学判断：

- 每条事实带稳定标识、眼别和原始位置（备注字符区间或模型字段路径）；
- 备注原文按句保留，不重写措辞；「未提供」不会被改写成「未检查」；
- 影像模型分数原样保留为模型输出，不转成诊断、排除或分期；
- 单眼影像不会被推断到另一眼；眼别未标注时按未知处理并记为缺口。

抽取结果是后续检索规划、提示词和核查共用的证据底稿，必须能回到原始输入。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

EYE_UNKNOWN = "unknown"
EYE_BOTH = "both"
EYE_LABELS_ZH = {
    "right": "右眼", "left": "左眼", "both": "双眼", "unknown": "眼别未标注",
}
_EYE_PATTERNS = (
    (EYE_BOTH, re.compile(r"双眼|双侧|OU\b|BOU\b", re.IGNORECASE)),
    ("right", re.compile(r"右眼|右側|右侧|OD\b", re.IGNORECASE)),
    ("left", re.compile(r"左眼|左側|左侧|OS\b", re.IGNORECASE)),
)
EYE_INPUTS = {"right": "right", "left": "left", "right eye": "right", "left eye": "left"}

# 检查/测量关键词。用于判断备注里已经提供了哪类资料，以及缺失信息。
EXAM_TERMS: dict[str, tuple[str, ...]] = {
    "iop": ("眼压", "IOP"),
    "cdr": ("杯盘比", "C/D", "CDR", "视杯"),
    "visual_field": ("视野",),
    "gonioscopy": ("房角", "前房角"),
    "oct": ("OCT", "光学相干", "黄斑扫描"),
    "fundus_photo": ("眼底照相", "眼底照", "眼底像"),
    "acuity": ("视力", "矫正视力"),
    "rnfl": ("RNFL", "神经纤维层"),
    "ffa": ("荧光素", "FFA", "荧光血管"),
    "grading": ("分级", "分期", "非增殖", "增殖期"),
    "macular": ("黄斑水肿", "DME", "黄斑"),
    "subtype": ("干性", "湿性", "萎缩型", "新生血管"),
}
EXAM_LABELS = {
    "iop": "眼压", "cdr": "视盘/杯盘比", "visual_field": "视野", "gonioscopy": "房角",
    "oct": "OCT 黄斑结构", "fundus_photo": "眼底照相", "acuity": "视力",
    "rnfl": "视网膜神经纤维层", "ffa": "荧光血管造影", "grading": "糖网分级/分期",
    "macular": "黄斑评估", "subtype": "干性/湿性分型",
}
# 每病种影响判断的关键资料。缺失时记为缺口，不推断检查是否做过。
REQUIRED_INFO: dict[str, tuple[str, ...]] = {
    "glaucoma": ("iop", "cdr", "visual_field", "gonioscopy"),
    "diabetic_retinopathy": ("grading", "macular", "oct"),
    "age_related_macular_degeneration": ("subtype", "oct", "acuity"),
}
DIAGNOSIS_MARKERS = ("诊断", "确诊", "既往", "病史", "患有", "已行", "曾行")
MISSING_MARKERS = ("未提供", "未检查", "未采集", "未做", "未行", "缺失", "未查")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def normalize_eye(value: str | None) -> str:
    text = (value or "").strip().lower()
    if text in EYE_INPUTS:
        return EYE_INPUTS[text]
    return EYE_UNKNOWN


def detect_eye(text: str) -> str:
    for eye, pattern in _EYE_PATTERNS:
        if pattern.search(text):
            return eye
    return EYE_UNKNOWN


def detect_exams(text: str) -> tuple[str, ...]:
    found = []
    for key, terms in EXAM_TERMS.items():
        if any(term.lower() in text.lower() for term in terms):
            found.append(key)
    return tuple(found)


def _numbers(text: str) -> tuple[str, ...]:
    """归一化数值，供「同一眼同一检查出现不同取值」比较。"""
    values = []
    for raw in _NUMBER.findall(text):
        try:
            values.append(format(float(raw), "g"))
        except ValueError:
            continue
    return tuple(values)


def _fact_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]
    return f"cf-{prefix}{digest}"


@dataclass(frozen=True)
class CaseFact:
    id: str
    kind: str
    eye: str
    text: str
    source: str
    location: str
    disease: str = ""
    exams: tuple[str, ...] = ()
    numbers: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "eye": self.eye,
            "disease": self.disease, "text": self.text,
        }


@dataclass
class CaseFacts:
    note: str
    facts: list[CaseFact] = field(default_factory=list)
    missing: list[CaseFact] = field(default_factory=list)
    conflicts: list[CaseFact] = field(default_factory=list)
    diseases: tuple[str, ...] = ()
    declared_eye: str = EYE_UNKNOWN

    @property
    def all(self) -> list[CaseFact]:
        return [*self.facts, *self.missing, *self.conflicts]

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return tuple(fact.id for fact in self.facts)

    @property
    def has_model_output(self) -> bool:
        return any(fact.source == "imaging_model" for fact in self.facts)

    def key_features(self) -> str:
        """少量关键病例特征，供检索查询组合，避免把整份病例拼进每个查询。"""
        terms: list[str] = []
        if self.declared_eye in ("right", "left"):
            terms.append(EYE_LABELS_ZH[self.declared_eye])
        for fact in self.facts:
            for exam in fact.exams:
                label = EXAM_LABELS.get(exam)
                if label:
                    terms.append(label)
            if not fact.exams and fact.kind == "documented_diagnosis":
                terms.append("既往诊断")
        return " ".join(dict.fromkeys(terms))[:120]

    def prompt_block(self) -> str:
        """给检索规划的病例事实（纯数据，不含任何指令）。"""
        items = [fact.as_dict() for fact in self.facts]
        items += [{"id": fact.id, "kind": fact.kind, "eye": fact.eye, "disease": fact.disease,
                   "text": fact.text} for fact in (*self.missing, *self.conflicts)]
        return json.dumps(items, ensure_ascii=False, indent=None)

    def gaps_note(self) -> str:
        """写入撰稿上下文的缺失与冲突说明，供报告的限制一节如实写出。"""
        parts = []
        if self.missing:
            parts.append("未提供的资料（不等于未检查，也不能据此判断阴性）："
                         + "、".join(fact.text for fact in self.missing))
        if self.conflicts:
            parts.append("病例记录存在冲突（保留差异，不合并为确定结论）："
                         + "；".join(fact.text for fact in self.conflicts))
        return " ".join(parts)

    def verification_context(self) -> str:
        """核查用的病例上下文：原文在前，事实与缺口在后。

        备注原文必须保留——校验器用它核对病例复述；结构化事实只作补充，
        明确标为输入整理结果，不是诊断。
        """
        lines = ["Clinician note: " + (self.note.strip() or "No clinical note provided."), "",
                 "Case facts extracted from the input (stable ids; these are not diagnoses):"]
        for fact in self.facts:
            lines.append(f"- {fact.id} [{fact.kind}/{fact.eye}] {fact.text}")
        for fact in self.missing:
            lines.append(f"- {fact.id} [missing/{fact.eye}] {fact.text}")
        for fact in self.conflicts:
            lines.append(f"- {fact.id} [conflict/{fact.eye}] {fact.text}")
        return "\n".join(lines)

    def summary(self) -> dict[str, Any]:
        return {
            "case_sha256": hashlib.sha256(self.note.encode("utf-8")).hexdigest(),
            "declared_eye": self.declared_eye,
            "fact_count": len(self.facts),
            "diseases": list(self.diseases),
            "missing": [{"id": f.id, "eye": f.eye, "text": f.text} for f in self.missing],
            "conflicts": [{"id": f.id, "eye": f.eye, "text": f.text} for f in self.conflicts],
        }


def _note_facts(note: str) -> list[CaseFact]:
    facts: list[CaseFact] = []
    # 双眼常写在同一句，以逗号分隔；仅在逗号后出现眼别时另起事实。
    eye_clause = r"[,，]\s*(?=右眼|左眼|右侧|左侧|OD\b|OS\b)"
    for match in re.finditer(rf"(?:(?!{eye_clause})[^。！？\n；;])+", note, re.IGNORECASE):
        text = match.group(0).strip()
        if len(text) < 2:
            continue
        eye = detect_eye(text)
        exams = detect_exams(text)
        if any(marker in text for marker in DIAGNOSIS_MARKERS):
            kind = "documented_diagnosis"
        elif exams:
            kind = "documented_exam"
        else:
            kind = "user_record"
        facts.append(CaseFact(
            id=_fact_id("note", text, str(match.start())), kind=kind, eye=eye, text=text,
            source="clinical_note", location=f"note[{match.start()}:{match.end()}]",
            exams=exams, numbers=_numbers(text),
        ))
    return facts


def _model_facts(
    findings: dict[str, dict[str, Any]], declared_eye: str,
) -> list[CaseFact]:
    facts: list[CaseFact] = []
    for disease, finding in findings.items():
        fields: list[tuple[str, str, Any, str]] = []
        if finding.get("probability") is not None:
            fields.append(("probability", "分类模型输出概率", finding["probability"], "probability"))
        if finding.get("prompt_similarity_margin") is not None:
            fields.append(("margin", "FLAIR 提示词匹配差值（研究用途）",
                           finding["prompt_similarity_margin"], "probability"))
        for name, value in (finding.get("measurements") or {}).items():
            fields.append((name, name, value, "cdr" if name == "area_equivalent_cdr" else ""))
        for index, warning in enumerate(finding.get("warnings") or [], 1):
            fields.append((f"warning-{index}", "影像模型告警", warning, ""))
        for key, label, value, exam in fields:
            if isinstance(value, float):
                text = f"{label} = {value:.6f}"
            else:
                text = f"{label}: {value}"
            facts.append(CaseFact(
                id=f"cf-model-{disease}-{key}".replace(" ", "-"),
                kind="model_output", eye=declared_eye, text=text, source="imaging_model",
                location=f"model:{disease}.{key}", disease=disease,
                exams=(exam,) if exam else (), numbers=_numbers(text),
            ))
    return facts


def _submission_facts(
    *, declared_eye: str, laterality: str | None, captured_at: str | None,
    device: str, synthetic: bool, filename: str,
) -> list[CaseFact]:
    entries: list[tuple[str, str]] = []
    if laterality:
        entries.append(("laterality", f"上传影像眼别标记：{EYE_LABELS_ZH[declared_eye]}"))
    if captured_at:
        entries.append(("captured_at", f"采集时间：{captured_at}"))
    if device:
        entries.append(("device", f"采集设备：{device}"))
    if filename:
        entries.append(("filename", f"上传文件名：{filename}"))
    if synthetic:
        entries.append(("synthetic", "用户声明为合成病例"))
    return [
        CaseFact(
            id=f"cf-input-{key}", kind="user_record", eye=EYE_UNKNOWN, text=text,
            source="submission", location=f"submission:{key}", numbers=_numbers(text),
        )
        for key, text in entries
    ]


def _missing_facts(
    findings: dict[str, dict[str, Any]], facts: list[CaseFact], declared_eye: str,
) -> list[CaseFact]:
    available: set[str] = set()
    for fact in facts:
        available.update(fact.exams)
    missing: list[CaseFact] = []
    for disease in findings:
        for exam in REQUIRED_INFO.get(disease, ()):
            if exam in available:
                continue
            missing.append(CaseFact(
                id=f"cf-gap-{disease}-{exam}", kind="missing", eye=declared_eye,
                text=f"未提供{EXAM_LABELS[exam]}资料",
                source="case", location=f"gap:{disease}.{exam}", disease=disease, exams=(exam,),
            ))
    if findings and declared_eye == EYE_UNKNOWN:
        missing.append(CaseFact(
            id="cf-gap-laterality", kind="missing", eye=EYE_UNKNOWN,
            text="影像结果未标注眼别，无法按眼确认结论归属",
            source="case", location="gap:laterality",
        ))
    return missing


def _conflict_facts(
    facts: list[CaseFact], laterality: str | None, declared_eye: str,
) -> list[CaseFact]:
    conflicts: list[CaseFact] = []
    note_facts = [fact for fact in facts if fact.source == "clinical_note"]

    if laterality and declared_eye in ("right", "left"):
        # 只有另一眼确实带检查数据时才构成冲突；「左眼未提供检查」这类
        # 说明缺口的话不是矛盾，不能报成冲突。
        others = [
            fact for fact in note_facts
            if fact.eye in ("right", "left") and fact.eye != declared_eye
            and (fact.exams or fact.numbers)
            and not any(marker in fact.text for marker in MISSING_MARKERS)
        ]
        if others:
            target = EYE_LABELS_ZH[others[0].eye]
            conflicts.append(CaseFact(
                id=_fact_id("conflict-eye", declared_eye, others[0].id), kind="conflict",
                eye=declared_eye,
                text=(f"上传影像标注为{EYE_LABELS_ZH[declared_eye]}眼，"
                      f"但病例记录含{target}描述（{others[0].id}），不能合并为同一眼结论"),
                source="case", location="conflict:laterality",
            ))

    # 同一眼、同一检查出现不同数值：保留冲突，不替用户选一个。
    # 一句话里混有多种检查（如眼压与杯盘比）时无法把数值可靠归到某一检查，
    # 这类记录不做数值冲突比较，避免把两个不同指标误报成矛盾。
    groups: dict[tuple[str, str], list[CaseFact]] = {}
    for fact in note_facts:
        if fact.eye not in ("right", "left") or len(fact.exams) != 1 or not fact.numbers:
            continue
        groups.setdefault((fact.eye, fact.exams[0]), []).append(fact)
    for (eye, exam), items in groups.items():
        values = sorted({number for item in items for number in item.numbers})
        if len(values) < 2:
            continue
        conflicts.append(CaseFact(
            id=_fact_id("conflict-value", eye, exam, *values), kind="conflict", eye=eye,
            text=(f"{EYE_LABELS_ZH[eye]}{EXAM_LABELS[exam]}记录存在不同取值："
                  + "、".join(values) + "（" + "、".join(item.id for item in items) + "）"),
            source="case", location="conflict:value", exams=(exam,),
        ))
    return conflicts


def build_case_facts(
    findings: dict[str, dict[str, Any]] | None = None,
    note: str = "",
    *,
    laterality: str | None = None,
    captured_at: str | None = None,
    device: str = "",
    synthetic: bool = False,
    filename: str = "",
) -> CaseFacts:
    """按来源整理病例事实。findings 是影像模型结果（逐病种 dict）。"""
    findings = findings or {}
    declared_eye = normalize_eye(laterality)
    facts = _note_facts(note)
    facts += _model_facts(findings, declared_eye)
    facts += _submission_facts(
        declared_eye=declared_eye, laterality=laterality, captured_at=captured_at,
        device=device, synthetic=synthetic, filename=filename,
    )
    return CaseFacts(
        note=note, facts=facts,
        missing=_missing_facts(findings, facts, declared_eye),
        conflicts=_conflict_facts(facts, laterality, declared_eye),
        diseases=tuple(findings),
        declared_eye=declared_eye,
    )
