"""Перевірка фото на білий фон (вимога Prom): смуга ~2.5% по периметру,
фото «біле», якщо >= 95% пікселів смуги мають R, G, B >= 240."""

import sys

from PIL import Image

BORDER = 0.025
MIN_WHITE = 0.95
LEVEL = 240


def is_white_background(path_or_file):
    with Image.open(path_or_file) as im:
        im = im.convert("RGB")
        w, h = im.size
        bw, bh = max(1, int(w * BORDER)), max(1, int(h * BORDER))
        px = im.load()
        total = white = 0
        for y in range(h):
            xs = range(w) if (y < bh or y >= h - bh) else [*range(bw), *range(w - bw, w)]
            for x in xs:
                r, g, b = px[x, y]
                total += 1
                white += r >= LEVEL and g >= LEVEL and b >= LEVEL
        return white / total >= MIN_WHITE


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(("white  " if is_white_background(p) else "NOT    ") + p)
