"""Deterministic version-bound rendering shared by explanations and exports."""
import json
STATUS = {"not_captured": "未拍", "not_assessed": "未评估", "ungradable": "不可判读", "gradable": "可判读"}
FINDING = {"not_assessed": "未形成结论", "no_target_signs": "未见目标征象（仅此眼此任务）", "suspect": "可疑，需复核"}


def describe(case: dict) -> str:
    exam = case["examination"]
    lines = ["# 合成病例演练记录（不构成临床签发）", f"病例 {case['id']} · 快照 v{case['revision']}",
             f"就诊编号：{exam['encounter_id']} · 机构：{exam['institution']}",
             f"跟进人：{exam['followup_owner']}", f"合成记录：{exam['note']}"]
    if exam["urgent_handoff"]:
        lines.append("立即人工交接标记已开启；不等待模型或报告。机构急诊路径仍待确认。")
    for eye in exam["eyes"]:
        lines.append("## " + ("右眼" if eye["laterality"] == "right" else "左眼"))
        lines.append(f"采集 {len(eye['captures'])} 次，补拍 {max(0, len(eye['captures']) - 1)} 次")
        for capture in eye["captures"]:
            lines.append(f"原图引用：{capture['image_ref']} · {capture['captured_at']} · {capture['device']} · {capture['field']}")
        for task in eye["tasks"]:
            reference = task.get("reference_exam")
            if reference:
                lines.append(f"{task['disease']} · {reference['modality']} · {reference['acquired_on']} · "
                             f"{reference['source']} · 人工记录：{reference['interpretation']}")
            lines.extend([f"任务：{task['disease']} · {STATUS[task['status']]} · {FINDING[task['finding']]}",
                          f"可见区域：{task['visible_region']} · 来源：人工演练记录",
                          f"所见：{task['observations'] or '未提供'}", f"原因：{task['reason'] or '未记录'}",
                          f"下一步：{task['next_step']}"])
    signature = case["signature"]
    if signature:
        lines.extend([f"## 模拟签发 · 报告 v{signature['signed_revision']}",
                      f"操作者：{signature['actor_name']} · {signature['actor_id']}", signature["plan"]])
    else:
        lines.append("未模拟签发，无有效签发计划。")
    for source in case.get("analysis_sources", []):
        report = source["report"]
        lines.extend([f"## 研究分析来源 · {'右眼' if source['laterality'] == 'right' else '左眼'}",
                      f"报告：{source['report_id']} · 来源哈希：{source['report_hash']}",
                      f"原图：{source['original']['status']} · 采集：{source['captured_at'] or '缺失'} · 设备：{source['device'] or '缺失'}",
                      f"原报告引用校验：{report['verification'].get('status', 'unknown')} · 原正文拒答：{bool(report['rejected'])}",
                      "以下为模型研究信息，与人工评估分开保存，不自动转换为诊断或计划。",
                      json.dumps(report['visual_findings'], ensure_ascii=False)])
    for event in case["events"]:
        if event["action"] == "followup":
            followup = event["detail"]
            lines.append(f"随访 · 计划 v{followup['signed_revision']} · 执行情况：{followup['adherence']} · "
                         f"症状：{followup['symptoms']} · 约定复查：{followup['next_visit'] or '未约定'}")
    for referral in case["referrals"]:
        lines.extend([f"## 转诊单 {referral['id']} · 绑定报告 v{referral['signed_revision']}",
                      f"去向：{referral['destination']} · 状态：{referral['status']}",
                      f"眼别：{', '.join(referral['eyes'])} · 跟进人：{referral['followup_owner']} · 截止：{referral['due_at']}"])
    lines.extend(["## 版本与解释边界", f"软件：{case['provenance']['software']} · 模型：{case['provenance']['model']}",
                  "合成联调，未经临床验证。引用校验不等于医生签发。",
                  "缺失、未拍、未评估、不可判读均不代表阴性；不得跨眼、跨日期推断。治疗变更交接诊医生。"])
    return "\n\n".join(lines)
