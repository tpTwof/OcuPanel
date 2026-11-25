"""最小端到端示例：检索 → 撰稿 → Verifier 核查。

用一个自造的最小语料（1 条条款）和固定回复的假 LLM，把每一步的中间结果打印出来。
不访问网络、不加载视觉模型、不调用真实 LLM。

运行：.\\venv\\Scripts\\python.exe .\\examples\\report_pipeline_walkthrough.py
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowledge.retrieval import Retriever  # noqa: E402
from knowledge.report_focus import disease_focus  # noqa: E402
from report.context import build_context  # noqa: E402
from agents.verifier import CitationVerifier  # noqa: E402
from vision.models import DiseaseResult  # noqa: E402

MINI_CORPUS = """# 最小示例语料

## 检查与判读

开角型青光眼诊断需结合房角、视神经与视网膜神经纤维层改变及视野检查结果。

## 随访

病情稳定者通常每 3–6 个月复查眼压与视神经。
"""

# 患者输入（病例事实）
NOTE = "右眼眼压 26 mmHg，C/D 0.7，视野示上弓形暗点。多久复查一次？"

# 假 LLM 产出的草稿：三句话，分别对应三种核查结果
DRAFT = (
    "## 初步评估\n\n"
    "右眼眼压 26 mmHg，杯盘比 0.7。\n\n"          # ① 病例事实 → 不该挂引用
    "视野上弓形暗点提示青光眼性损害 [1]。\n\n"      # ② 外部知识 → 证据[1]支持
    "建议每 2 个月复查视野，并立即开始前列素治疗 [1]。"  # ③ 证据[1]不支持 → 应被判为问题
)


def hr(title):
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


# 对照语料：把随访条款改成能支持草稿里的建议
MINI_CORPUS_SUPPORTING = """# 最小示例语料（补充版）

## 检查与判读

开角型青光眼诊断需结合房角、视神经与视网膜神经纤维层改变及视野检查结果。

## 随访与用药

