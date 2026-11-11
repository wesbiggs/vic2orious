"""Print what a .v2i file holds: its header and its metadata (the settings it was made with).

usage: python3 -m vic2.info FILE.v2i...
"""

import sys

from .build import read_v2i

SYSTEMS = {0: "PAL", 1: "NTSC"}


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__.strip())
    for i, path in enumerate(sys.argv[1:]):
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
        for line in (meta or "(no metadata)\n").splitlines():
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
