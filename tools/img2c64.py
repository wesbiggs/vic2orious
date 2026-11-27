"""Turn pictures into C64-ready PNGs: C64 colours, screen size, PAL/NTSC pixel aspect.

usage: python3 tools/img2c64.py [-a {both,pal,ntsc,none}] [-b] [-c S] [-P FILE.vpl]
                                [-d MODE | -w R,S,C] [-m] [-s WxH] [-o OUTPUT] INPUT...

  -o FILE     write to FILE (default: out.png); with an aspect, FILE-p.png / FILE-n.png
  -o DIR/     write each picture to DIR/<input name>[-p|-n].png; DIR is created if needed.
              A directory is meant when the path exists as one or ends with "/". Inputs
              may then be several files or glob patterns ("pics/*.jpg").
  -a ASPECT   both (default): one file per system, -p (PAL) and -n (NTSC); pal or ntsc:
              that one only; none: no stretch, no suffix (for pixel art made at C64 size)
  -b          leave room for a frame: fit 304x184 instead of 320x200 (one cell on each side,
              where the build draws the frame; see below)
  -d MODE     dithering: floydsteinberg (Pillow's; also fs), none, or one that
              leaves the converter fewer pixels it cannot place (in brackets: IMG_1639,
              320x168 PAL, wrong pixels after conversion; Floyd-Steinberg 15%, none 0.2%).
              Without -d, img2c64 picks one per picture and system (see -w):
              fs:K        Floyd-Steinberg passing on K (0-1) of the error (fs:0.5: 4%)
              atkinson:K  Atkinson's kernel (6/8 of the error), times K (default 1: 9%;
                          atkinson:0.75: 5%)
              hybrid:E    each 8x8 cell's best pair of colours, Floyd-Steinberg between
                          them, any colour where the pair is more than E (RGB distance,
                          default 90) off, within the line budget of -l; error clamped
                          to +-64
  -w R,S,C    without -d: try the dithers above (none, fs, fs:0.75, fs:0.5, atkinson,
              atkinson:0.75, hybrid with -l 8, 6 and none), run each result through the
              converter and keep the one whose C64 picture is closest to the source, by
              these weights for the 3x3-blurred RMS error, SSIM and colour (a*b*) error
              (default 0,1,1; web/js/pick.js, analysis/README.md). Prints each
              dither's metrics as it finishes (with wrong pixels and CPU time), then
              the ranking and the pick. The converter takes the most time (each dither of
              each picture in its own worker thread), so by default only the best 3 by a
              quick estimate go through it (see -t).
  -t N        without -d: rank the dithers first by an estimate of the converter
              (web/js/pick.js estimate: each cell's two commonest colours, each line's
              other pixels covered by up to 8 spans as if every one fitted; about 0.1 s)
              and convert only the best N (default 3); all converts every one, as before
              (kodim13: the estimate's top two were the converter's, PAL and NTSC). Not
              used with -m, which never runs the converter.
  -c S        choose colours as if the palette had S times its saturation (default 1;
              0 < S <= 2); the output still has the real colours. Photos are rarely as
              saturated as the C64's colours: at 1 their reds, browns and blues fall to
              grey. With -d hybrid it pays: -c 0.6 on IMG_1639 gives warm stone and a blue
              sky (and slightly fewer wrong pixels). With the others it puts more colours in each
              cell (fs:0.5: 11% wrong instead of 4%, none: 5% instead of 0.2%).
  -P FILE     choose colours as the screen shows them: FILE is a VICE palette (.vpl, 16
              colours, e.g. one measured from a photo of the TV running a colour bar).
              Default: tools/tv.vpl (measured from the author's TV, much paler than VICE's
              Colodore); -P none uses VICE's Colodore itself. The output is written in these
              colours, so it looks on a computer roughly as on that screen; the build
              reads PNGs in the palettes vic2/palette.py knows (tools/tv.vpl among them),
              any other colours go to the nearest Pepto ones, wrongly. -c applies to the
              choice only. Without -d, the dithers are judged by what that screen shows
  -m          multicolour bitmap: the picture is made of wide pixels (two screen pixels,
              so twice the pixel width of -a's), one PNG pixel each: 160 wide for the full
              screen, multiples of 4. -s and -b still count screen pixels. Not with
              -d hybrid (its cells are hires cells); without -d the other dithers are
              judged by the picture itself, each pixel doubled (the converter shows
              all but 0-0.6% of a multicolour picture's pixels, so it is not run).
              The PNG's settings get "mode: multicolor", from which the build knows
              it (version 4 .v2i; centred, without text or frame).
  -s WxH      fit WxH instead of 320x200 (multiples of 8; with -b, also inside 304x184)
  -l N        with -d hybrid: a line's colours outside their cell's pair must fit in at most
              N single colour runs of 24 pixels (the converter's sprites paint them; default
              8, none for no budget); a pixel needing one more takes the nearest colour that
              fits. On 5 Kodak photos (PAL, 320 wide; wrong pixels after conversion and
              3x3-blurred RMS error of what the C64 shows against the photo): hybrid 2.4% /
              13.1, -l 6 1.3% / 13.3, -l none 6.6% / 12.9, Floyd-Steinberg 9.9% / 13.6

Steps: read any format Pillow reads (HEIC too if pillow-heif is installed), apply the EXIF
orientation, convert from the embedded colour profile to sRGB, flatten transparency onto
black; stretch the width so the picture keeps its proportions on that system's TV (C64
pixels are not square: about 0.94 wide on PAL, 0.75 on NTSC); shrink proportionally to fit
320x200 (or -s WxH) if needed; round both sides to multiples of 8 (the converter needs that); map to
the palette: the screen's of -P (default tools/tv.vpl), or with -P none Colodore as VICE
shows it with its default colour controls (VICE's PAL rendering for -p and -a none files,
its NTSC one for -n). Pictures are never enlarged beyond the stretch. The output is tagged sRGB
and records the settings (source name, aspect, fit, dither, chroma, palette) in a PNG text
chunk "vic2orious"; the build copies them into the .v2i's metadata. It also holds a
thumbnail (text chunk "vic2orious-thumb", hex): the picture shrunk into 24x21 pixels (as
the C64 shows it: 24x15 for the full screen), in black and at most 8 other colours of the
same palette, which 8 sprites show exactly (web/js/thumb.js); the build puts it in the .v2i.

For a frame around the image on the C64, build with make FRAME=1 (v2i_frame draws it); -b
makes sure the picture leaves room for it.

Everything after reading the picture is the JavaScript the web page runs (web/js, through
vic2/engine.py and tools/engine.mjs), so it needs Node 18 or later; this reads the
picture and writes the PNGs.
"""

