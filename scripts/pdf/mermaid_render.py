#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Минимальный рендер Mermaid-блоков (``flowchart TD|LR``) монографии в SVG/PNG.

Поддерживается ровно то подмножество синтаксиса, которое используется в
``главы/*.md``: прямоугольные ``A["текст"]``, ромбовидные ``B{"текст"}`` и
скруглённые ``C("текст")`` узлы, рёбра ``-->``, ``-->|"подпись"|``,
пунктирные ``-. "подпись" .->`` / ``-.->``, цепочки ``A --> B --> C`` и
обратные рёбра (циклы). Раскладка — послойная (longest path + barycenter),
как у dagre, но без внешних зависимостей. Растр делается через
``scripts/audit_schemes/render.js`` (@resvg/resvg-js).
"""

from __future__ import annotations

import html
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "audit_schemes"))
from svglib import text_width, wrap  # noqa: E402

FONT = "DejaVu Sans, Verdana, Arial, sans-serif"
INK = "#1f2937"
EDGE = "#374151"
STYLES = {
    "rect": ("#eff6ff", "#1d4ed8"),
    "diamond": ("#fffbeb", "#b45309"),
    "round": ("#ecfdf5", "#15803d"),
}
FS = 20          # кегль текста узлов
LH = 26          # межстрочный интервал
LFS = 17         # кегль подписей рёбер
PAD_X, PAD_Y = 18, 12
GAP_SIBLING = 44  # зазор между узлами одного слоя
GAP_RANK = 64     # зазор между слоями реальных узлов (к нему добавляется высота подписей рёбер)
MARGIN = 30


class Node:
    def __init__(self, nid: str, shape: str = "rect", label: str | None = None):
        self.id = nid
        self.shape = shape
        self.label = label if label is not None else nid
        self.dummy = False
        self.lines: list[str] = []
        self.w = self.h = 0.0
        self.x = self.y = 0.0
        self.rank = 0
        self.order = 0


class Edge:
    def __init__(self, src: str, dst: str, label: str = "", dotted: bool = False):
        self.src, self.dst, self.label, self.dotted = src, dst, label, dotted
        self.back = False
        self.points: list[tuple[float, float]] = []


# ---------------------------------------------------------------- парсер ---
_ID = re.compile(r"[A-Za-z0-9_]+")
_OPEN = {"[": ("]", "rect"), "{": ("}", "diamond"), "(": (")", "round")}


def _parse_node(s: str, i: int, nodes: dict[str, Node], order: list[str]):
    m = _ID.match(s, i)
    if not m:
        return None, i
    nid = m.group(0)
    i = m.end()
    shape, label = None, None
    if i < len(s) and s[i] in _OPEN:
        close, shape = _OPEN[s[i]]
        i += 1
        if i < len(s) and s[i] == '"':
            j = s.index('"', i + 1)
            label = s[i + 1:j]
            i = j + 1
        else:
            j = s.index(close, i)
            label = s[i:j]
            i = j
        if i < len(s) and s[i] == close:
            i += 1
    if nid not in nodes:
        nodes[nid] = Node(nid, shape or "rect", label)
        order.append(nid)
    elif shape:
        nodes[nid].shape, nodes[nid].label = shape, label
    return nid, i


_ARROW = re.compile(
    r"\s*(?:"
    r"(?P<dot1>-\.\s*\"(?P<dl1>[^\"]*)\"\s*\.->)|"
    r"(?P<dot2>-\.\s*(?P<dl2>[^.\"]+?)\s*\.->)|"
    r"(?P<dot3>-\.->)|"
    r"(?P<solid>-->|==>|---)"
    r")\s*(?:\|\s*\"?(?P<lbl>[^|]*?)\"?\s*\|)?\s*"
)


def parse(text: str):
    nodes: dict[str, Node] = {}
    order: list[str] = []
    edges: list[Edge] = []
    direction = "TD"
    for raw in text.splitlines():
        line = raw.split("%%")[0].strip()
        if not line:
            continue
        m = re.match(r"^(flowchart|graph)\s+(\w+)", line)
        if m:
            direction = m.group(2).upper()
            continue
        nid, i = _parse_node(line, 0, nodes, order)
        if nid is None:
            continue
        while i < len(line):
            am = _ARROW.match(line, i)
            if not am or am.end() == i:
                break
            dotted = bool(am.group("dot1") or am.group("dot2") or am.group("dot3"))
            label = am.group("dl1") or am.group("dl2") or am.group("lbl") or ""
            i = am.end()
            dst, i = _parse_node(line, i, nodes, order)
            if dst is None:
                break
            edges.append(Edge(nid, dst, html.unescape(label.strip()), dotted))
            nid = dst
    if direction in ("TB",):
        direction = "TD"
    return direction, nodes, order, edges


# --------------------------------------------------------------- раскладка ---
def _size_nodes(nodes: dict[str, Node]):
    for n in nodes.values():
        if n.dummy:
            if not n.w:
                n.w, n.h = 2, 2
            continue
        label = n.label.replace("<br>", "\n").replace("<br/>", "\n")
        maxw = 170 if n.shape == "diamond" else 240
        n.lines = wrap(label, maxw, FS)
        tw = max(text_width(l, FS) for l in n.lines)
        th = LH * len(n.lines)
        if n.shape == "diamond":
            # вписанный прямоугольник: w/(2a)+h/(2b)=1 при a=w+pad, b=h+pad
            n.w = 2 * (tw + 24)
            n.h = 2 * (th + 10)
        else:
            n.w = tw + 2 * PAD_X
            n.h = th + 2 * PAD_Y


def _find_back_edges(order: list[str], edges: list[Edge]):
    out = defaultdict(list)
    for e in edges:
        out[e.src].append(e)
    state = {}
    def dfs(u):
        state[u] = 1
        for e in out[u]:
            v = e.dst
            if state.get(v) == 1:
                e.back = True
            elif v not in state:
                dfs(v)
        state[u] = 2
    sys.setrecursionlimit(10000)
    for u in order:
        if u not in state:
            dfs(u)


def _rank(nodes: dict[str, Node], order: list[str], edges: list[Edge]):
    fwd = [e for e in edges if not e.back]
    indeg = {u: 0 for u in order}
    out = defaultdict(list)
    for e in fwd:
        indeg[e.dst] += 1
        out[e.src].append(e.dst)
    rank = {u: 0 for u in order}
    queue = [u for u in order if indeg[u] == 0]
    seen = []
    while queue:
        u = queue.pop(0)
        seen.append(u)
        for v in out[u]:
            rank[v] = max(rank[v], rank[u] + 1)
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    # ранги удваиваем: нечётные слои отводятся под подписи рёбер (как у dagre)
    for u in order:
        nodes[u].rank = rank[u] * 2


def _label_box(label: str):
    lines = wrap(label, 190, LFS)
    tw = max(text_width(l, LFS) for l in lines)
    th = len(lines) * (LFS + 4)
    return lines, tw + 14, th + 8


def _insert_dummies(nodes, order, edges):
    """Рёбра разбиваем фиктивными узлами по промежуточным слоям: длинные рёбра
    не ложатся на чужие узлы, а подпись ребра занимает место в нечётном слое и
    не пересекается с соседними подписями."""
    new_edges = []
    counter = 0
    for e in edges:
        e.label_node = None
        if e.back:
            new_edges.append(e)
            continue
        r1, r2 = nodes[e.src].rank, nodes[e.dst].rank
        chain = [e.src]
        for r in range(r1 + 1, r2):
            counter += 1
            d = Node(f"__d{counter}")
            d.dummy = True
            d.rank = r
            if e.label and r == r1 + 1:
                _, d.w, d.h = _label_box(e.label)
                d.w += 10
                e.label_node = d.id
            nodes[d.id] = d
            order.append(d.id)
            chain.append(d.id)
        chain.append(e.dst)
        e.chain = chain
        new_edges.append(e)
    return new_edges


def _order(nodes, order, edges):
    ranks = defaultdict(list)
    for u in order:
        ranks[nodes[u].rank].append(u)
    R = max(ranks) + 1 if ranks else 0
    # соседи по цепочкам (с учётом фиктивных узлов)
    up, down = defaultdict(list), defaultdict(list)
    for e in edges:
        if e.back:
            continue
        chain = getattr(e, "chain", [e.src, e.dst])
        for a, b in zip(chain, chain[1:]):
            down[a].append(b)
            up[b].append(a)
    pos = {}
    def setpos():
        for r in range(R):
            for i, u in enumerate(ranks[r]):
                pos[u] = i
    setpos()
    def bary(u, neigh):
        vals = [pos[v] for v in neigh[u] if v in pos]
        return sum(vals) / len(vals) if vals else None
    for it in range(8):
        rng = range(1, R) if it % 2 == 0 else range(R - 2, -1, -1)
        neigh = up if it % 2 == 0 else down
        for r in rng:
            keyed = []
            for i, u in enumerate(ranks[r]):
                b = bary(u, neigh)
                keyed.append((b if b is not None else i, i, u))
            keyed.sort()
            ranks[r] = [u for _, _, u in keyed]
            setpos()
    for r in range(R):
        for i, u in enumerate(ranks[r]):
            nodes[u].order = i
    return ranks, up, down


def _place_with_gaps(want, sizes):
    """Ближайшие к желаемым (по L2) позиции при фиксированном порядке и минимальных
    зазорах между соседями: изотоническая регрессия (PAVA) по сдвинутым координатам."""
    n = len(want)
    cum = [0.0] * n
    for i in range(1, n):
        cum[i] = cum[i - 1] + sizes[i - 1] / 2 + GAP_SIBLING + sizes[i] / 2
    targets = [w - c for w, c in zip(want, cum)]
    blocks = []  # [sum, count]
    for t in targets:
        blocks.append([t, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            b = blocks.pop()
            blocks[-1][0] += b[0]
            blocks[-1][1] += b[1]
    ys = []
    for sm, cnt in blocks:
        ys.extend([sm / cnt] * cnt)
    return [y + c for y, c in zip(ys, cum)]


def _coords(nodes, ranks, up, down, direction):
    R = max(ranks) + 1
    # вдоль "главной" оси: слои
    main = 0.0
    layer_pos = []
    for r in range(R):
        thick = max([(nodes[u].h if direction == "TD" else nodes[u].w) for u in ranks[r]] or [0])
        if r % 2 == 0:  # слой реальных узлов
            layer_pos.append(main + thick / 2)
            main += thick
        else:           # слой подписей рёбер / точек маршрута
            gap = GAP_RANK + (thick + 28 if thick > 2 else 0)
            layer_pos.append(main + gap / 2)
            main += gap
    def ext(u):  # размер поперёк главной оси
        return nodes[u].w if direction == "TD" else nodes[u].h
    cross = {}
    # первичное размещение: центрирование слоя
    for r in range(R):
        if not ranks[r]:
            continue
        total = sum(ext(u) for u in ranks[r]) + GAP_SIBLING * (len(ranks[r]) - 1)
        c = -total / 2
        for u in ranks[r]:
            cross[u] = c + ext(u) / 2
            c += ext(u) + GAP_SIBLING
    # подтягивание к медиане родителей / детей
    for sweep in range(4):
        seq = range(1, R) if sweep % 2 == 0 else range(R - 2, -1, -1)
        neigh = up if sweep % 2 == 0 else down
        for r in seq:
            if not ranks[r]:
                continue
            want = []
            for u in ranks[r]:
                vals = sorted(cross[v] for v in neigh[u] if v in cross)
                if vals:
                    want.append(vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals)//2 - 1] + vals[len(vals)//2]) / 2)
                else:
                    want.append(cross[u])
            xs = _place_with_gaps(want, [ext(u) for u in ranks[r]])
            for u, x in zip(ranks[r], xs):
                cross[u] = x
    for r in range(R):
        for u in ranks[r]:
            if direction == "TD":
                nodes[u].x, nodes[u].y = cross[u], layer_pos[r]
            else:
                nodes[u].x, nodes[u].y = layer_pos[r], cross[u]


# ------------------------------------------------------------------ SVG ---
def _esc(t):
    return html.escape(t, quote=False)


def _node_svg(n: Node):
    fill, stroke = STYLES.get(n.shape, STYLES["rect"])
    x, y, w, h = n.x, n.y, n.w, n.h
    parts = []
    if n.shape == "diamond":
        pts = f"{x},{y - h/2} {x + w/2},{y} {x},{y + h/2} {x - w/2},{y}"
        parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
    elif n.shape == "round":
        parts.append(f'<rect x="{x - w/2}" y="{y - h/2}" width="{w}" height="{h}" rx="{h/2}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
    else:
        parts.append(f'<rect x="{x - w/2}" y="{y - h/2}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
    ty = y - LH * (len(n.lines) - 1) / 2 + FS * 0.35
    for i, line in enumerate(n.lines):
        parts.append(
            f'<text x="{x}" y="{ty + i * LH:.1f}" font-family="{FONT}" font-size="{FS}" '
            f'fill="{INK}" text-anchor="middle">{_esc(line)}</text>'
        )
    return "\n".join(parts)


def _anchor(n: Node, side: str):
    if side == "top":
        return n.x, n.y - n.h / 2
    if side == "bottom":
        return n.x, n.y + n.h / 2
    if side == "left":
        return n.x - n.w / 2, n.y
    return n.x + n.w / 2, n.y


def _smooth_path(points, direction):
    """Кусочно-кубическая кривая с касательными вдоль главной оси."""
    d = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if direction == "TD":
            dy = (y1 - y0) * 0.5
            d.append(f"C {x0:.1f} {y0 + dy:.1f}, {x1:.1f} {y1 - dy:.1f}, {x1:.1f} {y1:.1f}")
        else:
            dx = (x1 - x0) * 0.5
            d.append(f"C {x0 + dx:.1f} {y0:.1f}, {x1 - dx:.1f} {y1:.1f}, {x1:.1f} {y1:.1f}")
    return " ".join(d)


def _bezier_point(p0, p1, p2, p3, t):
    mt = 1 - t
    return (
        mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
        mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1],
    )


def _label_svg(x, y, label):
    lines, bw, bh = _label_box(label)
    th = bh - 8
    out = [f'<rect x="{x - bw/2:.1f}" y="{y - bh/2:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="4" fill="#ffffff" stroke="#d1d5db" stroke-width="1"/>']
    ty = y - th / 2 + LFS * 0.85 + 2
    for i, l in enumerate(lines):
        out.append(f'<text x="{x:.1f}" y="{ty + i * (LFS + 4):.1f}" font-family="{FONT}" font-size="{LFS}" fill="{INK}" text-anchor="middle">{_esc(l)}</text>')
    return "\n".join(out)


def layout(text: str):
    direction, nodes, order, edges = parse(text)
    _size_nodes(nodes)
    _find_back_edges(order, edges)
    _rank(nodes, order, edges)
    edges = _insert_dummies(nodes, order, edges)
    ranks, up, down = _order(nodes, order, edges)
    _coords(nodes, ranks, up, down, direction)
    return direction, nodes, order, edges, ranks


def to_svg(text: str) -> tuple[str, int, int]:
    direction, nodes, order, edges, ranks = layout(text)
    real = [n for n in nodes.values() if not n.dummy]
    boxed = real + [nodes[e.label_node] for e in edges if getattr(e, "label_node", None)]
    minx = min(n.x - n.w / 2 for n in boxed)
    maxx = max(n.x + n.w / 2 for n in boxed)
    miny = min(n.y - n.h / 2 for n in boxed)
    maxy = max(n.y + n.h / 2 for n in boxed)

    body = []
    labels = []
    back_i = 0
    back_targets = defaultdict(int)
    for e in edges:
        s, t = nodes[e.src], nodes[e.dst]
        dash = ' stroke-dasharray="7 6"' if e.dotted else ""
        if not e.back:
            chain = getattr(e, "chain", [e.src, e.dst])
            pts = []
            for k, nid in enumerate(chain):
                n = nodes[nid]
                if n.dummy:
                    pts.append((n.x, n.y))
                elif k == 0:
                    pts.append(_anchor(n, "bottom" if direction == "TD" else "right"))
                else:
                    pts.append(_anchor(n, "top" if direction == "TD" else "left"))
            d = _smooth_path(pts, direction)
            body.append(f'<path d="{d}" fill="none" stroke="{EDGE}" stroke-width="2"{dash} marker-end="url(#arr)"/>')
            if e.label and e.label_node:
                ln = nodes[e.label_node]
                labels.append(_label_svg(ln.x, ln.y, e.label))
        else:
            back_i += 1
            off = 26 + 22 * back_i
            k = back_targets[e.dst]
            back_targets[e.dst] += 1
            if direction == "TD":
                lo, hi = min(s.rank, t.rank), max(s.rank, t.rank)
                span = [nodes[u] for r in range(lo, hi + 1) for u in ranks[r] if not nodes[u].dummy]
                X = max(n.x + n.w / 2 for n in span) + off
                maxx = max(maxx, X + 10)
                p0 = _anchor(s, "right")
                p1 = _anchor(t, "right")
                p0 = (p0[0], p0[1] + 12 * k)
                p1 = (p1[0], p1[1] + 12 * k)
                d = (f"M {p0[0]:.1f} {p0[1]:.1f} L {X - 10:.1f} {p0[1]:.1f} Q {X:.1f} {p0[1]:.1f} {X:.1f} {p0[1] - 10:.1f} "
                     f"L {X:.1f} {p1[1] + 10:.1f} Q {X:.1f} {p1[1]:.1f} {X - 10:.1f} {p1[1]:.1f} L {p1[0] + 2:.1f} {p1[1]:.1f}")
                lx, ly = X, (p0[1] + p1[1]) / 2
            else:
                lo, hi = min(s.rank, t.rank), max(s.rank, t.rank)
                span = [nodes[u] for r in range(lo, hi + 1) for u in ranks[r] if not nodes[u].dummy]
                Y = max(n.y + n.h / 2 for n in span) + off
                maxy = max(maxy, Y + 10)
                p0 = _anchor(s, "bottom")
                p1 = _anchor(t, "bottom")
                p0 = (p0[0] - 12 * k, p0[1])
                p1 = (p1[0] - 12 * k, p1[1])
                d = (f"M {p0[0]:.1f} {p0[1]:.1f} L {p0[0]:.1f} {Y - 10:.1f} Q {p0[0]:.1f} {Y:.1f} {p0[0] - 10:.1f} {Y:.1f} "
                     f"L {p1[0] + 10:.1f} {Y:.1f} Q {p1[0]:.1f} {Y:.1f} {p1[0]:.1f} {Y - 10:.1f} L {p1[0]:.1f} {p1[1] + 2:.1f}")
                lx, ly = (p0[0] + p1[0]) / 2, Y
            body.append(f'<path d="{d}" fill="none" stroke="{EDGE}" stroke-width="2"{dash} marker-end="url(#arr)"/>')
            if e.label:
                labels.append(_label_svg(lx, ly, e.label))
    for n in real:
        body.append(_node_svg(n))
    body.extend(labels)

    # подписи рёбер могут выходить за габариты узлов — добавим запас
    W = int(maxx - minx + 2 * MARGIN + 40)
    H = int(maxy - miny + 2 * MARGIN + 20)
    ox, oy = -minx + MARGIN + 20, -miny + MARGIN + 10
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
        '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{EDGE}"/></marker></defs>',
        f'<g transform="translate({ox:.1f},{oy:.1f})">',
        *body,
        "</g></svg>",
    ]
    return "\n".join(svg), W, H


def render_png(svg_path: Path, png_path: Path, width: int):
    render_js = HERE.parent / "audit_schemes" / "render.js"
    env = dict(os.environ)
    if "NODE_PATH" not in env:
        for cand in (Path.home() / "svgtools" / "node_modules",):
            if cand.exists():
                env["NODE_PATH"] = str(cand)
    subprocess.run(["node", str(render_js), str(svg_path), str(png_path), str(width)],
                   check=True, env=env, stdout=subprocess.DEVNULL)


def render(text: str, out_base: Path, scale: float = 2.0) -> Path:
    svg, W, H = to_svg(text)
    svg_path = out_base.with_suffix(".svg")
    png_path = out_base.with_suffix(".png")
    svg_path.write_text(svg, encoding="utf-8")
    render_png(svg_path, png_path, int(min(W * scale, 3200)))
    return png_path


if __name__ == "__main__":
    src = Path(sys.argv[1]).read_text(encoding="utf-8")
    out = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    print(render(src, out))
