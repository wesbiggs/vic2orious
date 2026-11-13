"""Print what a .v2i file holds: its header, thumbnail and metadata (the settings it was
made with). With -t DIR, write each file's thumbnail to DIR/<name>_thumb.png (8x enlarged).

usage: python3 -m vic2.info [-t DIR] FILE.v2i...
"""

import os
import sys

from . import thumb
from .build import read_v2i
from .palette import PEPTO

SYSTEMS = {0: "PAL", 1: "NTSC"}


def main():
    args = sys.argv[1:]
    tdir = None
    if args[:1] == ["-t"] and len(args) > 1:
        tdir, args = args[1], args[2:]
    if not args:
        raise SystemExit(__doc__.strip())
    for i, path in enumerate(args):
        h, meta = read_v2i(path)
        if i:
            print()
        mc = h["mc"]
        print("%s: .v2i version %d, %s, %s %dx%d at column %d, row %d" % (
            path, h["version"], SYSTEMS.get(h["system"], "system %d" % h["system"]),
            "multicolour" if mc else "hires", h["cols"] * (4 if mc else 8), h["rows"] * 8,
            h["col0"], h["row0"]))
        print("  kernel %d bytes, bitmap %d, screen %d, sprites %d; %d lines, %d pixels not "
              "exact" % (h["kernel"], h["bitmap"], h["screen"], h["sprites"],
                         h["bad_lines"], h["wrong_px"]))
        if mc:
            print("  background %d, colour RAM %d bytes" % (h["background"], h["colour"]))
        if h["thumb"]:
            tw, th, bg, sprites = thumb.parse(h["thumb"])
            print("  thumbnail %dx%d, background %d, %d sprites: colours %s" % (
                tw, th, bg, len(sprites), " ".join(str(c) for c, _ in sprites)))
            if tdir:
                out = os.path.join(tdir, os.path.splitext(os.path.basename(path))[0] +
                                   "_thumb.png")
                thumb.save_png(out, h["thumb"], PEPTO)
                print("  thumbnail written to " + out)
        for line in (meta or "(no metadata)\n").splitlines():
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
