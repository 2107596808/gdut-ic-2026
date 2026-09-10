#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
个人简介 PDF 生成脚本
=====================================================================
个人信息都在下面的 PROFILE 字典里，改完运行：
    pip install reportlab
    python profile/make_pdf.py
就会生成 profile/个人简介.pdf（A4 一页）

为什么用脚本而不是直接用 Word？
    ① 内容用代码描述，改一个字就能重出一份，不会出现“PDF 和网页上的信息不一致”；
    ② 中文字体在代码里明确指定（黑体/宋体），换台电脑也不会变乱码；
    ③ 这份脚本本身也是仓库的一部分，评审能看到我是怎么做的。

（个人主页 docs/index.html 里是同一套信息，改完记得两边保持一致。）
=====================================================================
"""
import os
import sys

# ============================================================ 在这里改信息
PROFILE = {
    "name": "邵钜权",
    "title": "集成电路与集成系统 1 班",
    "school": "广东工业大学 集成电路学院",
    "contact": [
        ("邮箱", "2107596808@qq.com"),
        ("GitHub", "https://github.com/2107596808"),
        ("个人主页", "https://2107596808.github.io/gdut-ic-2026/"),
    ],
    "interests": [
        "模拟电路与仿真 —— 把电路先手算一遍、再用 PySpice 仿真一遍，看两者差在哪里",
        "算法与数据结构 —— 借 2048 的 AI 练搜索：expectimax、位棋盘、置换表、迭代加深",
        "工程习惯 —— 习惯用 Git 分步提交，动手之前先想清楚「怎么验收」",
    ],
    "skills": [
        ("编程语言", "Python / JavaScript"),
        ("工具", "Git、VS Code、Linux 命令行、AI 编程工具（DeepSeek Harness / Codex）"),
        ("正在学", "Verilog 与数字电路设计、集成电路设计与仿真流程"),
    ],
    "projects": [
        ("2048 游戏 + AI 自动求解",
         "纯前端单文件实现，阶段一可自由操作，阶段二用「角块启发式 + expectimax」自动演示，"
         "实测能稳定合出 1024 方块。仓库中附了完整的提示词迭代记录。"),
        ("PySpice 三个电路（RC 低通 / 戴维南验证 / NMOS 共源放大）",
         "用 PySpice + ngspice 在 WSL 里实跑，数据不是估算的：RC 低通的 τ = 100 µs、fc ≈ 1591.5 Hz，并给出方波瞬态响应与波特图；戴维南定理验证出 V_oc = 9 V、I_sc = 3 mA、R_th = 3 kΩ，等效电路替换后接负载的电压/电流误差 < 0.01%；NMOS 共源放大算出 V_GS = 2 V、I_D = 0.8 mA、V_DS = 3.4 V（工作在饱和区）、|Av| ≈ 3.10 且输出反相。"),
    ],
    "about": (
        "我是邵钜权，广东工业大学集成电路学院集成电路与集成系统专业的大一新生。"
        "最感兴趣的是硬件和代码的交界处：一边把电路的理论值算一遍、再用 PySpice 仿真一遍，看两者差在哪里；"
        "一边写点小项目，比如给 2048 写一个会自动下棋的 AI。"
        "这次考核印象最深的一句话是「AI 写代码很快，但判断它对不对只能靠自己」——"
        "移植 expectimax 时，缓存键整整错了三版，最后是写脚本把两个棋盘的键算出来逐位比对才找到的；"
        "从那以后我养成了先定验收标准、再动手的习惯。希望能加入协会，和更多同学一起把东西真正做出来。"
    ),
}

# ============================================================ 字体（Windows 自带）
FONT_CANDIDATES = [
    (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc"),   # 微软雅黑
    (r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simhei.ttf"),  # 黑体
    (r"C:\Windows\Fonts\simsun.ttc", r"C:\Windows\Fonts\simsunb.ttf"),  # 宋体
    ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/PingFang.ttc"),  # macOS
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
     "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),           # Linux
]


def find_fonts():
    """找一个能显示中文的字体；找不到就退回内置字体（会提示可能乱码）"""
    for regular, bold in FONT_CANDIDATES:
        if os.path.exists(regular):
            return regular, (bold if os.path.exists(bold) else regular)
    return None, None


def build_pdf(output_path):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    regular, bold = find_fonts()
    if regular:
        pdfmetrics.registerFont(TTFont("CN", regular))
        pdfmetrics.registerFont(TTFont("CN-Bold", bold))
        font, font_bold = "CN", "CN-Bold"
    else:
        print("  ! 没找到中文字体，中文可能显示为方块。")
        print("    Windows 上一般自带 C:\\Windows\\Fonts\\msyh.ttc，请检查该文件是否存在。")
        font = font_bold = "Helvetica"

    accent = colors.HexColor("#1f6feb")
    ink = colors.HexColor("#222222")
    dim = colors.HexColor("#666666")

    title = ParagraphStyle("title", fontName=font_bold, fontSize=26, leading=32, textColor=ink)
    subtitle = ParagraphStyle("subtitle", fontName=font, fontSize=12, leading=18, textColor=dim)
    section = ParagraphStyle("section", fontName=font_bold, fontSize=13, leading=20,
                             textColor=accent, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", fontName=font, fontSize=10.5, leading=17,
                          textColor=ink, alignment=TA_JUSTIFY)
    cell = ParagraphStyle("cell", fontName=font, fontSize=10, leading=15, textColor=ink)
    cell_dim = ParagraphStyle("cellDim", fontName=font, fontSize=10, leading=15, textColor=dim)

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=16 * mm,
        title=f"{PROFILE['name']} · 个人简介", author=PROFILE["name"],
    )
    flow = []

    # ---- 头部 ----
    flow.append(Paragraph(PROFILE["name"], title))
    flow.append(Spacer(1, 3))
    flow.append(Paragraph(f"{PROFILE['title']}　|　{PROFILE['school']}", subtitle))
    flow.append(Spacer(1, 6))
    flow.append(HRFlowable(width="100%", thickness=1.6, color=accent, spaceAfter=6))

    # ---- 联系方式 ----
    contact_bits = "　·　".join(f"{k}：{v}" for k, v in PROFILE["contact"] if v)
    flow.append(Paragraph(contact_bits, subtitle))

    # ---- 自我介绍 ----
    flow.append(Paragraph("自我介绍", section))
    flow.append(Paragraph(PROFILE["about"], body))

    # ---- 兴趣 ----
    flow.append(Paragraph("兴趣方向", section))
    for item in PROFILE["interests"]:
        flow.append(Paragraph(f"•　{item}", body))

    # ---- 技能 ----
    flow.append(Paragraph("技能与工具", section))
    skill_rows = [[Paragraph(f"<b>{k}</b>", cell), Paragraph(v, cell)] for k, v in PROFILE["skills"]]
    skill_table = Table(skill_rows, colWidths=[30 * mm, 140 * mm])
    skill_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#e5e5e5")),
    ]))
    flow.append(skill_table)

    # ---- 项目经历 ----
    flow.append(Paragraph("项目经历", section))
    for name, desc in PROFILE["projects"]:
        flow.append(Paragraph(f"<b>{name}</b>", body))
        flow.append(Paragraph(desc, cell_dim))
        flow.append(Spacer(1, 4))

    # ---- 页脚 ----
    flow.append(Spacer(1, 8))
    flow.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#dddddd")))
    flow.append(Spacer(1, 3))
    flow.append(Paragraph("本文件由 profile/make_pdf.py 生成（reportlab），源码与个人主页一并保存在我的 GitHub 仓库中。",
                          cell_dim))

    doc.build(flow)
    return bool(regular)


def publish_to_docs(pdf_path):
    """GitHub Pages 只能发布 docs/ 目录，所以把 PDF 复制一份过去供主页下载。"""
    import shutil
    here = os.path.dirname(os.path.abspath(__file__))
    docs_dir = os.path.normpath(os.path.join(here, "..", "docs"))
    if not os.path.isdir(docs_dir):
        return None
    target = os.path.join(docs_dir, os.path.basename(pdf_path))
    shutil.copyfile(pdf_path, target)
    return target


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    output = os.path.join(here, "个人简介.pdf")
    print("=" * 60)
    print("生成个人简介 PDF")
    print("=" * 60)
    ok = build_pdf(output)
    size = os.path.getsize(output)
    print(f"  ✓ 已生成 {output}（{size / 1024:.1f} KB）")
    copied = publish_to_docs(output)
    if copied:
        print(f"  ✓ 已复制到 {copied}（供个人主页的“下载个人简介 PDF”按钮使用）")
    if not ok:
        print("  ! 中文字体没找到，中文可能显示异常，请检查字体路径。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
