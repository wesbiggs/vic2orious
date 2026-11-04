"""Wrong pixels vs the source for v2i, retropixels AFLI and pynuvie NUFLI.

Each source (C64 colours, up to 296x200) is converted by vic2orious as it is, and placed at
x = 24 (right of the FLI bug columns), y = 0 on a black 320x200 canvas, drawn in Pepto, for
the FLI tools. Only the source's own area is scored. See README.md.

    python analysis/compare.py [SRC_DIR]     (default build/analysis/src)
"""
import glob
import os
import shlex
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vic2 import build, timing  # noqa: E402
from vic2.palette import PEPTO, load_indexed  # noqa: E402

from nuvie import _clean, _flibug  # noqa: E402
from nuvie.nufli import NufliImage  # noqa: E402
from nuvie.palette import C64_PALETTE  # noqa: E402

WORK = os.path.join(ROOT, "build", "analysis")
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(WORK, "src")
RETROPIXELS = shlex.split(os.environ.get("RETROPIXELS", "retropixels"))
X0 = 24

timing.set_standard("pal")
build.BUILD = os.path.join(WORK, "v2i")
OUT = os.path.join(WORK, "out")
os.makedirs(build.BUILD, exist_ok=True)
os.makedirs(OUT, exist_ok=True)


def nearest_rows(im, pal):
    a = np.asarray(im.convert("RGB"), dtype=np.int64)
    p = np.asarray(pal, dtype=np.int64)
    return ((a[:, :, None, :] - p[None, None]) ** 2).sum(-1).argmin(-1)


def wrong(src, got):
    h, w = src.shape
    return int((got[:h, X0:X0 + w] != src).sum())


rows = []
for path in sorted(glob.glob(os.path.join(SRC, "*.png"))):
    name = os.path.splitext(os.path.basename(path))[0]
    w, h, idx = load_indexed(path)
    assert w <= 320 - X0 and h <= 200, "%s: %dx%d, at most 296x200" % (name, w, h)
    src = np.array(idx)
    inf = build.convert_image(path, log=lambda *a: None, centre=True)
    v2i = inf["wrong_px"]

    canvas = np.zeros((200, 320), dtype=np.int64)
    canvas[:h, X0:X0 + w] = src
    cpath = os.path.join(OUT, name + "-canvas.png")
    Image.fromarray(np.asarray(PEPTO, dtype=np.uint8)[canvas]).save(cpath)

    # retropixels hires FLI (AFLI), no dither, no colour space conversion
    rpout = os.path.join(OUT, name + "-afli.png")
    subprocess.run(RETROPIXELS + ["-m", "fli", "-h", "-r", "0", "-p", "pepto", "-c", "rgb",
                                  "-s", "none", "-f", "png", "--overwrite", "-o", rpout, cpath],
                   check=True, capture_output=True)
    rp_img = Image.open(rpout)
    assert rp_img.size == (320, 200), rp_img.size
    afli = wrong(src, nearest_rows(rp_img, PEPTO))

    # pynuvie NUFLI: default encode, and texture=0 (flat, lowest error)
    pimg = Image.fromarray(np.asarray(C64_PALETTE, dtype=np.uint8)[canvas])
    nuf = NufliImage.from_image(pimg)
    nufli = wrong(src, np.array(nuf.decode_indices()))
    body = _clean.encode_clean(np.asarray(pimg), texture=0.0)
    _flibug.encode_flibug(pimg, body, has_main=True)
    nflat = NufliImage(bytes(body))
    nufli0 = wrong(src, np.array(nflat.decode_indices()))
    nflat.to_image().save(os.path.join(OUT, name + "-nufli0.png"))
    nuf.to_image().save(os.path.join(OUT, name + "-nufli.png"))

    rows.append((name, w * h, v2i, afli, nufli, nufli0))
    print("%-14s %6d  v2i %5d  afli %5d  nufli %5d  nufli(t=0) %5d" % rows[-1], flush=True)

print()
print("| image | pixels | v2i | AFLI (retropixels) | NUFLI (pynuvie) | NUFLI texture=0 |")
print("|---|---|---|---|---|---|")
for n, px, *v in rows:
    print("| %s | %d | " % (n, px) + " | ".join("%d (%.1f%%)" % (x, 100 * x / px) for x in v) + " |")
