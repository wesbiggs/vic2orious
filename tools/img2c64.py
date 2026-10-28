"""Turn pictures into C64-ready PNGs: C64 colours, screen size, PAL/NTSC pixel aspect.

usage: python3 tools/img2c64.py [-a {both,pal,ntsc,none}] [-b] [-d {floydsteinberg,none}]
                                [-o OUTPUT] INPUT...

  -o FILE     write to FILE (default: out.png); with an aspect, FILE-p.png / FILE-n.png
  -o DIR/     write each picture to DIR/<input name>[-p|-n].png; DIR is created if needed.
              A directory is meant when the path exists as one or ends with "/". Inputs
              may then be several files or glob patterns ("pics/*.jpg").
  -a ASPECT   both (default): one file per system, -p (PAL) and -n (NTSC); pal or ntsc:
              that one only; none: no stretch, no suffix (for pixel art made at C64 size)
  -b          leave room for a frame: fit 304x184 instead of 320x200 (one cell on each side,
              where the build draws the frame; see below)
  -d MODE     floydsteinberg (default) or none

Steps: read any format Pillow reads (HEIC too if pillow-heif is installed), apply the EXIF
orientation, convert from the embedded colour profile to sRGB, flatten transparency onto
black; stretch the width so the picture keeps its proportions on that system's TV (C64
pixels are not square: about 0.94 wide on PAL, 0.75 on NTSC); shrink proportionally to fit
320x200 if needed; round both sides to multiples of 8 (the converter needs that); map to
the palette: Colodore as VICE shows it with its default colour controls (VICE's PAL
rendering for -p and -a none files, its NTSC one for -n). Pictures are never enlarged beyond the stretch. The output is tagged sRGB.

For a frame around the image on the C64, build with make FRAME=1 (v2i_frame draws it); -b
makes sure the picture leaves room for it.
"""

import argparse
import glob
import io
import os
import sys

from PIL import Image, ImageCms, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

# Colodore (VICE colodore.vpl) as VICE shows it with its default colour controls (brighter
# and more saturated than the .vpl), per system; keep in sync with vic2/palette.py
# (COLODORE_VICE_PAL/_NTSC), whose exact lookup maps these back to their indices.
PALETTES = {
    "pal": [
        0x000000, 0xFFFFFF, 0xD32831, 0x58FFFF,
        0xDB29F1, 0x3CF82B, 0x2C27FF, 0xFFFF29,
        0xDC5404, 0x814000, 0xFF6C76, 0x595959,
        0x969696, 0xA1FF8D, 0x7D77FF, 0xDADADA,
    ],
    "ntsc": [
        0x000000, 0xFFFFFF, 0xD62933, 0x55FFFF,
        0xDD2BF3, 0x3AF529, 0x2B27FF, 0xFFFF2B,
        0xDD5606, 0x824100, 0xFF6E78, 0x595959,
        0x969696, 0xA0FF8C, 0x7D77FF, 0xDADADA,
    ],
}

DITHER = {"floydsteinberg": Image.Dither.FLOYDSTEINBERG, "none": Image.Dither.NONE}

# Pixel width / height on a 4:3 TV: square-pixel sampling rate of the TV standard over the
# VIC-II dot clock (PAL 7.375 / 7.882 MHz, NTSC 6.136 / 8.182 MHz).
PAR = {"pal": 0.936, "ntsc": 0.75}
SUFFIX = {"pal": "-p", "ntsc": "-n", None: ""}
SYSTEMS = {"both": ["pal", "ntsc"], "pal": ["pal"], "ntsc": ["ntsc"], "none": [None]}
MAX_W, MAX_H = 320, 200
FRAME = 16                      # -b: a cell of frame on each side

SRGB = ImageCms.createProfile("sRGB")
SRGB_ICC = ImageCms.ImageCmsProfile(SRGB).tobytes()


def palette_image(system):
    flat = []
    for c in PALETTES[system or "pal"]:
        flat += [(c >> 16) & 255, (c >> 8) & 255, c & 255]
    flat += [0] * (768 - len(flat))  # pad to 256 entries
    pal_img = Image.new("P", (1, 1))
    pal_img.putpalette(flat)
    return pal_img


