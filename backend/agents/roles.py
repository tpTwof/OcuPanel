"""各病种的分析职责。视觉测量由 vision 生成。"""
from agents.models import SpecialistRole


DISEASE_ROLES = {
    "glaucoma": SpecialistRole(
        "Glaucoma Specialist",
        "Interpret the glaucoma classifier and area-equivalent cup-to-disc ratio separately. "
        "Identify missing examination data. Do not infer stage or progression from one photo.",
    ),
    "diabetic_retinopathy": SpecialistRole(
        "Diabetic Retinopathy Specialist",
        "Discuss diabetic retinopathy using the supplied history and references. "
        "Treat FLAIR as research-only prompt matching. Do not infer lesions, diagnosis or grade.",
    ),
    "age_related_macular_degeneration": SpecialistRole(
        "AMD Specialist",
        "Discuss AMD using the supplied symptoms, history and references. "
        "Treat FLAIR as research-only prompt matching. Do not infer subtype, activity or stage.",
    ),
}
