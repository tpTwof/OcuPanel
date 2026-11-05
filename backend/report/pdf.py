from __future__ import annotations
from typing import Any
from typing import Any
import os
import re
import sys
import tempfile
from PIL import Image
from fpdf import FPDF
from utils.paths import OUTPUT_DIR
from .settings import LABELS, USE_CHINESE, _FONT_CANDIDATES
def plain_text(md: str) -> str:
    """把模型返回的 Markdown 压成纯文本，避免 PDF 里出现 ## 和 ** 符号。"""
    text = re.sub(r"^#{1,6}\s*", "", md, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "· ", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    return text

def soft_wrap(text: str, limit: int = 38) -> str:
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

def sanitize_for_latin1(text: str) -> str:
    return text.encode("latin-1", errors="replace").decode("latin-1")


class PDFRenderer:
    def generate_pdf_report(
        self,
        image_path: str,
        cup_to_disc_ratio: float | None,
        synthesis_text: str,
        output_path: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> None:
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

        def set_font(style: str, size: int) -> None:
            pdf.set_font(family, style, size)

        def write_text(text: str, height: float = 10) -> None:
            if fallback:
                text = sanitize_for_latin1(text)
            for line in soft_wrap(text).split("\n"):
                if line.strip():
                    pdf.multi_cell(0, height, line, new_x="LMARGIN", new_y="NEXT")

        def write_block(raw: str) -> None:
            block = plain_text(raw)
            if fallback:
                block = sanitize_for_latin1(block)
            for line in soft_wrap(block).split("\n"):
                if line.strip():
                    pdf.multi_cell(0, 10, line, new_x="LMARGIN", new_y="NEXT")
                else:
                    pdf.ln(4)

        set_font("B", 16)
        pdf.cell(0, 10, LABELS.title, new_x="LMARGIN", new_y="NEXT", align="C")

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
        if cup_to_disc_ratio is None:
            cdr_text = "未测量" if USE_CHINESE else "not measured"
        else:
            cdr_text = f"{cup_to_disc_ratio:.2f}"
        write_text(f"{LABELS.cdr}{sep}{cdr_text}")
        write_text(LABELS.legend)

        pdf.ln(4)
        set_font("B", 14)
        pdf.cell(0, 10, LABELS.summary, new_x="LMARGIN", new_y="NEXT")

        set_font("", 11)
        write_block(synthesis_text)

        if evidence:
            pdf.ln(4)
            set_font("B", 14)
            pdf.cell(0, 10, LABELS.references, new_x="LMARGIN", new_y="NEXT")
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
            pdf.cell(0, 10, LABELS.chat, new_x="LMARGIN", new_y="NEXT")

            for message in self.chat_history:
                pdf.ln(3)
                set_font("B", 11)
                label = LABELS.you if message["role"] == "user" else LABELS.ai
                pdf.cell(0, 8, label, new_x="LMARGIN", new_y="NEXT")
                set_font("", 11)
                write_block(message["content"])

        pdf.ln(8)
        set_font("I", 9)
        footer = LABELS.footer
        if fallback:
            footer = sanitize_for_latin1(footer)
        pdf.multi_cell(0, 6, footer, align="C", new_x="LMARGIN", new_y="NEXT")

        try:
            pdf.output(output_path)
        finally:
            # 渲染失败也不留垃圾文件
            if os.path.exists(rgb_image_path):
                os.remove(rgb_image_path)
