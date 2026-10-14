# -*- coding: utf-8 -*-
"""Tiny helper for hand-built explanatory SVG diagrams (DejaVu Sans, Cyrillic-safe)."""
import html, math

FONT = "DejaVu Sans, Verdana, Arial, sans-serif"

# palette
INK = "#1f2937"
MUTED = "#4b5563"
RED_F, RED_S = "#fee2e2", "#b91c1c"
AMB_F, AMB_S = "#fef3c7", "#b45309"
GRN_F, GRN_S = "#dcfce7", "#15803d"
BLU_F, BLU_S = "#dbeafe", "#1d4ed8"
VIO_F, VIO_S = "#ede9fe", "#6d28d9"
GRY_F, GRY_S = "#f3f4f6", "#6b7280"
TEA_F, TEA_S = "#ccfbf1", "#0f766e"


def _esc(t):
    return html.escape(t, quote=False)


def text_width(s, size, bold=False):
    """Rough advance-width estimate for DejaVu Sans."""
    w = 0.0
    for ch in s:
        if ch == " ":
            w += 0.32
        elif ch in "iIl.,:;!'|()[]":
            w += 0.30
        elif ch in "mwMWШЩЖЮМЫ":
            w += 0.95
        elif ch.isupper():
            w += 0.78
        elif ch.isdigit():
            w += 0.66
        elif ch in "–—":
            w += 0.62
        else:
            w += 0.655
    if bold:
        w *= 1.08
    return w * size


def wrap(text, max_w, size, bold=False):
    """Greedy word wrap; explicit '\n' forces a break."""
    out = []
    for para in text.split("\n"):
        words = para.split(" ")
        line = ""
        for w in words:
            cand = (line + " " + w).strip()
            if line and text_width(cand, size, bold) > max_w:
                out.append(line)
                line = w
            else:
                line = cand
        out.append(line)
    return out


class Canvas:
    def __init__(self, w=1600, h=900, bg="#ffffff"):
        self.w, self.h = w, h
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
            f'<rect width="{w}" height="{h}" fill="{bg}"/>',
            '<defs>'
            '<marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{MUTED}"/></marker>'
            '<marker id="arr-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{RED_S}"/></marker>'
            '</defs>',
        ]

    # ---- primitives -------------------------------------------------
    def text(self, x, y, s, size=20, fill=INK, anchor="start", bold=False, italic=False, opacity=1.0):
        fw = ' font-weight="bold"' if bold else ""
        fs = ' font-style="italic"' if italic else ""
        self.parts.append(
            f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}"{fw}{fs} opacity="{opacity}">{_esc(s)}</text>'
        )

    def lines(self, x, y, lines, size=20, fill=INK, anchor="start", bold=False, lh=1.3, italic=False):
        for i, ln in enumerate(lines):
            self.text(x, y + i * size * lh, ln, size, fill, anchor, bold, italic)
        return y + len(lines) * size * lh

    def rect(self, x, y, w, h, fill=GRY_F, stroke=GRY_S, sw=2.5, rx=14, dash=None, opacity=1.0):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{sw}"{d} opacity="{opacity}"/>'
        )

    def line(self, x1, y1, x2, y2, stroke=MUTED, sw=3, dash=None, arrow=False, red=False):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        m = ' marker-end="url(#arr-red)"' if (arrow and red) else (' marker-end="url(#arr)"' if arrow else "")
        self.parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}"{d}{m} stroke-linecap="round"/>'
        )

    def path(self, d, stroke=MUTED, sw=3, arrow=False, dash=None, fill="none"):
        m = ' marker-end="url(#arr)"' if arrow else ""
        dd = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{m}{dd} stroke-linejoin="round"/>')

    def circle(self, cx, cy, r, fill, stroke, sw=2.5):
        self.parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def diamond(self, cx, cy, w, h, fill=AMB_F, stroke=AMB_S, sw=2.5):
        pts = f"{cx},{cy-h/2} {cx+w/2},{cy} {cx},{cy+h/2} {cx-w/2},{cy}"
        self.parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"/>')

    # ---- composites -------------------------------------------------
    def box(self, x, y, w, h, title=None, body=None, fill=GRY_F, stroke=GRY_S, tsize=22, bsize=18,
            align="left", pad=16, rx=14, sw=2.5, title_fill=None, body_fill=INK, dash=None, vcenter=False):
        """Rounded box with optional bold title and wrapped body text. Returns bottom y of text."""
        self.rect(x, y, w, h, fill, stroke, sw, rx, dash)
        tx = x + pad if align == "left" else x + w / 2
        anchor = "start" if align == "left" else "middle"
        maxw = w - 2 * pad
        blocks = []
        if title:
            blocks.append(("t", wrap(title, maxw, tsize, True)))
        if body:
            if isinstance(body, str):
                body = [body]
            for b in body:
                blocks.append(("b", wrap(b, maxw, bsize, False)))
        # measure
        total = 0
        for kind, ls in blocks:
            sz = tsize if kind == "t" else bsize
            total += len(ls) * sz * 1.3 + (6 if kind == "t" else 4)
        cy = y + pad + (tsize if blocks and blocks[0][0] == "t" else bsize) * 0.9
        if vcenter:
            cy = y + (h - total) / 2 + (tsize if blocks and blocks[0][0] == "t" else bsize) * 0.95
        for kind, ls in blocks:
            if kind == "t":
                cy = self.lines(tx, cy, ls, tsize, title_fill or stroke, anchor, True) + 6
            else:
                cy = self.lines(tx, cy, ls, bsize, body_fill, anchor, False) + 4
        return cy

    def pill(self, x, y, label, fill, stroke, size=16, bold=True, pad=12, fg=None):
        w = text_width(label, size, bold) + 2 * pad
        h = size * 1.7
        self.rect(x, y, w, h, fill, stroke, 2, h / 2)
        self.text(x + w / 2, y + h * 0.68, label, size, fg or stroke, "middle", bold)
        return w

    def title(self, s, sub=None, size=34, y=52):
        self.text(self.w / 2, y, s, size, INK, "middle", True)
        if sub:
            self.text(self.w / 2, y + size * 1.05, sub, size * 0.56, MUTED, "middle", False)

    def footer(self, s, size=15):
        ls = wrap(s, self.w - 80, size)
        y0 = self.h - 18 - (len(ls) - 1) * size * 1.3
        self.lines(40, y0, ls, size, MUTED)

    def save(self, path):
        self.parts.append("</svg>")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.parts))
        return path
