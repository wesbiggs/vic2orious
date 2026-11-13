"""Thumbnails: a picture shrunk into one sprite's 24x21 pixels, in at most 8 colours over a
background colour, so that up to 8 hires sprites on top of each other, all at the same
position and one colour each, show it exactly (no raster tricks).

The data (docs/v2i-format.md, "Thumbnail"), as stored in a .v2i and, hex encoded, in a PNG
text chunk TEXT_KEY that tools/img2c64.py writes:

    width, height       the picture's size in pixels (at most 24 x 21), centred in the
                        24x21 sprite area; the rest is background
    background          colour of the pixels no sprite covers
    n                   number of sprites (0-8)
    n times: colour, 63 bytes of sprite data (3 bytes a line, 21 lines)

Pure Python (Pillow): img2c64 imports it, and so does the build, which makes a thumbnail
from the PNG itself when img2c64 did not put one in.
"""

from PIL import Image, ImageEnhance

W, H = 24, 21                 # one sprite
SPRITES = 8
TEXT_KEY = "vic2orious-thumb"  # PNG tEXt chunk: the thumbnail data in hex
BG = 0                        # background: black, as the screen around the images
SATURATE = 1.5                # the shrunk picture's saturation is raised this much before
                              # its colours are chosen: averaging greys the colours, and the
                              # nearest palette colours were browns and greys (Nov 2026,
                              # Kodak photos: 1.3-1.6 keep a parrot's green, 2 turns skin
                              # green; dithering 24 pixels only added noise)


def size(w, h):
    """Thumbnail size of a w x h picture (screen pixels): fitted into 24x21, never
    enlarged. A 320x200 picture gives 24x15."""
    s = min(W / w, H / h, 1.0)
    return max(1, min(W, round(w * s))), max(1, min(H, round(h * s)))


def _d2(p, q):
    return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2


def choose(px, pal, bg=BG, colours=SPRITES):
    """The colours (palette indices) for pixels px ((r, g, b) list) against pal (16 (r, g,
    b)): bg and at most `colours` others. Backward elimination: from all 16, drop the
    colour whose loss raises the error least, until few enough are left."""
    keep = set(range(len(pal)))
    cost = {}

    def err(cs):
        key = frozenset(cs)
        if key not in cost:
            cost[key] = sum(min(_d2(p, pal[c]) for c in cs) for p in px)
        return cost[key]
    while len(keep) > colours + 1:
        drop = min((c for c in keep if c != bg), key=lambda c: (err(keep - {c}), c))
        keep.discard(drop)
    return sorted(keep)


def make(img, screen_size, pal, bg=BG, colours=SPRITES):
    """Thumbnail bytes of img (RGB, any size), shown at screen_size (screen pixels: the
    picture as the C64 shows it, so its pixel aspect comes from there); colours chosen
    against pal (16 (r, g, b), the colours as the screen shows them)."""
    tw, th = size(*screen_size)
    small = img.convert("RGB").resize((tw, th), Image.Resampling.BOX)
    small = ImageEnhance.Color(small).enhance(SATURATE)
    px = [small.getpixel((x, y)) for y in range(th) for x in range(tw)]
    cs = choose(px, pal, bg, colours)
    idx = [min(cs, key=lambda c: (_d2(p, pal[c]), c)) for p in px]
    x0, y0 = (W - tw) // 2, (H - th) // 2
    used = sorted({c for c in idx if c != bg}, key=lambda c: (-idx.count(c), c))
    out = bytearray((tw, th, bg, len(used)))
    for c in used:
        spr = bytearray(63)
        for i, v in enumerate(idx):
            if v == c:
                x, y = x0 + i % tw, y0 + i // tw
                spr[y * 3 + x // 8] |= 0x80 >> (x % 8)
        out += bytes((c,)) + spr
    return bytes(out)


def parse(data):
    """(width, height, background, [(colour, 63 bytes)]) of thumbnail bytes; asserts they
    are well formed."""
    assert len(data) >= 4, "thumbnail too short"
    tw, th, bg, n = data[:4]
    assert 1 <= tw <= W and 1 <= th <= H and bg < 16 and n <= SPRITES, "bad thumbnail header"
    assert len(data) == 4 + 64 * n, "thumbnail length"
    sprites = [(data[4 + 64 * i], data[5 + 64 * i:4 + 64 * (i + 1)]) for i in range(n)]
    return tw, th, bg, sprites


def pixels(data):
    """The 24x21 sprite area as the C64 shows it: rows of palette indices (sprite 0 in
    front, as the VIC-II draws it; make never sets a pixel in two sprites)."""
    _, _, bg, sprites = parse(data)
    out = [[bg] * W for _ in range(H)]
    for c, spr in reversed(sprites):
        for y in range(H):
            for x in range(W):
                if spr[y * 3 + x // 8] & (0x80 >> (x % 8)):
                    out[y][x] = c
    return out


def to_text(data):
    return data.hex()


def from_png(path):
    """The thumbnail img2c64 put in the PNG, or None."""
    t = getattr(Image.open(path), "text", {}).get(TEXT_KEY)
    if not t:
        return None
    data = bytes.fromhex("".join(t.split()))
    parse(data)
    return data


def save_png(path, data, palette, scale=8):
    """The thumbnail as a PNG (palette: 16 (r, g, b)), scale times enlarged."""
    rows = pixels(data)
    im = Image.new("RGB", (W, H))
    im.putdata([palette[c] for row in rows for c in row])
    im.resize((W * scale, H * scale), Image.Resampling.NEAREST).save(path)
