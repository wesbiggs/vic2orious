"""Score img2c64 settings: wrong pixels after conversion and blurred RMS error vs the photo.

For every photo and setting: img2c64 (PAL) makes the C64 picture, the converter (PAL,
upper left) converts it. Printed per photo:

  wrong      pixels the converter gets wrong (vs the img2c64 picture)
  rms dith   3x3-blurred RMS error (RGB, 0-255) of the img2c64 picture vs the photo,
             resized as img2c64 resizes it
  rms c64    the same for what the C64 shows (the converter's output)

What the C64 shows is saved as build/analysis/dither/<photo>_<setting>.png, the resized
photo as <photo>_photo.png.

A setting is MODE[:K][,c=S][,l=N|none] (img2c64's -d, -c, -l), e.g. hybrid:90,c=0.6,l=6; also
spread=X and clamp=X|none, which replace HYBRID_SPREAD and HYBRID_CLAMP.
See README.md.

    python analysis/dither_score.py SETTING [PHOTO ...]   (default: kodim01, 03, 05, 15, 23)
"""
import importlib.util
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vic2 import convert, timing  # noqa: E402
from vic2.palette import COLODORE_VICE_PAL, KNOWN  # noqa: E402

spec = importlib.util.spec_from_file_location("img2c64", os.path.join(ROOT, "tools", "img2c64.py"))
img2c64 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(img2c64)

setting = sys.argv[1]
photos = sys.argv[2:] or [os.path.join(ROOT, "images", "kodak-full", "kodim%s.png" % k)
                          for k in ("01", "03", "05", "15", "23")]
mode, *opts = setting.split(",")
opts = dict(o.split("=") for o in opts)
dither = img2c64.parse_dither(mode)
chroma = float(opts.get("c", 1.0))
runs = img2c64.HYBRID_RUNS if "l" not in opts else None if opts["l"] == "none" else int(opts["l"])
if "spread" in opts:
    img2c64.HYBRID_SPREAD = float(opts["spread"])
if "clamp" in opts:
    img2c64.HYBRID_CLAMP = None if opts["clamp"] == "none" else float(opts["clamp"])
timing.set_standard("pal")
OUT = os.path.join(ROOT, "build", "analysis", "dither")
os.makedirs(OUT, exist_ok=True)


def blur_rms(a, b):
    a = np.asarray(a.filter(ImageFilter.BoxBlur(1)), dtype=np.float64)
    b = np.asarray(b.filter(ImageFilter.BoxBlur(1)), dtype=np.float64)
    return float(np.sqrt(((a - b) ** 2).mean()))


def rgb(rows):
    a = np.asarray(COLODORE_VICE_PAL, dtype=np.uint8)[np.array(rows)]
    return Image.fromarray(a)


tot = np.zeros(4)
for path in photos:
    photo = img2c64.load(path)
    out = img2c64.convert(photo, "pal", dither, chroma=chroma, runs=runs)
    w, h = out.size
    ref = photo.resize((w, h), Image.Resampling.LANCZOS)
    flat = [KNOWN[tuple(p)] for p in np.asarray(out).reshape(-1, 3).tolist()]
    img = [flat[y * w:(y + 1) * w] for y in range(h)]
    conv = convert.Converter(img, log=lambda *a: None)
    conv.run()
    shown = conv.render()
    wrong = sum(shown[y][x] != img[y][x] for y in range(h) for x in range(w))
    name = os.path.splitext(os.path.basename(path))[0]
    rgb(shown).save(os.path.join(OUT, "%s_%s.png" % (name, setting)))
    ref.save(os.path.join(OUT, "%s_photo.png" % name))
    r = (wrong, 100 * wrong / (w * h), blur_rms(out, ref), blur_rms(rgb(shown), ref))
    tot += r
    print("%-24s %-10s wrong %5d (%4.1f%%)  rms dith %5.2f  rms c64 %5.2f"
          % ((setting, name) + r), flush=True)
n = len(photos)
print("%-24s %-10s wrong %5d (%4.1f%%)  rms dith %5.2f  rms c64 %5.2f"
      % (setting, "mean", tot[0] / n, tot[1] / n, tot[2] / n, tot[3] / n))
