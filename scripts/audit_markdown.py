#!/usr/bin/env python3
"""Структурный аудит Markdown-пособия и сгенерированных материалов."""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from build_full_text import prepare


ROOT = Path(__file__).resolve().parents[1]
CHAPTERS = sorted((ROOT / "главы").glob("[0-9][0-9]-*.md"))
ROOT_DOCS = [ROOT / "README.md", ROOT / "ИСТОЧНИКИ.md", ROOT / "СЛАЙДЫ.md"]
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)")


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("не PNG")
    return struct.unpack(">II", header[16:24])


def check_links(path: Path, errors: list[str]) -> None:
    text = path.read_text()
    for target in IMAGE_RE.findall(text) + LINK_RE.findall(text):
        if re.match(r"^(?:https?://|mailto:)", target):
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            errors.append(f"{path.relative_to(ROOT)}: не найдена ссылка {target}")


def check_numbering(errors: list[str]) -> None:
    """Последовательность номеров глав, разделов и подразделов.

    Ловит не только дубли, но и разрывы: раздел, физически стоящий в конце
    главы с номером из её середины, — типичный след ручной вставки.
    """
    expected = 0
    for chapter in CHAPTERS:
        if chapter.name.startswith("00-"):
            continue
        expected += 1
        lines = chapter.read_text().splitlines()
        name = chapter.relative_to(ROOT)

        head = re.match(r"^# Глава (\d+)\.", lines[0]) if lines else None
        if head is None:
            errors.append(f"{name}: первая строка не «# Глава N.»")
            continue
        number = int(head.group(1))
        if number != expected:
            errors.append(f"{name}: «Глава {number}», по порядку файлов ожидается {expected}")

        sections: list[int] = []
        subsections: dict[int, list[int]] = {}
        for line in lines:
            level2 = re.match(r"^## (\d+)\.(\d+)\.", line)
            level3 = re.match(r"^### (\d+)\.(\d+)\.(\d+)\.", line)
            if level2:
                owner, index = int(level2.group(1)), int(level2.group(2))
                if owner != number:
                    errors.append(f"{name}: раздел {owner}.{index} в главе {number}")
                sections.append(index)
            if level3:
                owner, parent, index = (int(part) for part in level3.groups())
                if owner != number:
                    errors.append(
                        f"{name}: подраздел {owner}.{parent}.{index} в главе {number}"
                    )
                subsections.setdefault(parent, []).append(index)

        for label, items, prefix in [
            ("разделы", sections, f"{number}"),
            *[
                (f"подразделы {number}.{parent}", items, f"{number}.{parent}")
                for parent, items in subsections.items()
            ],
        ]:
            if not items:
                continue
            if items != sorted(items):
                errors.append(f"{name}: {label} идут не по возрастанию: {items}")
            duplicates = {i for i in items if items.count(i) > 1}
            if duplicates:
                errors.append(f"{name}: дублируются {label} {sorted(duplicates)}")
            gaps = [i for i in range(1, max(items) + 1) if i not in items]
            if gaps:
                errors.append(
                    f"{name}: пропущены {label} — нет {', '.join(f'{prefix}.{i}' for i in gaps)}"
                )


def main() -> None:
    errors: list[str] = []
    expected_numbers = [f"{number:02d}" for number in range(16)]
    actual_numbers = [path.name[:2] for path in CHAPTERS]
    if actual_numbers != expected_numbers:
        errors.append(
            f"нарушена последовательность глав: {', '.join(actual_numbers)}"
        )

    for chapter in CHAPTERS:
        text = chapter.read_text()
        number = chapter.name[:2]
        if number != "00":
            # Растровых иллюстраций в главах больше нет: они вынесены в
            # СЛАЙДЫ.md, в тексте остаются только Mermaid-схемы.
            if IMAGE_RE.search(text):
                errors.append(
                    f"{chapter}: в главах не должно быть растровых иллюстраций, "
                    "их место — СЛАЙДЫ.md"
                )
            visual_summary = re.search(
                r"<!-- visual-summary:start -->(.*?)<!-- visual-summary:end -->",
                text,
                re.DOTALL,
            )
            if visual_summary is None:
                errors.append(f"{chapter}: отсутствует блок визуального конспекта")
            elif "```mermaid" not in visual_summary.group(1):
                errors.append(
                    f"{chapter}: в визуальном конспекте должна быть Mermaid-схема"
                )
            if "```mermaid" not in text:
                errors.append(f"{chapter}: отсутствует Mermaid-схема")
            if "<!-- chapter-nav:start -->" not in text:
                errors.append(f"{chapter}: отсутствует навигация")
            if text.count("```mermaid") != 1 and number != "01":
                errors.append(f"{chapter}: ожидается одна сводная Mermaid-схема")

        if text.count("```") % 2:
            errors.append(f"{chapter}: незакрытый fenced-блок")
        check_links(chapter, errors)

    check_numbering(errors)

    for path in sorted((ROOT / "assets" / "slides").glob("*.png")):
        try:
            width, height = png_size(path)
        except ValueError:
            errors.append(f"{path.relative_to(ROOT)}: повреждённый PNG")
            continue
        if width < 1200 or height < 675 or width / height < 1.5:
            errors.append(
                f"{path.relative_to(ROOT)}: недостаточное разрешение {width}×{height}"
            )

    for path in ROOT_DOCS:
        check_links(path, errors)

    generated = ROOT / "polnyy-tekst.md"
    generated_text = generated.read_text()
    if "АВТОМАТИЧЕСКИ СОБРАНО" not in generated_text.splitlines()[0]:
        errors.append("polnyy-tekst.md не помечен как автоматически собранный")
    header = (
        "<!-- АВТОМАТИЧЕСКИ СОБРАНО scripts/build_full_text.py. "
        "НЕ РЕДАКТИРОВАТЬ ВРУЧНУЮ. -->\n\n"
    )
    expected_text = header + "\n\n---\n\n".join(
        prepare(path.read_text()) for path in CHAPTERS
    ) + "\n"
    if generated_text != expected_text:
        errors.append(
            "polnyy-tekst.md рассинхронизирован; запустите scripts/build_full_text.py"
        )

    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print(
        "OK: 15 глав, нумерация, Mermaid, навигация, отсутствие растровых "
        "иллюстраций, слайды, локальные ссылки и polnyy-tekst.md проверены"
    )


if __name__ == "__main__":
    main()
