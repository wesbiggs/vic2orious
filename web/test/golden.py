"""Reference results for the JavaScript port (web/test/golden.mjs): converts one picture
with the Python and writes its inputs and outputs as JSON.

    python3 web/test/golden.py pal input/dragon.png out.json

The picture is placed as the build places an image without text (centred). In place of
a picture it takes a JSON file with "img" (rows of palette indices) and "kw" (the
Converter's frame, at and mc), and then "std" from that file too if it has one."""

import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from vic2 import build, convert, timing  # noqa: E402
from vic2.palette import load_indexed  # noqa: E402


def main(std, png, out):
    if png.endswith(".json"):
        with open(png) as f:
            case = json.load(f)
        std, img, kw = case.get("std", std), case["img"], case["kw"]
    else:
        mc = build.png_mode(png) == build.MODE_MC
        w, h, img = load_indexed(png)
        cw = 4 if mc else 8
        col0, row0, _ = build.place(w // cw, h // 8, False, None, True)
        kw = dict(frame=False, at=[col0, row0], mc=mc)
    timing.set_standard(std)
    t = time.time()
    c = convert.Converter(img, log=lambda m: None, frame=kw["frame"], at=tuple(kw["at"]),
                          mc=kw["mc"])
    c.run()
    secs = time.time() - t
    ref = dict(
        std=std, img=img, kw=kw, secs=round(secs, 1),
        kernel=bytes(c.kernel.code).hex(),
        pairs=[[list(p) for p in row] for row in c.pairs],
        sdata=[sorted([r, b] for r, b in d.items()) for d in c.sdata],
        line_cfg=[sorted([r, list(v)] for r, v in d.items()) for d in c.line_cfg],
        bad_lines=sorted([y, why] for y, why in c.bad_lines.items()),
        render=c.render())
    with open(out, "w") as f:
        json.dump(ref, f)
    print("%s %s %.0fs kernel %s" % (os.path.basename(png), std, secs,
                                     hashlib.sha1(bytes(c.kernel.code)).hexdigest()[:12]))


if __name__ == "__main__":
    main(*sys.argv[1:4])
