"""专科定义只在此处维护；模型放在 models/agents.py。"""
from agents.models import SpecialistRole

SPECIALIST_ROLES: tuple[SpecialistRole, ...] = (
    SpecialistRole('Ophthalmologist', '青光眼 视神经 杯盘比 视野缺损 诊断 分型 鉴别'),
    SpecialistRole('Optometrist', '眼压 视野检查 视力 屈光 筛查'),
    SpecialistRole('Glaucoma Specialist', '杯盘比 盘沿 视杯 视盘 RNFL 目标眼压 进展 随访间隔'),
    SpecialistRole('Primary Care Physician', '高血压 低血压 全身因素 睡眠呼吸暂停 危险因素 筛查'),
    SpecialistRole('Ophthalmic Technician', '眼压测量 视野检查 OCT 随访记录 数据'),
    SpecialistRole('Pharmacist', '前列腺素类似物 β受体阻滞剂 禁忌 不良反应 药物相互作用 糖皮质激素'),
)
DEFAULT_ROLES: tuple[str, ...] = tuple(role.name for role in SPECIALIST_ROLES)

def get_role(name: str) -> SpecialistRole:
    for role in SPECIALIST_ROLES:
        if role.name == name:
            return role
    return SpecialistRole(name, name)