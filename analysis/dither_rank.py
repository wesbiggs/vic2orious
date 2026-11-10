"""Rank img2c64 dither settings for one picture by weighted blurred RMS, SSIM and colour error.

The metrics, their scaling and weights are vic2/dither_pick.py's, which img2c64 uses to
pick a dither when it is given no -d. Every setting goes through img2c64 (as `-a pal` or
`-a ntsc`) and the converter (upper left); what the C64 shows is scored against the photo, resized as img2c64 resizes it:

  rms    3x3-blurred RMS error (RGB, 0-255), as dither_score.py's `rms c64`; lower is better
  ssim   mean SSIM of the luma (Rec. 601; 11x11 Gaussian window, sigma 1.5, the usual
         constants), unblurred; 1 is identical
  color  mean colour error of the 3x3-blurred pictures: the distance in CIELAB's a*b*
         plane (chroma and hue, not lightness), sRGB D65; lower is better

With --blur, SSIM is measured on the same 3x3-blurred pictures as rms, so dither noise
counts as little as it does there.

SSIM only sees lightness, so on its own it prefers settings that turn coloured areas
grey (a weak error diffusion never builds up enough error to leave the nearest grey).
`color` charges for that. SSIM on colour channels did not: on YCbCr (and a signed a*b*
variant) it counts the dither's colour speckle as structure and preferred `none` even
more.

There is no PSNR: on the blurred pictures it is rms on a log scale (20 log10(255 / rms)),
and on the unblurred ones it ranked the settings as unblurred SSIM does (kodim12 and
kodim23: rank correlation 0.98 and 1.00; both measure how little a setting dithers).

Each metric is scaled over the settings tried, best 1 and worst 0, and the settings are
ranked by the weighted mean. So the combined score says how a setting does against the
others in this run, not on an absolute scale: adding or removing a setting can reorder
the rest. Weights are RMS,SSIM,COLOR: 1,2,1 counts SSIM twice, 0,1,1 ignores RMS. The
default, 0,1,1 with --blur, picked the settings that looked best on kodim05, 12 and 23.

A setting is written as for dither_score.py: MODE[:K][,c=S][,l=N|none][,spread=X]
[,clamp=X|none]. Without -s the settings are DEFAULT below. What the C64 shows is saved
as build/analysis/rank/<photo>_<setting>.png, the resized photo as <photo>_photo.png.

    python analysis/dither_rank.py PHOTO [-w RMS,SSIM,COLOR] [-s SETTING ...] [--blur] [--ntsc] [-j N]
"""
import argparse
import importlib.util
import os
import sys
from concurrent.futures import ProcessPoolExecutor

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vic2 import dither_pick  # noqa: E402

spec = importlib.util.spec_from_file_location("img2c64", os.path.join(ROOT, "tools", "img2c64.py"))
img2c64 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(img2c64)

DEFAULT = [name for name, _, _ in dither_pick.CANDIDATES]
OUT = os.path.join(ROOT, "build", "analysis", "rank")
SPREAD, CLAMP = img2c64.HYBRID_SPREAD, img2c64.HYBRID_CLAMP


def parse_setting(setting):
    """(dither, chroma, runs, spread, clamp) from MODE[:K][,c=S][,l=N|none][,spread=X][,clamp=X]."""
    mode, *opts = setting.split(",")
    opts = dict(o.split("=") for o in opts)
    unknown = set(opts) - {"c", "l", "spread", "clamp"}
    if unknown:
        raise ValueError("%s: unknown option %s" % (setting, ", ".join(sorted(unknown))))
    runs = img2c64.HYBRID_RUNS if "l" not in opts else None if opts["l"] == "none" else int(opts["l"])
    clamp = CLAMP if "clamp" not in opts else None if opts["clamp"] == "none" else float(opts["clamp"])
    return (img2c64.parse_dither(mode), float(opts.get("c", 1.0)), runs,
            float(opts.get("spread", SPREAD)), clamp)


def score(path, setting, system, blurred=False):
    """Convert the photo with one setting; the scores and wrong pixels of what the C64 shows."""
    dither, chroma, runs, img2c64.HYBRID_SPREAD, img2c64.HYBRID_CLAMP = parse_setting(setting)
    photo = img2c64.load(path)
    out = img2c64.convert(photo, system, dither, chroma=chroma, runs=runs)
    w, h = out.size
    ref = photo.resize((w, h), Image.Resampling.LANCZOS)
    c64, wrong = dither_pick.shown(out, system)
    name = os.path.splitext(os.path.basename(path))[0]
    c64.save(os.path.join(OUT, "%s_%s.png" % (name, setting)))
    ref.save(os.path.join(OUT, "%s_photo.png" % name))
    r = {"setting": setting, "wrong": wrong, "pct": 100 * wrong / (w * h)}
    r.update(dither_pick.scores(c64, ref, blurred))
    return r


rank = dither_pick.rank


def parse_weights(v):
    try:
        return dither_pick.parse_weights(v)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("photo")
    ap.add_argument("-w", "--weights", type=parse_weights, default=list(dither_pick.WEIGHTS),
                    help="RMS,SSIM,COLOR (default 0,1,1)")
    ap.add_argument("-s", "--settings", nargs="+", default=DEFAULT,
                    help="settings to try (default: %s)" % " ".join(DEFAULT))
    ap.add_argument("--blur", action="store_true",
                    help="measure SSIM on the blurred pictures too")
    ap.add_argument("--ntsc", action="store_true", help="NTSC aspect, palette and timing")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count(),
                    help="processes (default: one per CPU)")
    args = ap.parse_args()
    for s in args.settings:
        try:
            parse_setting(s)
        except (ValueError, argparse.ArgumentTypeError) as e:
            ap.error(str(e))
    os.makedirs(OUT, exist_ok=True)
    system = "ntsc" if args.ntsc else "pal"
    with ProcessPoolExecutor(args.jobs) as ex:
        results = list(ex.map(score, [args.photo] * len(args.settings), args.settings,
                              [system] * len(args.settings), [args.blur] * len(args.settings)))
    w = args.weights
    print("%s (%s), weights rms %g, ssim %g, color %g, ssim %s"
          % (os.path.basename(args.photo), system, w[0], w[1], w[2],
             "blurred" if args.blur else "unblurred"))
    print("rank  %-22s %6s  %6s  %6s  %6s  %13s"
          % ("setting", "score", "rms", "ssim", "color", "wrong"))
    for i, r in enumerate(rank(results, w), 1):
        print("%4d  %-22s %6.3f  %6.2f  %6.4f  %6.2f  %5d (%4.1f%%)"
              % (i, r["setting"], r["score"], r["rms"], r["ssim"], r["color"], r["wrong"],
                 r["pct"]))


if __name__ == "__main__":
    main()
