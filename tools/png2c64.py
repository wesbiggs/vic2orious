"""Quantise pictures to the C64 palette (Pepto).

usage: python3 tools/png2c64.py [-d {floydsteinberg,none}] [-o OUTPUT] INPUT...

  -o FILE     write one converted picture to FILE (default: out.png)
  -o DIR/     write each picture to DIR/<input name>.png; DIR is created if needed. A
              directory is meant when the path exists as one or ends with "/". Inputs
              may then be several files or glob patterns ("pics/*.jpg").
  -d MODE     floydsteinberg (default) or none

For a frame around the image on the C64, build with make FRAME=1 (v2i_frame draws it).
"""

import argparse
import glob
import os
import sys

from PIL import Image

PALETTE = [
    0x000000, 0xFFFFFF, 0x68372B, 0x70A4B2,
    0x6F3D86, 0x588D43, 0x352879, 0xB8C76F,
    0x6F4F25, 0x433900, 0x9A6759, 0x444444,
    0x6C6C6C, 0x9AD284, 0x6C5EB5, 0x959595,
]

DITHER = {"floydsteinberg": Image.Dither.FLOYDSTEINBERG, "none": Image.Dither.NONE}


def palette_image():
    flat = []
    for c in PALETTE:
        flat += [(c >> 16) & 255, (c >> 8) & 255, c & 255]
    flat += [0] * (768 - len(flat))  # pad to 256 entries
    pal_img = Image.new("P", (1, 1))
    pal_img.putpalette(flat)
    return pal_img


def convert(path, dither):
    img = Image.open(path).convert("RGB")
    return img.quantize(palette=palette_image(), dither=DITHER[dither]).convert("RGB")


def expand(patterns):
    """Input names, with glob patterns expanded (for shells that pass them through)."""
    files = []
    for p in patterns:
        matches = sorted(glob.glob(p)) if glob.has_magic(p) else [p]
        if not matches:
            raise SystemExit("png2c64: no files match %s" % p)
        files += matches
    return files


def main():
    ap = argparse.ArgumentParser(description="Quantise pictures to the C64 palette (Pepto).")
    ap.add_argument("inputs", nargs="+", metavar="INPUT", help="picture files or glob patterns")
    ap.add_argument("-o", "--output", default="out.png",
                    help="output file, or a directory (existing, or ending in /) to keep the "
                         "input names; default out.png")
    ap.add_argument("-d", "--dither", default="floydsteinberg", type=str.lower,
                    choices=sorted(DITHER), help="dithering (default floydsteinberg)")
    a = ap.parse_args()
    inputs = expand(a.inputs)
    to_dir = os.path.isdir(a.output) or a.output.endswith(("/", os.sep))
    if len(inputs) > 1 and not to_dir:
        ap.error("several inputs need -o DIRECTORY/")
    if to_dir:
        os.makedirs(a.output, exist_ok=True)
        jobs = [(p, os.path.join(a.output, os.path.splitext(os.path.basename(p))[0] + ".png"))
                for p in inputs]
    else:
        jobs = [(inputs[0], a.output)]
    for src, dst in jobs:
        if os.path.exists(dst) and os.path.samefile(src, dst):
            raise SystemExit("png2c64: %s would overwrite its input; choose another -o" % src)
    for src, dst in jobs:
        convert(src, a.dither).save(dst)
        print("%s -> %s" % (src, dst))
    return 0


if __name__ == "__main__":
    sys.exit(main())
