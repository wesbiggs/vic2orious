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

Making one is web/js/thumb.js (through vic2/engine.py); this reads them: from img2c64's
PNG, to check and to draw them.
"""

from PIL import Image

W, H = 24, 21                 # one sprite
SPRITES = 8
TEXT_KEY = "vic2orious-thumb"  # PNG tEXt chunk: the thumbnail data in hex


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
    front, as the VIC-II draws it; web/js/thumb.js never sets a pixel in two sprites)."""
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
