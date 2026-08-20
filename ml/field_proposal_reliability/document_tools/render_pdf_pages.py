"""Render every PDF page to a PNG for Word layout inspection."""

from __future__ import annotations

import argparse
from pathlib import Path

import pypdfium2 as pdfium


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--scale", type=float, default=2.2)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(str(args.pdf))
    stem = args.pdf.stem
    for index in range(len(document)):
        page = document[index]
        bitmap = page.render(scale=args.scale)
        image = bitmap.to_pil()
        output = args.output_dir / f"{stem}-page-{index + 1:02d}.png"
        image.save(output)
        print(output)


if __name__ == "__main__":
    main()
