"""Commodore 64 palette (Pepto PAL) and image loading helpers."""

from PIL import Image

PEPTO = [
    (0x00, 0x00, 0x00),  # 0 black
    (0xFF, 0xFF, 0xFF),  # 1 white
    (0x68, 0x37, 0x2B),  # 2 red
    (0x70, 0xA4, 0xB2),  # 3 cyan
    (0x6F, 0x3D, 0x86),  # 4 purple
    (0x58, 0x8D, 0x43),  # 5 green
    (0x35, 0x28, 0x79),  # 6 blue
    (0xB8, 0xC7, 0x6F),  # 7 yellow
    (0x6F, 0x4F, 0x25),  # 8 orange
    (0x43, 0x39, 0x00),  # 9 brown
    (0x9A, 0x67, 0x59),  # 10 light red
    (0x44, 0x44, 0x44),  # 11 dark grey
    (0x6C, 0x6C, 0x6C),  # 12 grey
    (0x9A, 0xD2, 0x84),  # 13 light green
    (0x6C, 0x5E, 0xB5),  # 14 light blue
    (0x95, 0x95, 0x95),  # 15 light grey
]


def nearest(rgb, palette=PEPTO):
    r, g, b = rgb[:3]
    return min(range(len(palette)),
               key=lambda i: (palette[i][0] - r) ** 2 + (palette[i][1] - g) ** 2 + (palette[i][2] - b) ** 2)


def load_indexed(path, palette=PEPTO):
    """Load an image and map every pixel to a palette index; returns (w, h, rows)."""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()
    cache = {}
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            c = px[x, y]
            if c not in cache:
                cache[c] = nearest(c, palette)
            row.append(cache[c])
        rows.append(row)
    return w, h, rows


def save_indexed(path, rows, palette=PEPTO, scale=1):
    h = len(rows)
    w = len(rows[0])
    im = Image.new("RGB", (w, h))
    im.putdata([palette[c] for row in rows for c in row])
    if scale != 1:
        im = im.resize((w * scale, h * scale), Image.NEAREST)
    im.save(path)


def load_vpl(path):
    pal = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            pal.append(tuple(int(p, 16) for p in parts[:3]))
    return pal[:16]
