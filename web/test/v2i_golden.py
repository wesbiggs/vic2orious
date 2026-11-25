"""Reference .v2i for the JavaScript packing (web/test/v2i_golden.mjs): converts an
img2c64 PNG as vic2.prg does (centred) with build.convert_new, and writes its inputs (the
indices, img2c64's settings text, the thumbnail) and the .v2i as JSON.

    python3 web/test/v2i_golden.py pal picture-p.png out.json
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
from PIL import Image  # noqa: E402
from vic2 import build, thumb, timing  # noqa: E402
from vic2.palette import load_indexed  # noqa: E402


def main(std, png, out):
    timing.set_standard(std)
    build.BUILD = tempfile.mkdtemp()
    name = os.path.splitext(os.path.basename(png))[0]
    inf = build.convert_new(png, name, "", lambda m: None, False, None, True)
    with open(inf["v2i"], "rb") as f:
        v2i = f.read()
    w, h, img = load_indexed(png)
    ref = dict(std=std, img=img, mc=build.png_mode(png) == build.MODE_MC,
               settings=Image.open(png).text.get(build.META_KEY, ""),
               thumb=thumb.from_png(png).hex(), image=os.path.basename(png), v2i=v2i.hex(),
               wrong=inf["wrong_px"], bad_lines=inf["bad_lines"], top_slot=inf["top_slot"])
    with open(out, "w") as f:
        json.dump(ref, f)


if __name__ == "__main__":
    main(*sys.argv[1:])
