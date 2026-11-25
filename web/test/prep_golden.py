"""Reference results for the JavaScript picture preparation (web/test/prep_golden.mjs):
runs tools/img2c64.py's convert, settings and thumbnail on one picture, for each system
and dither candidate, and writes the loaded picture and the results as JSON.

    python3 web/test/prep_golden.py photo.jpg out.json [-m] [-s WxH] [-c S]
"""

import base64
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import img2c64  # noqa: E402
from vic2 import dither_pick, thumb  # noqa: E402
from vic2.palette import KNOWN  # noqa: E402


def main(src, out, *opts):
    mc = "-m" in opts
    box = (320, 200)
    chroma = 1.0
    if "-s" in opts:
        box = tuple(int(v) for v in opts[opts.index("-s") + 1].split("x"))
    if "-c" in opts:
        chroma = float(opts[opts.index("-c") + 1])
    img = img2c64.load(src)
    view = img2c64.load_vpl(img2c64.VIEW)
    ref = dict(width=img.width, height=img.height, mc=mc, box=box, chroma=chroma,
               rgb=base64.b64encode(img.tobytes()).decode(), results=[])
    for system in ("pal", "ntsc"):
        for name, d, runs in dither_pick.CANDIDATES:
            if mc and d == "hybrid":
                continue
            dither = img2c64.parse_dither(d)
            o = img2c64.convert(img, system, dither, False, box, chroma, runs, view, mc)
            raw = o.tobytes()
            idx = bytes(KNOWN[tuple(raw[i:i + 3])] for i in range(0, len(raw), 3))
            ref["results"].append(dict(
                system=system, name=name, dither=d, runs=runs, w=o.width, h=o.height,
                idx=hashlib.sha1(idx).hexdigest(), idx_b64=base64.b64encode(idx).decode(),
                settings=img2c64.settings(src, system, dither, False, box, chroma, runs,
                                          None, "tv.vpl", mc),
                thumb=img2c64.thumbnail(img, o, system, view, mc).hex()))
            print(system, name, o.size, ref["results"][-1]["idx"][:12], flush=True)
    with open(out, "w") as f:
        json.dump(ref, f)


if __name__ == "__main__":
    main(*sys.argv[1:])
