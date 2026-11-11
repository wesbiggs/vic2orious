"""Would a multicolour bitmap (160x200, 3 colours per cell + one background) with
X-expanded hires sprites beat today's hires conversion? Timing-free estimate.

For every photo and dither, img2c64 (PAL, Colodore) makes two pictures of the same scale:
hires 320 wide, and multicolour 160 wide in wide pixels (the photo squeezed to half width
first, so img2c64's PAL stretch gives wide pixels of 2 x PAR). Then:

  hires  the real converter (cell pairs, cover, timing): wrong pixels and what it shows;
         also "cover", its pairs' exact timing-free cover (wrong pixels with no timing)
  mc     the same cell search as the converter's (single and neighbour-pair moves, cost
         150 per uncovered pixel + 5 per span, no retask cost), choosing 3 colours per
         4x8 cell (from its 7 most common, the background excluded) and the background
         (each of the image's 3 most common colours tried); convert.cover in wide pixel
         units: an X-expanded sprite is a 24 wide pixel, single colour span. No timing.

Pixels the cover misses fall back to the nearest of their cell's colours. Printed per
photo: wrong pixels (% of the picture's pixels) and 3x3-blurred RMS error (RGB) of what
the C64 shows (mc doubled to 320 wide) vs the photo resized as img2c64 resizes it for
hires. Pictures are saved as build/analysis/mc/<photo>_<dither>_<hires|mc>.png.
See README.md.

    python analysis/mc_estimate.py [DITHER ...] [-- PHOTO ...]
        (default: none fs; kodim01, 03, 05, 15, 23)
"""
import importlib.util
import itertools
import os
import sys
import time

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vic2 import convert, timing  # noqa: E402
from vic2.palette import COLODORE_VICE_PAL, KNOWN  # noqa: E402

spec = importlib.util.spec_from_file_location("img2c64", os.path.join(ROOT, "tools", "img2c64.py"))
img2c64 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(img2c64)

args = sys.argv[1:]
if "--" in args:
    i = args.index("--")
    dithers, photos = args[:i], args[i + 1:]
else:
    dithers, photos = args, []
dithers = dithers or ["none", "fs"]
photos = photos or [os.path.join(ROOT, "images", "kodak-full", "kodim%s.png" % k)
                    for k in ("01", "03", "05", "15", "23")]
timing.set_standard("pal")
OUT = os.path.join(ROOT, "build", "analysis", "mc")
os.makedirs(OUT, exist_ok=True)

LOST_W = 150      # cost of a pixel no span covers (the converter's first ROW_WEIGHTS)
SPAN_W = 5        # cost of a span
NCAND = 7         # a cell's colour sets are drawn from its NCAND most common colours
NBG = 3           # backgrounds tried: the image's NBG most common colours
PAL = np.asarray(COLODORE_VICE_PAL, dtype=np.int64)


def blur_rms(a, b):
    a = np.asarray(a.filter(ImageFilter.BoxBlur(1)), dtype=np.float64)
    b = np.asarray(b.filter(ImageFilter.BoxBlur(1)), dtype=np.float64)
    return float(np.sqrt(((a - b) ** 2).mean()))


def rgb(rows):
    return Image.fromarray(PAL.astype(np.uint8)[np.array(rows)])


def indexed(out):
    w, h = out.size
    flat = [KNOWN[tuple(p)] for p in np.asarray(out).reshape(-1, 3).tolist()]
    return [flat[y * w:(y + 1) * w] for y in range(h)]


def nearest(c, cols):
    return min(cols, key=lambda d: int(((PAL[c] - PAL[d]) ** 2).sum()))


