"""条款级元数据：材料类型、审核状态、主题与适用条件。

语料混有不同用途的材料，支持结论的强度不同：指南条款能支撑诊断解释与处置，
患者教育材料只能支撑通俗解释，草稿示例不能冒充已核对条款。这个模块把差异
显式化，供检索筛选、证据格式化和校验记录共用。

兼容规则（旧条款没有这些字段时）：
- 材料类型按已知来源登记补全（``SOURCE_MATERIAL_TYPES``），无法判断时记 unknown；
- 审核状态**不推断**，缺失一律表示 unknown，不自动提升为已审核；
- 主题缺失时按小节名推断，仅用于覆盖统计，不改变条款正文；
- 适用范围缺失时按「未记录」处理，调用方不能默认满足。
"""

from __future__ import annotations

from typing import Any, Iterable

# 材料类型：指南与共识支撑诊疗建议；病例资料仅供参照；患者教育不自动承担诊疗决策。
MATERIAL_TYPES = frozenset({
    "guideline", "consensus", "expert_consensus", "systematic_review",
    "case_report", "patient_education", "reference_text",
})
CLINICAL_MATERIAL_TYPES = frozenset({
    "guideline", "consensus", "expert_consensus", "systematic_review",
})
EDUCATION_MATERIAL_TYPES = frozenset({
    "patient_education", "guideline", "consensus", "expert_consensus",
    "systematic_review",
})

# 审核状态：只有 verified 表示原文与专业复核均已完成。
REVIEW_STATUSES = frozenset({"verified", "pending", "draft", "unknown"})

# 问题主题。与 report_focus 的主题词一一对应，新增主题需同时补检索词。
TOPICS = (
    "diagnosis", "interpretation", "examination",
    "differential", "treatment", "followup", "education",
)

TOPIC_MATERIAL_TYPES: dict[str, frozenset[str]] = {
    "diagnosis": CLINICAL_MATERIAL_TYPES,
    "interpretation": CLINICAL_MATERIAL_TYPES,
    "examination": CLINICAL_MATERIAL_TYPES,
    "differential": CLINICAL_MATERIAL_TYPES,
    "treatment": CLINICAL_MATERIAL_TYPES,
    "followup": CLINICAL_MATERIAL_TYPES,
    "education": EDUCATION_MATERIAL_TYPES,
}

MATERIAL_TYPE_LABELS = {
    "guideline": "指南条款", "consensus": "共识条款", "expert_consensus": "专家共识",
    "systematic_review": "系统综述", "case_report": "病例资料",
    "patient_education": "患者教育材料", "reference_text": "参考资料",
    "unknown": "材料类型未登记",
}
REVIEW_STATUS_LABELS = {
    "verified": "原文与专业复核均已完成",
    "pending": "原文核对或专业复核待完成",
    "draft": "草稿/示例材料，未完成核对",
    "unknown": "审核状态未登记",
}

# 旧语料兼容：按来源标识推断材料类型。只推断类型，不推断审核状态。
SOURCE_MATERIAL_TYPES = {
    "patient_education": ("nei-",),
    "guideline": ("cn-", "nice-", "aao-", "ada-", "uspstf-", "nhc-", "icdr-"),
}

