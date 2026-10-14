#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка итоговых документов монографии (редакция после аудита 2026-10).

Выход (в корне репозитория):

* ``Гипертермический_синдром_итоговый_текст_2026-10.md`` — полный текст
  (титул, оглавление, главы 1–15, приложения: отчёт аудита и источники) со
  встроенными схемами аудита ``assets/audit/*.png`` и Mermaid-блоками глав;
* ``Гипертермический_синдром_Монография_2026-10.pdf`` — тот же текст в PDF
  со **всеми** схемами: 16 визуальных сводок глав (Mermaid → SVG → PNG
  средствами ``mermaid_render.py``) и 8 схем аудита;
* ``Гипертермический_синдром_Схемы_2026-10.pdf`` — только PNG-схемы аудита
  (альбомная ориентация, по одной схеме на страницу).

Зависимости: python3, reportlab, Pillow, markdown-it-py; node ≥ 18 с пакетом
``@resvg/resvg-js`` (переменная ``NODE_PATH`` или ``~/svgtools/node_modules``)
для растеризации Mermaid-схем; шрифты DejaVu (система или пакет npm
``dejavu-fonts-ttf`` — для курсивных начертаний).

    python3 scripts/pdf/build_final_docs.py            # всё
    python3 scripts/pdf/build_final_docs.py --md       # только итоговый MD
    python3 scripts/pdf/build_final_docs.py --pdf      # только PDF монографии
    python3 scripts/pdf/build_final_docs.py --schemes  # только PDF со схемами
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import os
import re
import sys
import tempfile
from pathlib import Path

from markdown_it import MarkdownIt
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping
from reportlab.platypus.doctemplate import ActionFlowable
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame,
                                HRFlowable, Image, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle, XPreformatted)
from reportlab.platypus.tableofcontents import TableOfContents

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CHAPTERS_DIR = ROOT / "главы"
ASSETS_AUDIT = ROOT / "assets" / "audit"
sys.path.insert(0, str(HERE))
import mermaid_render  # noqa: E402

OUT_MD = ROOT / "Гипертермический_синдром_итоговый_текст_2026-10.md"
OUT_PDF = ROOT / "Гипертермический_синдром_Монография_2026-10.pdf"
OUT_SCHEMES_PDF = ROOT / "Гипертермический_синдром_Схемы_2026-10.pdf"
WORK = Path(os.environ.get("PDF_WORKDIR", Path(tempfile.gettempdir()) / "pdfbuild" / "mermaid"))
EDITION = "Итоговая редакция после содержательного аудита, октябрь 2026"
PAGE_MARGINS = dict(left=20 * mm, right=18 * mm, top=18 * mm, bottom=17 * mm)
LAND_W = landscape(A4)[0] - PAGE_MARGINS["left"] - PAGE_MARGINS["right"]
LAND_H = landscape(A4)[1] - PAGE_MARGINS["top"] - PAGE_MARGINS["bottom"]
TODAY = dt.date(2026, 10, 14)

NAV_RE = re.compile(r"\n?<!-- chapter-nav:start -->.*?<!-- chapter-nav:end -->\n?", re.S)
AUDIT_PNG_RE = re.compile(r"\[([^\]]+)\]\(\.\./assets/audit/([^)]+\.png)\)")

# подписи к схемам аудита (в порядке файлов assets/audit)
AUDIT_SCHEMES = [
    ("01-tireotoksicheskiy-kriz-4v1", "Тиреотоксический криз: «блокада 4 в 1» — порядок и дозы", "§ 9.6.5"),
    ("02-kriterii-nzs", "Критерии нейролептического злокачественного синдрома: три системы", "§ 7.8.1"),
    ("03-zlokachestvennaya-gipertermiya-priznaki", "Злокачественная гипертермия: ранние, развёрнутые и поздние признаки", "§ 5.4.2, § 4.2.1, § 7.8.3"),
    ("04-likhoradka-mladenec-do-3-mes", "Лихорадка у младенца до 3 месяцев: два устоявшихся подхода", "§ 7.4.1, § 12.1"),
    ("05-sudorogi-lestnica-terapii", "Судороги на фоне гипертермии: лестница терапии и дозы", "§ 9.5.4, § 12.1.5, § 14.5"),
    ("06-dve-modeli-termoregulyacii", "Две модели терморегуляции: «установочная точка» и «точка равновесия»", "§ 2.1.1"),
    ("07-spektr-teplovyh-porazheniy", "Спектр тепловых поражений: от тепловых судорог до теплового удара", "§ 4.3"),
    ("08-karta-audita", "Карта аудита 2026-10: исправления, разные мнения, современные положения", "АУДИТ-2026-10.md"),
]
ALERTS = {
    "NOTE": ("Примечание", "#1d4ed8", "#eff6ff"),
    "TIP": ("Совет", "#15803d", "#ecfdf5"),
    "IMPORTANT": ("Важно", "#6d28d9", "#f5f3ff"),
    "WARNING": ("Предупреждение", "#b45309", "#fffbeb"),
    "CAUTION": ("Осторожно", "#b91c1c", "#fef2f2"),
}


# ------------------------------------------------------------------ шрифты ---
def register_fonts() -> dict:
    cands = [
        os.environ.get("DEJAVU_DIR"),
        str(Path.home() / "svgtools" / "node_modules" / "dejavu-fonts-ttf" / "ttf"),
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/dejavu",
        "/usr/share/fonts/TTF",
    ]
    dirs = [Path(c) for c in cands if c and Path(c).is_dir()]

    def find(name):
        for d in dirs:
            p = d / f"{name}.ttf"
            if p.exists():
                return str(p)
        return None

    def reg(alias, name, fallback):
        path = find(name) or find(fallback)
        if not path:
            raise SystemExit(f"Не найден шрифт {name}.ttf — установите пакет DejaVu")
        pdfmetrics.registerFont(TTFont(alias, path))

    reg("Serif", "DejaVuSerif", "DejaVuSerif")
    reg("Serif-B", "DejaVuSerif-Bold", "DejaVuSerif")
    reg("Serif-I", "DejaVuSerif-Italic", "DejaVuSerif")
    reg("Serif-BI", "DejaVuSerif-BoldItalic", "DejaVuSerif-Bold")
    reg("Sans", "DejaVuSans", "DejaVuSans")
    reg("Sans-B", "DejaVuSans-Bold", "DejaVuSans")
    reg("Sans-I", "DejaVuSans-Oblique", "DejaVuSans")
    reg("Sans-BI", "DejaVuSans-BoldOblique", "DejaVuSans-Bold")
    reg("Mono", "DejaVuSansMono", "DejaVuSansMono")
    reg("Mono-B", "DejaVuSansMono-Bold", "DejaVuSansMono")
    for fam, (n, b, i, bi) in {
        "Serif": ("Serif", "Serif-B", "Serif-I", "Serif-BI"),
        "Sans": ("Sans", "Sans-B", "Sans-I", "Sans-BI"),
        "Mono": ("Mono", "Mono-B", "Mono", "Mono-B"),
    }.items():
        addMapping(fam, 0, 0, n)
        addMapping(fam, 1, 0, b)
        addMapping(fam, 0, 1, i)
        addMapping(fam, 1, 1, bi)
    return {"serif": "Serif", "sans": "Sans", "mono": "Mono"}


def make_styles():
    S = {}
    S["body"] = ParagraphStyle("body", fontName="Serif", fontSize=10.3, leading=14.2,
                               spaceAfter=5, alignment=TA_JUSTIFY, splitLongWords=1)
    S["body_tight"] = ParagraphStyle("body_tight", parent=S["body"], spaceAfter=1.5)
    S["title"] = ParagraphStyle("title", fontName="Sans-B", fontSize=21, leading=26,
                                alignment=TA_CENTER, spaceAfter=10, textColor=colors.HexColor("#1e3a8a"))
    S["subtitle"] = ParagraphStyle("subtitle", fontName="Sans", fontSize=12.5, leading=17,
                                   alignment=TA_CENTER, spaceAfter=8, textColor=colors.HexColor("#374151"))
    S["h1"] = ParagraphStyle("h1", fontName="Sans-B", fontSize=18, leading=23, spaceBefore=0,
                             spaceAfter=14, textColor=colors.HexColor("#1e3a8a"))
    S["h2"] = ParagraphStyle("h2", fontName="Sans-B", fontSize=13.5, leading=17, spaceBefore=14,
                             spaceAfter=6, keepWithNext=1, textColor=colors.HexColor("#1e3a8a"))
    S["h3"] = ParagraphStyle("h3", fontName="Sans-B", fontSize=11.3, leading=14.5, spaceBefore=11,
                             spaceAfter=4, keepWithNext=1, textColor=colors.HexColor("#111827"))
    S["h4"] = ParagraphStyle("h4", fontName="Serif-B", fontSize=10.5, leading=14, spaceBefore=8,
                             spaceAfter=3, keepWithNext=1)
    S["quote"] = ParagraphStyle("quote", parent=S["body"], fontSize=9.8, leading=13.4, leftIndent=8,
                                backColor=colors.HexColor("#f3f4f6"), borderPadding=(3, 5, 3, 5),
                                spaceBefore=3, spaceAfter=4)
    S["cell"] = ParagraphStyle("cell", fontName="Sans", fontSize=8.3, leading=10.4, alignment=TA_LEFT,
                               splitLongWords=1)
    S["cell_head"] = ParagraphStyle("cell_head", parent=S["cell"], fontName="Sans-B")
    S["caption"] = ParagraphStyle("caption", fontName="Sans-I", fontSize=8.6, leading=11,
                                  alignment=TA_CENTER, textColor=colors.HexColor("#4b5563"),
                                  spaceBefore=3, spaceAfter=10)
    S["code"] = ParagraphStyle("code", fontName="Mono", fontSize=7.8, leading=9.8, leftIndent=6,
                               backColor=colors.HexColor("#f3f4f6"), borderPadding=(3, 4, 3, 4),
                               spaceBefore=4, spaceAfter=8)
    S["small"] = ParagraphStyle("small", fontName="Sans", fontSize=8.5, leading=11,
                                textColor=colors.HexColor("#4b5563"))
    S["toc0"] = ParagraphStyle("toc0", fontName="Sans-B", fontSize=10.5, leading=15, spaceBefore=5)
    S["toc1"] = ParagraphStyle("toc1", fontName="Sans", fontSize=9.2, leading=12.5, leftIndent=14)
    S["answer"] = ParagraphStyle("answer", parent=S["body"], fontName="Sans-B", fontSize=9,
                                 textColor=colors.HexColor("#15803d"), spaceAfter=2, spaceBefore=2)
    return S


# ------------------------------------------------------------ вспомогательное ---
def esc(t: str) -> str:
    return html.escape(t, quote=False)


def slug(text: str) -> str:
    """Якорь заголовка в стиле GitHub (кириллица сохраняется)."""
    t = text.strip().lower()
    t = re.sub(r"[^\w\s\-]", "", t)
    t = re.sub(r"\s+", "-", t)
    return t


def md_parser() -> MarkdownIt:
    return MarkdownIt("commonmark").enable(["table", "strikethrough"])


def strip_nav(text: str) -> str:
    return NAV_RE.sub("\n", text)


def chapter_files():
    return sorted(CHAPTERS_DIR.glob("[0-9][0-9]-*.md"))


def chapter_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def tidy_scheme_links(text: str) -> str:
    """Убирает служебные хвосты « — PNG» и «([SVG](...))» у ссылок на схемы аудита."""
    text = re.sub(r"\s*\(\[SVG\]\(\.\./assets/audit/[^)]*\.svg\)\)\.?", ".", text)
    text = re.sub(r"\s*(?:>\s*)?\(исходник: \[SVG\]\(\.\./assets/audit/[^)]*\.svg\)\)\.?", ".", text)
    text = text.replace(" — PNG](../assets/audit/", "](../assets/audit/")
    text = text.replace("..\n", ".\n")
    return text


# ---------------------------------------------------------- итоговый Markdown ---
def build_final_md() -> Path:
    files = chapter_files()
    titul = [p for p in files if p.name.startswith("00-")]
    chapters = [p for p in files if not p.name.startswith("00-")]
    parts = []
    parts.append(
        "<!-- АВТОМАТИЧЕСКИ СОБРАНО scripts/pdf/build_final_docs.py из главы/*.md, "
        "АУДИТ-2026-10.md и ИСТОЧНИКИ.md. НЕ РЕДАКТИРОВАТЬ ВРУЧНУЮ: правки вносятся в главы. -->\n"
    )
    if titul:
        t = strip_nav(titul[0].read_text(encoding="utf-8")).strip().replace("../assets/", "assets/")
        parts.append(re.sub(r"\n-{3,}\s*$", "", t).strip())
    parts.append(
        f"**{EDITION}.** Текст полностью соответствует файлам `главы/01…15` по состоянию на "
        f"{TODAY:%d.%m.%Y}; изменения, внесённые при аудите, перечислены в Приложении А. "
        "Схемы аудита (SVG → PNG) встроены в текст в местах, к которым они относятся; визуальные "
        "сводки глав оставлены в виде блоков Mermaid. Печатные версии: "
        f"`{OUT_PDF.name}` (все схемы) и `{OUT_SCHEMES_PDF.name}` (только PNG-схемы)."
    )
    # оглавление
    toc = ["## Оглавление", ""]
    for p in chapters:
        t = chapter_title(p)
        toc.append(f"- [{t}](#{slug(t)})")
    toc.append("- [Приложение А. Содержательный аудит монографии — октябрь 2026](#приложение-а-содержательный-аудит-монографии--октябрь-2026)")
    toc.append("- [Приложение Б. Источники и границы доказательности](#приложение-б-источники-и-границы-доказательности)")
    parts.append("\n".join(toc))

    for p in chapters:
        text = strip_nav(p.read_text(encoding="utf-8"))
        text = tidy_scheme_links(text)
        # после абзаца со ссылкой на схему аудита — встраиваем саму схему
        out_lines = []
        pending = []
        for line in text.split("\n"):
            out_lines.append(line)
            for m in AUDIT_PNG_RE.finditer(line):
                pending.append((m.group(1), m.group(2)))
            if pending and line.strip() == "":
                for cap, fn in pending:
                    out_lines.append(f"![{cap}](../assets/audit/{fn})")
                    out_lines.append("")
                    out_lines.append(f"*Схема аудита 2026-10: {cap}.*")
                    out_lines.append("")
                pending = []
        if pending:
            out_lines.append("")
            for cap, fn in pending:
                out_lines.append(f"![{cap}](../assets/audit/{fn})")
                out_lines.append("")
                out_lines.append(f"*Схема аудита 2026-10: {cap}.*")
        text = "\n".join(out_lines)
        text = text.replace("../assets/", "assets/").replace("../ИСТОЧНИКИ.md", "ИСТОЧНИКИ.md").replace("../README.md", "README.md")
        parts.append(text.strip())

    audit = (ROOT / "АУДИТ-2026-10.md").read_text(encoding="utf-8").strip()
    audit = audit.replace("# Содержательный аудит монографии — октябрь 2026",
                          "# Приложение А. Содержательный аудит монографии — октябрь 2026", 1)
    parts.append(audit)
    src = (ROOT / "ИСТОЧНИКИ.md").read_text(encoding="utf-8").strip()
    src = src.replace("# Источники и границы доказательности",
                      "# Приложение Б. Источники и границы доказательности", 1)
    parts.append(src)
    OUT_MD.write_text("\n\n---\n\n".join(parts) + "\n", encoding="utf-8")
    return OUT_MD


# ------------------------------------------------------------- PDF: флоуэблы ---
class FloatFigure(Flowable):
    """Альбомная страница со схемой, «плавающая» до ближайшей границы страницы.

    Сам флоуэбл нулевого размера; MonographDoc.handle_flowable откладывает его,
    пока текущая книжная страница не заполнится текстом, и лишь затем вставляет
    альбомную страницу — без пустых хвостов на предыдущей странице."""

    _ZEROSIZE = True
    locChanger = 1

    def __init__(self, content):
        super().__init__()
        self.content = list(content)

    def wrap(self, aw, ah):
        return 0, 0

    def draw(self):
        pass


class Heading(Paragraph):
    """Абзац-заголовок с данными для оглавления и закладок."""

    def __init__(self, text, style, level, plain, key):
        super().__init__(text, style)
        self._toc = (level, plain, key)


class MdRenderer:
    """Поток токенов markdown-it → список флоуэблов reportlab."""

    def __init__(self, styles, frame_w, frame_h, base_dir: Path, toc_levels=2, chapter_tag=""):
        self.S = styles
        self.fw, self.fh = frame_w, frame_h
        self.base_dir = base_dir
        self.toc_levels = toc_levels
        self.chapter_tag = chapter_tag
        self.story = []
        self.list_stack = []      # [(kind, counter, start)]
        self.quote_depth = 0
        self.alert = None
        self.alert_first = False
        self.table = None
        self.row = None
        self.in_head = False
        self.key_counter = 0
        self.mermaid_counter = 0
        self.pending_images = []
        self.title_mode = False   # титульный лист: H1/H2 без оглавления
        self.start_landscape = False   # первая страница главы — альбомная (широкая схема сразу после заголовков)
        self._pending_portrait = False  # после альбомной страницы вернуться к книжной перед следующим элементом
        self.appendix_mode = False      # приложение: схемы аудита уменьшенно, без альбомных страниц

    def emit(self, fl):
        if self._pending_portrait:
            self._pending_portrait = False
            self.story.append(NextPageTemplate("body"))
            self.story.append(PageBreak())
        self.story.append(fl)

    # ------------------------------------------------------------- inline ---
    def inline(self, children) -> tuple[str, list]:
        out = []
        images = []
        audit_links = []
        link_stack = []
        for t in children or []:
            ty = t.type
            if ty == "text" or ty == "text_special":
                out.append(esc(t.content))
            elif ty == "softbreak":
                out.append(" ")
            elif ty == "hardbreak":
                out.append("<br/>")
            elif ty == "strong_open":
                out.append("<b>")
            elif ty == "strong_close":
                out.append("</b>")
            elif ty == "em_open":
                out.append("<i>")
            elif ty == "em_close":
                out.append("</i>")
            elif ty == "s_open":
                out.append("<strike>")
            elif ty == "s_close":
                out.append("</strike>")
            elif ty == "code_inline":
                out.append(f'<font face="Mono" size="-1">{esc(t.content)}</font>')
            elif ty == "link_open":
                href = t.attrGet("href") or ""
                if href.startswith("http://") or href.startswith("https://"):
                    out.append(f'<a href="{esc(href)}" color="#1d4ed8">')
                    link_stack.append("</a>")
                elif "assets/audit/" in href and href.endswith(".png"):
                    audit_links.append(href)
                    out.append("<i>")
                    link_stack.append("</i>")
                else:
                    # внутренняя ссылка (на главу/якорь): оставляем только текст
                    link_stack.append("")
            elif ty == "link_close":
                out.append(link_stack.pop() if link_stack else "")
            elif ty == "image":
                src = t.attrGet("src") or ""
                alt = "".join(c.content for c in (t.children or []) if c.type == "text")
                images.append((src, alt))
            elif ty == "html_inline":
                c = t.content.lower()
                if c.startswith("<br"):
                    out.append("<br/>")
                elif c == "<sup>":
                    out.append("<super>")
                elif c == "</sup>":
                    out.append("</super>")
                elif c == "<sub>":
                    out.append("<sub>")
                elif c == "</sub>":
                    out.append("</sub>")
            elif ty == "entity":
                out.append(esc(html.unescape(t.content)))
            else:
                if t.content:
                    out.append(esc(t.content))
        markup = "".join(out)
        # ссылки на схемы аудита: подготовим картинки после абзаца
        for href in audit_links:
            name = Path(href).name
            path = ASSETS_AUDIT / name
            cap = next((c for n, c, _ in AUDIT_SCHEMES if n == path.stem), path.stem)
            images.append((str(path), f"Схема аудита 2026-10. {cap}"))
        return markup, images

    @staticmethod
    def plain(children) -> str:
        return "".join(c.content if c.type in ("text", "code_inline", "text_special") else (" " if c.type == "softbreak" else MdRenderer.plain(c.children) if c.children else "")
                       for c in children or [])

    # ------------------------------------------------------------- блоки ---
    def para_style(self, hidden=False):
        S = self.S
        if self.title_mode:
            return ParagraphStyle("title_body", parent=S["body"], alignment=TA_LEFT, fontSize=10, leading=13.5)
        if self.table is not None:
            return S["cell_head"] if self.in_head else S["cell"]
        if self.alert:
            st = ParagraphStyle(f"alert_{self.alert}", parent=S["quote"],
                                backColor=colors.HexColor(ALERTS[self.alert][2]))
            return st
        if self.quote_depth:
            return S["quote"]
        return S["body_tight"] if hidden else S["body"]

    def add_para(self, markup, hidden=False):
        st = self.para_style(hidden)
        bullet = None
        if self.list_stack:
            kind, counter, start = self.list_stack[-1]
            level = len(self.list_stack)
            indent = 14 * level + (8 if self.quote_depth else 0)
            st = ParagraphStyle(f"li{level}{st.name}", parent=st, leftIndent=st.leftIndent + indent,
                                bulletIndent=st.leftIndent + indent - 11, spaceAfter=2 if hidden else 4,
                                bulletFontName=st.fontName, bulletFontSize=st.fontSize)
            if getattr(self, "_item_fresh", False):
                bullet = "•" if kind == "bullet" else f"{counter}."
                if kind == "bullet" and level > 1:
                    bullet = "–"
                self._item_fresh = False
        if self.table is not None:
            self.row.append(Paragraph(markup, st))
            return
        if bullet is not None:
            self.emit(Paragraph(markup, st, bulletText=bullet))
        else:
            self.emit(Paragraph(markup, st))

    def _only_headings_so_far(self) -> bool:
        for fl in self.story:
            if isinstance(fl, (Heading, CondPageBreak, Spacer)):
                continue
            if isinstance(fl, Paragraph) and fl.style.name in ("h1", "h2", "h3", "h4", "title", "subtitle"):
                continue
            return False
        return True

    def add_image(self, src, caption, kind="audit"):
        path = Path(src)
        if not path.is_absolute():
            path = (self.base_dir / src).resolve()
        if not path.exists():
            self.emit(Paragraph(f"<i>[изображение не найдено: {esc(src)}]</i>", self.S["small"]))
            return
        with PILImage.open(path) as im:
            pw, ph = im.size
        cap_par = Paragraph(esc(caption), self.S["caption"]) if caption else Spacer(1, 6)

        if kind == "mermaid":
            # 1 px SVG = 2 px PNG; целевой масштаб 0.17 мм на px SVG (текст ≈ 9–10 pt)
            nat_w = pw / 2 * 0.17 * mm
            wide = nat_w > self.fw * 1.5 and pw / ph > 1.9
        else:
            nat_w = self.fw
            # схемы аудита — на альбомных страницах; в приложении (где они повторяются
            # уменьшенно) альбомную страницу получает только карта аудита
            wide = (kind == "audit") and (not self.appendix_mode or path.stem.startswith("08-"))

        if wide:
            # альбомная страница: ширина LAND_W, высота LAND_H (минус подпись и заголовки)
            w = min(nat_w, LAND_W) if kind == "mermaid" else LAND_W
            h = w * ph / pw
            max_h = LAND_H - 14 * mm - (26 * mm if self._only_headings_so_far() else 0)
            if h > max_h:
                h = max_h
                w = h * pw / ph
            img = Image(str(path), width=w, height=h)
            img.hAlign = "CENTER"
            if self._only_headings_so_far() and not self.start_landscape and not self._pending_portrait:
                # глава начинается с широкой схемы: вся первая страница — альбомная
                self.start_landscape = True
                self.story.append(img)
                self.story.append(cap_par)
                self._pending_portrait = True
            else:
                self.emit(FloatFigure([img, cap_par]))
            return

        max_h = 0.72 * self.fh
        w = min(nat_w, self.fw)
        if self.appendix_mode and kind == "audit":
            w = min(w, 0.78 * self.fw)
        h = w * ph / pw
        if h > max_h:
            h = max_h
            w = h * pw / ph
        img = Image(str(path), width=w, height=h)
        img.hAlign = "CENTER"
        self.emit(KeepTogether([Spacer(1, 4), img, cap_par]))

    def heading(self, level, markup, plain):
        S = self.S
        if self.title_mode:
            self.emit(Paragraph(markup, S["title"] if level == 1 else S["subtitle"]))
            return
        self.key_counter += 1
        key = f"{self.chapter_tag}h{self.key_counter}"
        if level == 1:
            self.emit(Heading(markup, S["h1"], 0, plain, key))
        elif level == 2:
            self.emit(CondPageBreak(60))
            self.emit(Heading(markup, S["h2"], 1, plain, key))
        elif level == 3:
            self.emit(CondPageBreak(45))
            self.emit(Heading(markup, S["h3"], 2, plain, key))
        else:
            self.emit(Paragraph(markup, S["h4"]))

    def fence(self, token):
        info = (token.info or "").strip().lower()
        if info == "mermaid":
            self.mermaid_counter += 1
            WORK.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha1(token.content.encode("utf-8")).hexdigest()[:12]
            base = WORK / f"mmd-{digest}"
            png = base.with_suffix(".png")
            if not png.exists():
                mermaid_render.render(token.content, base)
            tag = self.chapter_tag.rstrip("-").lstrip("c") or "x"
            cap = f"Рис. {tag}.{self.mermaid_counter}. Визуальная сводка главы (Mermaid-схема, автоматическая отрисовка)"
            self.add_image(str(png), cap, kind="mermaid")
            return
        text = esc(token.content.rstrip("\n"))
        lines = []
        for ln in text.split("\n"):
            while len(ln) > 95:
                lines.append(ln[:95])
                ln = ln[95:]
            lines.append(ln)
        self.emit(XPreformatted("\n".join(lines), self.S["code"]))

    def html_block(self, content: str):
        c = content.strip()
        if c.startswith("<!--"):
            return
        if "<summary" in c:
            self.emit(Paragraph("Ответ", self.S["answer"]))
            return
        # <details>, </details> и прочее — пропускаем

    def finish_table(self):
        if not self.table:
            self.table = None
            return
        rows = self.table
        ncols = max(len(r) for r in rows)
        for r in rows:
            while len(r) < ncols:
                r.append(Paragraph("", self.S["cell"]))
        # ширины колонок по длине содержимого
        weights = []
        for ci in range(ncols):
            lens = []
            for r in rows:
                t = r[ci].text if hasattr(r[ci], "text") else ""
                t = re.sub(r"<[^>]+>", "", t)
                lens.append(len(t))
            mx = max(lens) if lens else 10
            avg = sum(lens) / len(lens) if lens else 10
            weights.append(max(min(0.5 * mx + 0.5 * avg, 55), 7))
        total = sum(weights)
        colw = [self.fw * w / total for w in weights]
        t = Table(rows, colWidths=colw, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9ca3af")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
        ]))
        self.emit(Spacer(1, 3))
        self.emit(t)
        self.emit(Spacer(1, 7))
        self.table = None

    # ------------------------------------------------------------ обход ---
    def render(self, text: str):
        tokens = md_parser().parse(text)
        i = 0
        n = len(tokens)
        while i < n:
            t = tokens[i]
            ty = t.type
            if ty == "heading_open":
                inl = tokens[i + 1]
                markup, _ = self.inline(inl.children)
                self.heading(int(t.tag[1]), markup, self.plain(inl.children))
                i += 3
                continue
            if ty == "paragraph_open":
                inl = tokens[i + 1]
                children = list(inl.children or [])
                # GitHub-алерты: первая строка цитаты [!TYPE]
                if self.quote_depth and children and children[0].type == "text":
                    m = re.match(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$", children[0].content)
                    if m:
                        self.alert = m.group(1)
                        title, color, bg = ALERTS[self.alert]
                        st = ParagraphStyle("alert_title", parent=self.S["quote"], fontName="Sans-B",
                                            textColor=colors.HexColor(color), backColor=colors.HexColor(bg),
                                            spaceAfter=0, keepWithNext=1)
                        self.emit(Paragraph(title, st))
                        children = children[1:]
                        if children and children[0].type == "softbreak":
                            children = children[1:]
                markup, images = self.inline(children)
                if markup.strip():
                    self.add_para(markup, hidden=t.hidden)
                for src, alt in images:
                    self.add_image(src, "" if (self.appendix_mode and not alt.startswith("Схема аудита")) else alt)
                i += 3
                continue
            if ty == "bullet_list_open":
                self.list_stack.append(["bullet", 0, 1])
            elif ty == "ordered_list_open":
                start = int(t.attrGet("start") or 1)
                self.list_stack.append(["ordered", start - 1, start])
            elif ty in ("bullet_list_close", "ordered_list_close"):
                self.list_stack.pop()
                if not self.list_stack and self.table is None:
                    self.emit(Spacer(1, 3))
            elif ty == "list_item_open":
                self.list_stack[-1][1] += 1
                self._item_fresh = True
            elif ty == "list_item_close":
                self._item_fresh = False
            elif ty == "blockquote_open":
                self.quote_depth += 1
            elif ty == "blockquote_close":
                self.quote_depth -= 1
                self.alert = None
                self.emit(Spacer(1, 4))
            elif ty == "fence" or ty == "code_block":
                self.fence(t)
            elif ty == "html_block":
                self.html_block(t.content)
            elif ty == "hr":
                self.emit(Spacer(1, 4))
                self.emit(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#9ca3af"),
                                             spaceBefore=2, spaceAfter=8))
            elif ty == "table_open":
                self.table = []
            elif ty == "table_close":
                self.finish_table()
            elif ty == "thead_open":
                self.in_head = True
            elif ty == "thead_close":
                self.in_head = False
            elif ty == "tr_open":
                self.row = []
            elif ty == "tr_close":
                self.table.append(self.row)
                self.row = None
            elif ty in ("th_open", "td_open"):
                inl = tokens[i + 1]
                markup, _ = self.inline(inl.children) if inl.type == "inline" else ("", [])
                st = self.S["cell_head"] if self.in_head else self.S["cell"]
                self.row.append(Paragraph(markup, st))
                i += 3
                continue
            i += 1
        return self.story


# --------------------------------------------------------- PDF: шаблон ---
class MonographDoc(BaseDocTemplate):
    def __init__(self, path, title, **kw):
        M = PAGE_MARGINS
        super().__init__(str(path), pagesize=A4, leftMargin=M["left"], rightMargin=M["right"],
                         topMargin=M["top"], bottomMargin=M["bottom"], title=title,
                         author="Коллектив авторов; аудит 2026-10", subject=title, **kw)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        land_frame = Frame(M["left"], M["bottom"], LAND_W, LAND_H, id="land",
                           leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([
            PageTemplate(id="title", frames=[frame], onPage=lambda c, d: None),
            PageTemplate(id="body", frames=[frame], onPage=self._decorate),
            PageTemplate(id="land", frames=[land_frame], onPage=self._decorate_land,
                         pagesize=landscape(A4)),
        ])
        self.running = ""
        self._last_level = -1
        self.short_title = "Гипертермический синдром и тепловые поражения — редакция 2026-10"

    def _footer(self, canv, doc, width):
        canv.saveState()
        canv.setFont("Sans", 7.8)
        canv.setFillColor(colors.HexColor("#6b7280"))
        y = self.bottomMargin - 8 * mm
        canv.drawString(self.leftMargin, y, self.short_title)
        canv.drawRightString(self.leftMargin + width, y, str(doc.page))
        canv.setStrokeColor(colors.HexColor("#d1d5db"))
        canv.setLineWidth(0.4)
        canv.line(self.leftMargin, y + 4 * mm, self.leftMargin + width, y + 4 * mm)
        canv.restoreState()

    def _decorate(self, canv, doc):
        self._footer(canv, doc, self.width)

    def _decorate_land(self, canv, doc):
        self._footer(canv, doc, LAND_W)

    # --- «плавающие» альбомные страницы со схемами -------------------------
    def handle_flowable(self, flowables):
        if isinstance(flowables[0], FloatFigure):
            self._handle_float(flowables)
            return
        super().handle_flowable(flowables)

    def _handle_float(self, flowables):
        fig = flowables[0]
        land = [NextPageTemplate("land"), PageBreak(), *fig.content]
        if len(flowables) == 1:
            flowables[0:1] = land
            return
        nxt = flowables[1]
        if isinstance(nxt, FloatFigure):
            flowables[0:2] = [FloatFigure(fig.content + [PageBreak()] + nxt.content)]
            return
        if isinstance(nxt, PageBreak):                # граница уже рядом
            flowables[0:1] = land + [NextPageTemplate("body")]
            return
        if isinstance(nxt, ActionFlowable):           # NextPageTemplate(...) и т. п.
            flowables[0:1] = land
            return
        frame = self.frame
        remaining = frame._y - frame._y1p
        if isinstance(nxt, CondPageBreak):
            if remaining < nxt.height:
                flowables[0:1] = land + [NextPageTemplate("body"), PageBreak()]
            else:
                flowables[0], flowables[1] = flowables[1], flowables[0]
            return
        avail = remaining - (0 if frame._atTop else nxt.getSpaceBefore())
        try:
            _, h = nxt.wrap(frame._aW, max(avail, 0))
        except Exception:
            h = avail + 1
        if h <= avail:                                # следующий элемент ещё помещается — пропускаем его вперёд
            flowables[0], flowables[1] = flowables[1], flowables[0]
            return
        S = frame.split(nxt, self.canv) if self.allowSplitting else []
        if len(S) >= 2 and not isinstance(S[0], (PageBreak, ActionFlowable)):
            flowables[0:2] = [S[0], fig] + list(S[1:])   # дозаполняем страницу началом абзаца
            return
        if S and isinstance(S[0], PageBreak):
            flowables[0:2] = land + [NextPageTemplate("body")] + list(S)
            return
        flowables[0:1] = land + [NextPageTemplate("body"), PageBreak()]

    def afterFlowable(self, fl):
        toc = getattr(fl, "_toc", None)
        if not toc:
            return
        level, text, key = toc
        self.canv.bookmarkPage(key)
        lvl = min(level, self._last_level + 1)
        self.canv.addOutlineEntry(text, key, level=lvl, closed=(lvl >= 1))
        self._last_level = lvl
        if level <= 1:
            self.notify("TOCEntry", (level, text, self.page, key))


def build_pdf() -> Path:
    register_fonts()
    S = make_styles()
    doc = MonographDoc(OUT_PDF, "Гипертермический синдром и тепловые поражения. Монография (редакция 2026-10)")
    fw, fh = doc.width, doc.height
    story = []

    files = chapter_files()
    titul = [p for p in files if p.name.startswith("00-")]
    chapters = [p for p in files if not p.name.startswith("00-")]

    # титульный лист
    story.append(Spacer(1, 40 * mm))
    r = MdRenderer(S, fw, fh, CHAPTERS_DIR)
    r.title_mode = True
    if titul:
        r.render(strip_nav(titul[0].read_text(encoding="utf-8")))
    story.extend(r.story)
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(f"<b>{EDITION}</b>", S["subtitle"]))
    story.append(Paragraph(
        "В издание включены все схемы: 16 визуальных сводок глав (Mermaid-схемы, автоматическая отрисовка) "
        "и 8 пояснительных схем аудита (SVG → PNG, каталог assets/audit). Приложение А — отчёт об аудите "
        "с перечнем исправлений, разных устоявшихся мнений и современных положений; Приложение Б — источники.",
        ParagraphStyle("tp", parent=S["small"], alignment=TA_CENTER)))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(f"Сборка: scripts/pdf/build_final_docs.py · {TODAY:%d.%m.%Y}",
                           ParagraphStyle("tp2", parent=S["small"], alignment=TA_CENTER)))
    story.append(NextPageTemplate("body"))
    story.append(PageBreak())

    # оглавление
    story.append(Paragraph("Содержание", S["h1"]))
    toc = TableOfContents()
    toc.levelStyles = [S["toc0"], S["toc1"]]
    toc.dotsMinLevel = 0
    story.append(toc)

    def add_part(renderer):
        story.append(NextPageTemplate("land" if renderer.start_landscape else "body"))
        story.append(PageBreak())
        story.extend(renderer.story)

    # главы
    for p in chapters:
        tag = p.name[:2].lstrip("0") or "0"
        r = MdRenderer(S, fw, fh, CHAPTERS_DIR, chapter_tag=f"c{tag}-")
        text = tidy_scheme_links(strip_nav(p.read_text(encoding="utf-8")))
        r.render(text)
        add_part(r)

    # приложения
    r = MdRenderer(S, fw, fh, ROOT, chapter_tag="apA-")
    r.appendix_mode = True
    audit = (ROOT / "АУДИТ-2026-10.md").read_text(encoding="utf-8")
    audit = audit.replace("# Содержательный аудит монографии — октябрь 2026",
                          "# Приложение А. Содержательный аудит монографии — октябрь 2026", 1)
    r.render(audit)
    add_part(r)
    r = MdRenderer(S, fw, fh, ROOT, chapter_tag="apB-")
    src = (ROOT / "ИСТОЧНИКИ.md").read_text(encoding="utf-8")
    src = src.replace("# Источники и границы доказательности",
                      "# Приложение Б. Источники и границы доказательности", 1)
    r.render(src)
    add_part(r)

    doc.multiBuild(story)
    return OUT_PDF


# ------------------------------------------------------- PDF: только схемы ---
class SchemesDoc(BaseDocTemplate):
    def __init__(self, path, **kw):
        super().__init__(str(path), pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                         topMargin=12 * mm, bottomMargin=12 * mm,
                         title="Гипертермический синдром — схемы аудита 2026-10 (PNG)",
                         author="Аудит 2026-10", **kw)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="body", frames=[frame], onPage=self._decorate)])

    def _decorate(self, canv, doc):
        canv.saveState()
        canv.setFont("Sans", 7.8)
        canv.setFillColor(colors.HexColor("#6b7280"))
        y = self.bottomMargin - 6 * mm
        canv.drawString(self.leftMargin, y, "Гипертермический синдром и тепловые поражения — схемы аудита 2026-10")
        canv.drawRightString(self.leftMargin + self.width, y, str(doc.page))
        canv.restoreState()

    def afterFlowable(self, fl):
        toc = getattr(fl, "_toc", None)
        if toc:
            level, text, key = toc
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=0)


def build_schemes_pdf() -> Path:
    register_fonts()
    S = make_styles()
    doc = SchemesDoc(OUT_SCHEMES_PDF)
    fw, fh = doc.width, doc.height
    story = []
    story.append(Spacer(1, 30 * mm))
    story.append(Paragraph("ГИПЕРТЕРМИЧЕСКИЙ СИНДРОМ И ТЕПЛОВЫЕ ПОРАЖЕНИЯ", S["title"]))
    story.append(Paragraph("Пояснительные схемы содержательного аудита 2026-10 (PNG, 2400 × 1350)", S["subtitle"]))
    story.append(Spacer(1, 8 * mm))
    rows = [[Paragraph("<b>№</b>", S["cell"]), Paragraph("<b>Схема</b>", S["cell"]),
             Paragraph("<b>Разделы монографии</b>", S["cell"]), Paragraph("<b>Файл</b>", S["cell"])]]
    for i, (name, cap, ref) in enumerate(AUDIT_SCHEMES, 1):
        rows.append([Paragraph(str(i), S["cell"]), Paragraph(esc(cap), S["cell"]),
                     Paragraph(esc(ref), S["cell"]), Paragraph(f"assets/audit/{name}.png", S["cell"])])
    t = Table(rows, colWidths=[10 * mm, 110 * mm, 55 * mm, fw - 175 * mm], hAlign="CENTER")
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9ca3af")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "Исходники — SVG в том же каталоге (assets/audit/*.svg), генераторы — scripts/audit_schemes/. "
        "Схемы являются пояснительными; дозы и критерии следует сверять с текстом монографии, локальным "
        "протоколом и инструкцией к препарату. Визуальные сводки глав (Mermaid) включены в PDF монографии.",
        ParagraphStyle("note", parent=S["small"], alignment=TA_CENTER)))
    story.append(PageBreak())
    for i, (name, cap, ref) in enumerate(AUDIT_SCHEMES, 1):
        path = ASSETS_AUDIT / f"{name}.png"
        with PILImage.open(path) as im:
            pw, ph = im.size
        head = Heading(f"Схема {i}. {esc(cap)}", ParagraphStyle("sh", parent=S["h2"], spaceBefore=0, spaceAfter=4),
                       0, f"Схема {i}. {cap}", f"s{i}")
        avail_h = fh - 16 * mm
        w = fw
        h = w * ph / pw
        if h > avail_h:
            h = avail_h
            w = h * pw / ph
        img = Image(str(path), width=w, height=h)
        img.hAlign = "CENTER"
        story.append(head)
        story.append(img)
        story.append(Paragraph(f"Относится к: {esc(ref)} · файл assets/audit/{name}.png",
                               ParagraphStyle("cap2", parent=S["caption"], spaceBefore=2)))
        if i < len(AUDIT_SCHEMES):
            story.append(PageBreak())
    doc.build(story)
    return OUT_SCHEMES_PDF


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--schemes", action="store_true")
    a = ap.parse_args()
    if not (a.md or a.pdf or a.schemes):
        a.md = a.pdf = a.schemes = True
    if a.md:
        print("MD  →", build_final_md().relative_to(ROOT))
    if a.pdf:
        print("PDF →", build_pdf().relative_to(ROOT))
    if a.schemes:
        print("PDF →", build_schemes_pdf().relative_to(ROOT))


if __name__ == "__main__":
    main()
