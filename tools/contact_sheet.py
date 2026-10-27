"""Tile rendered PNG pages into one sheet for quick visual review."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw


def sheet(pages: list[Path], out: Path, cols: int = 2, width: int = 640):
    imgs = [Image.open(p).convert("RGB") for p in pages]
    h = int(width * imgs[0].height / imgs[0].width)
    rows = (len(imgs) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * width + (cols + 1) * 8, rows * h + (rows + 1) * 8), "#888")
    for i, im in enumerate(imgs):
        x, y = 8 + (i % cols) * (width + 8), 8 + (i // cols) * (h + 8)
        canvas.paste(im.resize((width, h), Image.LANCZOS), (x, y))
        ImageDraw.Draw(canvas).text((x + 4, y + 4), str(i + 1), fill="#f0f")
    canvas.save(out)


if __name__ == "__main__":
    src = Path(sys.argv[1])
    sheet(sorted(src.glob("page-*.png")), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 2)
