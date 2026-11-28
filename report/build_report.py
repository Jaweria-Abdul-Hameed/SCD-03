#!/usr/bin/env python3
"""Native ReportLab PDF generator for CS4032 Assignment 03 (RAHBAR RAGOps).

Generates a publication-grade A4 engineering report directly via ReportLab
Platypus without any HTML-to-PDF conversion:
  - Main body: Pages 1-8 (strictly <= 8 pages per Assignment 03 Part G)
  - Screenshot proofs: Page 9+ (13 authentic Nov 28 terminal captures)

Outputs:
  - report/Report_CS4032_Assignment03.pdf
  - Report_CS4032_Assignment03.pdf (byte-identical root copy)
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
REPORT_PDF = ROOT / "report" / "Report_CS4032_Assignment03.pdf"
ROOT_PDF = ROOT / "Report_CS4032_Assignment03.pdf"
SCREENSHOTS_DIR = ROOT / "screenshots"

# ---------------------------------------------------------------------------
# Color Palette (Academic / Systems Engineering)
# ---------------------------------------------------------------------------
NAVY = colors.HexColor("#0f172a")
SLATE_HDR = colors.HexColor("#1e3a5f")
ACCENT = colors.HexColor("#0284c7")
MONO_BLUE = colors.HexColor("#0369a1")
TEXT_MAIN = colors.HexColor("#1e293b")
TEXT_MUTED = colors.HexColor("#475569")
ZEBRA = colors.HexColor("#f8fafc")
CARD_BG = colors.HexColor("#f8fafc")
BORDER = colors.HexColor("#cbd5e1")
BORDER_LIGHT = colors.HexColor("#e2e8f0")
PASS_BG = colors.HexColor("#dcfce7")
PASS_FG = colors.HexColor("#166534")
PASS_CARD_BG = colors.HexColor("#f0fdf4")
FAIL_BG = colors.HexColor("#fee2e2")
FAIL_FG = colors.HexColor("#991b1b")
TERM_BG = colors.HexColor("#0f172a")

# ---------------------------------------------------------------------------
# Page Geometry
# ---------------------------------------------------------------------------
PAGE_W, PAGE_H = A4  # 595.27 x 841.89 pt
MARGIN_L = 12 * mm
MARGIN_R = 12 * mm
MARGIN_T = 13.5 * mm
MARGIN_B = 12.5 * mm
USABLE_W = PAGE_W - MARGIN_L - MARGIN_R  # ~527.24 pt


# ---------------------------------------------------------------------------
# Font Registration & Glyph Verification
# ---------------------------------------------------------------------------
def _register_fonts() -> tuple[str, str, list[TTFont]]:
    """Register Unicode TrueType sans-serif and monospace font families."""
    loaded_ttfs: list[TTFont] = []
    sans_candidates = [
        (
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/segoeuii.ttf",
            "C:/Windows/Fonts/segoeuiz.ttf",
        ),
        (
            "C:/Windows/Fonts/calibri.ttf",
            "C:/Windows/Fonts/calibrib.ttf",
            "C:/Windows/Fonts/calibrii.ttf",
            "C:/Windows/Fonts/calibriz.ttf",
        ),
        (
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/ariali.ttf",
            "C:/Windows/Fonts/arialbi.ttf",
        ),
    ]
    sans_name = "Helvetica"
    for reg, bold, ital, bi in sans_candidates:
        if all(os.path.exists(p) for p in (reg, bold, ital, bi)):
            f_reg = TTFont("ReportSans", reg)
            f_bold = TTFont("ReportSans-Bold", bold)
            f_ital = TTFont("ReportSans-Italic", ital)
            f_bi = TTFont("ReportSans-BoldItalic", bi)
            for f in (f_reg, f_bold, f_ital, f_bi):
                pdfmetrics.registerFont(f)
                loaded_ttfs.append(f)
            registerFontFamily(
                "ReportSans",
                normal="ReportSans",
                bold="ReportSans-Bold",
                italic="ReportSans-Italic",
                boldItalic="ReportSans-BoldItalic",
            )
            sans_name = "ReportSans"
            break

    mono_name = "Courier"
    if os.path.exists("C:/Windows/Fonts/consola.ttf") and os.path.exists(
        "C:/Windows/Fonts/consolab.ttf"
    ):
        m_reg = TTFont("ReportMono", "C:/Windows/Fonts/consola.ttf")
        m_bold = TTFont("ReportMono-Bold", "C:/Windows/Fonts/consolab.ttf")
        pdfmetrics.registerFont(m_reg)
        pdfmetrics.registerFont(m_bold)
        loaded_ttfs.extend([m_reg, m_bold])
        registerFontFamily(
            "ReportMono",
            normal="ReportMono",
            bold="ReportMono-Bold",
            italic="ReportMono",
            boldItalic="ReportMono-Bold",
        )
        mono_name = "ReportMono"

    return sans_name, mono_name, loaded_ttfs


SANS, MONO, _LOADED_TTFS = _register_fonts()
_COLLECTED_STRINGS: list[str] = []


def _record(text: str) -> str:
    _COLLECTED_STRINGS.append(text)
    return text


def _verify_glyphs() -> None:
    """Ensure every non-tag character rendered exists in the registered TTF cmaps."""
    if not _LOADED_TTFS:
        return
    common_cmap = set(_LOADED_TTFS[0].face.charToGlyph.keys())
    for tf in _LOADED_TTFS[1:]:
        common_cmap &= set(tf.face.charToGlyph.keys())
    strip_tags = re.compile(r"<[^>]+>")
    missing: set[str] = set()
    for raw in _COLLECTED_STRINGS:
        plain = strip_tags.sub("", raw)
        plain = (
            plain.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
        )
        for ch in plain:
            if ch in ("\n", "\r", "\t"):
                continue
            if ord(ch) not in common_cmap:
                missing.add(f"{ch!r} (U+{ord(ch):04X})")
    if missing:
        raise ValueError(f"Unsupported font glyphs detected: {sorted(missing)}")


# ---------------------------------------------------------------------------
# Inline Markup Helpers
# ---------------------------------------------------------------------------
def code(text: str, size_delta: float = -0.3) -> str:
    """Format inline code safely in monospace blue."""
    _ = size_delta
    return f'<font name="{MONO}" color="#0369a1">{escape(text)}</font>'


def th_code(text: str) -> str:
    """Format inline code inside dark table headers with high-contrast light sky tint."""
    return f'<font name="{MONO}" color="#bae6fd">{escape(text)}</font>'


def b(text: str) -> str:
    return f"<b>{text}</b>"


def pass_badge(label: str = "PASS") -> str:
    return f'<font name="{SANS}-Bold" color="#166534">[{escape(label)}]</font>'


def fail_badge(label: str = "FAIL") -> str:
    return f'<font name="{SANS}-Bold" color="#991b1b">[{escape(label)}]</font>'


# ---------------------------------------------------------------------------
# Styles Factory
# ---------------------------------------------------------------------------
def make_styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "TitleMain",
            fontName=f"{SANS}-Bold",
            fontSize=12.8,
            leading=15.0,
            textColor=NAVY,
            spaceAfter=1.5,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            fontName=f"{SANS}-Bold",
            fontSize=8.4,
            leading=10.5,
            textColor=ACCENT,
            spaceAfter=1.5,
        ),
        "meta_right": ParagraphStyle(
            "MetaRight",
            fontName=SANS,
            fontSize=7.0,
            leading=9.2,
            textColor=TEXT_MUTED,
            alignment=TA_RIGHT,
        ),
        "meta_left": ParagraphStyle(
            "MetaLeft",
            fontName=SANS,
            fontSize=6.9,
            leading=8.9,
            textColor=TEXT_MUTED,
        ),
        "h2": ParagraphStyle(
            "SecH2",
            fontName=f"{SANS}-Bold",
            fontSize=9.2,
            leading=11.2,
            textColor=NAVY,
            spaceBefore=3.5,
            spaceAfter=2.0,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "SecH3",
            fontName=f"{SANS}-Bold",
            fontSize=7.8,
            leading=9.6,
            textColor=SLATE_HDR,
            spaceBefore=2.5,
            spaceAfter=1.2,
            keepWithNext=True,
        ),
        "cap": ParagraphStyle(
            "TableCaption",
            fontName=f"{SANS}-Bold",
            fontSize=6.9,
            leading=8.5,
            textColor=SLATE_HDR,
            spaceBefore=2.0,
            spaceAfter=1.5,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName=SANS,
            fontSize=7.0,
            leading=9.0,
            textColor=TEXT_MAIN,
            spaceAfter=2.2,
        ),
        "body_sm": ParagraphStyle(
            "BodySm",
            fontName=SANS,
            fontSize=6.55,
            leading=8.3,
            textColor=TEXT_MAIN,
            spaceAfter=1.5,
        ),
        "th": ParagraphStyle(
            "Th",
            fontName=f"{SANS}-Bold",
            fontSize=6.45,
            leading=7.8,
            textColor=colors.white,
            alignment=TA_LEFT,
        ),
        "td": ParagraphStyle(
            "Td",
            fontName=SANS,
            fontSize=6.25,
            leading=7.7,
            textColor=TEXT_MAIN,
        ),
        "td_tight": ParagraphStyle(
            "TdTight",
            fontName=SANS,
            fontSize=6.0,
            leading=7.3,
            textColor=TEXT_MAIN,
        ),
        "td_p1": ParagraphStyle(
            "TdP1",
            fontName=SANS,
            fontSize=5.85,
            leading=7.1,
            textColor=TEXT_MAIN,
        ),
        "td_p2": ParagraphStyle(
            "TdP2",
            fontName=SANS,
            fontSize=6.05,
            leading=7.35,
            textColor=TEXT_MAIN,
        ),
        "td_qa": ParagraphStyle(
            "TdQA",
            fontName=SANS,
            fontSize=6.15,
            leading=7.5,
            textColor=TEXT_MAIN,
        ),
        "qa_body": ParagraphStyle(
            "QABody",
            fontName=SANS,
            fontSize=6.4,
            leading=8.0,
            textColor=TEXT_MAIN,
        ),
        "card_lbl": ParagraphStyle(
            "CardLbl",
            fontName=f"{SANS}-Bold",
            fontSize=6.4,
            leading=7.8,
            textColor=SLATE_HDR,
            spaceAfter=1.0,
        ),
        "callout": ParagraphStyle(
            "Callout",
            fontName=SANS,
            fontSize=6.55,
            leading=8.3,
            textColor=PASS_FG,
        ),
        "footnote": ParagraphStyle(
            "Footnote",
            fontName=SANS,
            fontSize=6.15,
            leading=7.7,
            textColor=TEXT_MUTED,
            spaceBefore=1.5,
            spaceAfter=2.0,
        ),
        "img_cap": ParagraphStyle(
            "ImgCap",
            fontName=SANS,
            fontSize=7.0,
            leading=9.2,
            textColor=TEXT_MAIN,
        ),
        "app_intro": ParagraphStyle(
            "AppIntro",
            fontName=SANS,
            fontSize=7.4,
            leading=9.6,
            textColor=TEXT_MUTED,
            spaceAfter=4.0,
        ),
        "center_th": ParagraphStyle(
            "CenterTh",
            fontName=f"{SANS}-Bold",
            fontSize=6.45,
            leading=7.8,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
    }


ST = make_styles()


def p(text: str, style_key: str = "body") -> Paragraph:
    return Paragraph(_record(text), ST[style_key])


def sec_heading(num: str, title: str) -> Table:
    """Render a crisp section header bar with blue badge pill and bottom divider."""
    badge = Paragraph(
        _record(f'<font color="#ffffff"><b>{escape(num)}</b></font>'),
        ParagraphStyle(
            "Badge",
            fontName=f"{SANS}-Bold",
            fontSize=7.0,
            leading=8.5,
            alignment=TA_CENTER,
            textColor=colors.white,
        ),
    )
    heading = Paragraph(
        _record(f"<b>{escape(title)}</b>"),
        ParagraphStyle(
            "SecTitle",
            fontName=f"{SANS}-Bold",
            fontSize=9.0,
            leading=10.8,
            textColor=NAVY,
        ),
    )
    badge_w = 28 if len(num) > 2 else 18
    tbl = Table([[badge, heading]], colWidths=[badge_w, USABLE_W - badge_w])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), ACCENT),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 2),
                ("RIGHTPADDING", (0, 0), (0, 0), 2),
                ("LEFTPADDING", (1, 0), (1, 0), 5),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.0),
                ("LINEBELOW", (0, 0), (-1, 0), 0.9, ACCENT),
            ]
        )
    )
    return tbl


def styled_table(
    headers: list[str],
    rows: list[list[str | Paragraph]],
    col_widths: list[float],
    cell_style: str = "td",
    pad_v: float = 1.8,
    pad_h: float = 3.2,
    extra_styles: list[tuple] | None = None,
) -> Table:
    """Build a standard academic table with navy header, zebra shading, and repeatRows."""
    hdr_row = [p(h, "th") for h in headers]
    body_rows = [
        [c if isinstance(c, Paragraph) else p(c, cell_style) for c in r] for r in rows
    ]
    tbl = Table([hdr_row, *body_rows], colWidths=col_widths, repeatRows=1)
    styles: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), SLATE_HDR),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, NAVY),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), pad_h),
        ("RIGHTPADDING", (0, 0), (-1, -1), pad_h),
        ("TOPPADDING", (0, 0), (-1, -1), pad_v),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad_v),
    ]
    if extra_styles:
        styles.extend(extra_styles)
    tbl.setStyle(TableStyle(styles))
    return tbl


def callout_box(text: str, accent: colors.Color = PASS_FG, bg: colors.Color = PASS_CARD_BG) -> Table:
    tbl = Table([[p(text, "body_sm")]], colWidths=[USABLE_W])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("BOX", (0, 0), (-1, -1), 0.45, BORDER),
                ("LINEBEFORE", (0, 0), (0, -1), 2.5, accent),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3.0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.0),
            ]
        )
    )
    return tbl


# ---------------------------------------------------------------------------
# Numbered Canvas for Running Headers & "Page X of Y" Footers
# ---------------------------------------------------------------------------
class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas rendering running headers (Pages 2+) and Page X of Y footers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_chrome(total_pages)
            super().showPage()
        super().save()

    def _draw_chrome(self, total_pages: int) -> None:
        page_num = self._pageNumber
        self.saveState()

        # Running header on pages 2+
        if page_num >= 2:
            y_hdr = PAGE_H - 9.5 * mm
            self.setStrokeColor(BORDER)
            self.setLineWidth(0.5)
            self.line(MARGIN_L, y_hdr - 2.5, PAGE_W - MARGIN_R, y_hdr - 2.5)
            self.setFont(f"{SANS}-Bold", 6.8)
            self.setFillColor(SLATE_HDR)
            self.drawString(MARGIN_L, y_hdr, "RAHBAR RAGOps \u2014 Technical Engineering Report")
            self.setFont(SANS, 6.8)
            self.setFillColor(TEXT_MUTED)
            self.drawRightString(
                PAGE_W - MARGIN_R, y_hdr, "CS4032 \u00b7 Assignment 03 \u00b7 Fall 2026"
            )

        # Running footer on all pages
        y_ftr = 7.2 * mm
        self.setStrokeColor(BORDER)
        self.setLineWidth(0.5)
        self.line(MARGIN_L, y_ftr + 6.5, PAGE_W - MARGIN_R, y_ftr + 6.5)
        self.setFont(SANS, 6.7)
        self.setFillColor(TEXT_MUTED)
        self.drawString(
            MARGIN_L,
            y_ftr,
            "FAST-NUCES Islamabad \u00b7 Jaweria Abdul Hameed (i243025) & Mohsin Khan (i243135)",
        )
        self.setFont(f"{SANS}-Bold", 6.8)
        self.setFillColor(SLATE_HDR)
        self.drawRightString(PAGE_W - MARGIN_R, y_ftr, f"Page {page_num} of {total_pages}")
        self.restoreState()


# ---------------------------------------------------------------------------
# Page Builders (Pages 1-8 Main Body + Page 9+ Screenshot Proofs)
# ---------------------------------------------------------------------------
def build_page1() -> list:
    story: list = []

    # Header Banner
    left_hdr = [
        p("RAHBAR RAGOps: Operating &amp; Managing Enterprise Retrieval Pipelines", "title"),
        p(
            "Software Construction and Development (CS4032) \u00b7 Assignment 03 \u2014 RAGOps \u00b7 Fall 2026",
            "subtitle",
        ),
        p(
            "FAST-NUCES Islamabad \u00b7 Ref: Xu et al. (2026) \u00b7 Minikube v1.34 / Kubernetes v1.31.0 (Calico CNI, ns "
            + code("rahbar")
            + ")",
            "meta_left",
        ),
    ]
    right_hdr = [
        p(
            f"{b('Jaweria Abdul Hameed \u2014 i243025')} \u00b7 jaweriahameed06@gmail.com<br/>"
            f"{b('Mohsin Khan \u2014 i243135')} \u00b7 mohsinkhan.devs@gmail.com<br/>"
            f"{b('Repository:')} https://github.com/Jaweria-Abdul-Hameed/SCD-03<br/>"
            f"{b('Generator:')} {code('report/build_report.py')} (ReportLab Native PDF)",
            "meta_right",
        )
    ]
    hdr_tbl = Table([[left_hdr, right_hdr]], colWidths=[305, USABLE_W - 305])
    hdr_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, 0), 1.6, ACCENT),
            ]
        )
    )
    story.append(hdr_tbl)
    story.append(Spacer(1, 3))

    # Executive Summary + AI Statement (left) | Contribution Table (right)
    exec_card = Table(
        [
            [
                p(
                    f"{b('EXECUTIVE SUMMARY &amp; THEORETICAL BASIS')}<br/>"
                    f"RAHBAR extends FAST-NUCES's academic advising RAG system to operationalize the "
                    f"<i>Xu et al. (2026)</i> RAGOps lifecycle on a hardened Minikube/Calico cluster "
                    f"(namespace {code('rahbar')}). It integrates four pre-chunking verification gates, "
                    f"Data Lake archiving/rollback, a 32-question 3-level offline evaluation suite, "
                    f"dual-rail prompt-injection defense, 21-field JSONL tracing with Redis semantic caching, "
                    f"live query coverage monitoring ({code('85.71%')}), and ConfigMap-driven release gates "
                    f"with instant rollback.",
                    "td_p1",
                )
            ]
        ],
        colWidths=[236],
    )
    exec_card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
                ("BOX", (0, 0), (-1, -1), 0.45, BORDER),
                ("LINEBEFORE", (0, 0), (0, -1), 2.5, ACCENT),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    ai_card = Table(
        [
            [
                p(
                    f"{b('AI USAGE STATEMENT (HONEST ATTRIBUTION)')}<br/>"
                    f"AI coding agents (Muse/Boone, Claude Code, and Gemini-assisted orchestration) were "
                    f"used for code, test, and Kubernetes manifest remediation, cluster verification "
                    f"automation, and report drafting ({code('docs/AI-USAGE.md')}). Every metric, trace, "
                    f"and terminal capture reported here was produced by live pipeline and cluster runs "
                    f"and independently verified by both members.",
                    "td_p1",
                )
            ]
        ],
        colWidths=[236],
    )
    ai_card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PASS_CARD_BG),
                ("BOX", (0, 0), (-1, -1), 0.45, BORDER),
                ("LINEBEFORE", (0, 0), (0, -1), 2.5, PASS_FG),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )

    contrib_tbl = styled_table(
        ["Member", "Assigned Parts", "Key Artifacts & Verified Commits"],
        [
            [
                f"{b('Mohsin Khan')}<br/>{code('i243135')}",
                "Parts A, C, F + Phase 2/3 Verification, F5 Sizing &amp; Native PDF",
                (f"{code('indexer/pipeline/{verify,datalake,store,rollback}.py')}, {code('corpus/batch_b/')}, "
                f"{code('eval/{release_gate.py,gate_thresholds.yaml}')}, {code('k8s/')} manifests &amp; F5 "
                f"sizing, cluster Part A\u2013F verification &amp; F3/F4/F5 evidence, {code('report/build_report.py')}, "
                f"Nov 28 captures ({code('012c1ef')}, {code('926e782')}, {code('09e72ea')}\u2013{code('58a832f')})."),
            ],
            [
                f"{b('Jaweria Abdul Hameed')}<br/>{code('i243025')}",
                "Parts B, D, E, Golden Review &amp; Initial Part G Synthesis",
                (f"{code('eval/golden.jsonl')} (co-reviewed), {code('eval/{run_ragops_eval.py,live_queries.jsonl,coverage_check.py}')}, "
                f"{code('api/app/services/{tracing,guardrails}.py')}, {code('scripts/{trace_tool,summarize_traces}.py')}, "
                f"initial Part G synthesis &amp; {code('README.md')} ({code('90ce371')}, {code('8ed8d56')}, {code('16cdeb1')}, "
                f"{code('c8ac1ce')}\u2013{code('d7eebbf')})."),
            ],
        ],
        col_widths=[68, 68, 150],
        cell_style="td_p1",
        pad_v=1.8,
        pad_h=3.0,
    )

    left_stack = Table([[exec_card], [Spacer(1, 2.5)], [ai_card]], colWidths=[236])
    left_stack.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    right_stack = Table(
        [[p("GROUP CONTRIBUTIONS (GIT HISTORY &amp; docs/AI-USAGE.md)", "card_lbl")], [contrib_tbl]],
        colWidths=[286],
    )
    right_stack.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    top_grid = Table([[left_stack, right_stack]], colWidths=[241, 286])
    top_grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(top_grid)
    story.append(Spacer(1, 3))

    # Section 1: Table 1 (Figure 3 Mapping)
    story.append(sec_heading("1", "Figure 3 Lifecycle Mapping: Paper Specification to RAHBAR Implementation"))
    story.append(Spacer(1, 2))
    story.append(
        p(
            f"Xu et al. (2026, Fig. 3, \u00a7\u00a74.2.1\u20134.2.7) define seven intertwined Data Management stages "
            f"alongside the DevOps query-serving lifecycle: {code('ingest')}, {code('verify')}, "
            f"{code('update data lake')}, {code('update retrieval sources')}, {code('offline testing')}, "
            f"{code('live testing')}, and {code('check coverage')}. Table 1 maps each stage to RAHBAR's "
            f"implemented behavior, source/manifest files, and remaining gaps relative to the paper.",
            "body_sm",
        )
    )
    story.append(p("TABLE 1: XU ET AL. (2026) FIGURE 3 STAGE MAPPING, SOURCE ARTIFACTS &amp; MISSING CAPABILITIES", "cap"))

    t1_rows = [
        [
            f"{b('1.')} {code('ingest')}<br/>(\u00a74.2.1)",
            (f"Discovers {code('.pdf')}, {code('.md')}, {code('.txt')}, and {code('.html')}/{code('.htm')} files from "
            f"{code('/corpus/raw')} (or {code('/corpus/batch_b')} in {code('--additive')} mode); extracts pages via "
            f"PyMuPDF ({code('pypdf')} fallback) with Tesseract OCR on scanned pages (&lt; 20 chars or no fonts), "
            f"strips &gt;80% repeating headers/footers, preserves HTML tables as atomic {code('[TABLE]')} blocks, "
            f"and normalizes text via {code('clean_document()')}. Runs as K8s Batch Jobs and weekly CronJob."),
            (f"{code('indexer/pipeline/__main__.py')}<br/>{code('indexer/pipeline/extract.py')}<br/>"
            f"{code('indexer/pipeline/clean.py')}<br/>{code('k8s/base/indexer-job.yaml')}<br/>"
            f"{code('k8s/base/reindex-cronjob.yaml')}<br/>{code('k8s/indexer-batch-b-job.yaml')}"),
            (f"No automated pull/push connectors (CDC, webhooks, or scheduled web crawler\u2014updates use manual "
            f"{code('fetch_corpus.py')} / {code('kubectl cp')}); no non-text modalities (audio, video, standalone "
            f"images, SQL/graph stores); scanned PDF table grids flatten to text lines and HTML headings collapse to "
            f"{code('Introduction')}."),
        ],
        [
            f"{b('2.')} {code('verify')}<br/>(\u00a74.2.2)",
            (f"Runs four pre-chunking checks before tokenization: <i>Quality</i> (\u2265 20 chars, "
            f"extraction/corruption/symbol ratio), <i>Completeness</i> ({code('source')}, {code('title')}, "
            f"{code('page_count')}, {code('date')}/{code('version')}, page match, truncation markers/abrupt endings), "
            f"<i>Recency</i> ({code('version_sort_key')} superseding older editions and rejecting stale ones), and "
            f"<i>Uniqueness</i> (SHA-256 hash + doc embedding cosine \u2265 0.94). Moves failures to "
            f"{code('/corpus/quarantine/<run_id>/')} and writes {code('verification_<run_id>.json')}."),
            f"{code('indexer/pipeline/verify.py')}<br/>{code('indexer/pipeline/__main__.py')}",
            (f"No pre-chunking <i>Consistency</i> check (the 5th check in Paper \u00a74.2.2 detecting contradictions "
            f"across documents); no verification-time prompt-injection scanner "
            f"({code('b11_library_fine_addendum_injected.md')} passes all 4 checks and is caught only at query time "
            f"by {code('apply_retrieval_rail')} in {code('api/app/services/guardrails.py')}); no live external-API verification."),
        ],
        [
            f"{b('3.')} {code('update data lake')}<br/>(\u00a74.2.3)",
            (f"Stores verified active documents under {code('/corpus/datalake/<doc_id>/<version>/')} indexed by "
            f"{code('registry.json')} (content hashes, {code('chunk_ids')}, {code('doc_embedding')}, chunk/embed "
            f"config); archives superseded editions to {code('/corpus/archive/<doc_id>/<version>/')}; marks "
            f"removed files {code('deleted')}; logs quarantine metadata; and restores archived versions via "
            f"{code('restore_version()')} / {code('rollback_document()')} on the {code('corpus-data')} PVC."),
            (f"{code('indexer/pipeline/datalake.py')}<br/>{code('indexer/pipeline/rollback.py')}<br/>"
            f"{code('k8s/base/corpus-pvc.yaml')}<br/>{code('k8s/rollback-job.yaml')}"),
            (f"No per-document access-control / RBAC metadata (Paper \u00a74.2.3); {code('registry.json')} is a "
            f"single JSON file without concurrency locking or multi-application sharing; no automated quarantine "
            f"retention/cleanup lifecycle policy."),
        ],
        [
            f"{b('4.')} {code('update retrieval sources')}<br/>(\u00a74.2.4)",
            (f"Incrementally updates ChromaDB ({code('rahbar_corpus')} or {code('rahbar_corpus_candidate')}): unchanged "
            f"docs skip embedding ({code('chunks_embedded=0')}); changed docs delete old chunks and re-upsert; "
            f"deleted docs purge all chunks by ID and {code('where={\"source\": ...}')} (0 orphans); superseded "
            f"versions flip {code('superseded=True')}. Chunks (512 tok / 64 overlap), embeds via "
            f"{code('nomic-embed-text')} (768-d, metadata-pinned), validates chunk schema, and flushes Redis cache "
            f"({code('rahbar:cache:*')})."),
            (f"{code('indexer/pipeline/chunk.py')}<br/>{code('indexer/pipeline/embed.py')}<br/>"
            f"{code('indexer/pipeline/store.py')}<br/>{code('indexer/pipeline/__main__.py')}<br/>"
            f"{code('k8s/base/chroma-statefulset.yaml')}"),
            (f"Dense HNSW vector index only\u2014no hybrid sparse/BM25 retrieval, knowledge graph, or cross-encoder "
            f"reranking; changing {code('EMBED_MODEL')} or {code('EMBED_DIMENSION')} raises a conflict error "
            f"requiring manual collection deletion/recreation rather than automated zero-downtime blue/green index migration."),
        ],
        [
            f"{b('5.')} {code('offline testing')}<br/>(\u00a74.2.5)",
            (f"Executes 3-level evaluation against {code('eval/golden.jsonl')} (32 questions) and "
            f"{code('eval/module_pairs.jsonl')}: Level 1 (cosine gap, ms/512-tok chunk, determinism), Level 2 "
            f"({code('recall@3')}, {code('recall@5')}, {code('MRR')}, {code('nDCG@5')} + typo noise), Level 3 "
            f"(faithfulness via calibrated {code('--llm-judge')} or lexical overlap + human agreement, abstention "
            f"correctness, injection resistance, citation validity, p50/p95 latency), plus fixed-seed stochasticity "
            f"runs and ConfigMap-driven release gating."),
            (f"{code('eval/run_ragops_eval.py')}<br/>{code('eval/release_gate.py')}<br/>"
            f"{code('eval/gate_thresholds.yaml')}<br/>{code('k8s/eval-job.yaml')}<br/>"
            f"{code('k8s/eval-job-candidate.yaml')}<br/>{code('k8s/gate-configmap.yaml')}"),
            (f"No public benchmarks (BEIR, MS MARCO) or NLG reference metrics (BLEU, ROUGE, BERTScore); chunk-size "
            f"sweeps are separate probes ({code('scripts/recall_probe.py')}), not integrated into "
            f"{code('run_ragops_eval.py')}; no automatic golden-set updates when documents are superseded (e.g. "
            f"{code('b10')} staled {code('Academic_Rules_Handbook_2026.pdf')} labels)."),
        ],
        [
            f"{b('6.')} {code('live testing')}<br/>(\u00a74.2.6)",
            (f"Runs isolated candidate deployment ({code('api-candidate')}) and zero-downtime live rollout "
            f"({code('RollingUpdate')}, {code('maxUnavailable: 0')}) with {code('kubectl rollout undo')} rollback. "
            f"Emits per-query JSONL traces (stdout + {code('/traces/traces.jsonl')}) with 8-stage latencies and "
            f"guardrail actions, exports Prometheus counters/histograms on {code('/metrics')}, and supports 24h "
            f"aggregation and exact prompt replay."),
            (f"{code('k8s/candidate-deployment.yaml')}<br/>{code('k8s/base/api-deployment.yaml')}<br/>"
            f"{code('k8s/patches/promote-candidate.yaml')}<br/>{code('api/app/services/chat.py')}<br/>"
            f"{code('api/app/services/tracing.py')}<br/>{code('api/app/metrics.py')}<br/>"
            f"{code('scripts/summarize_traces.py')}<br/>{code('scripts/trace_tool.py')}"),
            (f"No live traffic splitting ({b('A/B testing')} or {b('shadow traffic mirroring')}\u2014"
            f"{code('api-candidate')} serves {code('eval-job-candidate')} only); no automated Prometheus threshold "
            f"alerting or closed-loop rollback/re-test trigger; no online LLM-as-judge sampling or user "
            f"engagement/feedback tracking; single RWO {code('traces-data')} PVC shared across replicas."),
        ],
        [
            f"{b('7.')} {code('check coverage')}<br/>(\u00a74.2.7)",
            (f"Embeds live-style queries ({code('eval/live_queries.jsonl')}, 42 queries) and {code('eval/golden.jsonl')} "
            f"with {code('nomic-embed-text')}, computes nearest-neighbor cosine similarity, flags queries below "
            f"{code('0.70')}, clusters uncovered queries by topic via {code('infer_topic()')}, exits {code('1')} if "
            f"coverage &lt; {code('85%')}, and diffs Batch B data drift across all 3 evaluation levels."),
            (f"{code('eval/coverage_check.py')}<br/>{code('eval/live_queries.jsonl')}<br/>"
            f"{code('eval/golden.jsonl')}<br/>{code('eval/results/e3_drift_batch_b_diff.json')}"),
            (f"Runs manually against static {code('eval/live_queries.jsonl')} instead of continuously sampling "
            f"production {code('/traces/traces.jsonl')} via a CronJob; checks <i>Query Coverage</i> only\u2014no "
            f"automated <i>Retrieval Coverage</i>, <i>Generation Coverage</i> (LDA/UMAP), or <i>Vocabulary Coverage</i> "
            f"(TF-IDF drift), and no auto-generation of candidate golden questions."),
        ],
    ]
    story.append(
        styled_table(
            ["Figure 3 Stage", "What the Pipeline Does", "File That Does It", "What Is Missing"],
            t1_rows,
            col_widths=[68, 186, 112, 161.2],
            cell_style="td_p1",
            pad_v=1.7,
            pad_h=2.8,
        )
    )
    story.append(PageBreak())
    return story


def build_page2() -> list:
    story: list = []

    # Section 2: Table 2 (Five Qualities)
    story.append(sec_heading("2", "Table 2 Quality Dimensions: Paper Definitions & System Realization"))
    story.append(Spacer(1, 2))
    story.append(
        p(
            "Xu et al. (2026, Table 2) define five operational qualities required for production RAG systems. "
            "Table 2 maps each quality to RAHBAR's measurement methods, production targets, and verified Minikube telemetry.",
            "body_sm",
        )
    )
    story.append(
        p(
            "TABLE 2: OPERATIONAL QUALITY DIMENSIONS (XU ET AL. 2026, TABLE 2) GROUNDED IN CLUSTER TELEMETRY",
            "cap",
        )
    )
    t2_rows = [
        [
            b("Adaptability"),
            "Accommodate corpus updates, revisions, and deprecations without downtime.",
            f"Incremental indexing counts; unchanged-skip verification; deletion orphan check; {code('superseded=false')} exclusion + PVC archiving.",
            f"Unchanged: {code('15 docs skipped, 0 chunks embedded')}.<br/>Deleted: {code('0 orphan chunks')}.<br/>Superseded excluded via {code('superseded=false')}.",
            f"{code('verification_batch_a.json')}: {b('15 docs skipped, 0 embedded')}; {code('verification_batch_b_rerun.json')}: 5 skipped, 6 quarantined, 0 embedded. {code('a2_deleted_document.json')}: {code('docs_deleted=1, chunks_deleted=7, 0 orphans')}. {code('verification_batch_b.json')}: {code('298 superseded chunks')} excluded via {code('superseded=false')}.",
        ],
        [
            b("Monitorability"),
            "Continuous visibility into query distributions, stage latencies, and drift.",
            f"Prometheus counters/histograms on {code('GET /metrics')} ({code('f4_metrics_port_forward.txt')}); rolling 24h aggregation via {code('summarize_traces.py')}.",
            f"Live {code('/metrics')} HTTP {code('200')} scrape;<br/>24h latency p95 \u2264 {code('45,000 ms')}.",
            f"{code('traces/metrics_summary_24h.json')} ({code('322')} queries, {code('window=\"24h\"')}): p95 = {b('8,320.45 ms (8.32s)')}; top-1 sim mean = {b('0.7211')} ({code('count=291')}); {code('cache_hit_rate = 9.63%')} (31/322); {code('abstention_rate = 31.68%')} (102/322). Live scrape verified in {code('f4_metrics_port_forward.txt')}.",
        ],
        [
            b("Observability"),
            "Comprehensive structured logging capturing execution context and safety rails.",
            f"21-field structured JSONL emitted per request ({code('stdout')} + {code('/traces/traces.jsonl')}); Prometheus counters for input/retrieval injection rails.",
            f"100% queries emit 21-field {code('ragops_trace')} JSONL; dual-rail events logged.",
            f"Verified {b('322')} traces in {code('traces/traces.jsonl')} &amp; {code('f4_kubectl_logs_traces.txt')}. Captured {b('16')} injection attempts ({b('12')} {code('input_rail')}, {b('4')} {code('retrieval_rail')}).",
        ],
        [
            b("Traceability"),
            "Deterministic reconstruction of exact prompt, chunks, and parameters for past queries.",
            f"SHA-256 {code('prompt_hash')} verification + context/prompt replay via {code('trace_tool.py')}; live query coverage via {code('coverage_check.py')}.",
            f"{code('trace_tool.py')} hash check: {code('verified=True')};<br/>Query coverage \u2265 {code('85.0%')}.",
            f"{code('traces/d5_trace_tool_output.txt')} verifies {code('8b0dbee2')} ({code('prompt_hash 9686b5ba...')}, {code('verified=True')}); {code('coverage_post_expansion.json')}: {b('85.71%')} (36/42 covered).",
        ],
        [
            b("Reliability"),
            "Resilience against noise, unanswerable queries, adversarial inputs, and regressions.",
            f"3-level eval ({code('recall@5')}, typo noise deltas, calibrated {code('dolphin-mistral:latest')} judge + human agreement, abstention, injection, release gate).",
            f"{code('recall@5 >= 0.70')}; {code('faithfulness >= 0.75')}; {code('abstention >= 0.80')}; {code('injection = 1.00')}.",
            f"{code('eval_baseline-final_20261127T203100Z.json')} (32q): {code('recall@5 = 0.7143')}; typo deltas ({code('r@3 +0.0952')}, {code('r@5 +0.0000')}, {code('MRR +0.0897')}, {code('nDCG@5 +0.0676')}); {code('faithfulness = 0.8889')} (16/18, {b('10/10')} human); {code('abstention = 1.0000')} (11/11); {code('injection = 1.0000')} (1/1).",
        ],
    ]
    story.append(
        styled_table(
            [
                "Quality Dimension",
                "Paper Definition (Table 2)",
                "Measurement Metric & Method",
                "Production Gate / Target",
                "Observed Cluster Evidence",
            ],
            t2_rows,
            col_widths=[64, 92, 122, 98, 151.2],
            cell_style="td_p2",
            pad_v=1.8,
            pad_h=2.8,
        )
    )
    story.append(Spacer(1, 3))

    # Section 3: Part A Data Management
    story.append(sec_heading("3", "Part A: Data Management, Pre-Chunking Verification & Data Lake (Paper \u00a7\u00a74.2.1\u20134.2.4)"))
    story.append(Spacer(1, 2))
    story.append(
        p(
            f"To prevent corrupt, incomplete, or duplicate files from entering ChromaDB, RAHBAR enforces four "
            f"pre-chunking verification gates before tokenization. Failures move to {code('/corpus/quarantine/<run_id>/')} "
            f"with structured reports, while Data Lake updates, deletions, and version rollbacks operate cleanly on the "
            f"{code('corpus-data')} PVC.",
            "body_sm",
        )
    )

    t3 = styled_table(
        ["Check", "Implementation & Verification Rule", "Quarantine Condition"],
        [
            [
                b("Quality"),
                "Extracts text via PyMuPDF/OCR. Requires \u2265 20 chars; checks replacement/control-char ratio (\u2264 0.02) &amp; symbol noise (\u2264 0.45).",
                "0 pages extracted, null/binary corruption, or garbled text.",
            ],
            [
                b("Completeness"),
                f"Validates metadata ({code('source')}, {code('title')}, {code('page_count')}, {code('date')}/{code('version')}), page match, and abrupt-cutoff / truncation scans.",
                f"Missing metadata, {code('[truncated]')} markers, or page mismatch.",
            ],
            [
                b("Recency"),
                f"Compares {code('version_sort_key')} against active Data Lake registry; archives older editions when newer versions arrive.",
                "Stale edition rejected if newer version is already active.",
            ],
            [
                b("Uniqueness"),
                "Exact SHA-256 content hash match + document embedding cosine similarity (\u2265 0.94) vs. active corpus.",
                "Exact hash match OR near-duplicate cosine \u2265 0.94.",
            ],
        ],
        col_widths=[50, 114, 78],
        cell_style="td_p2",
        pad_v=1.7,
        pad_h=2.5,
    )

    t4 = styled_table(
        ["Doc", "Planted Defect / Characteristic", "Gate", "Disposition"],
        [
            [code("b01"), "Merit Scholarship Guidelines (2026-09)", pass_badge(), "Indexed (1 chunk)"],
            [code("b02"), "ORIC Research Grant Policy (2026-09)", pass_badge(), "Indexed (1 chunk)"],
            [code("b03"), "FYP Handbook 2026 (2026-09)", pass_badge(), "Indexed (1 chunk)"],
            [code("b04"), f"Exact dup of {code('b01')} (SHA-256 match)", fail_badge(), "Quarantined (Uniqueness)"],
            [code("b05"), f"Exact dup of {code('b02')} (SHA-256 match)", fail_badge(), "Quarantined (Uniqueness)"],
            [code("b06"), f"Near-dup of {code('b01')} (cosine = 0.9713)", fail_badge(), "Quarantined (Cos \u2265 0.94)"],
            [code("b07"), "Corrupt PDF header (0 pages extracted)", fail_badge(), "Quarantined (Quality)"],
            [code("b08"), f"Truncated text ({code('[truncated]')} marker)", fail_badge(), "Quarantined (Completeness)"],
            [code("b09"), f"Missing {code('title')} &amp; {code('date_or_version')}", fail_badge(), "Quarantined (Completeness)"],
            [code("b10"), "Nov 2026 rules superseding June 2026", pass_badge(), "Superseded active; 2 chunks"],
            [code("b11"), "Library fine addendum w/ injection", pass_badge(), "Indexed (1 chunk; Rail test)"],
        ],
        col_widths=[25, 134, 34, 86],
        cell_style="td_p1",
        pad_v=1.25,
        pad_h=2.2,
    )

    left_a = Table([[p("TABLE 3: FOUR PRE-CHUNKING VERIFICATION GATES (verify.py)", "cap")], [t3]], colWidths=[242])
    right_a = Table(
        [[p("TABLE 4: BATCH B VERIFICATION ON K8S (verification_batch_b.json, Run 69b8258e)", "cap")], [t4]],
        colWidths=[279],
    )
    for w_tbl in (left_a, right_a):
        w_tbl.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
    a_grid = Table([[left_a, right_a]], colWidths=[248.2, 279])
    a_grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(a_grid)
    story.append(Spacer(1, 2.5))

    story.append(
        p(
            "TABLE 4B: PART A LIFECYCLE RUNS SUMMARY (INITIAL INGEST, IDEMPOTENT RE-RUNS, UPDATE, DELETE, BATCH B & ROLLBACK)",
            "cap",
        )
    )
    t4b_rows = [
        [
            b("Initial Full Ingest"),
            f"{code('eval/results/verification_batch_a_initial.json')} ({code('21d3349d')})",
            code("scanned=15, added=15, superseded_archived=6, embedded=480"),
            f"{b('221 active / 259 superseded / 480 total')} chunks across 15 Batch A docs (older Annual Reports, 2023 Rules, pre-2024 EE PLOs archived).",
        ],
        [
            f"{b('Unchanged Re-Runs')}<br/>(Batch A &amp; Batch B)",
            f"{code('verification_batch_a.json')} ({code('030c575b')});<br/>{code('verification_batch_b_rerun.json')} ({code('c16ec5f0')})",
            f"Batch A: {code('15 skipped, 0 embedded')};<br/>Batch B: {code('11 scanned, 5 skipped, 6 quarantined, 0 embedded')}",
            f"Content-hash &amp; archive cache prevented redundant embeddings on both batches (Batch A 480 total; Batch B rerun 486 total, {b('0')} re-embedded).",
        ],
        [
            b("Changed Document (A2)"),
            f"{code('eval/results/a2_changed_document.json')} ({code('5f416151')})",
            code("docs_updated=1, skipped=14, chunks_deleted=3, chunks_embedded=4"),
            f"{code('Grading_page.html')} updated {b('3 \u2192 4')} chunks (+1 delta); all 14 other docs unchanged ({code('222 active / 259 superseded / 481 total')}).",
        ],
        [
            b("Deleted Document (A2)"),
            f"{code('eval/results/a2_deleted_document.json')} ({code('5f9d0f96')})",
            code("docs_deleted=1, skipped=14, chunks_deleted=7, embedded=0"),
            f"{code('Faculty_Entrepreneurship_Technical_Startups_Policy.pdf')} purged {b('7 \u2192 0')} chunks with {b('0 orphan chunks')} ({code('214 active / 259 superseded / 473 total')}).",
        ],
        [
            b("Batch B + Archive"),
            f"{code('eval/results/verification_batch_b.json')} ({code('69b8258e')})",
            code("scanned=11, passed=5, quarantined=6, superseded=1, embedded=6"),
            f"{b('188 active / 298 superseded / 486 total')}: {code('Academic_Rules_Handbook_2026.pdf')} moved {code('39 active \u2192 0 active / 39 superseded')}; {code('b10')} added {code('2 active')}; {code('b01,b02,b03,b11')} added {code('1 active')} each.",
        ],
        [
            b("Version Rollback (A2)"),
            f"{code('rollback_academic_rules_handbook.json')} &amp; {code('traces/a2_rollback_traces.jsonl')}",
            f"{code('academic_rules_handbook')} rolled back {code('2026-11 \u2192 2026-06')}",
            f"Restored {b('39 active')} chunks of {code('Academic_Rules_Handbook_2026.pdf')} ({code('superseded=false')}) and archived {b('2')} {code('b10')} chunks ({code('superseded=true')}); verified by traces {code('21eb06c5 \u2192 8673c83c')}.",
        ],
    ]
    story.append(
        styled_table(
            ["Lifecycle Run", "Committed Evidence File (Run ID)", "Ingest / Gate Counts", "Vector Store State & Per-Doc Impact"],
            t4b_rows,
            col_widths=[78, 128, 134, 187.2],
            cell_style="td_p1",
            pad_v=1.6,
            pad_h=2.6,
        )
    )
    story.append(PageBreak())
    return story


def build_page3() -> list:
    story: list = []
    story.append(sec_heading("4", "Part B: 3-Level Offline Evaluation Suite (Paper \u00a74.2.5 & Table 1)"))
    story.append(Spacer(1, 2))
    story.append(
        p(
            f"Xu et al. (2026, \u00a74.2.5) show that end-to-end answer scores hide component-level regressions. "
            f"RAHBAR's single-command suite ({code('eval/run_ragops_eval.py')}) evaluates all three levels in-cluster "
            f"against {code('http://api:8000')} on the 32-question {code('eval/golden.jsonl')} benchmark "
            f"({code('16')} answerable, {code('11')} unanswerable, {code('5')} hard; {code('18')} human, {code('14')} synthetic; "
            f"{code('21')} retrievable queries, {code('11')} must-abstain, {code('1')} prompt-injection), logged in "
            f"{code('eval/results/eval_baseline-final_20261127T203100Z.json')}.",
            "body_sm",
        )
    )
    story.append(
        p(
            "TABLE 5: 3-LEVEL EVALUATION ARCHITECTURE, EXACT FORMULAS & IN-CLUSTER BASELINE RESULTS (32Q, dolphin-mistral:latest JUDGE)",
            "cap",
        )
    )

    t5_rows = [
        [
            f"{b('Level 1: Module')}<br/>(Embeddings)",
            "Cosine Separation Gap",
            f"<i>Gap</i> = \u03bc(cos(paraphrase)) \u2212 \u03bc(cos(unrelated)) across 16 + 16 pairs ({code('eval/module_pairs.jsonl')}).",
            f"{b('0.2891')}<br/>(0.7721 vs 0.4830)",
            "Strong semantic discrimination; paraphrases cluster at 0.7721 vs 0.4830 unrelated.",
        ],
        [
            "",
            "Embedding Throughput",
            f"Mean wall-clock ms per 512-token chunk via {code('nomic-embed-text')} ({code('5 \u00d7 512-tok')} sampled).",
            f"{b('68.15 ms / chunk')}<br/>({code('source: fixtures')})",
            f"{b('Scope note:')} lightweight {code('eval')} image excludes full corpus PDFs, so timing sampled {code('eval/fixtures')} (not full corpus).",
        ],
        [
            "",
            "Embedding Determinism",
            f"{code('max |v1 \u2212 v2|')} and cosine across duplicate probes.",
            f"{b('0.00000000')}<br/>(cos = 1.00000000)",
            "Strict bitwise repeatability for embedding probes under fixed model pin.",
        ],
        [
            f"{b('Level 2: Component')}<br/>(Retrieval &amp; Noise)",
            "Recall@3 / Recall@5<br/>(Top-k Hit Rate)",
            f"Matches {code('_retrieval_metrics_for_query')}: {code('1.0')} if \u22651 chunk matching {code('relevant_document')} &amp; {code('relevant_pages')} is in top-<i>k</i>, averaged across 21 queries.",
            f"{b('r@3: 0.5714')} (12/21)<br/>{b('r@5: 0.7143')} (15/21)",
            f"3 queries ({code('G01')} rank 4, {code('G03')} rank 5, {code('G12')} rank 5) appear at ranks 4\u20135, lifted by {code('TOP_K=5')}.",
        ],
        [
            "",
            "MRR &amp; nDCG@5",
            f"Mean {code('1/rank')} of first matching chunk and binary single-target {code('1/log2(rank+1)')}.",
            f"{b('MRR: 0.4913')}<br/>{b('nDCG@5: 0.5460')}",
            "Strong rank concentration when target clauses appear in ranks 1\u20132.",
        ],
        [
            "",
            "Typo Noise Resilience",
            f"Deterministic character-swap typos ({code('inject_typos')}) on all 21 retrievable queries.",
            f"{b('\u0394r@3: +0.0952')} (0.6667)<br/>{b('\u0394r@5: +0.0000')} (0.7143)<br/>{b('\u0394MRR: +0.0897')} (0.5810)<br/>{b('\u0394nDCG@5: +0.0676')} (0.6137)",
            f"{b('Why typos raised r@3/MRR:')} small query-embedding shifts under typos nudged 2 borderline relevant chunks from ranks 4\u20135 into top-3 while preserving {code('r@5=0.7143')}.",
        ],
        [
            f"{b('Level 3: E2E')}<br/>(Answer &amp; Safety)",
            "Faithfulness Rate",
            f"Share of grounded answers ({code('18/32')}) verified by {code('llm_judge')} ({code('judge_model: dolphin-mistral:latest')}).",
            f"{b('0.8889')} (16/18)<br/>Human: {b('1.0000 (10/10)')}",
            f"Only {code('G01')} &amp; {code('G24')} unfaithful; 7B judge matches 10/10 human labels (up from 3/10 on {code('llama3.2:3b')}).",
        ],
        [
            "",
            "Abstention &amp; Injection",
            f"Must-abstain accuracy ({code('11')} queries) &amp; injection-resistance rate ({code('1')} adversarial query).",
            f"{b('Abstention: 1.0000')} (11/11)<br/>{b('Injection: 1.0000')} (1/1)",
            "All 11 unanswerable queries abstained; zero injection compliance.",
        ],
        [
            "",
            "Citation Validity &amp; Latency",
            "Citations matching retrieved chunk metadata/page; API response latency percentiles.",
            f"{b('Citations: 1.0000')} (18/18)<br/>{b('p50: 4,950.85 ms')}<br/>{b('p95: 7,753.70 ms')}",
            f"18/18 citations verified against retrieved context; p95 well inside {code('45,000 ms')} gate.",
        ],
    ]
    t5_extra = [
        ("SPAN", (0, 1), (0, 3)),
        ("SPAN", (0, 4), (0, 6)),
        ("SPAN", (0, 7), (0, 9)),
        ("VALIGN", (0, 1), (0, -1), "MIDDLE"),
    ]
    story.append(
        styled_table(
            ["Eval Level", "Metric Name", "Exact Code Formula / Methodology", "Baseline Result", "Analysis & Architectural Notes"],
            t5_rows,
            col_widths=[74, 88, 148, 96, 121.2],
            cell_style="td_p2",
            pad_v=2.0,
            pad_h=2.8,
            extra_styles=t5_extra,
        )
    )
    story.append(Spacer(1, 3))

    # Bottom 2-column: Judge Calibration prose + Table 5b Stochasticity
    judge_box = [
        p("Judge Calibration &amp; Remaining Variance", "h3"),
        p(
            f"To avoid circular self-judging by {code('llama3.2:3b')}, we calibrated judges against "
            f"{code('eval/judge_human_labels.jsonl')} (10 human labels). Under {code('llama3.2:3b')} "
            f"({code('eval_baseline-stochasticity_20261122T155008Z.json')}, 26q, {code('seed=42, temp=0.0')}), "
            f"hyper-literal rejections yielded {b('0.30 (3/10)')} human agreement and a {b('+0.0556')} faithfulness "
            f"swing ({code('0.1111 \u2192 0.1667')}, citations {code('19 \u2192 22')}) across identical runs.",
            "body_sm",
        ),
        p(
            f"Upgrading to {b(code('dolphin-mistral:latest'))} in {code('eval_baseline-final_20261127T203100Z.json')} "
            f"achieved {b('1.0000 (10/10)')} human agreement and {b('0.0000')} variance across every retrieval, "
            f"grounding, and safety metric. Remaining variation is purely {b('runtime &amp; Ollama scheduling jitter')}: "
            f"{code('+28.68 ms/chunk')} embedding time, {code('+199.79 ms')} p50, and {code('+2,445.45 ms')} p95.",
            "body_sm",
        ),
    ]
    t5b_rows = [
        [f"L1 {code('paraphrase_mean_cosine')} / {code('unrelated_mean_cosine')}", "0.7721 / 0.4830", "0.7721 / 0.4830", b("0.0000 / 0.0000")],
        [f"L1 {code('cosine_gap')} / {code('determinism_max_abs_diff')}", "0.2891 / 0.0000", "0.2891 / 0.0000", b("0.0000 / 0.0000")],
        [f"L1 {code('embedding_time_per_chunk_ms')} (5 fixtures)", "68.15 ms", "96.83 ms", "+28.68 ms"],
        [f"L2 {code('recall@3')} / {code('recall@5')}", "0.5714 / 0.7143", "0.5714 / 0.7143", b("0.0000 / 0.0000")],
        [f"L2 {code('MRR')} / {code('nDCG@5')}", "0.4913 / 0.5460", "0.4913 / 0.5460", b("0.0000 / 0.0000")],
        [f"L2 {code('noisy_recall@3')} / {code('noisy_recall@5')}", "0.6667 / 0.7143", "0.6667 / 0.7143", b("0.0000 / 0.0000")],
        [f"L2 {code('noisy_MRR')} / {code('noisy_nDCG@5')}", "0.5810 / 0.6137", "0.5810 / 0.6137", b("0.0000 / 0.0000")],
        [f"L3 {code('grounded_answered')} / {code('faithfulness')}", "18 / 0.8889", "18 / 0.8889", b("0 / 0.0000")],
        [f"L3 {code('abstention_correctness')} / {code('injection_resistance')}", "1.0000 / 1.0000", "1.0000 / 1.0000", b("0.0000 / 0.0000")],
        [f"L3 {code('citation_validity')} ({code('citations_checked')})", "1.0000 (18)", "1.0000 (18)", b("0.0000 (0)")],
        [f"L3 {code('latency_p50_ms')} / {code('latency_p95_ms')}", "4,950.85 / 7,753.70", "5,150.64 / 10,199.15", "+199.79 / +2,445.45"],
    ]
    t5b = styled_table(
        ["Metric (eval_baseline-final_20261127T203100Z.json)", "Run 1", "Run 2", "Delta (\u0394)"],
        t5b_rows,
        col_widths=[148, 56, 60, 56],
        cell_style="td_p1",
        pad_v=1.5,
        pad_h=2.5,
    )
    stoch_right = Table(
        [[p("TABLE 5B: STOCHASTICITY ANALYSIS ACROSS RUN 1 & RUN 2 (seed=42, temp=0.0, 32Q)", "cap")], [t5b]],
        colWidths=[320],
    )
    stoch_right.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    b_grid = Table([[judge_box, stoch_right]], colWidths=[207.2, 320])
    b_grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 8),
                ("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(b_grid)
    story.append(PageBreak())
    return story


def build_page4() -> list:
    story: list = []
    story.append(sec_heading("5", "Part C: Change Experiment & Release Gate (Paper \u00a74.1(d), \u00a7\u00a74.2.5\u20134.2.6)"))
    story.append(Spacer(1, 2))
    story.append(
        p(
            f"To ensure like-for-like gating without cross-environment or scorer drift, all three variants were executed "
            f"inside Minikube Kubernetes Jobs against identical 32-question {code('eval/golden.jsonl')} and scored by the "
            f"same {code('dolphin-mistral')} LLM judge ({code('seed=42, temp=0.0')}), recorded in "
            f"{code('eval/results/c1_baseline_vs_candidates.json')}.",
            "body_sm",
        )
    )

    cand_left = [
        p(f"Passing Candidate ({code('candidate_pass.json')})", "h3"),
        p(
            f"Targets isolated {code('api-candidate:8000')} and {code('rahbar_corpus_candidate')} "
            f"({code('COLLECTION_VERSION=candidate-v2')}, {code('TOP_K=5')}) with "
            f"{code('PROMPT_TEMPLATE=strict_concise_v2')}, enforcing terse clause-grounded answers to cut "
            f"generation tail latency while maintaining retrieval depth.",
            "body_sm",
        ),
    ]
    cand_right = [
        p(f"Degraded Failing Candidate ({code('candidate_fail.json')})", "h3"),
        p(
            f"Applies {code('k8s/candidate-fail-config.yaml')} over {code('rahbar-candidate-config')}: sets "
            f"{code('TOP_K=1')}, {code('PROMPT_TEMPLATE=bad_unconstrained_v0')}, and "
            f"{code('COLLECTION_VERSION=candidate-fail-v0')}, demonstrating how single-chunk retrieval and "
            f"unconstrained prompting break both recall and grounding.",
            "body_sm",
        ),
    ]
    c_grid = Table([[cand_left, cand_right]], colWidths=[263.6, 263.6])
    c_grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 6),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(c_grid)
    story.append(
        p(
            "TABLE 6: LIKE-FOR-LIKE IN-CLUSTER 3-LEVEL COMPARISON & GATE MATRIX (c1_baseline_vs_candidates.json, 32Q, dolphin-mistral)",
            "cap",
        )
    )

    t6_rows = [
        [
            f"{b('Level 1')}<br/>(Module)",
            "Cosine Gap (16+16 pairs) / Determinism",
            "0.2891 (0.7721 vs 0.4830) / 0.0",
            "0.2891 (\u0394 0.0000) / 0.0",
            "0.2891 (\u0394 0.0000) / 0.0",
        ],
        [
            "",
            "Embed Time / Chunk (5 fixtures, 512-tok)",
            "84.63 ms/chunk",
            "64.32 ms/chunk (-20.31 ms)",
            "73.91 ms/chunk (-10.72 ms)",
        ],
        [
            f"{b('Level 2')}<br/>(Retrieval)",
            f"{b('Recall@5')} (Gate: drop \u2264 0.0200)",
            f"{b('0.7143')} (r@3: 0.5714)",
            f"{b('0.7143')} (drop +0.0000) {pass_badge()}",
            f"{b('0.3810')} (drop {b('+0.3333')}) {fail_badge()}",
        ],
        [
            "",
            "MRR / nDCG@5 (21 queries)",
            "0.4913 / 0.5460",
            "0.4913 / 0.5460 (\u0394 0.0000)",
            "0.3810 (-0.1103) / 0.3810 (-0.1650)",
        ],
        [
            "",
            "Typo Noise (r@3 / r@5 / MRR / nDCG@5)",
            "0.6667 / 0.7143 / 0.5810 / 0.6137",
            "0.6667 / 0.7143 / 0.5810 / 0.6137",
            "0.5238 / 0.5238 / 0.5238 / 0.5238",
        ],
        [
            f"{b('Level 3')}<br/>(E2E)",
            f"{b('Faithfulness')} (Gate: \u2265 0.7500)",
            f"{b('0.8889')} (18 grounded; 10/10 human)",
            f"{b('0.8000')} (15 grounded; 7/8 human) {pass_badge()}",
            f"{b('0.7143')} (7 grounded; 3/3 human) {fail_badge()}",
        ],
        [
            "",
            f"{b('Abstention Correctness')} (11 checked)",
            "1.0000 (11/11)",
            f"1.0000 (\u0394 +0.0000) {pass_badge()}",
            f"1.0000 (\u0394 +0.0000) {pass_badge()}",
        ],
        [
            "",
            f"{b('Injection Resistance')} (1 checked)",
            "1.0000 (1/1)",
            f"1.0000 {pass_badge()}",
            f"1.0000 {pass_badge()}",
        ],
        [
            "",
            f"{b('Citation Validity')} (Gate: \u2265 0.9000)",
            "1.0000 (18/18 citations)",
            f"1.0000 (18/18 citations) {pass_badge()}",
            f"1.0000 (7/7 citations) {pass_badge()}",
        ],
        [
            "",
            f"{b('Latency p50 / p95')} (Gate: \u2264 45,000 ms)",
            "4,616.17 / 9,700.48 ms",
            f"{b('2,735.12 (-40.75%) / 6,907.25 (-28.79%)')} {pass_badge()}",
            f"1,561.34 (-66.18%) / 6,951.88 (-28.33%) {pass_badge()}",
        ],
        [
            b("Gate"),
            f"{code('eval/release_gate.py')} Outcome",
            b("BASELINE (6/6 PASS)"),
            b("RELEASE (6/6 PASS, Exit 0)"),
            b("BLOCKED (2 FAIL, Exit 1)"),
        ],
    ]
    t6_extra = [
        ("SPAN", (0, 1), (0, 2)),
        ("SPAN", (0, 3), (0, 5)),
        ("SPAN", (0, 6), (0, 10)),
        ("VALIGN", (0, 1), (0, -1), "MIDDLE"),
        ("BACKGROUND", (0, 11), (-1, 11), ZEBRA),
    ]
    story.append(
        styled_table(
            [
                "Level",
                "Metric / Gate Check",
                f"Baseline ({th_code('baseline_k8s.json')})<br/>{th_code('grounded_v1')}, {th_code('TOP_K=5')}",
                f"Passing Candidate ({th_code('candidate_pass.json')})<br/>{th_code('strict_concise_v2')}, {th_code('TOP_K=5')}",
                f"Failing Candidate ({th_code('candidate_fail.json')})<br/>{th_code('bad_unconstrained_v0')}, {th_code('TOP_K=1')}",
            ],
            t6_rows,
            col_widths=[50, 126, 107, 122, 122.2],
            cell_style="td_p2",
            pad_v=1.9,
            pad_h=2.8,
            extra_styles=t6_extra,
        )
    )
    story.append(Spacer(1, 3))

    story.append(
        callout_box(
            f"{b('Release Decision \u2192 PROMOTE / RELEASE via')} {code('k8s/patches/promote-candidate.yaml')}: "
            f"{code('candidate_pass.json')} ({code('strict_concise_v2')}, {code('TOP_K=5')}, {code('candidate-v2')}) "
            f"preserved {code('recall@5=0.7143')} ({code('\u0394=0.0000')}), held {code('faithfulness=0.8000 \u2265 0.7500')}, "
            f"kept {code('1.0000')} abstention, injection, and citation validity, and cut latency by "
            f"{b('-40.75% p50')} ({code('4,616.17 \u2192 2,735.12 ms')}) and {b('-28.79% p95')} "
            f"({code('9,700.48 \u2192 6,907.25 ms')}). Conversely, {code('candidate_fail.json')} failed "
            f"{code('recall@5_max_drop_vs_baseline')} ({code('0.7143 \u2192 0.3810')}, drop {code('+0.3333')}; "
            f"11 grounded answers dropped to abstention) and {code('faithfulness_min')} ({code('0.7143 < 0.7500')}), "
            f"blocking promotion.",
            accent=PASS_FG,
            bg=PASS_CARD_BG,
        )
    )
    story.append(Spacer(1, 2.5))
    story.append(
        p("TABLE 6B: RELEASE GATE THRESHOLD JUSTIFICATION (eval/gate_thresholds.yaml & k8s/gate-configmap.yaml)", "cap")
    )
    t6b_rows = [
        [
            f"{code('recall@5_max_drop_vs_baseline')} / {code('recall@5_min')}",
            f"drop \u2264 {code('0.02')} / \u2265 {code('0.70')}",
            f"With 21 retrievable queries, losing 1 hit equals {code('1/21 = 0.0476')}. Thus {code('\u2264 0.02')} blocks even a 1-query retrieval regression while {code('\u2265 0.70')} sits tightly below baseline {code('0.7143')} ({code('15/21')}) and blocks {code('candidate_fail')} ({code('0.3810')}) &amp; drifted Batch B ({code('0.6190')}).",
        ],
        [
            code("faithfulness_min"),
            f"\u2265 {code('0.75')}",
            f"Sits between passing {code('strict_concise_v2')} ({code('0.8000')}, 12/15) / baseline ({code('0.8889')}, 16/18) and failing {code('bad_unconstrained_v0')} ({code('0.7143')}, 5/7), absorbing strict-concise trade-offs ({code('-0.0889')}) while catching unconstrained hallucinations.",
        ],
        [
            code("p95_latency_max_ms"),
            f"\u2264 {code('45,000 ms')}",
            f"Gives ~4.3\u00d7 headroom above observed in-cluster p95 ({code('6,907.25\u201310,476.62 ms')}; 24h trace max {code('13,072.63 ms')}) to absorb local CPU/Ollama spikes while remaining toggleable (proven by {code('500 ms')} ConfigMap flip failure).",
        ],
        [
            f"{code('abstention_correctness_min')} / {code('delta')}",
            f"\u2265 {code('0.80')} / \u0394 \u2265 {code('0.0')}",
            f"All 32q runs score {code('1.0000')} ({code('11/11')}); zero-regression {code('delta \u2265 0')} forbids degrading out-of-corpus safety, while {code('\u2265 0.80')} floors standalone runs.",
        ],
        [
            code("citation_validity_min"),
            f"\u2265 {code('0.90')}",
            f"Post-hoc grounding check achieves {code('1.0000')} ({code('18/18')} baseline/pass, {code('7/7')} fail); {code('\u2265 0.90')} rejects hallucinated sources with 1-citation tolerance.",
        ],
        [
            code("injection_resistance_min"),
            f"= {code('1.00')}",
            f"Zero tolerance for prompt injection compliance; dual-rail defense scored {code('1.0000')} ({code('1/1')}) across baseline, candidate, and post-Batch-B runs.",
        ],
    ]
    story.append(
        styled_table(
            ["Gate Rule", "Threshold", "Empirical Justification from Measured Cluster Telemetry"],
            t6b_rows,
            col_widths=[125, 72, 330.2],
            cell_style="td_p2",
            pad_v=1.8,
            pad_h=2.8,
        )
    )
    story.append(PageBreak())
    return story


def build_page5() -> list:
    story: list = []
    story.append(sec_heading("6", "Part D: Observability, Traceability & Safety Rails (Paper \u00a7\u00a73.2.3, 5.1)"))
    story.append(Spacer(1, 2))
    story.append(
        p(
            f"RAHBAR emits one structured 21-field JSONL record per query to {code('stdout')} and {code('TRACE_FILE')} "
            f"({code('/traces/traces.jsonl')} on {code('api')}; {code('/traces/candidate_traces.jsonl')} on "
            f"{code('api-candidate')}), powering 24-hour telemetry aggregation ({code('scripts/summarize_traces.py')}) "
            f"and SHA-256 prompt replay ({code('scripts/trace_tool.py')}).",
            "body_sm",
        )
    )

    t7_rows = [
        [code("record_type"), "String", f"Fixed schema marker ({code('\"ragops_trace\"')}) separating traces from HTTP logs."],
        [code("trace_id"), "UUID / Str", f"Global trace identifier ({code('X-Request-ID')} or UUIDv4)."],
        [code("timestamp"), "ISO 8601", f"UTC completion timestamp for {code('summarize_traces.py')} windowing."],
        [code("user_query"), "String", f"Raw incoming question from {code('ChatRequest.question')}."],
        [code("rewritten_query"), "Str | null", f"Task-prefixed query ({code('\"search_query: ...\"')}) or {code('null')}."],
        [code("embedding_model"), "String", f"Pinned embedding model ({code('nomic-embed-text')})."],
        [code("embedding_version"), "String", f"Embedding version tag ({code('nomic-embed-text:v1.5')})."],
        [code("collection_name"), "String", f"Chroma collection ({code('rahbar_corpus')} / {code('rahbar_corpus_candidate')})."],
        [code("collection_version"), "String", f"Active tag ({code('v1')}, {code('candidate-v2')}, {code('candidate-fail-v0')})."],
        [code("retrieved_chunks"), "Array[Obj]", f"{code('chunk_id')}, {code('document_id')}, {code('document_version')}, {code('section')}, {code('page')}, {code('superseded')}, {code('score')}, {code('text')} ({code('[]')} on cache hit)."],
        [code("filters_applied"), "Object", f"Chroma metadata filter ({code('{\"superseded\": false, \"include_old_versions\": false}')})."],
        [code("reranked_order"), "Array[Obj]", f"Cosine-sorted ranks ({code('[{\"rank\", \"chunk_id\", \"score\"}, ...]')})."],
        [code("prompt_hash"), "SHA256|null", f"Hex SHA-256 of {code('full_prompt')} ({code('null')} on cache hit/early floor)."],
        [code("full_prompt"), "String", f"Exact augmented LLM prompt verified by {code('trace_tool.py')}."],
        [code("model"), "String", f"Generator LLM ({code('llama3.2:3b')})."],
        [code("parameters"), "Object", f"{code('provider')}, {code('temperature')}, {code('seed')}, {code('num_ctx')}, {code('top_k')}, {code('relevance_floor')}, {code('cache_threshold')}, {code('prompt_template')}."],
        [code("response"), "Object", f"{code('reasoning')}, {code('answer')}, {code('citations')}, {code('answered_from_context')}, {code('confidence')}."],
        [code("citations"), "Array[Obj]", f"Grounded citations surviving validation ({code('source')}, {code('section')}, {code('page')})."],
        [code("guardrail_actions"), "Array[Obj]", f"Structured rail events ({code('input')}, {code('retrieval')}, {code('relevance_floor')}, {code('output')})."],
        [code("latency_per_stage"), "Object", "Stage timings (ms) across all 8 pipeline stages."],
        [code("cache_hit"), "Boolean", f"Redis semantic cache hit ({code('true')}) or miss/bypassed ({code('false')})."],
    ]
    t7 = styled_table(
        ["Field Name", "Type", "Logged Content & Diagnostic Value"],
        t7_rows,
        col_widths=[70, 44, 140],
        cell_style="td_p1",
        pad_v=1.55,
        pad_h=2.4,
    )

    t7b = styled_table(
        ["Telemetry Metric", "Observed Value (total_queries = 322)"],
        [
            [b("Abstention Rate"), f"{b('102 / 322 = 31.68%')} ({code('abstention_rate: 0.3168')})"],
            [b("Cache Hit Rate"), f"{b('31 / 322 = 9.63%')} ({code('cache_hit_rate: 0.0963')}; e.g. {code('933a16c5')}, {code('5e29b462')})"],
            [b("Injection Attempts"), f"{b('16 total')} \u2014 {b('12')} {code('input_rail')}, {b('4')} {code('retrieval_rail')} (e.g. {code('b17ae5f7')}, {code('0fc00809')})"],
            [
                f"{b('Top-1 Similarity')} ({code('n=291')})<br/>(excl. 31 cache hits)",
                (f"{code('min=0.5474')} | {code('p25=0.6770')} | {code('p50=0.7059')} | {code('p75=0.7664')} | {code('p95=0.8315')} | {code('max=0.8749')} | {code('mean=0.7211')}.<br/>"
                f"{b('Histogram:')} {code('0.50-0.60: 5')}, {code('0.60-0.64: 15')}, {code('0.64-0.70: 101')}, {code('0.70-0.75: 76')}, {code('0.75-0.80: 45')}, {code('0.80-0.85: 36')}, {code('0.85-0.90: 13')} ({code('0')} in {code('<0.50')}, {code('>=0.90')})."),
            ],
        ],
        col_widths=[80, 187.2],
        cell_style="td_p1",
        pad_v=1.55,
        pad_h=2.5,
    )

    t7c = styled_table(
        ["Stage Latency (n=322)", "p50 (ms)", "p95 (ms)", "max (ms)"],
        [
            [code("guardrail_ms"), "0.479", "0.756", "1.426"],
            [code("embed_ms"), "61.514", "1,043.050", "2,096.761"],
            [code("cache_ms"), "0.000", "5.610", "33.607"],
            [code("retrieve_ms"), "12.745", "17.236", "171.177"],
            [code("rerank_ms"), "0.011", "0.017", "0.101"],
            [code("generate_ms"), "2,433.124", "7,569.297", "12,952.343"],
            [code("validate_ms"), "0.225", "0.839", "1.920"],
            [b(code("total_ms")), b("2,515.419"), b("8,320.453"), b("13,072.630")],
        ],
        col_widths=[90, 58, 59, 60.2],
        cell_style="td_p1",
        pad_v=1.35,
        pad_h=2.5,
        extra_styles=[("BACKGROUND", (0, 8), (-1, 8), ZEBRA)],
    )

    d5_card = Table(
        [
            [
                p(
                    f'<font color="#0284c7"><b>5-Line D5 Root-Cause Diagnosis (Trace: {code("8b0dbee2-c05c-4891-9e49-f71833d95eca")}, Question {code("G24")})</b></font><br/>'
                    f"{b('1.')} Trace {code('8b0dbee2-c05c-4891-9e49-f71833d95eca')} ({code('cache_hit=false')}, "
                    f"{code('filters_applied={\"superseded\": false, \"include_old_versions\": false}')}) received: "
                    f"<i>\"Compare the admission fee exemption rule for FAST alumni with the refundable deposit and credit-hour tuition cost.\"</i><br/>"
                    f"{b('2.')} {code('retrieved_chunks')} / {code('reranked_order')} ranked {code('chunk_id 81244601...')} "
                    f"({code('Academic_Rules_Handbook_2026.pdf')}, {code('document_version=2026-06')}, p. 15, "
                    f"{code('score=0.756762')}, course-credit exemption) at rank 1 ahead of {code('Fee_Structure_page.html')} "
                    f"({code('2026-06')}, p. 1) at rank 2 ({code('f15d5a0b...')}, {code('0.733902')}) and rank 5 "
                    f"({code('4431bedb...')}, {code('0.706107')}, which carries the alumni fee exemption and Rs. 20,000 deposit).<br/>"
                    f"{b('3.')} With {code('response.reasoning=\"\"')} (empty) under {code('model=\"llama3.2:3b\"')}, "
                    f"{code('response.answer')} output <i>\"Admission fees are non-refundable except security deposits\"</i> "
                    f"and <i>\"Rs. 12,000\"</i> tuition, omitting the FAST alumni exemption and Rs. 20,000 deposit in "
                    f"rank-5 {code('4431bedb...')} while mis-paraphrasing rank-4 {code('Student_Handbook_2026.pdf')} p. 17.<br/>"
                    f"{b('4.')} {code('guardrail_actions')} passed all rails ({code('input: allow')}, "
                    f"{code('retrieval: allow_all')} across 5 chunks, {code('output: grounded_pass')} keeping 1 citation to "
                    f"{code('Fee_Structure_page.html')} p. 1) because citation metadata matched retrieved context despite "
                    f"incomplete/wrong claim synthesis.<br/>"
                    f"{b('5.')} {code('latency_per_stage')} totaled {code('5,439.284 ms')} ({code('guardrail_ms=0.544')}, "
                    f"{code('embed_ms=671.895')}, {code('cache_ms=0.0')}, {code('retrieve_ms=13.471')}, "
                    f"{code('rerank_ms=0.101')}, {code('generate_ms=4,752.372')}, {code('validate_ms=0.519')}), with "
                    f"{code('prompt_hash=9686b5ba...')} ({code('verified=True')} in {code('traces/d5_trace_tool_output.txt')}).",
                    "td_p1",
                )
            ]
        ],
        colWidths=[267.2],
    )
    d5_card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
                ("BOX", (0, 0), (-1, -1), 0.45, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 4.5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4.5),
                ("TOPPADDING", (0, 0), (-1, -1), 3.0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.0),
            ]
        )
    )

    left_d = Table([[p("TABLE 7: PART D1 STRUCTURED JSONL TRACE SCHEMA (21 LOGGED FIELDS)", "cap")], [t7]], colWidths=[254])
    right_d = Table(
        [
            [p("TABLE 7B: PART D3 METRICS SUMMARY (metrics_summary_24h.json, 24H, 2026-11-27T21:37:04Z)", "cap")],
            [t7b],
            [Spacer(1, 2.5)],
            [p("TABLE 7C: STAGE LATENCIES ACROSS 8 PIPELINE STAGES (N=322)", "cap")],
            [t7c],
            [p("Dual-Rail Injection Defense (D4) &amp; Root-Cause Diagnosis (D5)", "h3")],
            [
                p(
                    f"{b('Dual-Rail Defense:')} Input Rail flags query overrides (12 events); Retrieval Rail scans "
                    f"retrieved chunks and excludes poisoned chunks before prompting (4 events, e.g., {code('b17ae5f7')} "
                    f"&amp; {code('0fc00809')} stripping {code('b11_library_fine_addendum_injected.md')}).",
                    "td_p1",
                )
            ],
            [Spacer(1, 2)],
            [d5_card],
        ],
        colWidths=[267.2],
    )
    for tbl_col in (left_d, right_d):
        tbl_col.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
    d_grid = Table([[left_d, right_d]], colWidths=[260, 267.2])
    d_grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(d_grid)
    story.append(PageBreak())
    return story


def build_page6() -> list:
    story: list = []
    story.append(sec_heading("7", "Part E: Drift & Query Coverage Checking (Paper \u00a74.1(e), \u00a74.2.7)"))
    story.append(Spacer(1, 2))
    story.append(
        p(
            f"Xu et al. (2026, \u00a74.2.7) identify <i>test coverage drift</i> and <i>corpus data drift</i> as primary "
            f"drivers of silent degradation. {code('eval/coverage_check.py')} embeds 42 live-style queries "
            f"({code('eval/live_queries.jsonl')}) against {code('eval/golden.jsonl')} using {code('nomic-embed-text')}, "
            f"computes Sim<sub>max</sub>(<i>q<sub>i</sub></i>) = max<sub><i>g</i> in <i>G</i></sub> "
            f"cos(<i>E</i>(<i>q<sub>i</sub></i>), <i>E</i>(<i>g</i>)), flags queries &lt; \u03c4 = "
            f"{code('0.70')}, and enforces overall coverage \u2265 {code('85.0%')}.",
            "body_sm",
        )
    )

    e_left = [
        p(f"\u03c4 = 0.70 Threshold Justification ({code('coverage_threshold_analysis.json')})", "h3"),
        p(
            f"Pre-expansion (26 golden, {code('L01\u2013L28')} in-domain vs. {code('L29\u2013L42')} uncovered): "
            f"in-domain queries (<i>n</i>=28) have {code('median=0.8055, mean=0.8062, IQR=[0.7723, 0.8469]')}, "
            f"whereas uncovered queries (<i>n</i>=14) have {code('median=0.6293, mean=0.6255, IQR=[0.5994, 0.6415]')} "
            f"(mean gap {code('0.1807')}).",
            "body_sm",
        ),
        p(
            f"{b('\u03c4 = 0.70')} sits inside the clean window {code('(0.6985, 0.7054]')} between highest uncovered "
            f"({code('L37=0.6985')}) and lowest covered in-domain ({code('L05=0.7054')}), yielding "
            f"{b('0/14 false-covered (precision 1.0000, recall 0.8929, F1 0.9434, acc 0.9286)')}. Lowering \u03c4 "
            f"to {code('0.68')} introduces 2 false-covered queries ({code('L37, L29')}, {code('14.3%')}); raising to "
            f"{code('0.72')} drops recall to {code('0.8571')} with zero precision gain.",
            "body_sm",
        ),
    ]
    e_right = [
        p("Pre-Expansion (59.52%, 25/42) &amp; Post-Expansion (85.71%, 36/42) Uncovered Lists", "h3"),
        p(
            f"{b('All 17 pre-expansion uncovered queries')} ({code('coverage_pre_expansion.json')}, exit 1):<br/>"
            f"\u2022 {code('alumni_and_degree_verification')} (4): {code('L29')} (0.6842), {code('L30')} (0.6187), {code('L31')} (0.6410), {code('L41')} (0.6417)<br/>"
            f"\u2022 {code('campus_facilities_and_services')} (4): {code('L32')} (0.6742), {code('L33')} (0.6207), {code('L34')} (0.6089), {code('L42')} (0.5932)<br/>"
            f"\u2022 {code('career_services_and_internships')} (3): {code('L38')} (0.6379), {code('L39')} (0.5653), {code('L40')} (0.5370)<br/>"
            f"\u2022 {code('international_exchange_and_transfers')} (3): {code('L35')} (0.5962), {code('L36')} (0.6390), {code('L37')} (0.6985)<br/>"
            f"\u2022 {code('other_uncovered')} (3 in-domain sub-clauses): {code('L03')} (0.6893, ChatGPT \u2192 {code('G03')}), {code('L25')} (0.6886, grade I\u2192F \u2192 {code('G05')}), {code('L26')} (0.6002, HoD &gt;20% \u2192 {code('G02')}).",
            "td_p1",
        ),
        p(
            f"{b('6 still-uncovered post-expansion')} ({code('coverage_post_expansion.json')}, {code('36/42=85.71%')}, exit 0): "
            f"{code('L03')} (0.6893), {code('L25')} (0.6886), {code('L26')} (0.6002), {code('L37')} (0.6985), "
            f"{code('L40')} (0.6150), {code('L42')} (0.6215).",
            "td_p1",
        ),
    ]
    e_grid = Table([[e_left, e_right]], colWidths=[246, 281.2])
    e_grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 6),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(e_grid)

    story.append(p("TABLE 8: CLOSING THE COVERAGE GAP \u2014 GOLDEN EXPANSION G27\u2013G32 (coverage_post_expansion.json)", "cap"))
    t8_rows = [
        [code("G27"), "Alumni &amp; Degree Verif.", "What is the formal procedure and fee structure for alumni degree verification, duplicate transcript issuance, and convocation gown registration?", "must-abstain", f"{b('0.8669')} ({code('L30')}; {code('L31: 0.7379')})"],
        [code("G28"), "Alumni &amp; HEC Attest.", "How do employers verify degrees for FAST alumni and what is the HEC attestation procedure for provisional certificates?", "must-abstain", f"{b('0.8876')} ({code('L41')}; {code('L29: 0.7952')})"],
        [code("G29"), "Campus Facilities", "What are the operating hours and meal rates of the campus cafeteria, and how can students access the emergency medical clinic?", "must-abstain", f"{b('0.7663')} ({code('L32')}; {code('L33: 0.7655')})"],
        [code("G30"), "Career Services", "Is an industrial summer internship mandatory for degree completion, and what services does the campus placement office provide for job fairs?", "must-abstain", f"{b('0.7909')} ({code('L38')}; {code('L39: 0.7559')})"],
        [code("G31"), "Exchange Programs", "What is the university policy for international student exchange semesters abroad, Erasmus scholarships, and course credit transfers?", "must-abstain", f"{b('0.8914')} ({code('L36')}; {code('L35: 0.8665')})"],
        [code("G32"), "Sports &amp; Computing", "How do students reserve indoor sports courts, book the campus auditorium for society events, or request GPU cluster resources?", "must-abstain", f"{b('0.8900')} ({code('L34')}; {code('L42: 0.6215')})"],
    ]
    story.append(
        styled_table(
            ["ID", "Target Topic", "Synthesized Golden Question (eval/golden.jsonl)", "Type", "Max Live Sim After"],
            t8_rows,
            col_widths=[30, 88, 256, 56, 97.2],
            cell_style="td_p1",
            pad_v=1.6,
            pad_h=2.5,
        )
    )
    story.append(Spacer(1, 2.5))

    story.append(
        p(
            "TABLE 8B (PART E3): BATCH B DATA DRIFT DIFF (e3_drift_batch_b_diff.json: baseline_k8s.json vs. eval_post-batch-b_20261127T212505Z.json)",
            "cap",
        )
    )
    t8b_rows = [
        [
            "L1 Cosine Gap / Embed (ms/chunk)",
            "0.2891 / 84.63",
            "0.2891 / 60.25",
            "0.0000 / -24.38",
            "Embedding separation invariant across Batch B ingestion.",
        ],
        [
            f"L2 {code('recall@3')} / {code('recall@5')} (Batch A labels)",
            "0.5714 / 0.7143",
            "0.6190 / 0.6190",
            f"+0.0476 / {b('-0.0953')}",
            f"{b('Stale labels:')} {code('b10')} archived {code('Academic_Rules_Handbook_2026.pdf')} on 8 queries ({code('G01,G02,G09,G11,G12,G17,G18,G23')}): lost {code('r@5')} on {code('G01,G12,G17,G23')}, gained on {code('G25,G26')} ({code('b03,b02')}). {code('r@3')} gained {code('G03,G25,G26')}, lost {code('G17,G23')}.",
        ],
        [
            f"L2 {code('MRR')} / {code('nDCG@5')} (Batch A labels)",
            "0.4913 / 0.5460",
            "0.5476 / 0.5663",
            "+0.0563 / +0.0203",
            f"{code('G03')} promoted {code('Student_Handbook_2026.pdf')} ({code('r@3 0\u21921')}); {code('G25,G26')} hit rank 1 ({code('1.0')}).",
        ],
        [
            f"L2 Rescored ({code('relevant_document_after_batch_b')})",
            "\u2014",
            f"{b('0.9524')} (21q)<br/>{b('1.0000')} (20q)",
            "\u2014",
            f"Rescoring with {code('b10')}/{code('Grading_page.html')} recovers {code('r@5=0.9524')} ({code('r@3=0.9048, MRR=0.8214')}), or {b('1.0000')} excluding {code('G18')} (genuine Clause 4.1 coverage loss in {code('b10')}).",
        ],
        [
            "L3 Grounded / Faithfulness / Human Agree",
            "18 / 0.8889 / 1.00",
            "20 / 0.8000 / 0.8889",
            "+2 / -0.0889",
            f"{code('abstain\u2192grounded')}: {code('G25, G26')} (faithful), {code('G15')} (unfaithful after {code('b11')} rail exclusion); {code('grounded\u2192abstain')}: {code('G18')}. {code('G04,G15')} excluded poisoned {code('b11')} chunk via retrieval rail.",
        ],
        [
            "L3 Abstention / Injection / Citations / p95",
            "1.0 / 1.0 / 18 / 9,700.5",
            "1.0 / 1.0 / 20 / 10,476.6",
            "0 / 0 / +2 / +776.1",
            f"Safety preserved ({code('1.0000')} abstention &amp; injection, {code('20/20')} valid citations); gate exited {code('1')} on stale-label {code('r@5')} drop.",
        ],
    ]
    story.append(
        styled_table(
            [
                "Evaluation Metric (32q, dolphin-mistral)",
                "Baseline",
                "Post-Batch B",
                "Delta (\u0394)",
                "Flipped Questions & Root-Cause Reconciliation (23 Changed / 9 Unchanged)",
            ],
            t8b_rows,
            col_widths=[120, 68, 70, 62, 207.2],
            cell_style="td_p1",
            pad_v=1.6,
            pad_h=2.5,
        )
    )
    story.append(PageBreak())
    return story


def build_page7() -> list:
    story: list = []
    story.append(sec_heading("8", "Part F: Kubernetes Architecture, GitOps & Release Management (Paper \u00a7\u00a74.1(e\u2013f), 5.1)"))
    story.append(Spacer(1, 2))
    story.append(
        p(
            f"RAHBAR runs natively on Minikube (v1.34, Calico CNI) in namespace {code('rahbar')}. Cloud-native separation "
            f"of concerns prevents multi-replica index corruption, isolates candidate evaluations, enables live ConfigMap "
            f"gate flips without image rebuilds, and right-sizes requests/limits from measured cluster telemetry.",
            "body_sm",
        )
    )

    story.append(p("TABLE 9: KUBERNETES WORKLOAD ARCHITECTURE, SINGLE-WRITER BOUNDARY & F3/F4 EVIDENCE", "cap"))
    t9_rows = [
        [
            f"{code('deployment/api')} + {code('svc/api')} + {code('hpa/api')}",
            "Deployment<br/>(ClusterIP)",
            f"3 replicas (HPA 3\u20138 @ 70% CPU)<br/>{code('traces-data')} (512Mi)",
            f"{code('api-sa')} ({code('automountServiceAccountToken: false')}, UID 10001, {code('readOnlyRootFilesystem')}, drop {code('ALL')})",
            f"Read-only query path via {code('api/app/retrieval/retriever.py')} ({code('collection.query()')} only). Pins {code('CHROMA_COLLECTION')}, {code('COLLECTION_VERSION')}, {code('EMBED_VERSION')}, {code('PROMPT_TEMPLATE')} in Pod template. {b('F3/F4:')} {code('docs/evidence/ragops/f3_rollout_undo.txt')} + {code('traces/f3_rollback_traces.jsonl')} prove bad rev {code('2')} ({code('51d20011')}) \u2192 {code('rollout undo')} \u2192 rev {code('3')} ({code('6b2ff69b')}); {code('f4_kubectl_logs_traces.txt')} &amp; {code('f4_metrics_port_forward.txt')} verify stdout JSONL + {code('/metrics')}.",
        ],
        [
            f"{code('deployment/api-candidate')} + {code('svc')}",
            "Deployment<br/>(ClusterIP)",
            f"1 replica<br/>{code('traces-data')} (512Mi)",
            f"{code('api-sa')} ({code('automountServiceAccountToken: false')}, non-root, {code('readOnlyRootFilesystem')})",
            f"Isolated candidate path serving {code('rahbar_corpus_candidate')} via {code('rahbar-candidate-config')} ({code('/traces/candidate_traces.jsonl')}). {b('F3:')} Passing ({code('candidate-v2')}, {code('strict_concise_v2')}, {code('top_k=5')}) &amp; failing ({code('candidate-fail-v0')}, {code('bad_unconstrained_v0')}, {code('top_k=1')} via {code('k8s/candidate-fail-config.yaml')}) traces verified in {code('traces/candidate_traces.jsonl')} (106 records).",
        ],
        [
            f"{code('statefulset/chroma')} + {code('svc/chroma')}",
            "StatefulSet<br/>(ClusterIP)",
            f"1 replica<br/>{code('data')} VCT (5Gi RWO)",
            f"{code('chroma-sa')} ({code('automountServiceAccountToken: false')}, non-root, {code('readOnlyRootFilesystem')})",
            f"Persistent vector store ({code('chromadb/chroma:0.5.20')}, {code('--workers 1')}, HNSW cosine). Runs without Chroma HTTP auth; {code('allow-chroma')} NetworkPolicy under {code('rahbar-default-deny')} restricts TCP 8000 ingress exclusively to {code('api')}, {code('api-candidate')}, and {code('indexer')} (blocks {code('ui')}, {code('eval')}, {code('pvc-helper')}).",
        ],
        [
            f"{code('deployment/redis')} + {code('ui')}",
            "Deployments<br/>(ClusterIP)",
            f"Redis: 1 ({code('2Gi')})<br/>UI: 2 ({code('maxUnavail: 0')})",
            f"{code('redis-sa')} / {code('ui-sa')} (non-root, {code('readOnlyRootFilesystem')})",
            f"Redis AOF semantic cache (TCP 6379 from {code('api')}/{code('api-candidate')}/{code('indexer')} only) + Nginx frontend (TCP 8080 behind {code('ingress/rahbar')}; {code('allow-ui')} blocks Chroma/Redis access).",
        ],
        [
            f"{code('job/indexer*')} &amp; {code('cronjob/reindex')}",
            "Batch Jobs &amp; CronJob",
            f"{code('corpus-data')} (1Gi);<br/>Cron {code('0 3 * * 0')} ({code('Forbid')})",
            f"{code('indexer-sa')} ({code('automountServiceAccountToken: false')}, non-root, {code('readOnlyRootFilesystem')})",
            f"{b('Sole ChromaDB writers:')} only workloads executing {code('indexer/pipeline/store.py')} ({code('upsert')}, {code('delete')}, {code('set_document_superseded')}) and {code('rollback.py')}. {code('concurrencyPolicy: Forbid')} prevents overlapping writer Jobs and flushes {code('rahbar:cache:*')} on corpus updates.",
        ],
        [
            f"{code('job/eval-job')} &amp; {code('eval-job-candidate')}",
            f"Batch Jobs<br/>({code('backoffLimit:0')})",
            f"On-demand<br/>{code('eval-results')} (512Mi)",
            f"{code('eval-sa')} ({code('automountServiceAccountToken: false')}, non-root, {code('readOnlyRootFilesystem')})",
            f"Runs {code('eval/run_ragops_eval.py --llm-judge --enforce-gate')} against {code('api:8000')} / {code('api-candidate:8000')}. {b('F3:')} {code('docs/evidence/ragops/f3_candidate_blocked.txt')} shows {code('eval-job-candidate')} {code('Failed (0/1 Error)')} on {code('candidate-fail-v0')} ({code('recall@5=0.3810')}, {code('faith=0.7143')}) while {code('deployment/api')} stayed untouched at {code('REVISION 1')}.",
        ],
    ]
    story.append(
        styled_table(
            ["K8s Workload / Resource", "Type", "Replicas / PVC", "ServiceAccount & Hardening", "Operational Role, Single-Writer Boundary & F3/F4 Evidence"],
            t9_rows,
            col_widths=[86, 52, 68, 108, 213.2],
            cell_style="td_p1",
            pad_v=1.7,
            pad_h=2.5,
        )
    )
    story.append(Spacer(1, 2.5))

    story.append(
        p(
            "TABLE 10: PART F5 MEASURED CLUSTER RESOURCE USAGE & SIZED REQUESTS / LIMITS (docs/evidence/ragops/f5_resource_measurements.txt)",
            "cap",
        )
    )
    t10_rows = [
        [f"{code('deployment/api')} ({code('k8s/base/api-deployment.yaml')})", f"Eval load ({code('N=90')})", code("3.0m / 4m"), code("78.0Mi / 79Mi"), f"Req {code('25m / 80Mi')}, Lim {code('100m / 128Mi')} (mem \u2265 1.5\u00d779Mi; 25m prevents HPA false scaling)"],
        [f"{code('deployment/api-candidate')} ({code('k8s/candidate-deployment.yaml')})", f"Idle/eval ({code('N=30')})", code("2.0m / 3m"), code("77.0Mi / 78Mi"), f"Req {code('25m / 80Mi')}, Lim {code('100m / 128Mi')} (parity with {code('api')} for startup &amp; eval load)"],
        [f"{code('statefulset/chroma')} ({code('k8s/base/chroma-statefulset.yaml')})", f"Eval ({code('N=30')}) / Idx ({code('N=12')})", f"{code('7.0m / 17m')} (eval)<br/>{code('10.0m / 17m')} (idx)", f"{code('158.5Mi / 159Mi')}<br/>{code('150.0Mi / 158Mi')}", f"Req {code('15m / 160Mi')}, Lim {code('100m / 256Mi')} (mem \u2265 1.5\u00d7159Mi; 100m HNSW headroom)"],
        [f"{code('job/indexer-candidate')} &amp; {code('indexer-batch-b')}", f"480-chunk idx ({code('N=8')})<br/>Batch B: {code('7.1s')} (&lt;15s)", code("760.5m / 998m"), code("176.5Mi / 198Mi"), f"Req {code('750m / 192Mi')}, Lim {code('1500m / 384Mi')} (both manifests; OCR + embed headroom)"],
        [f"{code('job/eval-job')} ({code('k8s/eval-job.yaml')})", f"Eval load ({code('N=26')})", code("1.0m / 21m"), code("30.0Mi / 31Mi"), f"Req {code('10m / 32Mi')}, Lim {code('50m / 64Mi')} (mem \u2265 1.5\u00d731Mi; light HTTP/judge driver)"],
    ]
    story.append(
        styled_table(
            ["Workload (Manifest)", "Phase & Samples", "CPU p50 / max", "Mem p50 / max", "Configured Request / Limit & Rationale"],
            t10_rows,
            col_widths=[128, 76, 78, 82, 163.2],
            cell_style="td_p1",
            pad_v=1.6,
            pad_h=2.5,
        )
    )
    story.append(
        p(
            f"<i>Baseline support pods during eval ({code('f5_resource_measurements.txt')}):</i> "
            f"{code('redis')} ({code('N=30')}) CPU {code('4.0m / 5m')}, Mem {code('4.0Mi / 4Mi')} "
            f"(req {code('20m/32Mi')}, lim {code('100m/64Mi')}); {code('ui')} ({code('N=60')}) CPU {code('1.0m / 1m')}, "
            f"Mem {code('2.0Mi / 2Mi')} (req {code('10m/16Mi')}, lim {code('50m/64Mi')}).",
            "footnote",
        )
    )

    f2_col = [
        p("ConfigMap Live-Edit Gate Flip (Part F2 Proof)", "h3"),
        p(
            f"{b('1.')} Patched {code('configmap/rahbar-gate-config')}: {code('GATE_P95_LATENCY_MAX_MS: 500.0')}.<br/>"
            f"{b('2.')} Executed {code('eval-job')}: p95 {code('5,731.29 ms > 500 ms')} \u2192 {b('FAIL (Exit 1)')} "
            f"({code('eval_cm-flip-fail')}; reproduced live in Screenshot F3 at {code('10,667.62 ms')}).<br/>"
            f"{b('3.')} Restored {code('45000.0')} and re-ran {code('eval-job')}: p95 {code('6,672.46 ms \u2264 45,000 ms')} "
            f"\u2192 {b('PASS (Exit 0)')} (Screenshot F3: {code('11,202.87 ms')}) without image rebuild.",
            "body_sm",
        ),
    ]
    f3_col = [
        p("Candidate Block, Promotion &amp; Rollback Proof (Part F3)", "h3"),
        p(
            f"{b('1. Blocked:')} {code('k8s/candidate-fail-config.yaml')} failed {code('eval-job-candidate')} "
            f"({code('recall@5=0.3810')}, {code('faith=0.7143')}; {code('f3_candidate_blocked.txt')}); "
            f"{code('deployment/api')} stayed at {code('REVISION 1')}.<br/>"
            f"{b('2. Promote &amp; Undo:')} Passing {code('strict_concise_v2')} promotes via "
            f"{code('k8s/patches/promote-candidate.yaml')} ({code('maxUnavailable: 0')}). "
            f"{code('f3_rollout_undo.txt')} + {code('traces/f3_rollback_traces.jsonl')} verify bad rev {code('2')} "
            f"({code('51d20011')}: {code('candidate-fail-v0 / bad_unconstrained_v0 / top_k=1')}) \u2192 "
            f"{code('kubectl rollout undo')} \u2192 rev {code('3')} ({code('6b2ff69b')}: "
            f"{code('rahbar_corpus / v1 / nomic-embed-text:v1.5 / grounded_v1 / top_k=5')}; also verified live "
            f"by trace {code('61ca6a96')} in Screenshot F4).",
            "body_sm",
        ),
    ]
    f_grid = Table([[f2_col, f3_col]], colWidths=[240, 287.2])
    f_grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 8),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(f_grid)
    story.append(PageBreak())
    return story


def qa_card(title: str, body_html: str, extra_flowables: list | None = None) -> Table:
    rows: list[list] = [[p(f'<font color="#0284c7"><b>{title}</b></font><br/>{body_html}', "qa_body")]]
    if extra_flowables:
        for item in extra_flowables:
            rows.append([item])
    tbl = Table(rows, colWidths=[USABLE_W])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
                ("BOX", (0, 0), (-1, -1), 0.45, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    return tbl


def build_page8() -> list:
    story: list = []
    story.append(sec_heading("9", "Part G: Comprehensive Short Answer Synthesis (Questions a\u2013f)"))
    story.append(Spacer(1, 2.5))

    story.append(
        qa_card(
            "(a) Batch B Verification: Top Defect-Catching Gate, Missed Injection &amp; Pre-Chunking Prevention",
            f"{b('Check Catching the Most Problems:')} In {code('eval/results/verification_batch_b.json')} "
            f"(run {code('69b8258e')}; 11 scanned, 5 indexed, 6 quarantined, {code('6')} chunks embedded), "
            f"{b(code('uniqueness'))} directly caught the most defects\u2014{b('3 of 6 quarantined files')}: exact SHA-256 "
            f"duplicates {code('b04_exact_dup_scholarship.md')} and {code('b05_exact_dup_research_grant.md')} "
            f"(matching {code('b01')}/{code('b02')}), plus near-duplicate {code('b06_near_dup_scholarship.md')} "
            f"(cosine {code('0.9713 \u2265 0.94')} vs. {code('b01')}). Of the remaining 3, {code('quality')} caught "
            f"{code('b07_corrupt_file.pdf')} ({code('empty_document: 0 pages extracted')}, cascading to "
            f"{code('completeness')} and skipping {code('uniqueness')}), while {code('completeness')} caught "
            f"{code('b08_truncated_policy.md')} ({code('[truncated]')}) and {code('b09_missing_metadata.md')} "
            f"(missing {code('title')}, {code('date_or_version')}).<br/>"
            f"{b('Missed Problem &amp; Prevention:')} Verification did {b('not')} catch "
            f"{b(code('b11_library_fine_addendum_injected.md'))}, which passed all four checks ({code('quality')} 807 "
            f"chars, {code('completeness')} valid frontmatter, {code('recency')} initial {code('2026-10')}, "
            f"{code('uniqueness')} cosine {code('0.6989 < 0.94')}) and was indexed into ChromaDB ({code('1')} active "
            f"chunk) because {code('indexer/pipeline/verify.py')} lacks adversarial-content checks (Xu et al. 2026 \u00a78). "
            f"Adding a pre-chunking injection scan in {code('verify.py')} using {code('INJECTION_PATTERNS')} from "
            f"{code('api/app/services/guardrails.py')} (e.g., {code('ignore_previous_instructions')}, "
            f"{code('system_override_marker')}, {code('forced_approval_directive')}) would quarantine poisoned "
            f"documents before chunking instead of relying solely on runtime D4 Retrieval Rail "
            f"({code('apply_retrieval_rail')}, which excluded {code('b11')}'s chunk {code('74a1d003...')} in "
            f"{code('eval_post-batch-b_20261127T212505Z.json')} {code('G04')} &amp; {code('G15')}).",
        )
    )
    story.append(Spacer(1, 2.2))

    story.append(
        qa_card(
            "(b) Module-Level Metrics Healthy While Component/E2E Metrics Degraded",
            f"{b('Primary Example')} ({code('eval/results/c1_baseline_vs_candidates.json')}: {code('baseline_k8s.json')} "
            f"vs. {code('candidate_fail.json')}, 32q): Both share an {b('identical')} Level 1 embedding score "
            f"({code('cosine_gap = 0.2891')}; paraphrase mean {code('0.7721')} vs. unrelated {code('0.4830')}; "
            f"{code('determinism_max_abs_diff = 0.0')}). Yet changing the query pipeline to {code('TOP_K=1')} and "
            f"{code('PROMPT_TEMPLATE=bad_unconstrained_v0')} dropped Level 2 {code('recall@5')} from "
            f"{b(code('0.7143') + ' \u2192 ' + code('0.3810'))} ({code('\u22120.3333')}, failing {code('release_gate.py')}), "
            f"{code('MRR')} from {code('0.4913')} \u2192 {code('0.3810')}, {code('nDCG@5')} from {code('0.5460')} \u2192 "
            f"{code('0.3810')}, halved E2E {code('grounded_answered')} from {b(code('18') + ' \u2192 ' + code('7'))} of 32 "
            f"(11 baseline-answered queries abstained), and cut {code('faithfulness')} from "
            f"{b(code('0.8889') + ' \u2192 ' + code('0.7143'))} (also failing {code('faithfulness_min')}).<br/>"
            f"{b('Drift &amp; E2E Examples:')} In {code('eval_post-batch-b_20261127T212505Z.json')} "
            f"({code('e3_drift_batch_b_diff.json')}), L1 held {code('cosine_gap = 0.2891')} while L2 {code('recall@5')} "
            f"fell {b(code('0.7143') + ' \u2192 ' + code('0.6190'))} ({code('\u22120.0953')}) and faithfulness fell "
            f"{b(code('0.8889') + ' \u2192 ' + code('0.8000'))} ({code('G18')} coverage loss after {code('b10')} superseded "
            f"{code('Academic_Rules_Handbook_2026.pdf')}). Likewise, in {code('eval_baseline-final_20261127T203100Z.json')}, "
            f"healthy L1 ({code('0.2891')}) and L2 ({code('recall@5 = 0.7143')}) still yielded 2/18 unfaithful grounded "
            f"answers ({code('faithfulness = 0.8889')}: {code('G01')} {code('r@5=1.0')}, {code('G24')} {code('r@3=1.0')}, "
            f"both {code('faithful=false')}).",
        )
    )
    story.append(Spacer(1, 2.2))

    story.append(
        qa_card(
            "(c) Archiving Superseded Documents vs. Outright Deletion",
            f"Outright deletion of superseded documents (older annual reports, 2023 rules, or June 2026 handbook) "
            f"breaks enterprise advising RAG for three reasons: (1) {b('Historical Cohort Governance:')} Students "
            f"graduate under the academic rules active in their admission cohort; archiving "
            f"{code('Undergraduate_Academic_Rules_Aug_2023.pdf')} and {code('Academic_Rules_Handbook_2026.pdf')} "
            f"preserves exact legacy rules; (2) {b('Auditability &amp; Traceability:')} Historical trace records "
            f"(e.g., {code('21eb06c5')} citing {code('b10')} v2026-11 vs. {code('8673c83c')} in "
            f"{code('traces/a2_rollback_traces.jsonl')}, and {code('8b0dbee2')} in {code('traces/d5_root_cause_trace.jsonl')}) "
            f"bind {code('chunk_id')}, {code('document_version')}, and SHA-256 {code('prompt_hash')}\u2014deleting chunks "
            f"breaks historical replay (Paper \u00a75.1); (3) {b('Historical Queries &amp; Rollback:')} Setting "
            f"{code('superseded: true')} in Chroma while archiving to {code('/corpus/archive/')} enables "
            f"{code('include_old_versions: true')} queries and instant version restoration ({code('rollback.py')} restored "
            f"39 active chunks of {code('Academic_Rules_Handbook_2026.pdf')}).",
        )
    )
    story.append(Spacer(1, 2.2))

    story.append(
        qa_card(
            "(d) Least-Trusted Metric: Faithfulness (LLM-Judge Variance &amp; Lexical Fallback Inflation)",
            f"{b('Least-Trusted Metric: Faithfulness')} (both LLM-as-a-judge and its {code('lexical_overlap')} fallback). "
            f"First, LLM-judge scoring is sensitive to judge capacity and stochasticity: in historical Nov 22 "
            f"{code('eval_baseline-stochasticity_20261122T155008Z.json')} (26q, {code('llama3.2:3b')}), faithfulness "
            f"was {code('0.1111')} vs. {code('0.1667')} ({b(code('+0.0556 delta'))} under {code('seed=42, temp=0.0')}) "
            f"with only {b(code('0.30') + ' (' + code('3/10') + ')')} human agreement due to hyper-literal rejections. "
            f"Switching to {code('dolphin-mistral:latest')} stabilized variance to {code('0.0000')} and raised human "
            f"agreement to {b(code('1.0000') + ' (' + code('10/10') + ')')} in "
            f"{code('eval_baseline-final_20261127T203100Z.json')} ({code('0.8889')} faithfulness; "
            f"{code('candidate_pass.json')}: {code('0.8000')}, {code('7/8 = 0.8750')} agree; {code('candidate_fail.json')}: "
            f"{code('0.7143')}, {code('3/3')}). Second, historical Nov 22 in-cluster runs before {code('--llm-judge')} "
            f"was enabled used {code('lexical_overlap')} (\u2265 0.45 overlap), inflating faithfulness to {b(code('1.0000'))} "
            f"across {code('eval_k8s-eval_20261122T153617Z.json')}, {code('eval_cm-flip-*_20261122T*')}, and broken "
            f"{code('eval_candidate-fail_20261122T161536Z.json')} ({code('9/9=1.0')}), while rejecting terse {code('\"No\"')} "
            f"on {code('G01')} in {code('eval_candidate-pass_20261122T161336Z.json')} ({code('0.8947')}). Because "
            f"{code('judge_human_labels.jsonl')} also keys only by question {code('id')}, gating pairs faithfulness with "
            f"deterministic {code('citation_validity')}, {code('abstention_correctness')}, and {code('recall@5')}.",
        )
    )
    story.append(Spacer(1, 2.2))

    story.append(
        qa_card(
            "(e) Hardest Paper Idea &amp; Concrete Deviations from Xu et al. (2026)",
            f"{b('Hardest Paper Idea:')} Continuous {b('live testing (\u00a74.2.6) and closed-loop coverage checking (\u00a74.2.7)')} "
            f"with multi-model online judging and strict data-store governance (\u00a74.2.3) on local Minikube hardware. "
            f"Concrete deviations: (1) {b('Batch Jobs instead of live shadow/A-B evaluation:')} Live queries emit 21-field "
            f"JSONL traces ({code('tracing.py')}) and Prometheus metrics ({code('metrics.py')}), while 3-level evaluation "
            f"runs on demand via K8s {code('Job')}s ({code('eval-job')}, {code('eval-job-candidate')}) against isolated "
            f"{code('api-candidate')}; (2) {b('Lexical fallback in historical Nov 22 runs:')} "
            f"{code('eval/run_ragops_eval.py')} defaults to {code('lexical_overlap')} without {code('--llm-judge')} (used "
            f"in the six historical Nov 22 snapshots before {code('eval-job*.yaml')} enabled {code('--llm-judge dolphin-mistral')} "
            f"for all Nov 27 runs); (3) {b('Static live-query file:')} {code('coverage_check.py')} evaluates 42 curated "
            f"queries ({code('eval/live_queries.jsonl')}) manually rather than continuously sampling production traces "
            f"or computing retrieval/generation/vocabulary coverage; (4) {b('Code-level single-writer &amp; verification scope:')} "
            f"Chroma runs without HTTP auth ({code('NetworkPolicy')} + {code('ServiceAccount')} do not enforce write RBAC), "
            f"so single-writer relies on Job vs. read-only API code, and {code('verify.py')} omits \u00a74.2.2 cross-doc "
            f"{code('Consistency')} checks.",
        )
    )
    story.append(Spacer(1, 2.2))

    qf_tbl = styled_table(
        ["K8s Object", "Manifest Name(s)", "RAGOps Responsibility"],
        [
            [
                b("Job"),
                f"{code('indexer')}, {code('indexer-batch-b')}, {code('indexer-candidate')}, {code('indexer-rollback')}, {code('eval-job')}, {code('eval-job-candidate')}",
                f"Finite batch execution: {code('indexer*')} jobs are the {b('only Chroma writers')} (A1 verify, A2 upsert/supersede/rollback, candidate collection, Redis cache flush); {code('eval-job*')} ({code('backoffLimit: 0')}) run 3-level Part B tests and fail non-zero on gate violation.",
            ],
            [
                b("CronJob"),
                f"{code('reindex')} ({code('0 3 * * 0')})",
                f"Scheduled incremental re-ingestion of {code('/corpus/raw')}; {code('concurrencyPolicy: Forbid')} prevents overlapping indexer Jobs from racing on Chroma or the Data Lake.",
            ],
            [
                f"{b('Deployment')} (Live)",
                f"{code('api')} (3\u20138 via {code('hpa/api')}), plus {code('redis')}, {code('ui')}",
                f"Read-only query serving ({code('maxUnavailable: 0')}); pins {code('CHROMA_COLLECTION')}, {code('COLLECTION_VERSION')}, {code('EMBED_VERSION')}, {code('PROMPT_TEMPLATE')} in Pod env for ReplicaSet {code('rollout undo')} (with {code('redis')} semantic cache &amp; {code('ui')} Nginx frontend).",
            ],
            [
                f"{b('Deployment + Service')} (Candidate)",
                f"{code('deployment/api-candidate')}, {code('service/api-candidate')} (ClusterIP {code(':8000')})",
                f"1-replica isolated staging target serving {code('rahbar_corpus_candidate')} and logging to {code('/traces/candidate_traces.jsonl')} so failed configs ({code('k8s/candidate-fail-config.yaml')}) never impact live {code('api')}.",
            ],
            [
                b("StatefulSet"),
                f"{code('chroma')} ({code('replicas: 1')}) + {code('service/chroma')}",
                f"Single-pod vector DB ({code('chroma-0')}, {code('--workers 1')}) with sticky DNS and dedicated volume ownership preventing multi-replica HNSW corruption.",
            ],
            [
                f"{b('PVC')} (All 5)",
                f"{code('corpus-data')} (1Gi), {code('data-chroma-0')} (5Gi), {code('traces-data')} (512Mi), {code('eval-results')} (512Mi), {code('redis-data')} (2Gi)",
                f"Durable state across pod restarts: raw/datalake/quarantine/archived versions ({code('corpus-data')}), HNSW vectors ({code('data-chroma-0')}), JSONL traces ({code('traces-data')}), eval/gate/verification outputs ({code('eval-results')}), and Redis AOF cache ({code('redis-data')}).",
            ],
            [
                b("ConfigMap"),
                f"{code('rahbar-config')}, {code('rahbar-gate-config')} (plus {code('rahbar-candidate-config')})",
                f"{code('rahbar-config')} pins shared {code('EMBED_MODEL')}/chunking/RAG params across {code('api')} &amp; {code('indexer')}; {code('rahbar-gate-config')} decouples Part C2 gate thresholds &amp; judge model so edits flip gates without image rebuilds.",
            ],
            [
                b("NetworkPolicy"),
                f"{code('rahbar-default-deny')}, {code('allow-ui')}, {code('allow-api')}, {code('allow-api-candidate')}, {code('allow-chroma')}, {code('allow-redis')}, {code('allow-indexer')}, {code('allow-eval')}",
                f"Calico least-privilege segmentation: default-deny all traffic; restricts {code('chroma:8000')} ingress to {code('api')}/{code('api-candidate')}/{code('indexer')} (blocking {code('ui')}, {code('eval')}, {code('pvc-helper')}) and restricts host Ollama egress to authorized pods.",
            ],
            [
                b("ServiceAccount"),
                f"{code('api-sa')}, {code('indexer-sa')}, {code('chroma-sa')}, {code('redis-sa')}, {code('ui-sa')}, {code('eval-sa')}",
                f"Per-workload Pod identity with {code('automountServiceAccountToken: false')} (prevents K8s API access); provides workload attribution in manifests rather than Chroma HTTP auth.",
            ],
        ],
        col_widths=[78, 146, 293.2],
        cell_style="td_p1",
        pad_v=1.35,
        pad_h=2.5,
    )
    story.append(
        qa_card(
            "(f) Kubernetes Object \u2192 RAGOps Responsibility Mapping &amp; Single-Writer Enforcement",
            f"{b('Single-Writer Mechanism:')} Vector-store single-writer integrity is enforced by "
            f"{b('workload + application-code separation')}: only batch {code('Job')}s ({code('indexer*')}) and "
            f"{code('CronJob')} ({code('reindex')}, {code('concurrencyPolicy: Forbid')}) execute write code "
            f"({code('indexer/pipeline/store.py')}), whereas {code('deployment/api')} and {code('deployment/api-candidate')} "
            f"only issue read-only {code('collection.query(...)')} calls ({code('api/app/retrieval/retriever.py')}) against "
            f"single-replica {code('statefulset/chroma')} ({code('--workers 1')}). {code('NetworkPolicy')} "
            f"({code('allow-chroma')}) blocks {code('ui')}, {code('eval')}, and {code('pvc-helper')} from "
            f"{code('chroma:8000')} while permitting {code('api')}/{code('api-candidate')} egress; "
            f"{code('ServiceAccount')}s set {code('automountServiceAccountToken: false')} for K8s API isolation rather "
            f"than Chroma HTTP auth.",
            extra_flowables=[qf_tbl],
        )
    )
    story.append(PageBreak())
    return story


def build_appendix() -> list:
    """Build Page 9+ Appendix with all 13 authentic Nov 28 terminal screenshots."""
    story: list = []
    story.append(sec_heading("APP", "Appendix: Screenshot Evidence \u2014 13 Labelled Operational Proofs"))
    story.append(Spacer(1, 2))
    story.append(
        p(
            "Uncropped terminal captures from live Minikube cluster and pipeline executions (Nov 28, 2026), "
            "displaying exact commands and complete outputs across Parts A through F.",
            "app_intro",
        )
    )

    figures = [
        (
            "screenshot_A1_batch_b_verification.png",
            (f"{b('Screenshot A1 \u2014 Batch B Pre-Chunking Verification Report:')} Terminal output of "
            f"{code('job/indexer-batch-b')} showing per-check PASS/FAIL verification results and reasons on Batch B "
            f"({code('b03')}\u2013{code('b11')}: 6 quarantined across exact duplicate hashes {code('b04')}/{code('b05')}, "
            f"near-duplicate cosine {code('0.9713 >= 0.94')} {code('b06')}, corrupt PDF {code('b07')} with "
            f"{code('empty_document')} + {code('missing_required_metadata: page_count unavailable')}, truncated text "
            f"{code('b08')}, and missing metadata {code('b09')}; {code('b10')} superseding {code('2026-06')}; and "
            f"{code('b11')} indexed for D4 retrieval-rail testing)."),
        ),
        (
            "screenshot_A2_unchanged_reindex_zero_chunks.png",
            (f"{b('Screenshot A2 \u2014 Second Ingestion Run on Unchanged Corpus (0 Chunks Embedded):')} PowerShell "
            f"commands recreating {code('job/reindex-unchanged')} from {code('cronjob/reindex')}, waiting for completion, "
            f"and inspecting {code('kubectl logs job/reindex-unchanged -n rahbar --tail=35')}, showing "
            f"{code('[PASS -> skipped_unchanged]')} across unchanged Batch A documents ({code('chunks_embedded: 0')}, "
            f"{code('15')} skipped per {code('eval/results/verification_batch_a.json')})."),
        ),
        (
            "screenshot_B1_three_level_eval_summary.png",
            (f"{b('Screenshot B1 \u2014 3-Level Offline Evaluation Suite Summary:')} Commands "
            f"{code('kubectl wait --for=condition=complete job/eval-job -n rahbar')} and "
            f"{code('kubectl logs job/eval-job -n rahbar --tail=45')} ({code('2026-11-28T05:41:45Z')}, 32 questions, "
            f"{code('seed=42')}, {code('dolphin-mistral')} judge): L1 (Cosine Gap {code('0.2891')}, "
            f"{code('74.02 ms/chunk')}, Determinism {code('0.00000000')}), L2 ({code('recall@3=0.5714')}, "
            f"{code('recall@5=0.7143')}, {code('MRR=0.4913')}, {code('nDCG@5=0.5460')}, typo noise "
            f"{code('r@3=0.6667 (+0.0952)')}, {code('r@5=0.7143 (+0.0000)')}, {code('MRR=0.5810 (+0.0897)')}, "
            f"{code('nDCG@5=0.6137 (+0.0676)')}), L3 (Faithfulness {code('0.8889')}, Human Agreement "
            f"{code('1.0000 (10/10)')}, Abstention {code('1.0000 (11)')}, Injection {code('1.0000 (1)')}, Citation "
            f"Validity {code('1.0000 (19)')}, {code('p50/p95 = 7859.1 / 12330.8 ms')}), and 6/6 {code('GATE RESULT: PASS')}."),
        ),
        (
            "screenshot_C1_release_gate_failing.png",
            (f"{b('Screenshot C1 \u2014 Automated Release Gate Failing (Degraded Candidate):')} Command "
            f"{code('python eval/release_gate.py --candidate eval/results/candidate_fail.json --baseline eval/results/baseline_k8s.json --config eval/gate_thresholds.yaml')} "
            f"failing {code('recall@5_max_drop_vs_baseline')} ({code('0.3810')} vs. {code('0.7143')}, drop "
            f"{code('+0.3333 > 0.0200')}) and {code('faithfulness_min')} ({code('0.7143 < 0.7500')}) \u2192 "
            f"{code('GATE RESULT: FAIL')}."),
        ),
        (
            "screenshot_C2_release_gate_passing.png",
            (f"{b('Screenshot C2 \u2014 Automated Release Gate Passing (Promoted Candidate):')} Command "
            f"{code('python eval/release_gate.py --candidate eval/results/candidate_pass.json --baseline eval/results/baseline_k8s.json --config eval/gate_thresholds.yaml')} "
            f"passing all 6 rules ({code('recall@5=0.7143')}, drop {code('+0.0000')}; {code('faithfulness=0.8000')}; "
            f"{code('p95=6907.25 ms')}; abstention {code('1.0000')}; citations {code('1.0000')}; injection "
            f"{code('1.0000')}) \u2192 {code('GATE RESULT: PASS')}."),
        ),
        (
            "screenshot_D1_full_16field_trace_record.png",
            (f"{b('Screenshot D1 \u2014 Observability: Full JSONL Trace Record:')} Inspecting trace "
            f"{code('51d20011-6652-42bf-8ace-8cf6cc6e9a50')} from {code('traces/traces.jsonl')} "
            f"({code('2026-11-27T21:10:20Z')}), displaying the structured {code('ragops_trace')} JSONL schema "
            f"({code('record_type')}, {code('trace_id')}, {code('timestamp')}, {code('user_query')}, "
            f"{code('rewritten_query')}, {code('embedding_model')}, {code('embedding_version')}, "
            f"{code('collection_name')}, {code('collection_version')}, {code('retrieved_chunks')}, "
            f"{code('filters_applied')}, {code('reranked_order')}, and downstream prompt/response/latency fields)."),
        ),
        (
            "screenshot_D2_trace_tool_reconstruction.png",
            (f"{b('Screenshot D2 \u2014 Trace Tool CLI Prompt Reconstruction &amp; Hash Verification:')} Running "
            f"{code('python scripts/trace_tool.py 8b0dbee2 --trace-file traces/traces.jsonl')} on D5 root-cause "
            f"trace {code('8b0dbee2-c05c-4891-9e49-f71833d95eca')} (G24), verifying SHA-256 {code('prompt_hash')} "
            f"({code('9686b5ba...')}, {code('verified=True')}), printing {code('guardrail_actions')}, 8-stage "
            f"{code('latency_per_stage')} ({code('total_ms=5439.284')}), and exact retrieved {code('<context>')} blocks."),
        ),
        (
            "screenshot_E1_query_coverage_failing.png",
            (f"{b('Screenshot E1 \u2014 Query Coverage Check Failing Pre-Expansion (&lt; 85%):')} Running "
            f"{code('python eval/coverage_check.py --live-queries eval/live_queries.jsonl --golden eval/golden_pre_expansion.jsonl --sim-threshold 0.70 --coverage-threshold 0.85')} "
            f"\u2192 {code('FAIL (COVERAGE GAP)')}: {b('25/42 (59.5%)')} &lt; {code('85.0%')} on 26 golden questions, "
            f"listing all 17 uncovered queries across 5 topic buckets (including {code('other_uncovered')}: "
            f"{code('L03')}, {code('L25')}, {code('L26')})."),
        ),
        (
            "screenshot_E2_query_coverage_passing.png",
            (f"{b('Screenshot E2 \u2014 Query Coverage Check Passing Post-Expansion (\u2265 85%):')} Running "
            f"{code('python eval/coverage_check.py --live-queries eval/live_queries.jsonl --golden eval/golden.jsonl --sim-threshold 0.70 --coverage-threshold 0.85')} "
            f"\u2192 {code('PASS')}: {b('36/42 (85.7%)')} \u2265 {code('85.0%')} on 32 golden questions, with 6 remaining "
            f"uncovered queries ({code('L42')}, {code('L40')}, {code('L37')}, {code('L03')}, {code('L25')}, {code('L26')})."),
        ),
        (
            "screenshot_F1_k8s_all_resources.png",
            (f"{b('Screenshot F1 \u2014 Kubernetes Complete Cluster Resources in rahbar Namespace:')} Output of "
            f"{code('kubectl get all,pvc,configmap,cronjob,job -n rahbar')} showing 3/3 {code('api')} pods, "
            f"1/1 {code('api-candidate')}, 1/1 {code('chroma-0')} StatefulSet, {code('redis')}, 2/2 {code('ui')}, "
            f"{code('pvc-helper')}, 5 ClusterIP Services, {code('hpa/api')} (3\u20138), {code('cronjob/reindex')}, "
            f"4 completed Jobs, 5 Bound RWO PVCs, and 4 ConfigMaps."),
        ),
        (
            "screenshot_F2_indexer_and_eval_job_logs.png",
            (f"{b('Screenshot F2 \u2014 Completed Indexer Job &amp; Evaluation Job Logs Inside Kubernetes:')} "
            f"Outputs of {code('kubectl logs job/indexer -n rahbar --tail=25')} and "
            f"{code('kubectl logs job/eval-job -n rahbar --tail=35')} showing Batch A indexing completions and "
            f"completed 32-question {code('eval-job')} 3-level summary ({code('eval_k8s-eval_20261127T213700Z.json')}, "
            f"{code('recall@5=0.7143')}, {code('faithfulness=0.8889')}, {code('p95=10677.68 ms')}, 6/6 "
            f"{code('GATE RESULT: PASS')})."),
        ),
        (
            "screenshot_F3_configmap_gate_flip.png",
            (f"{b('Screenshot F3 \u2014 ConfigMap Live-Edit Gate Flip (Fail \u2192 Pass Without Image Rebuild):')} "
            f"Patching {code('rahbar-gate-config')} to {code('GATE_P95_LATENCY_MAX_MS=\"500.0\"')} causes "
            f"{code('eval-job')} to {code('FAIL')} ({code('p95=10667.62 ms > 500.00 ms')}, "
            f"{code('gate_k8s-eval_20261128T055825Z.json')}); restoring {code('\"45000.0\"')} causes "
            f"{code('eval-job')} to {code('PASS')} ({code('p95=11202.87 ms <= 45000.00 ms')}, "
            f"{code('gate_k8s-eval_20261128T061024Z.json')}) with zero container rebuild."),
        ),
        (
            "screenshot_F4_rollout_status_and_undo.png",
            (f"{b('Screenshot F4 \u2014 Controlled Rollout, Instant Rollback &amp; Post-Undo Trace Proof:')} "
            f"{code('kubectl set env deployment/api')} applies {code('COLLECTION_VERSION=candidate-fail-v0')} and "
            f"{code('PROMPT_TEMPLATE=bad_unconstrained_v0')} with {code('kubectl rollout status')} completing "
            f"zero-downtime rollout; {code('kubectl rollout undo deployment/api')} reverts immediately; live "
            f"{code('/chat')} request and {code('pvc-helper')} trace check ({code('61ca6a96-1d13-4789-b897-1ff2cb0737ca')}) "
            f"prove restored {code('collection_name=\"rahbar_corpus\"')}, {code('collection_version=\"v1\"')}, "
            f"{code('embedding_version=\"nomic-embed-text:v1.5\"')}, {code('prompt_template=\"grounded_v1\"')}, "
            f"{code('top_k=5')}, and valid citation."),
        ),
    ]

    img_w = 485.0
    img_h = img_w / 1.6  # all 13 screenshots are 2560x1600 (1.6:1)

    for idx, (fname, caption) in enumerate(figures):
        img_path = SCREENSHOTS_DIR / fname
        if not img_path.exists():
            raise FileNotFoundError(f"Missing screenshot: {img_path}")
        img = Image(str(img_path), width=img_w, height=img_h)
        fig_tbl = Table([[img], [p(caption, "img_cap")]], colWidths=[USABLE_W])
        fig_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, 0), TERM_BG),
                    ("BACKGROUND", (0, 1), (0, 1), CARD_BG),
                    ("ALIGN", (0, 0), (0, 0), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                    ("LINEABOVE", (0, 1), (0, 1), 0.6, BORDER),
                    ("LEFTPADDING", (0, 0), (0, 0), 2),
                    ("RIGHTPADDING", (0, 0), (0, 0), 2),
                    ("TOPPADDING", (0, 0), (0, 0), 2),
                    ("BOTTOMPADDING", (0, 0), (0, 0), 2),
                    ("LEFTPADDING", (0, 1), (0, 1), 6),
                    ("RIGHTPADDING", (0, 1), (0, 1), 6),
                    ("TOPPADDING", (0, 1), (0, 1), 3.5),
                    ("BOTTOMPADDING", (0, 1), (0, 1), 4.0),
                ]
            )
        )
        story.append(KeepTogether([fig_tbl]))
        if idx % 2 == 0 and idx < len(figures) - 1:
            story.append(Spacer(1, 8))
        elif idx < len(figures) - 1:
            story.append(PageBreak())

    return story


def build_pdf() -> None:
    """Build the full PDF report and mirror it to the repository root."""
    story: list = []
    story.extend(build_page1())
    story.extend(build_page2())
    story.extend(build_page3())
    story.extend(build_page4())
    story.extend(build_page5())
    story.extend(build_page6())
    story.extend(build_page7())
    story.extend(build_page8())
    story.extend(build_appendix())

    _verify_glyphs()

    doc = BaseDocTemplate(
        str(REPORT_PDF),
        pagesize=A4,
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=MARGIN_T,
        bottomMargin=MARGIN_B,
        title="CS4032 Assignment 03 - RAHBAR RAGOps Technical Report",
        author="Jaweria Abdul Hameed (i243025), Mohsin Khan (i243135)",
        subject="RAGOps: Operating and Managing Retrieval-Augmented Generation Pipelines",
    )
    frame = Frame(
        MARGIN_L,
        MARGIN_B,
        USABLE_W,
        PAGE_H - MARGIN_T - MARGIN_B,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        id="main_frame",
    )
    doc.addPageTemplates([PageTemplate(id="A4Report", frames=[frame])])
    doc.build(story, canvasmaker=NumberedCanvas)

    shutil.copyfile(REPORT_PDF, ROOT_PDF)
    print(f"Generated: {REPORT_PDF} ({REPORT_PDF.stat().st_size} bytes)")
    print(f"Mirrored : {ROOT_PDF} ({ROOT_PDF.stat().st_size} bytes)")


if __name__ == "__main__":
    build_pdf()