import argparse
import glob
import io
import os
import sys

from PIL import Image, ImageCms, ImageOps, PngImagePlugin

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vic2 import engine  # noqa: E402

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

# -d MODE[:PARAM] -> (default PARAM, range); fs/floydsteinberg at full strength is Pillow's
DITHERS = {"none": None, "floydsteinberg": (1.0, (0.0, 1.0)), "fs": (1.0, (0.0, 1.0)),
           "atkinson": (1.0, (0.0, 1.0)), "hybrid": (90.0, (0.0, 442.0))}
HYBRID_RUNS = 8         # hybrid: default -l
TOP = 3                 # picker: default -t
SUFFIX = {"pal": "-p", "ntsc": "-n", None: ""}
SYSTEMS = {"both": ["pal", "ntsc"], "pal": ["pal"], "ntsc": ["ntsc"], "none": [None]}
MAX_W, MAX_H = 320, 200
TEXT_KEY = "vic2orious"         # PNG text chunk with the settings (web/js/img2c64.js settings)
THUMB_KEY = "vic2orious-thumb"  # PNG text chunk with the thumbnail (vic2/thumb.py TEXT_KEY)
# -P default: the screen colours are chosen for (measured from a photo of the author's TV)
VIEW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tv.vpl")

SRGB = ImageCms.createProfile("sRGB")
# without the creation date (header bytes 24-35), so the same picture gives the same file
# (the build's conversion cache hashes it)
SRGB_ICC = ImageCms.ImageCmsProfile(SRGB).tobytes()
SRGB_ICC = SRGB_ICC[:24] + bytes(12) + SRGB_ICC[36:]


