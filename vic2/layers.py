"""How the sprites are used in a conversion: build/<system>/<name>_sprites.png.

Four panels (2x2, scaled 3x like _compare.png), all in image coordinates:

  bitmap alone            | sprite pixels alone
  ------------------------+---------------------------------------
  sprites by number       | heat map, and sprites in use per line

- Bitmap alone: what the screen shows with the sprites off (each cell's two colours;
  multicolour: its three and the background). Multicolour panels are in wide pixels.
- Sprite pixels alone: the colours the sprites paint (topmost sprite wins, as on the
  VIC), on a grey checkerboard where no sprite paints.
- Sprites by number: each sprite's 24 pixel window on every line in its own hue
  (SPRITE_HUES), bright where it paints, dim where it is positioned but transparent.
  Sprite 0 is on top.
- Heat map: sprite-painted pixels per 8x8 cell, black (none) through blue, cyan, yellow
  to red (all 64; multicolour cells, 4x8 wide pixels, count double). The bar to its right is the number of sprites painting on each line
  (0-8, 3 px each), with a red tick right of it on lines that are not pixel perfect.
"""

from PIL import Image

from .palette import PEPTO

SPRITE_HUES = [(255, 64, 64), (255, 160, 32), (240, 240, 48), (64, 224, 64),
               (48, 208, 224), (64, 112, 255), (176, 80, 255), (255, 96, 208)]
CHECKER = ((48, 48, 48), (64, 64, 64))
GAP = 8
BAR = 30                    # margin, 8 sprites x 3 px, margin, bad line tick
SCALE = 3
HEAT = [(0, (0, 0, 0)), (1, (24, 32, 160)), (16, (0, 200, 220)), (40, (240, 230, 40)),
        (64, (255, 32, 32))]


def heat(n):
    """Colour of a cell with n (0-64) sprite pixels."""
    if n == 0:
        return HEAT[0][1]
    for (a, ca), (b, cb) in zip(HEAT[1:], HEAT[2:]):
        if n <= b:
            t = (n - a) / (b - a)
            return tuple(int(round(p + t * (q - p))) for p, q in zip(ca, cb))
    return HEAT[-1][1]


def windows(conv):
    """Per line y: [(sprite, xstart, colour, bits)] for the sprites set up on that line."""
    g = conv.g
    out = [[] for _ in range(g.h)]
    for s in range(8):
        for r, bits in conv.sdata[s].items():
            y = r - g.raster0
            if 0 <= y < g.h:
                xs, c = conv.line_cfg[s][r]
                out[y].append((s, xs, c, bits))
    return out


def sprite_layers(conv, path):
    """Write the four panels for a converted (run) Converter to path."""
    g = conv.g
    w, h = g.w, g.h
    bits = conv.bitmap()
    cov = conv.sprite_cover()
    wins = windows(conv)

    cw = g.cw

    def bmp_colour(y, x):
        p = conv.pairs[y >> 3][x // cw]
        if g.mc:
            return (p[3], p[0], p[1], p[2])[bits[y][x]]
        return p[0 if bits[y][x] else 1]
    bmp = Image.new("RGB", (w, h))
    bmp.putdata([PEPTO[bmp_colour(y, x)] for y in range(h) for x in range(w)])

    spr = Image.new("RGB", (w, h))
    spr.putdata([PEPTO[cov[y][x]] if cov[y][x] is not None
                 else CHECKER[((x >> 2) + (y >> 2)) & 1]
                 for y in range(h) for x in range(w)])

    num = [[(0, 0, 0)] * w for _ in range(h)]
    for y in range(h):
        for s, xs, _, b in sorted(wins[y], reverse=True):     # sprite 0 drawn last: on top
            hue = SPRITE_HUES[s]
            for i in range(24):
                x = xs + i
                if 0 <= x < w:
                    on = b & (1 << (23 - i))
                    num[y][x] = hue if on else tuple(v // 4 for v in hue)
    nums = Image.new("RGB", (w, h))
    nums.putdata([c for row in num for c in row])

    cells = [[0] * g.cols for _ in range(g.rows)]
    for y in range(h):
        for x in range(w):
            if cov[y][x] is not None:
                cells[y >> 3][x // cw] += 8 // cw
    hm = Image.new("RGB", (w + BAR, h), (24, 24, 24))
    hm.putdata([heat(cells[y >> 3][x // cw]) if x < w else (24, 24, 24)
                for y in range(h) for x in range(w + BAR)])
    px = hm.load()
    for y in range(h):
        n = sum(1 for _, _, _, b in wins[y] if b)
        for x in range(w + 2, w + 2 + 3 * n):
            px[x, y] = (160, 160, 160)
        if y in conv.bad_lines:
            px[w + 27, y] = px[w + 28, y] = (255, 0, 64)

    out = Image.new("RGB", (2 * w + GAP + BAR, 2 * h + GAP), (40, 40, 40))
    out.paste(bmp, (0, 0))
    out.paste(spr, (w + GAP, 0))
    out.paste(nums, (0, h + GAP))
    out.paste(hm, (w + GAP, h + GAP))
    out.resize((out.width * SCALE, out.height * SCALE), Image.NEAREST).save(path)
    return cells
