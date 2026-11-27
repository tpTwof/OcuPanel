"""影像报告按用户所选病种检索；这些是查询词，不是患者诊断。

报告正文固定要说四件事：当前评估、关键依据、下一步处置、随访安排。单条长查询
只能把「诊断评估」类条款排到前面，判读与随访类条款会被长病例文本稀释——实测
「弓形暗点」条款排第 16、「目标眼压」排第 21，报告因此写不出可直接引用的
判读与治疗目标依据。所以按四个方面分别检索，再合并去重。
"""

DISEASE_FOCUS = {
    "glaucoma": (
        "青光眼 glaucoma POAG 诊断评估 房角 视神经 RNFL 视野 眼压 "
        "目标眼压 降眼压治疗 随访 复查间隔 进展"
    ),
    "diabetic_retinopathy": (
        "糖尿病视网膜病变 diabetic retinopathy DR 评估 分级 分期 黄斑 "
        "黄斑水肿 抗VEGF 全视网膜光凝 激光 随访 复查"
    ),
    "age_related_macular_degeneration": (
        "年龄相关性黄斑变性 age-related macular degeneration AMD 评估 "
        "干性 湿性 玻璃膜疣 叶黄素 营养补充 随访 复查"
    ),
}

# 每个方面各自的检索词。顺序即合并时的优先次序；同一方面内仍按检索得分排序。
REPORT_TOPICS: dict[str, tuple[tuple[str, str], ...]] = {
    "glaucoma": (
        ("diagnosis", "开角型青光眼 诊断 房角 眼压 杯盘比 视神经"),
        ("interpretation", "视野缺损 弓形暗点 鼻侧阶梯 神经纤维层变薄 判读"),
        ("treatment", "目标眼压 降眼压 前列腺素 激光 手术 治疗目标"),
        ("followup", "随访间隔 复查眼压 视野复查 进展 依从性"),
    ),
    "diabetic_retinopathy": (
        ("diagnosis", "糖尿病视网膜病变 非增殖 增殖 微血管瘤"),
        ("interpretation", "黄斑水肿 OCT 硬性渗出 中心受累"),
        ("treatment", "抗VEGF 全视网膜光凝 激光 转诊"),
        ("followup", "随访间隔 复查 筛查"),
    ),
    "age_related_macular_degeneration": (
        ("diagnosis", "年龄相关性黄斑变性 干性 湿性 玻璃膜疣"),
        ("interpretation", "玻璃膜疣 地图样萎缩 视物变形"),
        ("treatment", "抗VEGF 叶黄素 营养补充 AREDS"),
        ("followup", "随访 复查 自我监测 阿姆斯勒"),
    ),
}


# 按问题主题组织的检索词。旧流程用 REPORT_TOPICS 固定覆盖四个方面；
# 新流程由检索规划 Agent 决定本病例需要哪些主题，这里只是每个主题的主题词，
# 不预设任何病例必须检索全部主题。
TOPIC_QUERIES: dict[str, dict[str, str]] = {
    "glaucoma": {
        "diagnosis": "开角型青光眼 诊断 房角 眼压 杯盘比 视神经 危险因素",
        "interpretation": "视野缺损 弓形暗点 鼻侧阶梯 神经纤维层变薄 RNFL 判读 进展",
        "examination": "眼压测量 房角镜检查 视野检查 视神经成像 OCT 检查目的 复查条件",
        "differential": "鉴别诊断 高眼压症 生理性大视杯 其他视神经病变 视野缺损鉴别",
        "treatment": "目标眼压 降眼压 前列腺素 激光 手术 治疗选择 转诊",
        "followup": "随访间隔 复查眼压 视野复查 进展 依从性 目标眼压",
        "education": "患者教育 依从性 自我管理 用药 症状变化 求助",
    },
    "diabetic_retinopathy": {
        "diagnosis": "糖尿病视网膜病变 诊断 分级 分期 非增殖 增殖 转诊指征",
        "interpretation": "黄斑水肿 OCT 硬性渗出 中心受累 判读",
        "examination": "眼底照相 散瞳 筛查 OCT 检查目的 复查条件",
        "differential": "鉴别诊断 高血压视网膜病变 视网膜静脉阻塞 黄斑水肿鉴别",
        "treatment": "抗VEGF 全视网膜光凝 激光 转诊 治疗条件",
        "followup": "随访间隔 复查 筛查 妊娠 进展",
        "education": "患者教育 血糖 控制 自我管理 定期检查 症状变化",
    },
    "age_related_macular_degeneration": {
        "diagnosis": "年龄相关性黄斑变性 诊断 干性 湿性 玻璃膜疣 分型",
        "interpretation": "玻璃膜疣 地图样萎缩 视物变形 脉络膜新生血管 OCT 判读",
        "examination": "OCT 眼底照相 视力 阿姆斯勒 Amsler 检查目的",
        "differential": "鉴别诊断 近视性黄斑病变 黄斑水肿 视网膜前膜",
        "treatment": "抗VEGF 叶黄素 营养补充 AREDS 治疗条件 转诊",
        "followup": "随访 复查 自我监测 阿姆斯勒 OCT 复查间隔",
        "education": "患者教育 自我监测 阿姆斯勒 戒烟 营养 求助",
    },
}