def load_vpl(path):
    """A VICE palette file: 16 lines "RR GG BB [dither]", # comments. (r, g, b) list."""
    pal = []
    with open(path) as f:
        for line in f:
            line = line.split("#")[0].split()
            if line:
                pal.append(tuple(int(v, 16) for v in line[:3]))
    if len(pal) != 16 or any(len(c) != 3 or not all(0 <= v <= 255 for v in c) for c in pal):
        raise ValueError("%s: not a 16 colour VICE palette" % path)
    return pal


def palette_image(colours):
    flat = [v for c in colours for v in c]
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


def save(out, dst, text, thumb=None):
    """out as dst: tagged sRGB, with text (settings) in a tEXt chunk, and thumb (thumbnail
    bytes) hex encoded in another."""
    info = PngImagePlugin.PngInfo()
    info.add_text(TEXT_KEY, text)
    if thumb:
        info.add_text(THUMB_KEY, thumb.hex())
    out.save(dst, icc_profile=SRGB_ICC, pnginfo=info)


def picture(w, h, idx, colours):
    """An output as an RGB image: palette indices idx (w x h) in colours (16 (r, g, b))."""
    out = Image.frombytes("P", (w, h), bytes(idx))
    out.putpalette(palette_image(colours).getpalette())
    return out.convert("RGB")


def parse_top(v):
    """-t N|all: how many of the estimate's best go through the converter."""
    if v.lower() == "all":
        return None
    try:
        n = int(v)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError("%s: takes a number of dithers (1 or more) or all" % v)
    return n


def parse_weights(v):
    """-w RMS,SSIM,COLOR: three numbers >= 0, not all 0."""
    try:
        w = [float(x) for x in v.strip("{}() ").split(",")]
    except ValueError:
        w = []
    if len(w) != 3 or min(w) < 0 or sum(w) == 0:
        raise argparse.ArgumentTypeError("takes three weights >= 0, not all 0, RMS,SSIM,COLOR, "
                                         "e.g. 0,1,1")
    return w


def parse_chroma(v):
    """-c S: a number above 0, at most 2."""
    try:
        s = float(v)
    except ValueError:
        s = -1
    if not 0 < s <= 2:
        raise argparse.ArgumentTypeError("%s: takes a number above 0, at most 2" % v)
    return s


def parse_dither(v):
    """-d MODE[:PARAM]: (mode, param), floydsteinberg as fs."""
    mode, _, arg = v.lower().partition(":")
    if mode not in DITHERS:
        raise argparse.ArgumentTypeError("%s: unknown mode (%s)" % (v, ", ".join(DITHERS)))
    if DITHERS[mode] is None:
        if arg:
            raise argparse.ArgumentTypeError("%s: none takes no parameter" % v)
        return "none", None
    default, (lo, hi) = DITHERS[mode]
    try:
        k = float(arg) if arg else default
    except ValueError:
        raise argparse.ArgumentTypeError("%s: the parameter is a number" % v)
    if not lo < k <= hi:
        raise argparse.ArgumentTypeError("%s: the parameter must be above %g, at most %g"
                                         % (v, lo, hi))
    return ("fs" if mode == "floydsteinberg" else mode), k


def check_dither(v):
    """-d as given, once parse_dither takes it (the engine parses it the same way)."""
    parse_dither(v)
    return v.lower()


