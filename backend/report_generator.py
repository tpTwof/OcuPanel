import openai
import numpy as np
import os
import re
import shutil
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import imageio.v2 as imageio
from PIL import Image
from fpdf import FPDF
from paths import OUTPUT_DIR
from retrieval import format_evidence_block
import config

DEFAULT_MODEL = config.DEFAULT_MODEL


def new_job_dir(prefix="job"):
    """为单次请求创建独占的临时工作目录。

    之前所有请求共用 output/temp_slo_fundus.png、output/segmented_image.png
    这类固定文件名，两个人同时上传就会互相覆盖，后到的请求可能拿到别人的
    分割图和杯盘比。改成每次请求一个目录后彻底隔离。
    """
    return Path(tempfile.mkdtemp(prefix=f"{prefix}_", dir=str(OUTPUT_DIR)))


def cleanup_job_dir(path):
    """删除本次请求的工作目录（幂等，失败不抛）。"""
    if not path:
        return
    shutil.rmtree(str(path), ignore_errors=True)


JOB_DIR_PREFIXES = ("job_", "report_", "content_")


# 各角色检索时附加的专业关键词：让药师去查药物相互作用、技师去查检查规范，
# 而不是六个角色拿到同一批证据（那样多智能体就退化成重复劳动了）。
ROLE_QUERY_HINTS = {
    "Ophthalmologist": "青光眼 视神经 杯盘比 视野缺损 诊断 分型 鉴别",
    "Optometrist": "眼压 视野检查 视力 屈光 筛查",
    "Glaucoma Specialist": "杯盘比 盘沿 视杯 视盘 RNFL 目标眼压 进展 随访间隔",
    "Primary Care Physician": "高血压 低血压 全身因素 睡眠呼吸暂停 危险因素 筛查",
    "Ophthalmic Technician": "眼压测量 视野检查 OCT 随访记录 数据",
    "Pharmacist": "前列腺素类似物 β受体阻滞剂 禁忌 不良反应 药物相互作用 糖皮质激素",
}


