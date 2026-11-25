"""生成报告链路流程图 docs/images/report-pipeline.png。

依赖仅 Pillow。链路变化后重跑即可更新：

    python tools/draw_report_pipeline.py

图中事实以 report/generation.py 与 agents/verifier.py 为准：检索读病例上下文，
撰稿读病例上下文加命中块，核查复用同一批块。
"""
from PIL import Image, ImageDraw, ImageFont
import pathlib

W, H = 1500, 2050
img = Image.new("RGB", (W, H), "#ffffff")
d = ImageDraw.Draw(img)

FONT = "C:/Windows/Fonts/msyh.ttc"
def f(size, bold=False):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc" if bold else FONT, size)
    except OSError:
        return ImageFont.load_default()

F_TITLE = f(34, True)
F_H = f(22, True)
F_BODY = f(18)
F_SMALL = f(15)
F_TINY = f(13)

INK = "#1a1a1a"
GREY = "#5b6472"
LINE = "#8a94a6"

def box(x, y, w, h, lines, fill, edge, fnt=F_BODY, fh=22, radius=8, align="center"):
    d.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill, outline=edge, width=2)
    total = len(lines) * fh
    ty = y + (h - total) // 2
    for ln in lines:
        tw = d.textlength(ln, font=fnt)
        tx = x + (w - tw) // 2 if align == "center" else x + 14
        d.text((tx, ty), ln, font=fnt, fill=INK)
        ty += fh