APPLICABILITY_FIELDS = ("population", "region", "care_stage", "preconditions", "exclusions")
APPLICABILITY_LABELS = {
    "population": "人群", "region": "地区", "care_stage": "诊疗阶段",
    "preconditions": "前提条件", "exclusions": "不适用条件",
}
# 诊疗阶段的规范取值；语料可写中文短语，按关键词匹配。
CARE_STAGES = ("screening", "diagnosis", "treatment", "followup")
_CARE_STAGE_TERMS = {
    "screening": ("筛查",),
    "diagnosis": ("诊断", "初诊", "评估"),
    "treatment": ("治疗", "用药", "手术", "干预"),
    "followup": ("随访", "复查", "监测"),
}
_TOPIC_SECTION_TERMS = (
    ("diagnosis", ("诊断", "分型", "分级", "分期", "Diagnosis", "Definition",
                   "Classification", "Staging", "Diagnostic")),
    ("interpretation", ("判读", "解释", "判定", "表现", "Interpretation", "Findings",
                        "Grading", "Severity")),
    ("differential", ("鉴别", "Differential")),
    ("treatment", ("治疗", "处置", "用药", "手术", "干预", "Treatment", "Management",
                   "Therapy", "Intervention", "Prevention")),
    ("followup", ("随访", "复查", "监测", "Follow-up", "Follow up", "Followup",
                  "Monitoring", "Surveillance")),
    ("examination", ("检查", "影像", "筛查", "Examination", "Imaging", "OCT",
                     "Visual field", "Screening")),
    ("education", ("教育", "自我管理", "患者", "Education", "Patient information",
                   "Patient education", "Counselling", "Self-monitoring")),
)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def normalize_material_type(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    if text not in MATERIAL_TYPES:
        raise ValueError(f"Invalid material_type: {text}")
    return text


def normalize_review_status(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    if text not in REVIEW_STATUSES:
        raise ValueError(f"Invalid review_status: {text}")
    return text


def normalize_topic(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    if text not in TOPICS:
        raise ValueError(f"Invalid topic: {text}")
    return text


def normalize_disease_scope(value: Any) -> tuple[str, ...]:
    """病种范围接受字符串或字符串列表；空值表示沿用来源登记。"""
    if value is None:
        return ()
    if isinstance(value, str):
        items = value.replace("，", ",").split(",")
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise ValueError("disease must be a string or a list of strings")
    scope = tuple(item.strip() for item in items if isinstance(item, str) and item.strip())
    if any(not isinstance(item, str) for item in items):
        raise ValueError("disease entries must be strings")
    return scope


def parse_applicability(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("applicability must be an object")
    result: dict[str, str] = {}
    for key, raw in value.items():
        if key not in APPLICABILITY_FIELDS:
            raise ValueError(f"Invalid applicability field: {key}")
        if isinstance(raw, str):
            result[key] = raw.strip()
        elif isinstance(raw, (list, tuple)):
            if any(not isinstance(item, str) for item in raw):
                raise ValueError(f"applicability.{key} entries must be strings")
            result[key] = "；".join(item.strip() for item in raw if item.strip())
        else:
            raise ValueError(f"applicability.{key} must be a string or list")
    return {key: text for key, text in result.items() if text}


def source_material_type(source: str | None) -> str:
    name = _text(source).lower()
    for material_type, prefixes in SOURCE_MATERIAL_TYPES.items():
        if name.startswith(prefixes):
            return material_type
    return ""


def resolve_material_type(item: dict[str, Any]) -> str:
    explicit = normalize_material_type(item.get("material_type")) or source_material_type(item.get("source"))
    return explicit or "unknown"


def resolve_review_status(item: dict[str, Any]) -> str:
    """缺失状态明确表示为 unknown；不因来源看起来权威就当作已审核。"""
    return normalize_review_status(item.get("review_status")) or "unknown"


def infer_topic(section: str | None) -> str:
    text = _text(section)
    for topic, terms in _TOPIC_SECTION_TERMS:
        if any(term in text for term in terms):
            return topic
    return ""


def resolve_topic(item: dict[str, Any]) -> str:
    return normalize_topic(item.get("topic")) or infer_topic(item.get("section"))


def clause_diseases(item: dict[str, Any]) -> frozenset[str] | None:
    """条款级病种范围优先，其次来源登记；None 表示通用条款。

    显式登记为空集表示「明确无关」，必须与「未登记」区分开。
    """
    explicit = normalize_disease_scope(item.get("disease"))
    if explicit:
        return frozenset(explicit)
    from modules.knowledge.report_focus import source_diseases

    source = item.get("source")
    if source in _registered_sources():
        return frozenset(source_diseases(source))
    return None


def _registered_sources() -> frozenset[str]:
    from modules.knowledge.report_focus import SOURCE_DISEASES

    return frozenset(SOURCE_DISEASES)


def matches_case_disease(item: dict[str, Any], disease: str | None) -> bool:
    if not disease:
        return True
    scope = clause_diseases(item)
    return scope is None or disease in scope


def material_types_for_topic(topic: str | None) -> frozenset[str] | None:
    return TOPIC_MATERIAL_TYPES.get(topic or "")


def material_allowed(item: dict[str, Any], topic: str | None, requested: Iterable[str] | None = None) -> tuple[bool, str]:
    """该条款的材料类型能否支撑当前主题的问题。

    返回 (是否可用, 不可用原因)。材料类型未登记时按 unknown 处理，
    不满足需要正式条款的主题，避免用草稿或教育材料冒充诊疗依据。
    """
    allowed = material_types_for_topic(topic)
    if requested:
        requested_set = frozenset(item for item in requested if item)
        if requested_set:
            allowed = requested_set if allowed is None else allowed & requested_set
    if allowed is None:
        return True, ""
    material_type = resolve_material_type(item)
    if material_type in allowed:
        return True, ""
    return False, "material_type"


def _overlap(filter_value: str, clause_value: str) -> bool:
    left, right = filter_value.strip().lower(), clause_value.strip().lower()
    if not left or not right:
        return True
    return left in right or right in left


def _care_stage_matches(filter_value: str, clause_value: str) -> bool:
    if not filter_value:
        return True
    if not clause_value:
        return False
    if _overlap(filter_value, clause_value):
        return True
    terms = _CARE_STAGE_TERMS.get(filter_value.strip().lower(), ())
    return any(term in clause_value for term in terms)


def applicability_check(item: dict[str, Any], filters: dict[str, Any]) -> dict[str, Any]:
    """核对条款适用条件与检索筛选是否冲突。

    缺失的适用条件记为 unknown——不能默认满足；只有条款明确写了不匹配的
    取值才算 mismatch，并把该条款排除出证据包。
    """
    applicability = item.get("applicability") or {}
    if not isinstance(applicability, dict):
        applicability = {}
    unknown: list[str] = []
    mismatch: list[str] = []

    for field in APPLICABILITY_FIELDS:
        if applicability.get(field) and (field in {"preconditions", "exclusions"} or not filters.get(field)):
            unknown.append(field)

    population = _text(filters.get("population"))
    if population:
        clause_value = _text(applicability.get("population"))
        if not clause_value:
            unknown.append("population")
        elif not _overlap(population, clause_value):
            mismatch.append("population")

    care_stage = _text(filters.get("care_stage"))
    if care_stage:
        clause_value = _text(applicability.get("care_stage"))
        if not clause_value:
            unknown.append("care_stage")
        elif not _care_stage_matches(care_stage, clause_value):
            mismatch.append("care_stage")

    region = _text(filters.get("region"))
    if region:
        clause_value = _text(applicability.get("region")) or _text(item.get("jurisdiction"))
        if not clause_value:
            unknown.append("region")
        elif region.upper() not in {part.strip().upper() for part in clause_value.split("；")}:
            if clause_value.upper() not in {"INT", "GLOBAL"}:
                mismatch.append("region")

    return {"ok": not mismatch, "unknown": unknown, "mismatch": mismatch}


def clause_fit(
    item: dict[str, Any],
    topic: str | None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """该条款能否支撑某主题的问题。

    两条独立判断：材料类型是否足以支撑该主题；条款适用条件是否与检索筛选矛盾。
    缺失或无法核实的适用条件**不算矛盾**，在 `unknown` 里返回——调用方不能默认它们
    已满足，要把它们当作报告必须写明的前提，而不是据此丢弃条款。条款越完整地登记了
    前提与例外，越应该被采用，只是引用它时要把限制一起写出来。
    """
    filters = filters or {}
    usable, reason = material_allowed(item, topic, filters.get("material_types"))
    if not usable:
        return {"ok": False, "reason": reason, "unknown": [], "mismatch": []}
    check = applicability_check(item, filters)
    return {
        "ok": check["ok"],
        "reason": "" if check["ok"] else "applicability",
        "unknown": check["unknown"],
        "mismatch": check["mismatch"],
    }


def filter_evidence(
    items: Iterable[dict[str, Any]],
    *,
    topic: str | None,
    filters: dict[str, Any] | None = None,
    disease: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按病种、材料类型和适用条件筛选检索结果，返回 (可用, 被排除)。

    被排除项保留原因，供检索记录说明「为什么没有采用这条条款」，而不是悄悄丢弃。
    通过筛选的条款若带未核实的适用条件，只加 `applicability_unknown` 标注；标注
    随证据进入撰稿提示词与存档，不能当作「条件已满足」。
    """
    filters = filters or {}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in items:
        if not matches_case_disease(item, disease or _text(filters.get("disease")) or None):
            rejected.append({"id": item.get("id"), "source": item.get("source"), "reason": "disease_scope"})
            continue
        fit = clause_fit(item, topic, filters)
        if not fit["ok"]:
            record = {"id": item.get("id"), "source": item.get("source"), "reason": fit["reason"]}
            if fit["mismatch"]:
                record["fields"] = fit["mismatch"]
            rejected.append(record)
            continue
        accepted.append(
            {**item, "applicability_unknown": fit["unknown"]} if fit["unknown"] else item
        )
    return accepted, rejected


def evidence_metadata(item: dict[str, Any]) -> dict[str, Any]:
    """证据条目对外暴露的适用性与审核信息，写入提示词和校验记录。"""
    applicability = item.get("applicability") or {}
    return {
        "material_type": resolve_material_type(item),
        "review_status": resolve_review_status(item),
        "topic": resolve_topic(item),
        "disease": ",".join(item.get("disease") or ()) if isinstance(item.get("disease"), (list, tuple))
        else _text(item.get("disease")),
        "applicability": applicability if isinstance(applicability, dict) else {},
        "content_hash": _text(item.get("content_hash")),
        "version": _text(item.get("version")),
        "url": _text(item.get("url")),
    }
