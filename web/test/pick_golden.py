"""Reference results for the JavaScript dither picker (web/test/pick_golden.mjs): runs
tools/img2c64.py's picker (estimate every candidate, convert the best TOP, rank) on one
picture for both systems, and writes the loaded picture, every metric and the picks.

    python3 web/test/pick_golden.py photo.jpg out.json [-m] [-s WxH]
"""

import base64
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import img2c64  # noqa: E402
from vic2 import dither_pick  # noqa: E402

KEYS = ("setting", "rms", "ssim", "color", "wrong", "score")


def clean(r):
    return {k: r.get(k) for k in KEYS}


def main(src, out, *opts):
    mc = "-m" in opts
    box = (320, 200)
    if "-s" in opts:
        box = tuple(int(v) for v in opts[opts.index("-s") + 1].split("x"))
    img = img2c64.load(src)
    view = img2c64.load_vpl(img2c64.VIEW)
    weights = dither_pick.WEIGHTS
    cands = [c for c in dither_pick.CANDIDATES if not (mc and c[1].startswith("hybrid"))]
    quick = not mc
    ref = dict(width=img.width, height=img.height, mc=mc, box=box,
               rgb=base64.b64encode(img.tobytes()).decode(), systems={})
    with ProcessPoolExecutor() as pool:
        for system in ("pal", "ntsc"):
            futs = [pool.submit(img2c64.candidate, img, system, n, d, r, False, box, 1.0, view,
                                mc, quick) for n, d, r in cands]
            ranked, outs = img2c64.pick(futs, weights, system + " estimate")
            stage1 = [clean(r) for r in ranked]
            extra = []
            if quick:
                futs = [pool.submit(img2c64.refine, img, outs[r["setting"]], r, system, view)
                        for r in ranked[:img2c64.TOP]]
                extra = ranked[img2c64.TOP:]
                ranked, _ = img2c64.pick(futs, weights, system, extra)
            final = [clean(r) for r in ranked]
            ranked = [r for r in ranked if not r.get("estimate")]
            ref["systems"][system] = dict(stage1=stage1, final=final,
                                          pick=ranked[0]["setting"])
    with open(out, "w") as f:
        json.dump(ref, f, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