def load(path):
    """The picture as sRGB, upright, transparency flattened onto black."""
    img = ImageOps.exif_transpose(Image.open(path))
    icc = img.info.get("icc_profile")
    alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
    mode = "RGBA" if alpha else "RGB"
    if icc and img.mode in ("RGB", "RGBA", "CMYK", "L"):
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            img = ImageCms.profileToProfile(img, src, SRGB, outputMode=mode)
        except ImageCms.PyCMSError as e:
            print("img2c64: %s: colour profile ignored (%s)" % (path, e), file=sys.stderr)
    if img.mode != mode:
        img = img.convert(mode)
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size)
        bg.paste(img, mask=img.getchannel("A"))
        img = bg
    return img


def round8(v, limit):
    return max(8, min(limit, int(v / 8 + 0.5) * 8))


def target_size(w, h, system, frame=False):
    """C64 size for a w x h picture: width stretched by 1/PAR, fitted into 320x200 (304x184
    with frame)."""
    if system:
        w = w / PAR[system]
    mw, mh = (MAX_W - FRAME, MAX_H - FRAME) if frame else (MAX_W, MAX_H)
    s = min(1.0, mw / w, mh / h)
    return round8(w * s, mw), round8(h * s, mh)


def convert(img, system, dither, frame=False):
    size = target_size(img.width, img.height, system, frame)
    if size != img.size:
        img = img.resize(size, Image.Resampling.LANCZOS)
    return img.quantize(palette=palette_image(system), dither=DITHER[dither]).convert("RGB")


def expand(patterns):
    """Input names, with glob patterns expanded (for shells that pass them through)."""
    files = []
    for p in patterns:
        matches = sorted(glob.glob(p)) if glob.has_magic(p) else [p]
        if not matches:
            raise SystemExit("img2c64: no files match %s" % p)
        files += matches
    return files


def main():
    ap = argparse.ArgumentParser(description="Turn pictures into C64-ready PNGs (Colodore "
                                             "colours as VICE shows them, 320x200 at most, PAL/NTSC aspect).")
    ap.add_argument("inputs", nargs="+", metavar="INPUT", help="picture files or glob patterns")
    ap.add_argument("-o", "--output", default="out.png",
                    help="output file, or a directory (existing, or ending in /) to keep the "
                         "input names; default out.png")
    ap.add_argument("-a", "--aspect", default="both", type=str.lower, choices=list(SYSTEMS),
                    help="pixel aspect to correct for: both (default; writes -p and -n "
                         "files), pal, ntsc, or none")
    ap.add_argument("-b", "--border", action="store_true",
                    help="leave room for the frame the build draws (make FRAME=1): fit "
                         "304x184 instead of 320x200")
    ap.add_argument("-d", "--dither", default="floydsteinberg", type=str.lower,
                    choices=sorted(DITHER), help="dithering (default floydsteinberg)")
    a = ap.parse_args()
    inputs = expand(a.inputs)
    to_dir = os.path.isdir(a.output) or a.output.endswith(("/", os.sep))
    if len(inputs) > 1 and not to_dir:
        ap.error("several inputs need -o DIRECTORY/")
    if to_dir:
        os.makedirs(a.output, exist_ok=True)
        bases = [(p, os.path.join(a.output, os.path.splitext(os.path.basename(p))[0]))
                 for p in inputs]
    else:
        bases = [(inputs[0], os.path.splitext(a.output)[0])]
    jobs = [(src, base + SUFFIX[s] + ".png", s) for src, base in bases for s in SYSTEMS[a.aspect]]
    for src, dst, _ in jobs:
        if os.path.exists(dst) and os.path.samefile(src, dst):
            raise SystemExit("img2c64: %s would overwrite its input; choose another -o" % src)
    for src in dict.fromkeys(src for src, _, _ in jobs):
        try:
            img = load(src)
        except (OSError, Image.UnidentifiedImageError) as e:
            raise SystemExit("img2c64: %s" % e)
        for _, dst, system in (j for j in jobs if j[0] == src):
            out = convert(img, system, a.dither, a.border)
            out.save(dst, icc_profile=SRGB_ICC)
            print("%s -> %s (%dx%d%s)" % (src, dst, out.width, out.height,
                                          ", " + system.upper() if system else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
