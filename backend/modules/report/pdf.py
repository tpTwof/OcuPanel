from __future__ import annotations

import os
import re
import sys
from io import BytesIO
from typing import Any

from fpdf import FPDF
from fpdf.fonts import FontFace
from PIL import Image

from core.paths import OUTPUT_DIR
from modules.report.settings import LABELS, USE_CHINESE, _FONT_CANDIDATES

_TABLE_SEPARATOR = re.compile(r":?-{3,}:?")
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+)$")
_LIST_ITEM = re.compile(r"^([-+*]|\d+[.)])[ \t]+(.+)$")
_CJK = re.compile(r"[\u3400-\u9fff]")


def _inline_text(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\((?:https?://)[^)\s]+\)", r"\1", text)
    text = re.sub(r"(\*{1,2})(?=\S)(.+?)(?<=\S)\1", r"\2", text)
    text = re.sub(r"(?<!\w)(_{1,2})(?=\S)(.+?)(?<=\S)\1(?!\w)", r"\2", text)
    return re.sub(r"\x60([^\x60]+)\x60", r"\1", text).strip()


def _table_cells(line: str) -> list[str]:
    line = line.strip().removeprefix("|")
    if not line.endswith(r"\|"):
        line = line.removesuffix("|")
    return [part.replace(r"\|", "|").strip()
            for part in re.split(r"(?<!\\)\|", line)]


class _ReportPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-11)
        self.set_font("Helvetica", size=9)
        self.set_text_color(92, 105, 120)
        self.cell(0, 5, str(self.page_no()), align="R")


def _register_cjk_font(pdf: FPDF) -> str | None:
    for path in _FONT_CANDIDATES:
        if not path or not os.path.isfile(path):
            continue
        try:
            family = "ReportCJK"
            for style in ("", "B", "I"):
                pdf.add_font(family, style, path)
            return family
        except Exception as exc:
            print(f"[PDF] 字体不可用，跳过 {path}: {exc}", file=sys.stderr)
    return None


class PDFRenderer:
    def generate_pdf_report(
        self,
        image_path: str,
        cup_to_disc_ratio: float | None,
        synthesis_text: str,
        output_path: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
        visual_findings_text: str = "",
        verification_status: str | None = None,
    ) -> None:
        output_path = output_path or str(OUTPUT_DIR / "diagnostic_report.pdf")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        pdf = _ReportPDF()
        pdf.set_title(LABELS.title)
        pdf.set_margins(16, 16)
        pdf.set_auto_page_break(True, margin=16)
        pdf.add_page()

        family = _register_cjk_font(pdf)
        if family is None:
            print("[PDF] 未找到中文字体，可设置 REPORT_FONT_PATH。", file=sys.stderr)

        def clean(value: str) -> str:
            return value if family else value.encode("latin-1", errors="replace").decode("latin-1")

        def write_text(text: str, height: float = 5.8, *, size: int = 11,
                       style: str = "", align: str = "L", link: str = "") -> None:
            pdf.set_font(family or "Helvetica", style, size)
            wrapmode = "CHAR" if _CJK.search(text) else "WORD"
            pdf.multi_cell(0, height, clean(text), align=align, link=link, wrapmode=wrapmode,
                           new_x="LMARGIN", new_y="NEXT")

        def heading(text: str, size: int = 14) -> None:
            if pdf.will_page_break(16):
                pdf.add_page()
            elif pdf.y > pdf.t_margin:
                pdf.ln(3)
            write_text(text, 7, size=size, style="B")

        def write_table(rows: list[list[str]], styles: list[str]) -> None:
            pdf.set_font(family or "Helvetica", size=10)
            align = ["CENTER" if cell.startswith(":") and cell.endswith(":")
                     else "RIGHT" if cell.endswith(":") else "LEFT" for cell in styles]
            rows = [[clean(_inline_text(cell)) for cell in cells] for cells in rows]
            wrapmode = "CHAR" if any(_CJK.search(cell) for row in rows for cell in row) else "WORD"
            weights = [max(18, min(64, max(map(pdf.get_string_width, column)))) for column in zip(*rows)]
            column_widths = [pdf.epw * weight / sum(weights) for weight in weights]
            line_height, padding = 5.2, 1.4

            def cell_lines(cells: list[str]) -> list[list[str]]:
                return [pdf.multi_cell(width, line_height, cell, align="L", padding=padding,
                                       wrapmode=wrapmode, dry_run=True, output="LINES")
                        for width, cell in zip(column_widths, cells)]

            # Account for the repeated heading when a single row is taller than a page.
            header_height = max(map(len, cell_lines(rows[0]))) * line_height + 2 * padding
            max_lines = max(1, int((pdf.eph - header_height - 2 * padding - 6) / line_height))
            with pdf.table(
                col_widths=weights, text_align=align, line_height=line_height, padding=padding,
                wrapmode=wrapmode,
                borders_layout="ALL", headings_style=FontFace(emphasis="BOLD", fill_color=(233, 240, 247)),
            ) as table:
                table.row(rows[0])
                for row_index, cells in enumerate(rows[1:]):
                    wrapped = cell_lines(cells)
                    height = max(map(len, wrapped))
                    if height <= max_lines:
                        table.row(cells)
                        continue
                    start = 0
                    if row_index == 0:
                        available = pdf.page_break_trigger - pdf.y - header_height - 2 * padding - 6
                        first_lines = min(max_lines, int(available / line_height))
                        if first_lines >= 4:
                            table.row(["\n".join(cell[:first_lines]) for cell in wrapped])
                            start = first_lines
                    for offset in range(start, height, max_lines):
                        table.row(["\n".join(cell[offset:offset + max_lines]) for cell in wrapped])
            pdf.ln(2)

        def write_block(raw: str) -> None:
            lines = raw.splitlines()
            index = 0
            gap = False
            while index < len(lines):
                line = lines[index].strip()
                index += 1
                if not line:
                    gap = True
                    continue
                if gap:
                    pdf.ln(2)
                    gap = False
                if "|" in line and index < len(lines) and "|" in lines[index]:
                    cells = _table_cells(line)
                    separators = _table_cells(lines[index])
                    if len(cells) == len(separators) and all(_TABLE_SEPARATOR.fullmatch(c) for c in separators):
                        rows = [cells]
                        index += 1
                        while index < len(lines) and "|" in lines[index]:
                            cells = _table_cells(lines[index])
                            if len(cells) != len(separators):
                                break
                            rows.append(cells)
                            index += 1
                        write_table(rows, separators)
                        continue
                if match := _HEADING.fullmatch(line):
                    heading(_inline_text(match[1]), 12)
                elif match := _LIST_ITEM.fullmatch(line):
                    marker = "·" if match[1] in "-+*" else match[1]
                    write_text(f"{marker} {_inline_text(match[2])}")
                elif not re.fullmatch(r"(?:-{3,}|\*{3,}|_{3,})", line):
                    write_text(_inline_text(line.removeprefix("> ").strip()))

        write_text(LABELS.title, height=10, size=19, style="B", align="C")
        pdf.ln(4)

        if image_path:
            with Image.open(image_path) as image, BytesIO() as jpeg:
                image.convert("RGB").save(jpeg, format="JPEG")
                jpeg.seek(0)
                width = min(pdf.epw, 92 * image.width / image.height)
                pdf.image(jpeg, x=(pdf.w - width) / 2, w=width)
            pdf.ln(1.5)
            write_text(LABELS.legend, height=5, size=9, align="C")

        if visual_findings_text:
            write_block(visual_findings_text)
        elif cup_to_disc_ratio is not None:
            separator = "：" if USE_CHINESE else ": "
            write_text(f"{LABELS.cdr}{separator}{cup_to_disc_ratio:.2f}", style="B")

        if verification_status == "pass":
            write_text("正文引用校验通过" if USE_CHINESE else "Report citations verified")
        elif verification_status == "rewritten":
            write_text("正文引用经修订后通过校验" if USE_CHINESE else "Report citations verified after revision")
        heading(LABELS.summary)
        write_block(synthesis_text)

        if evidence:
            heading(LABELS.references)
            for index, item in enumerate(evidence, 1):
                section = f" · {item['section']}" if item.get("section") else ""
                title = item.get("title") or item.get("source", "")
                url = item.get("url") or ""
                write_text(f"[{item.get('index', index)}] {title}{section}", size=10, style="B",
                           link=url if url.startswith(("https://", "http://")) else "")
                snippet = " ".join((item.get("text") or "").split())
                if snippet:
                    write_text(snippet[:120] + ("…" if len(snippet) > 120 else ""), height=5, size=9)
                pdf.ln(2)

        history = getattr(self, "chat_history", ())
        if history:
            heading(LABELS.chat)
            for message in history:
                label = LABELS.you if message["role"] == "user" else LABELS.ai
                write_text(label, style="B")
                write_block(message["content"])

        pdf.ln(3)
        write_text(LABELS.footer, height=5, size=9, align="C")
        pdf.output(output_path)
