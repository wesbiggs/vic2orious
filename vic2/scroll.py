"""One story (.txt, as the build reads input/<name>.txt) -> the smooth scroll demo PRG.

usage: python3 -m vic2.scroll [-o OUT.prg] [--font FILE.cvt[:SIZE]] [--leading N]
                             [--at COLUMN,ROW] [--width N] [--autoscroll N] FILE.txt

The text is laid out as the build lays out stories (pixel-width word wrap, "#" titles,
indents and blank lines kept) and assembled into asm/scroll.s alone, without the build's
intro page or any image. The PRG runs on PAL and NTSC. It is <name>.prg in the current
directory unless -o names another; intermediate files go to build/scroll/.

--at puts the first line at that character cell (default 1,1; row 24 starts it just below
the screen), --width wraps the text to N cells (default: to the right edge, one cell
margin). The page scrolls until its last line is at the bottom of the screen. With
--autoscroll N it scrolls down by itself, one pixel every N frames (1: 50 or 60 pixels a
second, as fast as it goes); the keys still work.
"""

import argparse
import os
import sys

from . import build
from . import font as fonts


def main():
    ap = argparse.ArgumentParser(description="Make the smooth scroll demo PRG from one text.")
    ap.add_argument("text", metavar="FILE.txt")
    ap.add_argument("-o", "--output", help="the PRG to write (default: <name>.prg)")
    ap.add_argument("--font", metavar="FILE.cvt[:SIZE]",
                    help="GEOS font (Convert format), its smallest point size unless SIZE is "
                         "given (default: the character ROM's; up to %d pixels high)"
                         % (8 * build.SCROLL_VOFF))
    ap.add_argument("--leading", type=int, default=build.TEXT_LEADING,
                    help="blank pixel lines between text lines (default %d)" % build.TEXT_LEADING)
    ap.add_argument("--at", metavar="COLUMN,ROW", default="1,1",
                    help="character cell of the first line's top left (default 1,1)")
    ap.add_argument("--width", type=int, metavar="N",
                    help="text width in character cells (default: to column 38)")
    ap.add_argument("--autoscroll", type=int, metavar="N", default=0,
                    help="scroll down by itself, one pixel every N frames (1-255; default "
                         "0: only with the keys)")
    a = ap.parse_args()
    if not 0 <= a.leading <= 64:
        ap.error("--leading must be 0..64")
    try:
        col, row = (int(v) for v in a.at.split(","))
    except ValueError:
        ap.error("--at takes COLUMN,ROW")
    if not (0 <= col < 40 and 0 <= row <= 24):
        ap.error("--at takes COLUMN,ROW in character cells (0-39, 0-24)")
    width = 39 - col if a.width is None else a.width
    if not 1 <= width <= 40 - col:
        ap.error("--width must be 1..%d at column %d" % (40 - col, col))
    if not 0 <= a.autoscroll <= 255:
        ap.error("--autoscroll must be 0..255")
    with open(a.text) as f:
        text = f.read()
    fonts.use(a.font)
    build.BUILD = os.path.join(build.ROOT, "build", "scroll")
    os.makedirs(build.BUILD, exist_ok=True)
    out = os.path.abspath(a.output or os.path.splitext(os.path.basename(a.text))[0] + ".prg")
    defines = ["AUTOSCROLL=%d" % a.autoscroll] if a.autoscroll else []
    lines, height, vmax = build.build_scroll([], a.leading, out, defines, texts=[text],
                                             area=(8 * col, width, 8 * row))
    print("%s: %d lines, %d pixels, %s font %d px" % (
        out, len(lines), height, fonts.current().name, fonts.current().height))
    return 0


if __name__ == "__main__":
    sys.exit(main())
