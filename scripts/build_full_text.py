#!/usr/bin/env python3
"""Собирает polnyy-tekst.md из глав и нормализует относительные ссылки."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAPTERS = ROOT / "главы"
OUTPUT = ROOT / "polnyy-tekst.md"
NAV_RE = re.compile(
    r"\n?<!-- chapter-nav:start -->.*?<!-- chapter-nav:end -->\n?",
    flags=re.DOTALL,
)


def prepare(text: str) -> str:
    text = NAV_RE.sub("\n", text)
    text = text.replace("../assets/", "assets/")
    text = text.replace("../ИСТОЧНИКИ.md", "ИСТОЧНИКИ.md")
    text = text.replace("../README.md", "README.md")
    return text.strip()


def main() -> None:
    files = sorted(CHAPTERS.glob("[0-9][0-9]-*.md"))
    if not files:
        raise SystemExit("Главы не найдены")

    header = (
        "<!-- АВТОМАТИЧЕСКИ СОБРАНО scripts/build_full_text.py. "
        "НЕ РЕДАКТИРОВАТЬ ВРУЧНУЮ. -->\n\n"
    )
    body = "\n\n---\n\n".join(prepare(path.read_text()) for path in files)
    OUTPUT.write_text(header + body + "\n")
    print(f"Собрано {len(files)} файлов: {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