def report_topics(disease: str) -> tuple[str, ...]:
    """旧流程固定覆盖的四个方面；未登记的病种退化为单一整句检索。"""
    topics = REPORT_TOPICS.get(disease)
    return tuple(query for _, query in topics) if topics else ()


def topic_query(disease: str, topic: str) -> str:
    """该病种某主题的检索词。

    新主题未登记时回退到旧流程的四个方面，再回退到病种整体检索词——
    宁可退化为旧行为，也不要让未登记主题变成空查询。
    """
    query = TOPIC_QUERIES.get(disease, {}).get(topic, "")
    if query:
        return query
    legacy = dict(REPORT_TOPICS.get(disease, ()))
    return legacy.get(topic) or DISEASE_FOCUS.get(disease, disease)

# 来源级病种归属。条款只属于其来源登记的检索病种，防止把妊娠期糖网、白内障
# 或筛查类条款塞进青光眼报告。未登记的来源视为通用条款，不受限制；
# 下面显式登记为空集的两个来源与三个报告病种无关，任何病种下都不参与。
SOURCE_DISEASES: dict[str, frozenset[str]] = {
    "cn-glaucoma-2020": frozenset({"glaucoma"}),
    "cn-glaucoma-followup": frozenset({"glaucoma"}),
    "nice-ng81": frozenset({"glaucoma"}),
    "nice-ng81-followup": frozenset({"glaucoma"}),
    "aao-poag-followup": frozenset({"glaucoma"}),
    "uspstf-poag": frozenset({"glaucoma"}),
    "nice-ng242": frozenset({"diabetic_retinopathy"}),
    "nice-ng242-treat": frozenset({"diabetic_retinopathy"}),
    "cn-dr-2022": frozenset({"diabetic_retinopathy"}),
    "cn-dr-treat-2022": frozenset({"diabetic_retinopathy"}),
    "icdr-2003": frozenset({"diabetic_retinopathy"}),
    "ada-2026": frozenset({"diabetic_retinopathy"}),
    "ada-2026-eyecare": frozenset({"diabetic_retinopathy"}),
    "nice-ng3": frozenset({"diabetic_retinopathy"}),
    "nice-ng82": frozenset({"age_related_macular_degeneration"}),
    "nice-ng82-followup": frozenset({"age_related_macular_degeneration"}),
    "cn-amd-2023": frozenset({"age_related_macular_degeneration"}),
    "cn-amd-treat-2023": frozenset({"age_related_macular_degeneration"}),
    "aao-amd-2023": frozenset({"age_related_macular_degeneration"}),
    "nei-amd": frozenset({"age_related_macular_degeneration"}),
    "nei-amd-dry": frozenset({"age_related_macular_degeneration"}),
    # 与三个报告病种无关：白内障管理与筛查类条款
    "nice-ng77": frozenset(),
    "nhc-cataract-2026": frozenset(),
}

# 空集来源（明确无关）与未登记来源（通用）必须区分：前者永不入选，后者不限制。
UNRELATED_SOURCES = frozenset({"nice-ng77", "nhc-cataract-2026"})


def disease_focus(disease: str) -> str:
    return DISEASE_FOCUS.get(disease, disease)


def source_diseases(source: str | None) -> frozenset[str]:
    """该来源所服务的检索病种；空集表示通用来源。"""
    return SOURCE_DISEASES.get(source or "", frozenset())


def matches_disease(source: str | None, disease: str | None) -> bool:
    """未指定病种时不限制；通用来源不限制；无关或他病种来源被排除。"""
    if not disease or source in UNRELATED_SOURCES:
        return not disease
    scope = source_diseases(source)
    return not scope or disease in scope