class Cells:
    """Cell colour search and timing-free cover for cells cw pixels wide holding k colours
    each plus bg (None: no shared colour)."""

    def __init__(self, img, cw, k):
        self.img, self.cw, self.k = img, cw, k
        self.h, self.w = len(img), len(img[0])
        self.cols = self.w // cw
        self.line_cells = []
        for y in range(self.h):
            cells = []
            for cx in range(self.cols):
                by_c = {}
                for x in range(cx * cw, cx * cw + cw):
                    by_c.setdefault(img[y][x], []).append(x)
                cells.append(tuple((c, tuple(xs)) for c, xs in by_c.items()))
            self.line_cells.append(cells)

    def spans_of(self, y, sets):
        by_c = {}
        for s, cell in zip(sets, self.line_cells[y]):
            for c, xs in cell:
                if c not in s:
                    by_c[c] = by_c[c] + xs if c in by_c else xs
        return convert.cover(tuple(by_c.items()), self.w, 8)

    def row_cost(self, cy, sets):
        cost = 0
        for y in range(cy * 8, cy * 8 + 8):
            sp, lost = self.spans_of(y, sets)
            cost += LOST_W * lost + SPAN_W * len(sp)
        return cost

    def choose_row(self, cy, bg):
        cands = []
        for cx in range(self.cols):
            cnt = {}
            for y in range(cy * 8, cy * 8 + 8):
                for x in range(cx * self.cw, cx * self.cw + self.cw):
                    c = self.img[y][x]
                    cnt[c] = cnt.get(c, 0) + 1
            cols = [c for c in sorted(cnt, key=lambda c: -cnt[c]) if c != bg][:NCAND]
            extra = () if bg is None else (bg,)
            if len(cols) <= self.k:
                cands.append([tuple(cols) + extra])
            else:
                cands.append([s + extra for s in itertools.combinations(cols, self.k)])
        sets = [c[0] for c in cands]
        best = self.row_cost(cy, sets)
        moves = [[(cx, p)] for cx in range(self.cols) for p in cands[cx] if len(cands[cx]) > 1]
        moves2 = [[(cx, p), (cx + 1, q)] for cx in range(self.cols - 1)
                  for p in cands[cx] for q in cands[cx + 1]
                  if len(cands[cx]) > 1 and len(cands[cx + 1]) > 1]
        stuck = False
        for _ in range(16):
            improved = False
            for mv in moves2 if stuck else moves:
                if all(sets[cx] == p for cx, p in mv):
                    continue
                old = [(cx, sets[cx]) for cx, _ in mv]
                for cx, p in mv:
                    sets[cx] = p
                c = self.row_cost(cy, sets)
                if c < best:
                    best, improved = c, True
                else:
                    for cx, p in old:
                        sets[cx] = p
            if not improved and stuck:
                break
            stuck = not improved
        return sets

    def run(self, bg):
        """(wrong pixels, shown picture) for background bg."""
        shown = [row[:] for row in self.img]
        wrong = 0
        for cy in range(self.h // 8):
            sets = self.choose_row(cy, bg)
            for y in range(cy * 8, cy * 8 + 8):
                spans, _ = self.spans_of(y, sets)
                done = {x for _, _, _, xs in spans for x in xs}
                for x in range(self.w):
                    s = sets[x // self.cw]
                    if self.img[y][x] not in s and x not in done:
                        shown[y][x] = nearest(self.img[y][x], s)
                        wrong += 1
        return wrong, shown


def multicolour(img):
    cnt = {}
    for row in img:
        for c in row:
            cnt[c] = cnt.get(c, 0) + 1
    best = None
    for bg in sorted(cnt, key=lambda c: -cnt[c])[:NBG]:
        convert.cover.cache_clear()
        convert.colour_cover.cache_clear()
        wrong, shown = Cells(img, 4, 3).run(bg)
        if best is None or wrong < best[0]:
            best = (wrong, shown, bg)
    return best


def line(*cols):
    print("%-10s %-6s %-6s wrong %5d (%4.1f%%)  rms %5.2f  %s" % cols, flush=True)


tot = {}
for path in photos:
    name = os.path.splitext(os.path.basename(path))[0]
    photo = img2c64.load(path)
    for d in dithers:
        dither = img2c64.parse_dither(d)
        t0 = time.time()
        hi = img2c64.convert(photo, "pal", dither, runs=None)
        w, h = hi.size
        ref = photo.resize((w, h), Image.Resampling.LANCZOS)
        img = indexed(hi)
        conv = convert.Converter(img, log=lambda *a: None)
        conv.run()
        shown = conv.render()
        wrong = sum(shown[y][x] != img[y][x] for y in range(h) for x in range(w))
        exact = sum(conv.spans_of(y, [conv.pairs[y >> 3][x >> 3] for x in range(0, w, 8)])[1]
                    for y in range(h))
        rgb(shown).save(os.path.join(OUT, "%s_%s_hires.png" % (name, d)))
        r_hi = (wrong, 100 * wrong / (w * h), blur_rms(rgb(shown), ref),
                "cover %d (%.1f%%)  %.0f s" % (exact, 100 * exact / (w * h), time.time() - t0))
        line(name, d, "hires", *r_hi)

        t0 = time.time()
        half = photo.resize((max(1, photo.width // 2), photo.height), Image.Resampling.LANCZOS)
        mc = img2c64.convert(half, "pal", dither, box=(160, 200), runs=None)
        mimg = indexed(mc)
        mw, mh = mc.size
        mwrong, mshown, bg = multicolour(mimg)
        big = rgb(mshown).resize((mw * 2, mh), Image.Resampling.NEAREST)
        if big.size != ref.size:
            ref2 = photo.resize(big.size, Image.Resampling.LANCZOS)
        else:
            ref2 = ref
        big.save(os.path.join(OUT, "%s_%s_mc.png" % (name, d)))
        r_mc = (mwrong, 100 * mwrong / (mw * mh), blur_rms(big, ref2),
                "bg %d, %dx%d  %.0f s" % (bg, mw, mh, time.time() - t0))
        line(name, d, "mc", *r_mc)
        for key, r in (((d, "hires"), r_hi), ((d, "mc"), r_mc)):
            t = tot.setdefault(key, np.zeros(3))
            t += r[:3]
n = len(photos)
for (d, mode), t in tot.items():
    line("mean", d, mode, t[0] / n, t[1] / n, t[2] / n, "")