def purge_stale_job_dirs(max_age_seconds=1800):
    """清掉进程被强杀后遗留的请求级临时目录，返回删除数量。"""
    import time

    now = time.time()
    removed = 0
    try:
        entries = list(OUTPUT_DIR.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.is_dir() or not entry.name.startswith(JOB_DIR_PREFIXES):
            continue
        try:
            if now - entry.stat().st_mtime < max_age_seconds:
                continue
        except OSError:
            continue
        shutil.rmtree(str(entry), ignore_errors=True)
        removed += 1
    return removed


# ---------------------------------------------------------------------------
# 知识检索（证据包）。检索器进程内只构建一次；语料很小，建索引 <10ms。
# 想换向量库 / 图谱时，只改 retrieval.Retriever.search 的实现即可。
# ---------------------------------------------------------------------------
_RETRIEVER = None
_RETRIEVER_LOCK = threading.Lock()


def get_retriever():
    global _RETRIEVER
    if _RETRIEVER is None:
        with _RETRIEVER_LOCK:
            if _RETRIEVER is None:
                from retrieval import Retriever

                _RETRIEVER = Retriever.from_corpus()
                print(f"[RAG] 语料已加载：{_RETRIEVER.size} 个片段", file=sys.stderr)
    return _RETRIEVER


def retrieve_evidence(query, boost=""):
    """检索带出处的证据片段；任何异常都退化为「不注入」，不影响报告生成。"""
    if not config.RAG_ENABLED:
        return []
    try:
        return get_retriever().search(
            query, k=config.RAG_TOP_K, min_score=config.RAG_MIN_SCORE, boost=boost
        )
    except Exception as exc:  # noqa: BLE001 - 检索失败不该让整条链路 500
        print(f"[RAG] 检索失败，本次不注入证据：{exc}", file=sys.stderr)
        return []


def resolve_model(model=None):
    """模型名：显式入参 > 环境变量 OPENAI_MODEL > 默认值。统一由 config 读取。"""
    return model or config.OPENAI_MODEL or DEFAULT_MODEL


def resolve_base_url():
    """OpenAI 兼容端点。None 表示官方 OpenAI API。"""
    return config.OPENAI_BASE_URL or None


def build_generator_for_user(cfg: dict) -> "MedicalReportGenerator":
    """用**用户自己的** LLM 配置造一个生成器。

    这是"个人管理 API"的落点：模型、端点、密钥全部来自该用户在 SQLite 里的配置，
    代码里不再有任何硬编码的厂商/模型。cfg 由 storage.load_llm_config() 解密得到。
    """
    return MedicalReportGenerator(
        api_key=cfg.get("api_key"),
        model=cfg.get("model") or None,
        base_url=(cfg.get("base_url") or None),
    )


def thinking_control(base_url=None):
    """DeepSeek 的 thinking 模式默认开启，会让单次生成慢 2-3 倍。

    LLM_DISABLE_THINKING=1 时通过 extra_body 关掉；其他厂商不支持该字段，
    因此只对 DeepSeek 端点生效，其余情况返回 None 不影响正常调用。
    base_url: 用户自定义端点也要照此判断，不能只看全局配置。
    """
    if not config.LLM_DISABLE_THINKING:
        return None
    base = base_url if base_url is not None else resolve_base_url()
    if "deepseek" not in (base or "").lower():
        return None
    return {"thinking": {"type": "disabled"}}


def describe_llm_error(exc, base_url=None, from_user_config=False):
    """把 SDK 抛出的嵌套异常压成一行可读信息，并附上排查提示。

    from_user_config=True 表示这次调用用的是某个用户在「个人设置」里填的 key，
    提示语必须指向那里的配置，而不是 backend/.env —— 否则用户会去改错地方。
    """
    chain = []
    cur = exc
    while cur is not None and len(chain) < 4:
        text = str(cur).strip()
        name = type(cur).__name__
        if text:
            chain.append(f"{name}: {text}")
        else:
            chain.append(name)
        cur = cur.__cause__ or cur.__context__
        if cur is chain:
            break

    detail = " | ".join(chain) if chain else type(exc).__name__
    joined = detail.lower()

    # 提示语里的「去哪儿改配置」随调用来源变化
    where = "「个人设置 → LLM API 配置」中填写的" if from_user_config else "backend/.env 中的"
    endpoint = base_url or resolve_base_url()

    hints = []
    if "certificate_verify_failed" in joined or "self-signed certificate" in joined:
        hints.append(
            "TLS 证书校验失败：本机代理/杀软可能在做 HTTPS 中间人。"
            "可先关闭代理直连，或设置 SSL_CERT_FILE 指向代理根证书。"
        )
    if "connection error" in joined or "connect" in joined:
        hints.append(
            f"无法建立连接：确认接口地址 {endpoint} 可访问；"
            "若 shell 里残留 HTTPS_PROXY/HTTP_PROXY，请先清空（Remove-Item Env:HTTPS_PROXY）。"
        )
    if "401" in joined or "authentication" in joined or "invalid_api_key" in joined:
        hints.append(f"鉴权失败：检查{where} API Key 是否正确、是否已过期。")
    if "404" in joined or ("model" in joined and "not exist" in joined):
        hints.append(
            f"模型名或接口地址可能不对：当前模型在 {endpoint} 上不存在，"
            "核对「接口地址 + 模型」是否为同一家服务商。"
        )
    if "402" in joined or "insufficient balance" in joined:
        hints.append("账户余额不足，请到服务商控制台充值。")

    if hints:
        detail += "  → " + " ".join(hints)
    return detail


# ---------------------------------------------------------------------------
# 报告语言 / PDF 文案
# ---------------------------------------------------------------------------
USE_CHINESE = config.REPORT_LANGUAGE.startswith("zh")

LANGUAGE_INSTRUCTION = (
    "\n\n请用简体中文撰写全部内容。专业术语首次出现时可在括号内保留英文缩写"
    "（如眼压 IOP、光学相干断层扫描 OCT、视网膜神经纤维层 RNFL）。"
    if USE_CHINESE
    else ""
)

# ---------------------------------------------------------------------------
# 对话（追问 / 答疑）专用的系统提示词
# ---------------------------------------------------------------------------
# 刻意不复用 MedicalReportGenerator.system_prompt：那一个同时是六专科子报告与
# Director 综合的系统消息（chat_with_gpt 的 system=None 会回落到它），改它会把
# 报告的语气和结构一起改掉。写报告和答疑是两种任务，提示词必须分开。
#
# 另外这里**不拼 LANGUAGE_INSTRUCTION**：那段带「如眼压 IOP、OCT、RNFL」的示例，
# 模型会把示例当成能力清单复述出来（之前打招呼就吐出这三个术语）。语言要求直接
# 写进正文，不带可复述的例子。
CHAT_SYSTEM_ZH = (
    "你是 OcuPanel 眼科辅助诊疗助手，服务于眼底疾病的影像解读辅助与临床答疑。"
    "覆盖范围包括青光眼、糖尿病视网膜病变等常见眼底病变，以及杯盘比（CDR）、眼压（IOP）、"
    "光学相干断层扫描（OCT）、视网膜神经纤维层（RNFL）厚度、视野等检查指标的释义。\n\n"
    "按两种情况回应：\n"
    "1. 用户已生成过报告：只依据报告里给出的影像结论、杯盘比、青光眼概率和引用的指南证据作答。"
    "不要推翻报告里的测量值，也不要引入报告中没有的数据。\n"
    "2. 用户只是打招呼或直接提问：先用一两句话说明你能做什么，再邀请他上传眼底照片或描述病情"
    "（症状、眼压、OCT 或视野结果、用药史）。不要罗列术语清单。\n\n"
    "边界，必须遵守：\n"
    "- 本系统是辅助工具，不能替代眼科医生的诊断。涉及确诊、用药调整、手术方案或急诊指征时，"
    "明确建议尽快就医。\n"
    "- 本系统的影像分析目前只覆盖青光眼（视盘/视杯分割、杯盘比、青光眼概率）。"
    "对糖尿病视网膜病变等其他眼底疾病，只能依据用户提供的文字信息答疑，"
    "不得声称分析过图像，也不得编造分级、病灶位置或检查数值。\n"
    "- 信息不足就直说不足并追问，不要臆测；给出结论时尽量说明依据。\n"
    "- 始终用简体中文回答，专业术语首次出现可在括号内保留英文缩写。"
    "回答简洁、可分点，不写客套话。"
)
CHAT_SYSTEM_EN = (
    "You are the OcuPanel ophthalmic assistant, supporting image-reading and clinical Q&A "
    "for fundus diseases such as glaucoma and diabetic retinopathy, including explanations of "
    "cup-to-disc ratio (CDR), intraocular pressure (IOP), OCT, retinal nerve fiber layer (RNFL) "
    "thickness and visual field results.\n\n"
    "Respond differently depending on the situation:\n"
    "1. If a report has already been generated: answer only from that report's imaging findings, "
    "CDR, glaucoma probability and cited guideline evidence. Never override its measurements or "
    "introduce data it does not contain.\n"
    "2. If the user is greeting you or asking a direct question: briefly state what you can do, "
    "then invite them to upload a fundus image or describe the case (symptoms, IOP, OCT or visual "
    "field results, medication history). Do not list terminology.\n\n"
    "Hard boundaries:\n"
    "- This is a decision-support tool, not a diagnosis. For confirmation, medication changes, "
    "surgery or red-flag symptoms, advise seeing an ophthalmologist promptly.\n"
    "- Image analysis currently covers glaucoma only (disc/cup segmentation, CDR, glaucoma "
    "probability). For diabetic retinopathy and other fundus diseases, answer from the text the "
    "user provides; never claim the image was analysed, and never invent grading, lesion location "
    "or measurements.\n"
    "- If information is insufficient, say so and ask; do not speculate. State your basis when "
    "giving a conclusion.\n"
    "- Always answer in English. Be concise; short paragraphs or bullets, no pleasantries."
)
CHAT_SYSTEM_PROMPT = {
    "role": "system",
    "content": CHAT_SYSTEM_ZH if USE_CHINESE else CHAT_SYSTEM_EN,
}

LABELS = (
    {
        "title": "青光眼诊断报告",
        "cdr": "杯盘比（C/D）",
        "legend": "红色 = 视盘，绿色 = 视杯",
        "summary": "最终诊断摘要",
        "references": "参考资料（知识库检索）",
        "chat": "对话记录",
        "you": "问：",
        "ai": "答：",
        "footer": "本报告由医学 AI 助手自动生成，仅供研究参考，不作为临床诊断依据。",
    }
    if USE_CHINESE
    else {
        "title": "Glaucoma Diagnostic Report",
        "cdr": "Cup-to-Disc Ratio (C/D)",
        "legend": "Red = Optic Disc, Green = Optic Cup",
        "summary": "Final Diagnostic Summary",
        "references": "References (knowledge retrieval)",
        "chat": "Chat History",
        "you": "You:",
        "ai": "AI:",
        "footer": "Generated by Medical AI Assistant. Research use only, not a clinical diagnosis.",
    }
)

# 中文字体候选：优先 REPORT_FONT_PATH，其次各系统常见路径。
# .ttf/.otf 最稳；.ttc 视 fpdf2 版本可能失败，失败会自动跳过。
_FONT_CANDIDATES = [
    config.REPORT_FONT_PATH,
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\Deng.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


def reject_message(verification):
    """拒答文案：告诉用户「为什么没有报告」，而不是交一份打了折的报告。"""
    remaining = verification.get("remaining_issues") or []
    is_error = verification.get("status") == "error"

    if USE_CHINESE:
        lines = ["## 无法生成有依据的诊断报告", ""]
        if is_error:
            lines.append("本次校验过程出错（%s），无法确认报告内容是否可靠。" % (verification.get("reason") or "unknown"))
        else:
            total = len(remaining) or verification.get("initial_issues", 0)
            lines.append(
                f"本轮报告有 {total} 处断言检索不到支持它们的资料，经过 {verification.get('rounds', 0)} 轮"
                "改写与重新生成后仍未消除。"
            )
        lines += ["", "为避免输出无依据的医学结论，本系统未生成诊断报告。"]
        if remaining:
            lines += ["", "未通过校验的表述（示例）："]
            for it in remaining[:5]:
                quote = (it.get("quote") or "")[:60]
                lines.append(f"- {quote}｜{it.get('reason') or it.get('verdict')}")
        lines += [
            "",
            "建议：补充视野、OCT、房角等检查资料，或完善本地知识库语料后重试。",
            "本系统不提供未经资料支持的推断性结论，这是刻意设计，而非故障。",
        ]
        return "\n".join(lines)

    lines = ["## No verifiable report could be generated", ""]
    if is_error:
        lines.append(f"Citation verification failed: {verification.get('reason') or 'unknown'}.")
    else:
        lines.append(
            f"{len(remaining) or verification.get('initial_issues', 0)} claims could not be grounded "
            f"in the knowledge base after {verification.get('rounds', 0)} rewrite rounds."
        )
    lines += ["", "The report was withheld to avoid unsupported clinical conclusions."]
    for it in remaining[:5]:
        lines.append(f"- {(it.get('quote') or '')[:60]} | {it.get('reason') or it.get('verdict')}")
    return "\n".join(lines)



def plain_text(md):
    """把模型返回的 Markdown 压成纯文本，避免 PDF 里出现 ## 和 ** 符号。"""
    text = re.sub(r"^#{1,6}\s*", "", md, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "· ", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    return text


def soft_wrap(text, limit=38):
    """按固定字数切断超长中文行。

    fpdf2 的 wrapmode="CHAR" 在长段中文上会陷入死循环（实测卡死 8 分钟以上），
    这里提前把长行切成 limit 个字符，剩下的交给默认的按词换行，绕开该分支。
    含空格的英文行交给 fpdf2 自己断词，不动。
    """
    out = []
    for line in text.split("\n"):
        if not line:
            out.append("")
            continue
        if " " in line:
            out.append(line)
            continue
        while len(line) > limit:
            out.append(line[:limit])
            line = line[limit:]
        out.append(line)
    return "\n".join(out)


def _register_cjk_font(pdf):
    """尝试注册中文字体，返回可用的 family 名；全部失败返回 None。"""
    for path in _FONT_CANDIDATES:
        if not path or not os.path.isfile(path):
            continue
        try:
            family = "ReportCJK"
            pdf.add_font(family, "", path)
            # 同一字体文件复用到粗体/斜体，避免 set_font 找不到样式而报错
            pdf.add_font(family, "B", path)
            pdf.add_font(family, "I", path)
            return family
        except Exception as exc:  # noqa: BLE001 - 换下一个候选字体
            print(f"[PDF] 字体不可用，跳过 {path}: {exc}", file=sys.stderr)
    return None


class MedicalReportGenerator:
    def __init__(self, api_key=None, model=None, base_url=None):
        """Initialize model parameters

        base_url: 用户自己配置的接口地址。为 None 时回落到环境变量里的全局配置，
        这样老的单用户模式（直接用 .env 里的 key）仍然跑得通。
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or None
        self.model = resolve_model(model)
        self.base_url = base_url if base_url is not None else resolve_base_url()
        self.system_prompt = {
            "role": "system",
            "content": (
                "You are a medical AI assistant answering questions after reviewing diagnostic reports."
                + LANGUAGE_INSTRUCTION
            )
        }
        self.chat_history = []
        self.messages = [self.system_prompt]
        # 同一用户的综合报告与后续追问可能并发，历史列表的读改写要串行化
        self._state_lock = threading.Lock()

    def chat_with_history(self, history: list[dict], user_message: str) -> str:
        """无状态对话：外部把历史传进来，本方法不读写 self.messages。

        引入数据库后，对话历史的事实来源是 SQLite 而不是进程内存，
        这样重启不丢、多台机器也能接上。这里只负责拼消息和发起调用。

        系统消息用 CHAT_SYSTEM_PROMPT（眼科辅助诊疗定位），不用 self.system_prompt
        ——后者是给六专科子报告与 Director 综合用的，措辞与目标都不同。
        """
        messages = [CHAT_SYSTEM_PROMPT]
        for item in history:
            role = item.get("role")
            if role in ("user", "assistant") and item.get("content"):
                messages.append({"role": role, "content": item["content"]})
        messages.append({"role": "user", "content": user_message})

        client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=config.LLM_TIMEOUT,
            max_retries=config.LLM_MAX_RETRIES,
        )
        kwargs = {"model": self.model, "messages": messages, "temperature": 0.7}
        extra = thinking_control(self.base_url)
        if extra:
            kwargs["extra_body"] = extra
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001 - 让上层统一转成可读错误
            raise RuntimeError(
                describe_llm_error(exc, self.base_url, from_user_config=True)
            ) from exc

    def chat_with_gpt(self, user_message, conversation=False, reset=True,
                      system=None, temperature=None):
        """Talk to GPT with optional context reset

        system / temperature: 供校验智能体使用。校验与重写需要独立的系统提示词
        （"你是校对员"而不是"你是医学助手"）和接近 0 的温度，否则同一个角色
        既写又判，等于自证清白。
        """
        try:
            sys_prompt = self.system_prompt if not system else {"role": "system", "content": system}
            if reset:
                messages = [sys_prompt, {"role": "user", "content": user_message}]
            else:
                with self._state_lock:
                    self.messages.append({"role": "user", "content": user_message})
                    messages = list(self.messages)

            client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=config.LLM_TIMEOUT,
                max_retries=config.LLM_MAX_RETRIES,
            )
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7 if temperature is None else temperature,
            }
            extra = thinking_control(self.base_url)
            if extra:
                kwargs["extra_body"] = extra
            response = client.chat.completions.create(**kwargs)
            reply = response.choices[0].message.content

            if not reset:
                with self._state_lock:
                    self.messages.append({"role": "assistant", "content": reply})

            if (conversation):
                with self._state_lock:
                    self.chat_history.append({"role": "user", "content": user_message})
                    self.chat_history.append({"role": "assistant", "content": reply})

            return reply
        except Exception as e:
            # 保留异常链，否则 UI 只能看到 "Connection error." 这类无信息量的外壳
            detail = describe_llm_error(e, self.base_url, from_user_config=True)
            print(f"[LLM ERROR] {detail}", file=sys.stderr)
            return f"Error: {detail}"

    def reset_conversation(self):
        """清空对话上下文。

        原来只清 chat_history（PDF 用的那份），self.messages 仍留着上一轮的
        问答，重置后模型其实还能"记得"之前的内容，属于隐性 bug，一并清掉。
        """
        with self._state_lock:
            self.chat_history.clear()
            self.messages = [self.system_prompt]

    def generate_reports(self, data_pth, note, roles=None, job_dir=None):
        """Generate diagnostic reports from multiple medical experts

        job_dir: 本次请求独占的临时目录。不传则自动新建（由调用方负责清理）。
        """
        # 惰性导入：torch/transformers 体积大，只在真正需要影像推理时加载，
        # 这样单纯生成 PDF 或做连通性检查不会拖慢启动。
        from classifier import GlaucomaProb2Text, predict_glaucoma
        from segmenter import calculate_cup_to_disc_ratio, segment_optic_disc_cup

        if roles is None:
            roles = ["Ophthalmologist"]

        job_dir = Path(job_dir) if job_dir else new_job_dir("report")
        job_dir.mkdir(parents=True, exist_ok=True)

        slo_fundus_image = imageio.imread(data_pth)
        temp_jpg_path = str(job_dir / "fundus.png")
        imageio.imwrite(temp_jpg_path, slo_fundus_image)
        segmented_image = segment_optic_disc_cup(temp_jpg_path)
        ratio = calculate_cup_to_disc_ratio(temp_jpg_path)

        segmented_output_path = str(job_dir / "segmented_image.png")
        imageio.imwrite(segmented_output_path, segmented_image)

        disease_prob = predict_glaucoma(temp_jpg_path)
        disease_class = GlaucomaProb2Text(disease_prob)
        core_prompt = disease_class.promptB()
        core_prompt += f" Network B estimates that the cup-to-disc ratio is approximately {ratio:.2f}."
        clinical_note = note if note.strip() else "No clinical note provided."
        core_prompt += f"\n\nClinician's note: {clinical_note}"

        # 证据检索：每个角色用自己的专业关键词去查，得到各自的证据子集。
        # 这是 GraphRAG 的第一步（关键词检索），换成分量库/图谱时接口不变。
        case_brief = f"{clinical_note[:200]} 青光眼 杯盘比 {ratio:.2f}"
        role_evidence: dict[str, list[dict]] = {}
        for role in roles:
            hint = ROLE_QUERY_HINTS.get(role, role)
            role_evidence[role] = retrieve_evidence(case_brief, boost=hint)

        # 全局编号：同一条资料在所有角色提示词里编号一致，Director 汇总时才不会串号
        evidence: list[dict] = []
        numbers: dict[str, int] = {}
        for role in roles:
            for item in role_evidence[role]:
                if item["id"] not in numbers:
                    numbers[item["id"]] = len(evidence) + 1
                    evidence.append({**item, "index": numbers[item["id"]]})
        evidence = evidence[: max(config.RAG_TOP_K * 2, 6)]

        if evidence:
            print(
                f"[RAG] 命中 {len(evidence)} 条证据：" +
                ", ".join(f"[{e['index']}]{e['id']}({e['score']})" for e in evidence)
            )

        os.remove(temp_jpg_path)

        # 证据块放在提示词最末尾：模型的注意力更靠后，引用规则容易被遵守
        def role_block(role):
            items = [i for i in role_evidence[role] if i["id"] in numbers]
            return format_evidence_block(items, numbers)

        def build_prompt(role):
            return (
                f"{core_prompt}\n\nAs a {role}, please analyze this case from your domain expertise. "
                f"Only include observations and recommendations relevant to your specialty. "
                f"Avoid repeating what is not within your scope. Do not mention Network A or B. "
                f"Write this as part of a professional medical report meant to be integrated with other specialists' insights."
                + LANGUAGE_INSTRUCTION
                + role_block(role)
            )

        prompts = {role: build_prompt(role) for role in roles}

        # 六个专科互不依赖，并发调用。串行时整条链路要 8 分钟以上，
        # 并发后耗时约等于最慢的那一次。
        # chat_with_gpt(reset=True) 只用局部 messages，不碰共享状态，可以安全并发。
        print(f"Concurrent expert calls: {len(roles)} roles\n")
        if len(roles) == 1:
            only = next(iter(roles))
            expert_reports = {only: self.chat_with_gpt(prompts[only], reset=True)}
        else:
            with ThreadPoolExecutor(max_workers=len(roles)) as pool:
                results = pool.map(
                    lambda r: (r, self.chat_with_gpt(prompts[r], reset=True)), roles
                )
                expert_reports = dict(results)

        return expert_reports, ratio, segmented_output_path, evidence

    def generate_synthesis(self, expert_reports: dict, evidence=None, avoid=None):
        """Generate a director-level synthesis based on all expert reports

        avoid: 上一版被引用校验判为无依据的断言。重生成时把它们作为「禁止写入
        清单」交给 Director —— 不告诉它哪里错了，它会换个说法把同样的幻觉写回来。
        """
        combined_reports = "\n\n".join(
            [f"{role} Report:\n{report}" for role, report in expert_reports.items()]
        )
        director_prompt = (
            f"The following is clinical information regarding a suspected case of glaucoma, including findings from a fundus image, "
            f"computer-aided analysis, and a clinician's note:\n\n{combined_reports}\n\n"
            f"Based on the information above, write a final comprehensive diagnostic report. Summarize the key findings, provide "
            f"diagnostic reasoning, and include appropriate recommendations. Do not mention any subreports. The report should be "
            f"written in a professional, neutral tone suitable for a clinical team or patient record."
            + LANGUAGE_INSTRUCTION
            + format_evidence_block(evidence or [])
        )
        if avoid:
            listed = "\n".join(
                f"- {str(it.get('quote', ''))[:80]}（问题：{it.get('verdict')}；{it.get('reason', '')}）"
                for it in list(avoid)[:12]
            )
            director_prompt += (
                "\n\n【上一版被判定缺乏依据的断言，本次禁止原样写入】\n"
                f"{listed}\n"
                "上述内容若要提及，只能写成资料支持得了的表述，或直接写「现有资料未涵盖」，"
                "不得换一种说法把同样的结论再写一遍。报告中每一条结论性表述都必须在句末标注资料编号 [n]。"
            )

        return self.chat_with_gpt(director_prompt, reset=False)

    def verify_synthesis(self, text, evidence, regenerate=None):
        """第 7 个智能体：核查引用、删掉没依据的句子、必要时重生成，最后仍不合格就拒答。

        返回 (文本, 校验报告)。**文本为 None 表示不交报告**（拒答或校验故障），
        调用方必须据此走拒答路径，不能把原文返回给用户。
        """
        if not config.VERIFY_ENABLED:
            return text, {"status": "disabled"}
        if not text or text.startswith("Error:"):
            return None, {"status": "rejected", "reason": "empty_text"}

        try:
            from verifier import CitationVerifier

            verifier = CitationVerifier(
                lambda prompt, system=None, temperature=None: self.chat_with_gpt(
                    prompt, reset=True, system=system, temperature=temperature
                ),
                min_chars=config.VERIFY_MIN_CHARS,
                # 语料混英文后，「资料未涵盖」这类偷懒改写的词面判据会失效，
                # 借用检索器的多语言向量做语义判据（bm25 模式下自动返回 0）
                sim_fn=get_retriever().similarity,
            )
            return verifier.verify_and_rewrite(
                text, evidence, max_rounds=config.VERIFY_MAX_ROUNDS,
                regenerate=regenerate,
            )
        except Exception as exc:  # noqa: BLE001 - 校验崩了也不许把未校验的稿子放出去
            print(f"[VERIFY] 校验链路异常，本次不输出报告：{exc}", file=sys.stderr)
            return None, {"status": "error", "reason": str(exc)[:200]}

    def generate_pdf_report(self, image_path, cup_to_disc_ratio, synthesis_text,
                            output_path=None, evidence=None):
        """生成 PDF 报告。

        有中文字体时正常输出中文；找不到字体则降级为内置 Helvetica +
        latin-1 清洗，保证任何环境下都不会崩。
        evidence: 检索到的证据片段，会附在报告末尾作为参考资料来源。
        """
        output_path = output_path or str(OUTPUT_DIR / "diagnostic_report.pdf")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        family = _register_cjk_font(pdf)
        fallback = family is None
        if fallback:
            family = "Helvetica"
            print(
                "[PDF] 未找到可用中文字体，PDF 将降级为拉丁字符。"
                "可设置 REPORT_FONT_PATH 指向一个 .ttf 中文字体。",
                file=sys.stderr,
            )

        def set_font(style, size):
            pdf.set_font(family, style, size)

        def write_text(text, height=10):
            if fallback:
                text = sanitize_for_latin1(text)
            for line in soft_wrap(text).split("\n"):
                if line.strip():
                    pdf.multi_cell(0, height, line, new_x="LMARGIN", new_y="NEXT")

        def write_block(raw):
            block = plain_text(raw)
            if fallback:
                block = sanitize_for_latin1(block)
            for line in soft_wrap(block).split("\n"):
                if line.strip():
                    pdf.multi_cell(0, 10, line, new_x="LMARGIN", new_y="NEXT")
                else:
                    pdf.ln(4)

        set_font("B", 16)
        pdf.cell(0, 10, LABELS["title"], new_x="LMARGIN", new_y="NEXT", align="C")

        im = Image.open(image_path)
        # 临时 jpg 也必须唯一：并发时共用 temp_rgb_image.jpg 会出现
        # 一个请求正在写、另一个请求已经删掉的竞态。
        rgb_fd, rgb_image_path = tempfile.mkstemp(
            prefix="pdf_img_", suffix=".jpg", dir=str(OUTPUT_DIR)
        )
        os.close(rgb_fd)
        im.convert("RGB").save(rgb_image_path)
        pdf.ln(6)
        pdf.image(rgb_image_path, x=25, w=160)

        set_font("", 12)
        pdf.ln(4)
        sep = "：" if USE_CHINESE else ": "
        write_text(f"{LABELS['cdr']}{sep}{cup_to_disc_ratio:.2f}")
        write_text(LABELS["legend"])

        pdf.ln(4)
        set_font("B", 14)
        pdf.cell(0, 10, LABELS["summary"], new_x="LMARGIN", new_y="NEXT")

        set_font("", 11)
        write_block(synthesis_text)

        if evidence:
            pdf.ln(4)
            set_font("B", 14)
            pdf.cell(0, 10, LABELS["references"], new_x="LMARGIN", new_y="NEXT")
            set_font("", 10)
            for i, item in enumerate(evidence, 1):
                cite = (
                    f"[{i}] {item.get('title', '')} §{item.get('section', '')}"
                    f"（来源：{item.get('source', '')}，相关度 {item.get('score', 0)}）"
                )
                write_text(cite, height=8)
                snippet = (item.get("text") or "").strip().replace("\n", " ")
                if len(snippet) > 120:
                    snippet = snippet[:120] + "…"
                write_text(f"    {snippet}", height=8)

        if len(self.chat_history) > 0:
            pdf.ln(4)
            set_font("B", 14)
            pdf.cell(0, 10, LABELS["chat"], new_x="LMARGIN", new_y="NEXT")

            for message in self.chat_history:
                pdf.ln(3)
                set_font("B", 11)
                label = LABELS["you"] if message["role"] == "user" else LABELS["ai"]
                pdf.cell(0, 8, label, new_x="LMARGIN", new_y="NEXT")
                set_font("", 11)
                write_block(message["content"])

        pdf.ln(8)
        set_font("I", 9)
        footer = LABELS["footer"]
        if fallback:
            footer = sanitize_for_latin1(footer)
        pdf.multi_cell(0, 6, footer, align="C", new_x="LMARGIN", new_y="NEXT")

        try:
            pdf.output(output_path)
        finally:
            # 渲染失败也不留垃圾文件
            if os.path.exists(rgb_image_path):
                os.remove(rgb_image_path)

def sanitize_for_latin1(text):
    return text.encode("latin-1", errors="replace").decode("latin-1")

if __name__ == "__main__":
    api_key = os.getenv("OPENAI_API_KEY")
    model = resolve_model()

    report_generator = MedicalReportGenerator(api_key, model)
    data_pth = "data/slo_fundus_00004.jpg"
    note = ""
    """    roles = [
        "Ophthalmologist", "Optometrist", "Glaucoma Specialist",
        "Primary Care Physician", "Ophthalmic Technician", "Pharmacist"
    ] """
    roles = ["Ophthalmologist", "Optometrist", "Glaucoma Specialist", "Ophthalmic Technician"]

    job_dir = new_job_dir("cli")
    try:
        reports, ratio, segmented_image_path, evidence = report_generator.generate_reports(
            data_pth, note, roles, job_dir
        )
        summary = report_generator.generate_synthesis(reports)
        print(summary)

        output_path = OUTPUT_DIR / "final_diagnostic_report.pdf"
        report_generator.generate_pdf_report(
            image_path=segmented_image_path,
            cup_to_disc_ratio=ratio,
            synthesis_text=summary,
            output_path=str(output_path),
        )
        print(f"PDF saved as {output_path}")
    finally:
        cleanup_job_dir(job_dir)

    print("\n--- Chat with the Medical AI (type 'exit' to quit) ---")
    while True:
        user_input = input("You: ")
        if user_input.lower() in ["exit", "quit"]:
            print("Goodbye!")
            break
        response = report_generator.chat_with_gpt(user_input, reset=False)
        print("AI:", response)