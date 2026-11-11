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
              (default 0,1,1; vic2/dither_pick.py, analysis/README.md). Prints the pick
              and the runners-up. Takes the repo's vic2 package and numpy, and about 40 s
              of CPU per dither and picture (the converter; run in parallel: about 50 s a
              picture and system on 12 cores).
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
chunk "vic2orious"; the build copies them into the .v2i's metadata.

For a frame around the image on the C64, build with make FRAME=1 (v2i_frame draws it); -b
makes sure the picture leaves room for it.
"""

import argparse
import bisect
import glob
import io
import os
import sys
from concurrent.futures import ProcessPoolExecutor

from PIL import Image, ImageCms, ImageOps, PngImagePlugin

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

# Colodore (VICE colodore.vpl) as VICE shows it with its default colour controls (brighter
# and more saturated than the .vpl), per system; keep in sync with vic2/palette.py
# (COLODORE_VICE_PAL/_NTSC), whose exact lookup maps these back to their indices. -P none.
# (-P's default, tools/tv.vpl, is in vic2/palette.py too: TV_2026_11.)
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

# -d MODE[:PARAM] -> (default PARAM, range); fs/floydsteinberg at full strength is Pillow's
DITHERS = {"none": None, "floydsteinberg": (1.0, (0.0, 1.0)), "fs": (1.0, (0.0, 1.0)),
           "atkinson": (1.0, (0.0, 1.0)), "hybrid": (90.0, (0.0, 442.0))}
# error diffusion kernels: (dx, dy, share); serpentine, so dx is mirrored on odd lines
KERNELS = {
    "fs": [(1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)],
    "atkinson": [(1, 0, 1 / 8), (2, 0, 1 / 8), (-1, 1, 1 / 8), (0, 1, 1 / 8), (1, 1, 1 / 8),
                 (0, 2, 1 / 8)],
}
HYBRID_CLAMP = 64       # hybrid: carried error per channel at most this
HYBRID_SPREAD = 0.1     # hybrid: cost of mixing far apart colours when picking a cell's pair
HYBRID_RUNS = 8         # hybrid: default -l
HYBRID_NEAR = 4         # hybrid: pair candidates are the cell pixels' 4 nearest colours
SPAN_W = 24             # -l: width of a run of colours outside the cell pair (a sprite)

# Pixel width / height on a 4:3 TV: square-pixel sampling rate of the TV standard over the
# VIC-II dot clock (PAL 7.375 / 7.882 MHz, NTSC 6.136 / 8.182 MHz).
PAR = {"pal": 0.936, "ntsc": 0.75}
SUFFIX = {"pal": "-p", "ntsc": "-n", None: ""}
SYSTEMS = {"both": ["pal", "ntsc"], "pal": ["pal"], "ntsc": ["ntsc"], "none": [None]}
MAX_W, MAX_H = 320, 200
FRAME = 16                      # -b: a cell of frame on each side
TEXT_KEY = "vic2orious"         # PNG text chunk with the settings (see settings)
MODE_MC = "multicolor"          # its "mode" line for -m (vic2/build.py reads it)
# -P default: the screen colours are chosen for (measured from a photo of the author's TV)
VIEW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tv.vpl")

SRGB = ImageCms.createProfile("sRGB")
# without the creation date (header bytes 24-35), so the same picture gives the same file
# (the build's conversion cache hashes it)
SRGB_ICC = ImageCms.ImageCmsProfile(SRGB).tobytes()
SRGB_ICC = SRGB_ICC[:24] + bytes(12) + SRGB_ICC[36:]


def palette(system, chroma=1.0, view=None):
    """The system's colours (or view's: 16 (r, g, b), -P) as (r, g, b), each moved away
    from its own grey (Rec. 601 luma) by chroma: 1 as they are, less to match pictures
    against paler colours (-c)."""
    out = []
    for c in view or PALETTES[system or "pal"]:
        rgb = c if view else ((c >> 16) & 255, (c >> 8) & 255, c & 255)
        y = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        out.append(tuple(max(0, min(255, int(round(y + chroma * (v - y))))) for v in rgb))
    return out


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


def round8(v, limit, step=8):
    return max(step, min(limit, int(v / step + 0.5) * step))


def target_size(w, h, system, frame=False, box=(MAX_W, MAX_H), mc=False):
    """C64 size for a w x h picture: width stretched by 1/PAR, fitted into box (at most
    320x200; 304x184 with frame). mc (multicolour): in wide pixels, each two screen pixels
    wide, so half the width (multiples of 4); with system None the input's pixels are
    taken as wide pixels already."""
    mw, mh = box
    if frame:
        mw, mh = min(mw, MAX_W - FRAME), min(mh, MAX_H - FRAME)
    if system:
        w = w / PAR[system] / (2 if mc else 1)
    if mc:
        mw //= 2
    s = min(1.0, mw / w, mh / h)
    return round8(w * s, mw, 4 if mc else 8), round8(h * s, mh)


def dist2(p, q):
    return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2


def nearest(p, pal, cand):
    return min(cand, key=lambda c: dist2(p, pal[c]))


def cell_pairs(px, w, h, pal):
    """hybrid: two colours per 8x8 cell, the pair whose mixes come closest to the cell's
    pixels (distance to the segment between them, plus HYBRID_SPREAD times the cost of
    mixing far apart colours, as in Yliluoma's dithering)."""
    pairs = {}
    for cy in range(h // 8):
        for cx in range(w // 8):
            cell = [px[y][x] for y in range(cy * 8, cy * 8 + 8) for x in range(cx * 8, cx * 8 + 8)]
            near = set()
            for p in cell:
                near.update(sorted(range(len(pal)), key=lambda c: dist2(p, pal[c]))[:HYBRID_NEAR])
            near = sorted(near)
            best = None
            for i, a in enumerate(near):
                for b in near[i:]:
                    A, B = pal[a], pal[b]
                    d = [B[k] - A[k] for k in range(3)]
                    dd = d[0] ** 2 + d[1] ** 2 + d[2] ** 2
                    cost = 0.0
                    for p in cell:
                        t = 0.0 if dd == 0 else max(0.0, min(1.0, sum(
                            (p[k] - A[k]) * d[k] for k in range(3)) / dd))
                        cost += dist2(p, [A[k] + t * d[k] for k in range(3)])
                        cost += HYBRID_SPREAD * dd * t * (1 - t)
                    if best is None or cost < best[0]:
                        best = (cost, a, b)
            pairs[cy, cx] = best[1:]
    return pairs


def runs_needed(xs):
    """Fewest SPAN_W wide runs covering the sorted xs (greedy from the left is optimal)."""
    n, end = 0, None
    for x in xs:
        if end is None or x > end:
            n, end = n + 1, x + SPAN_W - 1
    return n


def diffuse(img, pal, kernel, strength=1.0, clamp=None, pairs=None, escape=None, budget=None):
    """Serpentine error diffusion: each pixel takes the nearest palette colour (with pairs,
    the nearer of its cell's two, unless that is more than escape away: then the nearest
    of all), and passes strength times the error on (each channel clamped to clamp).
    With budget, a line's pixels outside their cell's pair must fit in at most budget
    single colour runs of SPAN_W pixels (what the converter's sprites paint): a pixel
    that would need one more takes the nearest colour that fits, its pair's if no other.
    Returns a "P" image of palette indices."""
    w, h = img.size
    src = img.load()
    buf = [[list(src[x, y]) for x in range(w)] for y in range(h)]
    out = Image.new("P", (w, h))
    put = out.load()
    full = range(len(pal))
    esc2 = None if escape is None else escape * escape
    for y in range(h):
        sgn = 1 if y % 2 == 0 else -1
        extra, used = {}, {}     # colour -> sorted xs outside their pair / runs they need
        for x in (range(w) if sgn > 0 else range(w - 1, -1, -1)):
            p = [max(0.0, min(255.0, v)) for v in buf[y][x]]
            pair = pairs[y // 8, x // 8] if pairs else full
            c = nearest(p, pal, pair)
            if pairs and dist2(p, pal[c]) > esc2:
                if budget is None:
                    c = nearest(p, pal, full)
                else:
                    for c2 in sorted(full, key=lambda c2: dist2(p, pal[c2])):
                        if c2 in pair:
                            c = c2
                            break
                        xs = extra.get(c2, [])
                        bisect.insort(xs, x)
                        n = runs_needed(xs)
                        if sum(used.values()) - used.get(c2, 0) + n <= budget:
                            extra[c2], used[c2], c = xs, n, c2
                            break
                        xs.remove(x)
            q = pal[c]
            put[x, y] = c
            e = [(p[k] - q[k]) * strength for k in range(3)]
            if clamp is not None:
                e = [max(-clamp, min(clamp, v)) for v in e]
            for dx, dy, f in KERNELS[kernel]:
                xx, yy = x + dx * sgn, y + dy
                if 0 <= xx < w and yy < h:
                    row = buf[yy][xx]
                    row[0] += e[0] * f
                    row[1] += e[1] * f
                    row[2] += e[2] * f
    return out


def convert(img, system, dither, frame=False, box=(MAX_W, MAX_H), chroma=1.0,
            runs=HYBRID_RUNS, view=None, mc=False):
    """dither: (mode, param) from parse_dither. Colours are chosen (and the dither's error
    measured) against palette(system, chroma, view); the result has view's colours (or the
    system's), without chroma. runs:
    hybrid's budget per line (see diffuse), None for none. mc: multicolour, one output
    pixel per wide pixel (target_size); hybrid's cells are hires cells, so not with mc."""
    if mc and dither[0] == "hybrid":
        raise ValueError("hybrid dithers hires cells; not with multicolour")
    size = target_size(img.width, img.height, system, frame, box, mc)
    if size != img.size:
        img = img.resize(size, Image.Resampling.LANCZOS)
    mode, k = dither
    pal = palette(system, chroma, view)
    if mode == "none" or (mode == "fs" and k == 1.0):
        d = Image.Dither.NONE if mode == "none" else Image.Dither.FLOYDSTEINBERG
        out = img.quantize(palette=palette_image(pal), dither=d)
    elif mode == "hybrid":
        src = img.load()
        px = [[src[x, y] for x in range(img.width)] for y in range(img.height)]
        out = diffuse(img, pal, "fs", clamp=HYBRID_CLAMP,
                      pairs=cell_pairs(px, img.width, img.height, pal), escape=k, budget=runs)
    else:
        out = diffuse(img, pal, mode, strength=k)
    out.putpalette(palette_image(palette(system, 1.0, view)).getpalette())
    return out.convert("RGB")


def settings(src, system, dither, frame=False, box=(MAX_W, MAX_H), chroma=1.0,
             runs=HYBRID_RUNS, picked=None, view_name=None, mc=False):
    """What convert was given, as "key: value" lines: written into the PNG (text chunk
    TEXT_KEY), from where the build copies them into the .v2i's metadata. picked: how -w
    chose the dither, if it did; view_name: -P's file name. mc adds "mode: multicolor"
    (MODE_MC), which the build reads; hires pictures have no mode line."""
    mode, k = dither
    if mode == "none":
        d = "none"
    elif mode == "fs" and k == 1.0:
        d = "floydsteinberg (Pillow's)"
    else:
        d = "%s:%g" % (mode, k)
    if mode == "hybrid":
        d += ", line runs %s, spread %g, clamp %s, pair candidates %d" % (
            "none" if runs is None else runs, HYBRID_SPREAD,
            "none" if HYBRID_CLAMP is None else "%g" % HYBRID_CLAMP, HYBRID_NEAR)
    mw, mh = box
    if frame:
        mw, mh = min(mw, MAX_W - FRAME), min(mh, MAX_H - FRAME)
    lines = [("quantiser", "img2c64"),
             ("source", os.path.basename(src)),
             ("aspect", "%s (pixel width %g)" % (system, PAR[system]) if system else "none"),
             ("fit", "%dx%d%s" % (mw, mh, ", room for a frame" if frame else "")),
             ("dither", d),
             ("chroma", "%g" % chroma),
             ("palette", view_name or "Colodore as VICE shows it (%s)" % (
                 system or "pal").upper())]
    if picked:
        lines.insert(5, ("dither choice", picked))
    if mc:
        lines[3] = ("fit", lines[3][1] + " (%dx%d wide pixels)" % (mw // 2, mh))
        lines.insert(1, ("mode", MODE_MC))
    return "".join("%s: %s\n" % kv for kv in lines)


def save(out, dst, text):
    """out as dst: tagged sRGB, with text (settings) in a tEXt chunk."""
    info = PngImagePlugin.PngInfo()
    info.add_text(TEXT_KEY, text)
    out.save(dst, icc_profile=SRGB_ICC, pnginfo=info)


def candidate(img, system, name, dither, runs, frame, box, chroma, view=None, mc=False):
    """One dither tried for -w: (name, the output, its scores and wrong pixels), as the
    screen shows it (view, -P, or VICE's Colodore). Multicolour pictures are scored as
    they are, each pixel doubled (the converter shows nearly every pixel of them, so it
    is not run), wrong pixels None."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from vic2 import dither_pick
    out = convert(img, system, parse_dither(dither), frame, box, chroma, runs, view, mc)
    if mc:
        c64, wrong = out.resize((2 * out.width, out.height), Image.Resampling.NEAREST), None
    else:
        c64, wrong = dither_pick.shown(out, system, view)
    r = dither_pick.scores(c64, img.resize(c64.size, Image.Resampling.LANCZOS))
    r.update(setting=name, dither=dither, runs=runs, wrong=wrong)
    return r, out


def pick(futures, weights):
    """The best of a picture's candidates: (result, output, ranked results)."""
    from vic2 import dither_pick
    done = [f.result() for f in futures]
    outs = {r["setting"]: out for r, out in done}
    ranked = dither_pick.rank([r for r, _ in done], weights)
    return ranked[0], outs[ranked[0]["setting"]], ranked


def parse_weights(v):
    """-w RMS,SSIM,COLOR."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from vic2 import dither_pick
    except ImportError as e:
        raise argparse.ArgumentTypeError("needs the repo's vic2 package and numpy (%s)" % e)
    try:
        return dither_pick.parse_weights(v)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


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
    ap.add_argument("-d", "--dither", type=parse_dither, metavar="MODE",
                    help="floydsteinberg (fs[:K]), atkinson[:K], hybrid[:E] or none; "
                         "default: pick per picture (see -w)")
    ap.add_argument("-w", "--weights", type=parse_weights, metavar="R,S,C",
                    help="without -d: weights for blurred RMS, SSIM and colour error when "
                         "picking the dither (default 0,1,1)")
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
    if a.multicolor and a.dither and a.dither[0] == "hybrid":
        ap.error("-d hybrid works on hires cells; not with -m")
    if a.line_runs is not None:
        if not a.dither or a.dither[0] != "hybrid":
            ap.error("-l needs -d hybrid")
        if a.line_runs == "none":
            a.line_runs = None
        elif a.line_runs.isdigit() and int(a.line_runs) <= 8:
            a.line_runs = int(a.line_runs)
        else:
            ap.error("-l takes 0-8 or none")
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
    pool = tried = None
    if not a.dither:
        weights = a.weights or parse_weights("0,1,1")
        from vic2 import dither_pick
        pool = ProcessPoolExecutor()
        # every candidate of every picture at once, so the pool stays busy
        cands = [c for c in dither_pick.CANDIDATES
                 if not (a.multicolor and c[1].startswith("hybrid"))]
        tried = [[pool.submit(candidate, imgs[src], system, name, d, runs, a.border, a.size,
                              a.chroma, view, a.multicolor) for name, d, runs in cands]
                 for src, _, system in jobs]
    try:
        for i, (src, dst, system) in enumerate(jobs):
            note = ""
            if tried:
                best, out, ranked = pick(tried[i], weights)
                dither, runs = parse_dither(best["dither"]), best["runs"]
                picked = ("picked by img2c64 from %d dithers (weights rms %g, ssim %g, "
                          "color %g): %s" % ((len(ranked),) + tuple(weights) + (
                              ", ".join("%s %.2f" % (r["setting"], r["score"])
                                        for r in ranked[:3]),)))
                note = "; dither %s (next: %s)" % (best["setting"], ", ".join(
                    "%s %.2f" % (r["setting"], r["score"]) for r in ranked[1:3]))
            else:
                dither, runs, picked = a.dither, a.line_runs, None
                out = convert(imgs[src], system, dither, a.border, a.size, a.chroma, runs,
                              view, a.multicolor)
            save(out, dst, settings(src, system, dither, a.border, a.size, a.chroma, runs,
                                    picked, view_name, a.multicolor))
            print("%s -> %s (%dx%d%s%s)%s" % (src, dst, out.width, out.height,
                                            " wide pixels" if a.multicolor else "",
                                            ", " + system.upper() if system else "", note),
                  flush=True)
    finally:
        if pool:
            pool.shutdown(cancel_futures=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
