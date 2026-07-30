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
ROOT_DOCS = [ROOT / "README.md", ROOT / "ИСТОЧНИКИ.md"]
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
            images = IMAGE_RE.findall(text)
            expected = f"../assets/chapters/{number}/"
            if sum(path.startswith(expected) for path in images) != 2:
                errors.append(f"{chapter}: ожидаются ровно 2 иллюстрации главы")
            visual_summary = re.search(
                r"<!-- visual-summary:start -->(.*?)<!-- visual-summary:end -->",
                text,
                re.DOTALL,
            )
            if visual_summary is None:
                errors.append(f"{chapter}: отсутствует блок визуального конспекта")
            elif len(IMAGE_RE.findall(visual_summary.group(1))) != 1:
                errors.append(
                    f"{chapter}: в верхнем визуальном конспекте должна быть "
                    "ровно 1 иллюстрация"
                )
            image_matches = list(IMAGE_RE.finditer(text))
            if len(image_matches) == 2:
                first_line = text.count("\n", 0, image_matches[0].start()) + 1
                second_line = text.count("\n", 0, image_matches[1].start()) + 1
                if second_line - first_line < 40:
                    errors.append(
                        f"{chapter}: иллюстрации расположены слишком близко "
                        f"(строки {first_line} и {second_line})"
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

    chapter_images = sorted((ROOT / "assets" / "chapters").glob("*/*.png"))
    if len(chapter_images) != 30:
        errors.append(f"ожидаются 30 PNG-иллюстраций, найдено {len(chapter_images)}")
    for path in chapter_images:
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
        "OK: 15 глав, 30 PNG, Mermaid, навигация, локальные ссылки "
        "и polnyy-tekst.md проверены"
    )


if __name__ == "__main__":
    main()