def parse_size(v):
    """-s WxH: (w, h), multiples of 8 within 320x200."""
    try:
        w, h = (int(n) for n in v.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError("takes WIDTHxHEIGHT, e.g. 160x96")
    if not (8 <= w <= MAX_W and 8 <= h <= MAX_H and w % 8 == 0 and h % 8 == 0):
        raise argparse.ArgumentTypeError("%s: width and height must be multiples of 8, at "
                                         "most %dx%d" % (v, MAX_W, MAX_H))
    return w, h


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
    ap.add_argument("-d", "--dither", type=check_dither, metavar="MODE",
                    help="floydsteinberg (fs[:K]), atkinson[:K], hybrid[:E] or none; "
                         "default: pick per picture (see -w)")
    ap.add_argument("-w", "--weights", type=parse_weights, metavar="R,S,C",
                    help="without -d: weights for blurred RMS, SSIM and colour error when "
                         "picking the dither (default 0,1,1)")
    ap.add_argument("-t", "--top", type=parse_top, default=-1, metavar="N",
                    help="without -d: rank the dithers by a quick estimate of the converter "
                         "first and convert only the best N (default %d; all: convert every "
                         "one, slow)" % TOP)
    ap.add_argument("-c", "--chroma", type=parse_chroma, default=1.0, metavar="S",
                    help="match against the colours at S times their saturation (default "
                         "1; with -d hybrid, 0.6 suits many photos: warmer colours and fewer "
                         "pixels the converter cannot place)")
    ap.add_argument("-P", "--palette", metavar="FILE.vpl", default=VIEW,
                    help="choose colours as a screen with this VICE palette shows them "
                         "(default tools/tv.vpl, measured from a TV; none: VICE's Colodore); "
                         "the output is written in its colours")
    ap.add_argument("-m", "--multicolor", action="store_true",
                    help="multicolour bitmap: wide pixels (two screen pixels each), so the "
                         "output is half as wide (160 for the full screen); not with -d "
                         "hybrid")
    ap.add_argument("-s", "--size", type=parse_size, default=(MAX_W, MAX_H), metavar="WxH",
                    help="fit WxH instead of 320x200 (multiples of 8)")
    ap.add_argument("-l", "--line-runs", metavar="N",
                    help="with -d hybrid: a line's colours outside their cell's pair fit in at "
                         "most N runs of 24 pixels (the converter has 8 sprites; default %d, "
                         "none for no budget)" % HYBRID_RUNS)
    a = ap.parse_args()
    if a.dither and a.weights:
        ap.error("-w picks the dither; leave out -d")
    if a.multicolor and a.dither and parse_dither(a.dither)[0] == "hybrid":
        ap.error("-d hybrid works on hires cells; not with -m")
    if a.line_runs is not None:
        if not a.dither or parse_dither(a.dither)[0] != "hybrid":
            ap.error("-l needs -d hybrid")
        if a.line_runs == "none":
            a.line_runs = None
        elif a.line_runs.isdigit() and int(a.line_runs) <= 8:
            a.line_runs = int(a.line_runs)
        else:
            ap.error("-l takes 0-8 or none")
    if a.dither and a.top != -1:
        ap.error("-t picks among dithers; not with -d")
    if a.top == -1:
        a.top = TOP
    else:
        a.line_runs = HYBRID_RUNS
    view = view_name = None
    if a.palette != "none":
        try:
            view, view_name = load_vpl(a.palette), os.path.basename(a.palette)
        except (OSError, ValueError) as e:
            ap.error(str(e))
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
    imgs = {}
    for src in dict.fromkeys(src for src, _, _ in jobs):
        try:
            imgs[src] = load(src)
        except (OSError, Image.UnidentifiedImageError) as e:
            raise SystemExit("img2c64: %s" % e)
    srcs = list(imgs)

    def done(i, w, h, idx, text, thumb, colours, note):
        src, dst, system = jobs[i]
        save(picture(w, h, idx, colours), dst, text, thumb)
        print("%s -> %s (%dx%d%s%s)%s" % (src, dst, w, h, " wide pixels" if a.multicolor else "",
                                        ", " + system.upper() if system else "", note),
              flush=True)

    # the work is the JavaScript of web/js (vic2/engine.py): fit, dither or pick one,
    # thumbnail; every dither of every picture at once in worker threads
    try:
        engine.img2c64(
            [(src, os.path.basename(src), os.path.basename(dst), system, srcs.index(src))
             for src, dst, system in jobs],
            [imgs[src] for src in srcs],
            dict(dither=a.dither, runs=a.line_runs, weights=a.weights or [0.0, 1.0, 1.0],
                 top=a.top, chroma=a.chroma, view=view and [list(c) for c in view],
                 viewName=view_name, mc=a.multicolor, frame=a.border, box=list(a.size)),
            log=lambda m: print(m, flush=True), on_result=done)
    except engine.EngineError as e:
        raise SystemExit("img2c64: %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