def arrow(x1, y1, x2, y2, label=None, dashed=False, lx=None, ly=None):
    if dashed:
        # 虚线
        import math
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        n = max(1, int(L // 12))
        for i in range(n):
            if i % 2 == 0:
                sx, sy = x1 + dx * i / n, y1 + dy * i / n
                ex, ey = x1 + dx * (i + 1) / n, y1 + dy * (i + 1) / n
                d.line([sx, sy, ex, ey], fill=LINE, width=2)
    else:
        d.line([x1, y1, x2, y2], fill=LINE, width=2)
    # 箭头头
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    s = 9
    d.polygon([(x2, y2),
               (x2 - s * math.cos(ang - 0.4), y2 - s * math.sin(ang - 0.4)),
               (x2 - s * math.cos(ang + 0.4), y2 - s * math.sin(ang + 0.4))], fill=LINE)
    if label:
        tw = d.textlength(label, font=F_SMALL)
        lx = lx if lx is not None else (x1 + x2) / 2 - tw / 2
        ly = ly if ly is not None else (y1 + y2) / 2 - 9
        d.rectangle([lx - 5, ly - 3, lx + tw + 5, ly + 19], fill="#ffffff")
        d.text((lx, ly), label, font=F_SMALL, fill=GREY)

# ---------- 标题 ----------
d.text((50, 30), "OcuPanel 报告生成链路", font=F_TITLE, fill=INK)
d.text((50, 76), "检索依据 = 病例上下文 ｜ 草稿依据 = 病例上下文 + 检索到的语料块", font=F_SMALL, fill=GREY)

Y0 = 120
CX = 300          # 主轴中心
BW = 330          # 主轴框宽

# ---------- 1 输入 ----------
box(CX - BW//2, Y0, BW, 70, ["① 上传眼底图 + 临床记录", "（图片文件、Clinician note）"],
    "#eef4ff", "#4a7dd6")

# ---------- 2 视觉 ----------
arrow(CX, Y0+70, CX, Y0+108)
box(CX - BW//2, Y0+108, BW, 76, ["② 视觉模型分析", "vision/analyze_fundus"],
    "#eef4ff", "#4a7dd6")

# ---------- 3 病例上下文 ----------
arrow(CX, Y0+184, CX, Y0+222)
box(CX - BW//2, Y0+222, BW, 96,
    ["③ 病例上下文 build_context", "影像结果：概率 / CDR / 警示", "+ Clinician note 原文"],
    "#dff0e8", "#3f9e6f")

# 右侧分支说明
box(700, Y0+222, 300, 96, ["这是检索与撰稿的", "共同起点", "★ 不是草稿"],
    "#fff8e1", "#d9a441", fnt=F_SMALL, fh=24)
arrow(CX + BW//2, Y0+270, 700, Y0+270, dashed=True)

# ---------- 4 检索 ----------
arrow(CX, Y0+318, CX, Y0+356)
box(CX - BW//2, Y0+356, BW, 92,
    ["④ 检索 retrieve_evidence", "按病种分四方面：诊断/判读/", "治疗/随访，各取若干条"],
    "#fdeee0", "#d97a2b")

# 语料库侧栏
LX = 700
box(LX, Y0+356, 560, 92, ["语料库 172 块（切分块）",
                          "corpus/*.md  +  corpus/guidelines/*.json",
                          "切分：按 ## 分节 → 段落"],
    "#f2f2f5", "#7b7f8a", fnt=F_SMALL, fh=26)
arrow(LX, Y0+402+0, CX + BW//2 + 4, Y0+402, "查询")
# 实际用箭头指向检索框
d.line([LX, Y0+392, CX + BW//2 + 6, Y0+392], fill=LINE, width=2)

# ---------- 5 编号 ----------
arrow(CX, Y0+448, CX, Y0+486)
box(CX - BW//2, Y0+486, BW, 82,
    ["⑤ 命中块 → 分配编号", "[1] [2] ... [n]  全局唯一", "（仅约 12 条，不是全部语料）"],
    "#fdeee0", "#d97a2b")

# ---------- 6 撰稿 ----------
arrow(CX, Y0+568, CX, Y0+606)
box(CX - BW//2, Y0+606, BW, 104,
    ["⑥ 撰稿 SpecialistAgent / Director", "提示词 = ③ 病例上下文", "＋ ⑤ 带编号的块",
     "→ 产出草稿，句末标 [n]"],
    "#e8e2f7", "#6b4fb0")

arrow(CX + BW//2, Y0+658, LX, Y0+658, "同一批块", dashed=True)

# ---------- 7 草稿 ----------
arrow(CX, Y0+710, CX, Y0+748)
box(CX - BW//2, Y0+748, BW, 60, ["⑦ 草稿文本（含 [n] 引用）"],
    "#e8e2f7", "#6b4fb0")

# ---------- 8 核查 ----------
arrow(CX, Y0+808, CX, Y0+846)
box(CX - BW//2, Y0+846, BW, 104,
    ["⑧ 核查 CitationVerifier", "逐句对照同一批块", "①编号是否存在 ②语义是否支持",
     "③ grounding 逐字核对原文"],
    "#ddeef7", "#2f7fa3")

arrow(CX + BW//2, Y0+898, LX, Y0+898, "不重新检索", dashed=True)
d.text((LX + 10, Y0+862), "用的还是 ⑤ 那批块", font=F_TINY, fill=GREY)
d.text((LX + 10, Y0+880), "编号不变，[3] 前后指同一条款", font=F_TINY, fill=GREY)

# ---------- 9 判定 ----------
arrow(CX, Y0+950, CX, Y0+988)
box(CX - BW//2, Y0+988, BW, 66, ["⑨ 有无法支持的句子？"], "#fff8e1", "#d9a441")

# 分支
arrow(CX - BW//2, Y0+1021, 150, Y0+1021, "否", lx=CX - BW//2 - 46, ly=Y0+998)
arrow(CX + BW//2, Y0+1021, W - 230, Y0+1021, "是", lx=CX + BW//2 + 14, ly=Y0+998)

# 通过
box(40, Y0+1060, 300, 92, ["交付正文", "status = pass / rewritten", "附带 grounding 对照"],
    "#e3f3e8", "#3f9e6f", fnt=F_SMALL, fh=26)

# 修订
box(W - 380, Y0+1060, 320, 92, ["⑩ 改写 / 删除问题句", "→ 复核（≤2 轮）"],
    "#fdeee0", "#d97a2b", fnt=F_SMALL, fh=26)

# 修订后仍失败
arrow(W - 220, Y0+1152, W - 220, Y0+1190)
box(W - 380, Y0+1190, 320, 92, ["整份撤回", "只剩病例记录摘要", "status = limited"],
    "#fbe3e3", "#c0504d", fnt=F_SMALL, fh=26)

# 修订成功回到交付
d.line([W - 380, Y0+1106, 355, Y0+1106], fill=LINE, width=2)
arrow(355, Y0+1106, 345, Y0+1106)

# ---------- 底部说明 ----------
BY = Y0 + 1320
d.rounded_rectangle([40, BY, W - 40, BY + 300], radius=10, fill="#f7f8fa", outline="#c9ced8", width=2)
d.text((60, BY + 16), "三个关键点", font=F_H, fill=INK)

notes = [
    ("检索在前，草稿在后。", "草稿还不存在时就不可能拿它去检索——检索用的是③病例上下文。"),
    ("切分块 = 语料。", "172 块静态存在于 corpus/，检索只是从中「命中」约 12 条，不是把草稿切分。"),
    ("核查与撰稿共用同一批块。", "编号一次分配贯穿始终；若核查时重新检索，[3] 可能指向不同条款，引用就失去意义。"),
]
ty = BY + 54
for head, body in notes:
    d.text((60, ty), "•", font=F_BODY, fill="#d97a2b")
    d.text((80, ty), head, font=f(18, True), fill=INK)
    ty += 28
    d.text((96, ty), body, font=F_SMALL, fill=GREY)
    ty += 46

d.text((60, ty + 6), "语料缺失时链路断在⑧：检索不到 → 核查无据 → ⑨判「是」 → 整份撤回。",
       font=F_SMALL, fill="#c0504d")

out = pathlib.Path("docs/images")
out.mkdir(parents=True, exist_ok=True)
p = out / "report-pipeline.png"
# 裁掉底部多余空白
img = img.crop((0, 0, W, BY + 330))
img.save(p)
print("saved", p, img.size)