进展期青光眼需每 1–2 个月复查视野，并考虑开始降眼压药物治疗。
"""


def run_verification(draft, evidence, ctx, verifier_reply, label):
    """跑一次 Verifier 并打印结果，返回交付正文（None 表示扣留）。"""
    print(f"\n--- {label} ---")

    def fake_llm(prompt, system=None, temperature=None):
        return verifier_reply

    verifier = CitationVerifier(fake_llm, min_chars=10, case_context=ctx, require_grounding=True)
    text, report = verifier.execute(draft, evidence, max_rounds=0)
    print(f"状态：{report['status']}   首轮问题数：{report['initial_issues']}")
    for issue in report.get("remaining_issues", []):
        print(f"  ✗ 「{issue['quote']}」")
        print(f"    verdict={issue['verdict']}  basis={issue.get('basis')}  impact={issue['impact']}")
        print(f"    原因：{issue['reason']}")
    if report.get("grounding"):
        print(f"  通过的来源对照：{len(report['grounding'])} 条")
    print(f"  交付正文：{'有' if text else '无（扣留）'}")
    return text


def main():
    # ---- 步骤 1：把最小语料写进临时目录，建立索引 ----------------------
    hr("步骤 1 · 建立索引")
    tmp = Path(tempfile.mkdtemp(prefix="ocupanel-demo-"))
    corpus = tmp / "corpus"
    (corpus / "guidelines").mkdir(parents=True)
    (corpus / "mini.md").write_text(MINI_CORPUS, encoding="utf-8")
    print(f"语料文件：{corpus / 'mini.md'}")

    retriever = Retriever.from_corpus(corpus, mode="bm25", graph_enabled=False)
    print(f"索引块数：{retriever.size}")
    for chunk in retriever.chunks:
        print(f"  [{chunk.id}] {chunk.text}")

    # ---- 步骤 2：组织病例上下文 --------------------------------------
    hr("步骤 2 · 组织病例上下文 (report/context.py::build_context)")
    ctx = build_context({"glaucoma": DiseaseResult(probability=0.91)}, NOTE)
    print(ctx)

    # ---- 步骤 3：检索证据 --------------------------------------------
    hr("步骤 3 · 检索证据 (knowledge/retrieval.py::Retriever.search)")
    hits = retriever.search(ctx, k=4, boost=disease_focus("glaucoma"), disease="glaucoma")
    evidence = []
    for index, item in enumerate(hits, 1):
        evidence.append({**item, "index": index})
        print(f"  [{index}] id={item['id']}  score={item.get('score')}")
        print(f"      {item['text']}")
    print(f"\n→ 共 {len(evidence)} 条证据，编号 [1]..[{len(evidence)}] 分配给撰稿模型")

    # ---- 步骤 4：撰稿（假 LLM） --------------------------------------
    hr("步骤 4 · 撰稿 (agents/specialist.py)")
    print("提示词会附上【参考资料】并给每条编号；模型被要求：")
    print("  · 依赖资料的结论必须标 [n]")
    print("  · 病例所见不挂编号")
    print("  · 资料未覆盖就写「资料未涵盖」，不要编造")
    print(f"\n假 LLM 返回的草稿：\n{DRAFT}")

    # ---- 步骤 5：Verifier 核查 ---------------------------------------
    hr("步骤 5 · Verifier 核查 (agents/verifier.py::verify_and_rewrite)")

    # 假 Verifier：逐句判定，模拟真实校验模型的行为
    verifier_reply = json.dumps({
        "claims": [{
            "quote": "建议每 2 个月复查视野，并立即开始前列素治疗 [1]。",
            "citations": [1],
            "verdict": "unsupported",
            "basis": "recommendation",
            "impact": "core",
            "reason": "证据仅写每 3–6 个月，且未提及用药方案",
        }],
        "grounding": [
            {"quote": "右眼眼压 26 mmHg，杯盘比 0.7。", "basis": "case_fact",
             "citations": [], "sources": [{"kind": "case", "quote": "右眼眼压 26 mmHg，C/D 0.7"}]},
            {"quote": "视野上弓形暗点提示青光眼性损害 [1]。", "basis": "medical_knowledge",
             "citations": [1],
             "sources": [{"kind": "evidence", "index": 1,
                          "quote": "开角型青光眼诊断需结合房角、视神经与视网膜神经纤维层改变及视野检查结果。"}]},
        ],
    }, ensure_ascii=False)

    def fake_llm(prompt, system=None, temperature=None):
        # 真实实现里这里是一次 LLM 调用；示例中固定返回上面的判定
        return verifier_reply

    verifier = CitationVerifier(fake_llm, min_chars=10, case_context=ctx, require_grounding=True)
    text, report = verifier.execute(DRAFT, evidence, max_rounds=0)

    print(f"状态：{report['status']}")
    print(f"首轮问题数：{report['initial_issues']}")
    for issue in report.get("remaining_issues", []):
        print(f"  ✗ 「{issue['quote']}」")
        print(f"    verdict={issue['verdict']}  basis={issue['basis']}  impact={issue['impact']}")
        print(f"    原因：{issue['reason']}")
    print(f"\n通过的来源对照 grounding：{len(report.get('grounding', []))} 条")
    for entry in report.get("grounding", []):
        print(f"  ✓ {entry['basis']}: {entry['quote']}")

    # ---- 步骤 6：结论 -------------------------------------------------
    hr("步骤 6 · 结果")
    if text is None:
        print("正文被扣留（text=None）→ 调用方必须走拒答/摘要路径，不能把草稿返回给用户。")
        print("这就是「核心报告无法核查导致无法输出」的实际现场。")
        print("注意：报告不是变短，而是整份诊疗正文被撤回，只留病例记录摘要。")
    else:
        print("正文通过核查：")
        print(text)

    # ---- 对照实验：换成能支持该建议的语料 ------------------------------
    hr("对照实验 · 语料覆盖该建议后会怎样")
    print("把随访条款改成「进展期需每 1–2 个月复查视野，并考虑降眼压药物」，")
    print("其余全部不变（同一份草稿、同一患者、同一判定逻辑）。")

    corpus2 = tmp / "corpus2"
    corpus2.mkdir()
    (corpus2 / "mini.md").write_text(MINI_CORPUS_SUPPORTING, encoding="utf-8")
    retriever2 = Retriever.from_corpus(corpus2, mode="bm25", graph_enabled=False)
    evidence2 = [{**item, "index": i} for i, item in
                 enumerate(retriever2.search(ctx, k=4, boost=disease_focus("glaucoma"),
                                             disease="glaucoma"), 1)]
    print(f"\n新语料检索到 {len(evidence2)} 条证据：")
    for item in evidence2:
        print(f"  [{item['index']}] {item['text']}")

    # 同样的建议句，这次证据能支持，所以校验判它通过。
    # 注意：编号按本次检索结果重新分配，grounding 必须引用对应编号的原文，
    # 代码会逐字核对来源片段，写错编号或抄错原文都会被判为未证实。
    def find(prefix):
        return next(item for item in evidence2 if item["text"].startswith(prefix))

    diagnosis = find("开角型青光眼诊断")
    followup = find("进展期青光眼")
    draft2 = (
        "## 初步评估\n\n"
        "右眼眼压 26 mmHg，杯盘比 0.7。\n\n"
        f"视野上弓形暗点提示青光眼性损害 [{diagnosis['index']}]。\n\n"
        f"建议每 2 个月复查视野，并立即开始前列素治疗 [{followup['index']}]。"
    )
    verifier_reply2 = json.dumps({
        "claims": [],
        "grounding": [
            {"quote": "右眼眼压 26 mmHg，杯盘比 0.7。", "basis": "case_fact",
             "citations": [], "sources": [{"kind": "case", "quote": "右眼眼压 26 mmHg，C/D 0.7"}]},
            {"quote": f"视野上弓形暗点提示青光眼性损害 [{diagnosis['index']}]。", "basis": "medical_knowledge",
             "citations": [diagnosis["index"]],
             "sources": [{"kind": "evidence", "index": diagnosis["index"],
                          "quote": diagnosis["text"]}]},
            {"quote": f"建议每 2 个月复查视野，并立即开始前列素治疗 [{followup['index']}]。",
             "basis": "recommendation", "citations": [followup["index"]],
             "sources": [{"kind": "evidence", "index": followup["index"],
                          "quote": followup["text"]}]},
        ],
    }, ensure_ascii=False)

    text2 = run_verification(draft2, evidence2, ctx, verifier_reply2, "语料覆盖后的同一份建议")
    if text2:
        print("\n交付正文：")
        print(text2)
        print("\n结论：草稿内容一字未改，只是语料补上了这一句依据，报告就从「扣留」变成「交付」。")
        print("这印证了上一轮的判断——问题在资料库，不在核查机制。")

    print(f"\n临时语料目录：{tmp}")


if __name__ == "__main__":
    try:
        main()
    finally:
        # 清理本次运行写出的临时语料目录
        import shutil
        for stale in Path.cwd().glob("ocupanel-demo-*"):
            if stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)