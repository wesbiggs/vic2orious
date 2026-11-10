"""Scoring img2c64 pictures for the dither recommender (img2c64 without -d, and
analysis/dither_rank.py).

An img2c64 output goes through the converter (upper left, like dither_rank; the build's
placement can move a few spans); what the C64 shows is compared with the source, resized
to the same size:

  rms    3x3-blurred RMS error (RGB, 0-255); lower is better
  ssim   mean SSIM of the luma (Rec. 601; 11x11 Gaussian window, sigma 1.5, the usual
         constants), of the blurred pictures (or unblurred: blurred=False); 1 is identical
  color  mean distance of the blurred pictures in CIELAB's a*b* plane (chroma and hue, not
         lightness); lower is better

rank scales each metric over the candidates, best 1 and worst 0, and orders them by the
weighted mean (WEIGHTS: rms, ssim, color). Why these metrics and weights:
analysis/README.md (dither_rank.py).
"""
import numpy as np
from PIL import Image, ImageFilter

from . import convert, timing
from .palette import COLODORE_VICE_NTSC, COLODORE_VICE_PAL, KNOWN

METRICS = ("rms", "ssim", "color")
HIGHER = {"rms": False, "ssim": True, "color": False}
WEIGHTS = (0.0, 1.0, 1.0)
# img2c64 settings tried: (name, -d, -l)
CANDIDATES = [("none", "none", None), ("fs", "fs", None), ("fs:0.75", "fs:0.75", None),
              ("fs:0.5", "fs:0.5", None), ("atkinson", "atkinson", None),
              ("atkinson:0.75", "atkinson:0.75", None), ("hybrid", "hybrid", 8),
              ("hybrid,l=6", "hybrid", 6), ("hybrid,l=none", "hybrid", None)]


def shown(out, system, view=None):
    """(what the C64 shows, as RGB, and the number of wrong pixels) for an img2c64 output
    (RGB, colours of COLODORE_VICE_PAL/NTSC). system: "pal", "ntsc" or None (PAL). view:
    16 (r, g, b) to show it in (img2c64 -P), else VICE's Colodore for the system."""
    system = system or "pal"
    timing.set_standard(system)
    w, h = out.size
    flat = [KNOWN[tuple(p)] for p in np.asarray(out).reshape(-1, 3).tolist()]
    img = [flat[y * w:(y + 1) * w] for y in range(h)]
    conv = convert.Converter(img, log=lambda *a: None)
    conv.run()
    rows = conv.render()
    wrong = sum(rows[y][x] != img[y][x] for y in range(h) for x in range(w))
    pal = view or (COLODORE_VICE_PAL if system == "pal" else COLODORE_VICE_NTSC)
    return Image.fromarray(np.asarray(pal, dtype=np.uint8)[np.array(rows)]), wrong


def blur(a):
    return a.filter(ImageFilter.BoxBlur(1))


def rms(a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    return float(np.sqrt(((a - b) ** 2).mean()))


def lab(img):
    """CIELAB (D65) of an sRGB picture, as an (h, w, 3) array of L*, a*, b*."""
    a = np.asarray(img, dtype=np.float64) / 255
    a = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]])
    xyz = a @ m.T / np.array([0.95047, 1.0, 1.08883])
    e = 6 / 29
    f = np.where(xyz > e ** 3, np.cbrt(xyz), xyz / (3 * e * e) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], -1)


def color(a, b):
    """Mean distance of the two pictures in the a*b* plane."""
    d = lab(a)[..., 1:] - lab(b)[..., 1:]
    return float(np.sqrt((d ** 2).sum(-1)).mean())


def gauss(a, sigma=1.5, radius=5):
    """Separable Gaussian filter, edges reflected."""
    k = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    k /= k.sum()
    for axis in (0, 1):
        p = np.pad(a, [(radius, radius) if i == axis else (0, 0) for i in (0, 1)], "reflect")
        n = a.shape[axis]
        a = sum(w * (p[i:i + n] if axis == 0 else p[:, i:i + n]) for i, w in enumerate(k))
    return a


def ssim(a, b):
    """Mean SSIM (Wang et al. 2004) of the two pictures' luma."""
    luma = np.array([0.299, 0.587, 0.114])
    x = np.asarray(a, dtype=np.float64) @ luma
    y = np.asarray(b, dtype=np.float64) @ luma
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mx, my = gauss(x), gauss(y)
    vx = gauss(x * x) - mx * mx
    vy = gauss(y * y) - my * my
    cxy = gauss(x * y) - mx * my
    s = ((2 * mx * my + c1) * (2 * cxy + c2)) / ((mx * mx + my * my + c1) * (vx + vy + c2))
    return float(s.mean())


def scores(c64, ref, blurred=True):
    """The metrics of c64 (what the C64 shows) against ref (the source at its size)."""
    bc, br = blur(c64), blur(ref)
    a, b = (bc, br) if blurred else (c64, ref)
    return {"rms": rms(bc, br), "ssim": ssim(a, b), "color": color(bc, br)}


def rank(results, weights=WEIGHTS):
    """Adds each result's scaled metrics (best 1, worst 0) and their weighted mean, `score`;
    returns the results best first."""
    for m in METRICS:
        vals = [r[m] for r in results]
        lo, hi = min(vals), max(vals)
        for r in results:
            t = 1.0 if hi == lo else (r[m] - lo) / (hi - lo)
            r["n" + m] = t if HIGHER[m] else 1 - t
    total = sum(weights)
    for r in results:
        r["score"] = sum(w * r["n" + m] for w, m in zip(weights, METRICS)) / total
    return sorted(results, key=lambda r: -r["score"])


def parse_weights(v):
    """RMS,SSIM,COLOR: three numbers >= 0, not all 0. Raises ValueError."""
    w = [float(x) for x in v.strip("{}() ").split(",")]
    if len(w) != 3 or min(w) < 0 or sum(w) == 0:
        raise ValueError("takes three weights >= 0, not all 0, RMS,SSIM,COLOR, e.g. 0,1,1")
    return w
