"""Convert images to .v2i files, assemble the slideshow, viewer and demos, build a D64
and optionally verify in VICE.

usage: python3 -m vic2.build [-b] [--at COLUMN,ROW] [--disk d64|d81] [--convert-only]
                             [--force] [--verify] [--run] [images...]

Each image is converted once: build/<name>.json records what the conversion depended on,
and later builds reuse the .v2i while that is unchanged (--force converts anyway).
--convert-only converts and builds nothing else; the Makefile uses it to convert images one
by one (make -j converts them in parallel).

File formats: docs/v2i-format.md (.v2i images) and docs/v2t-format.md (.v2t text and the
font). The C64 libraries that use them: docs/v2i-lib.md and docs/v2t-lib.md.
"""

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys

from PIL import Image

from . import convert
from .ask import Ask
from .font import Font
from .palette import load_indexed, save_indexed, PEPTO, nearest, load_vpl
from .screen import Screen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
ASM = os.path.join(ROOT, "asm")
V2I_VERSION = 1
V2I_LOAD = 0x2000
V2T_LOAD = 0x1800
V2T_VERSION = 3
TEXT_LEADING = 2              # default pixel lines between text lines (--leading)
TEXT_TITLE = (1 << 4) | 0     # "# " lines: white on black
TEXT_BODY = (15 << 4) | 0     # light grey on black
VPL = "/opt/homebrew/share/vice/C64/pepto-pal.vpl"
FRAME = (1, 1, 0, 1)          # frame rings from the outside in (palette indices)


def rle_zero(data):
    """$00,n = n zero bytes (1..255); other bytes literal; $00,$00 ends."""
    out = bytearray()
    i = 0
    while i < len(data):
        if data[i] == 0:
            n = 1
            while i + n < len(data) and data[i + n] == 0 and n < 255:
                n += 1
            out += bytes((0, n))
            i += n
        else:
            out.append(data[i])
            i += 1
    return out + b"\0\0"


CACHE_VERSION = 1             # bump when the .v2i/.txt packing below changes
CACHE_SOURCES = ("convert.py", "timing.py", "palette.py", "font.py")


def cache_key(path, frame, leading, at):
    """Everything a conversion depends on: the image, its text, the options and the
    converter sources."""
    h = hashlib.sha1(repr((CACHE_VERSION, frame, leading, at)).encode())
    txt = os.path.splitext(path)[0] + ".txt"
    for f in [path, txt] + [os.path.join(ROOT, "vic2", s) for s in CACHE_SOURCES]:
        if os.path.exists(f):             # contents only: the same file may be named
            with open(f, "rb") as fh:     # by a relative or an absolute path
                data = fh.read()
            h.update(b"%d:" % len(data) + data)
        else:
            h.update(b"-")
    return h.hexdigest()


def log_stats(inf, log, cached=False):
    w, h = inf["w"], inf["h"]
    log("%-17s %3dx%-3d bad lines %3d/%-3d  wrong pixels %5d (%.1f%%)  first bad line %3d  %5d bytes%s" %
        (inf["name"], w, h, len(inf["bad_lines"]), h, inf["wrong_px"], 100.0 * inf["wrong_px"] / (w * h),
         inf["first_bad"], inf["size"], "  (cached)" if cached else ""))


def cached_image(path, key):
    """The info convert_image returned for path last time, if nothing changed since."""
    name = os.path.splitext(os.path.basename(path))[0]
    meta = os.path.join(BUILD, name + ".json")
    try:
        with open(meta) as f:
            inf = json.load(f)
    except (OSError, ValueError):
        return None
    files = [inf.get("v2i"), inf.get("expected_png")] + ([inf["txt"]] if inf.get("txt") else [])
    if inf.get("key") != key or not all(f and os.path.exists(f) for f in files):
        return None
    os.utime(meta)                      # up to date (for make)
    g = inf.pop("geom")
    inf["geom"] = convert.Geometry(inf["w"], inf["h"], frame=g["frame"], at=(g["col0"], g["row0"]))
    inf["expected"] = load_indexed(inf["expected_png"])[2]
    return inf


def convert_image(path, log=print, frame=False, leading=TEXT_LEADING, at=None, force=False):
    """Convert one image to build/<name>.v2i (and its text to build/<name>.txt.prg). Reuses
    the previous result (build/<name>.json) when nothing it depends on changed, unless
    force."""
    name = os.path.splitext(os.path.basename(path))[0]
    key = cache_key(path, frame, leading, at)
    if not force:
        inf = cached_image(path, key)
        if inf:
            log_stats(inf, log, cached=True)
            return inf
    w, h, img = load_indexed(path)
    pos = at or ((1, 1) if frame else (0, 0))
    if frame and not convert.Geometry.frame_fits(pos[0], pos[1], w // 8, h // 8):
        log("  %s: %dx%d, no room for a frame" % (name, w, h))
        frame = False
        pos = at or (0, 0)
    conv = convert.Converter(img, log=lambda m: log("  " + m), frame=frame, at=pos)
    g = conv.g
    conv.run()
    bits = conv.bitmap()
    # bitmap and screen are stored as whole screen rows (zero padded, zero-run compressed),
    # so the player can decode them straight into place
    bmp = bytearray(320 * g.rows)
    scr = bytearray(40 * g.rows)
    for cy in range(g.rows):
        for cx in range(g.cols):
            fg, bg = conv.pairs[cy][cx]
            o = cy * 320 + (g.col0 + cx) * 8
            for i in range(8):
                y = cy * 8 + i
                b = 0
                for j in range(8):
                    if bits[y][cx * 8 + j]:
                        b |= 0x80 >> j
                bmp[o + i] = b
            scr[cy * 40 + g.col0 + cx] = (fg << 4) | bg
    # sprite blocks, slot ZERO_SLOT first
    slots = {}
    for s in range(8):
        for r, sbits in conv.sdata[s].items():
            k = convert.block_of(s, r)
            slot = g.slot_of(s, k)
            assert slot != convert.ZERO_SLOT
            row = r - convert.block_start(s, k)
            blk = slots.setdefault(slot, bytearray(64))
            blk[row * 3:row * 3 + 3] = sbits.to_bytes(3, "big")
    nslots = (max(slots) - convert.ZERO_SLOT + 1) if slots else 1
    spr = bytearray(64 * nslots)
    for slot, blk in slots.items():
        o = (slot - convert.ZERO_SLOT) * 64
        spr[o:o + 64] = blk
    os.makedirs(BUILD, exist_ok=True)
    packed = [bytes(conv.kernel.code), rle_zero(bmp), rle_zero(scr), rle_zero(spr)]
    out = conv.render()
    expected_png = os.path.join(BUILD, "%s_expected.png" % name)
    save_indexed(expected_png, out)
    wrong_px = sum(1 for y in range(h) for x in range(w) if out[y][x] != img[y][x])
    bad_lines = sorted(y for y in range(h) if any(out[y][x] != img[y][x] for x in range(w)))
    first_bad = bad_lines[0] if bad_lines else h
    hdr = bytearray(b"V2I") + bytes((V2I_VERSION, g.cols, g.rows, g.col0, g.row0))
    for v in [len(d) for d in packed] + [0xE000 + 320 * g.row0, 0xC000 + 40 * g.row0,
                                         len(bad_lines), min(wrong_px, 0xFFFF)]:
        hdr += v.to_bytes(2, "little")
    assert len(hdr) == 24
    v2i = os.path.join(BUILD, name + ".v2i")
    with open(v2i, "wb") as f:
        f.write(V2I_LOAD.to_bytes(2, "little") + hdr + b"".join(packed))
    size = os.path.getsize(v2i) - 2
    txt = os.path.splitext(path)[0] + ".txt"
    txt = make_text(txt, g, name, log, leading) if os.path.exists(txt) else None
    info = dict(txt=txt, name=name, w=w, h=h, geom=g, expected=out, size=size,
                bad_lines=bad_lines, wrong_px=wrong_px, first_bad=first_bad, v2i=v2i)
    log_stats(info, log)
    # side-by-side: source | expected C64 output | wrong pixels
    sbs = Image.new("RGB", (w * 3 + 16, h), (40, 40, 40))
    for i, rows in enumerate((img, out)):
        part = Image.new("RGB", (w, h))
        part.putdata([PEPTO[c] for row in rows for c in row])
        sbs.paste(part, (i * (w + 8), 0))
    diff = Image.new("RGB", (w, h))
    diff.putdata([(255, 0, 64) if out[y][x] != img[y][x] else tuple(v // 4 for v in PEPTO[img[y][x]])
                  for y in range(h) for x in range(w)])
    sbs.paste(diff, (2 * (w + 8), 0))
    sbs.resize((sbs.width * 3, sbs.height * 3), Image.NEAREST).save(
        os.path.join(BUILD, "%s_compare.png" % name))
    meta = {k: v for k, v in info.items() if k not in ("geom", "expected")}
    meta.update(key=key, expected_png=expected_png,
                geom=dict(col0=g.col0, row0=g.row0, frame=g.frame))
    with open(os.path.join(BUILD, name + ".json"), "w") as f:
        json.dump(meta, f)
    return info


def write_inc(infos, auto_frames):
    lines = ["IMAGE_COUNT = %d" % len(infos), "AUTO_FRAMES = %d" % auto_frames, "", "        .data"]
    lines.append("img_lo: .byte %s" % ",".join("<img%d" % i for i in range(len(infos))))
    lines.append("img_hi: .byte %s" % ",".join(">img%d" % i for i in range(len(infos))))
    lines.append("txt_lo: .byte %s" % ",".join("<txt%d" % i if f["txt"] else "0" for i, f in enumerate(infos)))
    lines.append("txt_hi: .byte %s" % ",".join(">txt%d" % i if f["txt"] else "0" for i, f in enumerate(infos)))
    for i, inf in enumerate(infos):
        lines.append('img%d: .incbin "%s", 2' % (i, inf["v2i"]))
        if inf["txt"]:
            lines.append('txt%d: .incbin "%s", 2' % (i, inf["txt"]))
    with open(os.path.join(BUILD, "images.inc"), "w") as f:
        f.write("\n".join(lines) + "\n")


def write_diskshow_inc(infos, hold_frames):
    """File names for asm/diskshow.s, as c1541 writes them (see disk_files)."""
    def entry(label, name):
        return "%s: .byte %d,%s" % (label, len(name), ",".join("$%02x" % petscii(c) for c in name))
    lines = ["SHOW_COUNT = %d" % len(infos), "HOLD_FRAMES = %d" % hold_frames, "", "        .data"]
    lines.append("name_lo: .byte %s" % ",".join("<dsn%d" % i for i in range(len(infos))))
    lines.append("name_hi: .byte %s" % ",".join(">dsn%d" % i for i in range(len(infos))))
    lines.append("tname_lo: .byte %s" % ",".join("<dst%d" % i if f["txt"] else "0" for i, f in enumerate(infos)))
    lines.append("tname_hi: .byte %s" % ",".join(">dst%d" % i if f["txt"] else "0" for i, f in enumerate(infos)))
    for i, inf in enumerate(infos):
        lines.append(entry("dsn%d" % i, disk_name(inf["name"])))
        if inf["txt"]:
            lines.append(entry("dst%d" % i, text_disk_name(inf["name"])))
    with open(os.path.join(BUILD, "diskshow.inc"), "w") as f:
        f.write("\n".join(lines) + "\n")


def text_layout(text, font, px, height, leading=0):
    """Word-wrap paragraphs (blank-line separated) to px pixels. A paragraph starting with
    "# " is a title. Lines are 8 + leading pixels apart in a height pixel area. Returns
    [(colour, line)] and the number of lines that did not fit."""
    rows = []
    for i, para in enumerate(p for p in text.strip().split("\n\n") if p.strip()):
        col = TEXT_BODY
        para = " ".join(para.split())
        if para.startswith("# "):
            col, para = TEXT_TITLE, para[2:]
        if i:
            rows.append((TEXT_BODY, ""))
        rows += [(col, l) for l in font.wrap(para, px)]
    fit = (height + leading) // (8 + leading)
    return rows[:fit], max(0, len(rows) - fit)


def text_area(g, min_width=8):
    """(column, row, width, height) in cells of the free area beside the image (one cell
    margin): right of it, else left, else below, else above. None if nothing fits."""
    x0, x1 = g.col0 - g.frame, g.col0 + g.cols + g.frame      # occupied columns x0..x1-1
    y0, y1 = g.row0 - g.frame, g.row0 + g.rows + g.frame
    for col0, row0, width, height in ((x1 + 1, 0, 40 - x1 - 1, 25), (0, 0, x0 - 1, 25),
                                      (0, y1 + 1, 40, 25 - y1 - 1), (0, 0, 40, y0 - 1)):
        if width >= min_width and height > 0:
            return col0, row0, width, height
    return None


def make_text(path, g, name, log, leading=TEXT_LEADING):
    """Pack input/<name>.txt for the free area beside the image (see text_area)."""
    from .font import screen_code
    with open(path) as f:
        text = f.read()
    area = text_area(g)
    if area is None:
        log("  %s: no room for text" % name)
        return None
    col0, row0, width, height = area
    rows, lost = text_layout(text, Font(), width * 8, height * 8, leading)
    if lost:
        log("  %s: text does not fit, %d line(s) dropped" % (name, lost))
    data = bytearray(b"V2T") + bytes((V2T_VERSION, col0, row0, width, len(rows), 0, leading))
    for colour, line in rows:
        data += bytes((colour, len(line))) + bytes(screen_code(c) for c in line)
    out = os.path.join(BUILD, name + ".txt.prg")
    with open(out, "wb") as f:
        f.write(V2T_LOAD.to_bytes(2, "little") + data)
    log("  %s: text area %dx%d at column %d, row %d: %d lines, leading %d" %
        (name, width, height, col0, row0, len(rows), leading))
    return out


def disk_name(name):
    return name.upper().replace("-C64", "")[:16]


def text_disk_name(name):
    return disk_name(name)[:12] + ".TXT"


def petscii(c):
    """The byte c1541 writes for c in a file name we pass in lower case (A-Z as typed on the
    C64, unshifted)."""
    return ord(c.upper())


DISKS = {"d64": (664, 144), "d81": (3160, 296)}     # free blocks, directory entries


def blocks(path):
    return max(1, -(-os.path.getsize(path) // 254))


def make_disk(files, kind):
    """Write build/vic2orious.<kind> with files [(path, disk name)]; kind None: d64 if
    everything fits, else d81. Removes the other kind. Returns the disk's path."""
    need = sum(blocks(p) for p, _ in files)
    fits = [k for k, (free, entries) in DISKS.items() if need <= free and len(files) <= entries]
    if kind is None:
        if not fits:
            raise SystemExit("%d files (%d blocks) do not fit even on a d81; pass fewer images"
                             % (len(files), need))
        kind = fits[0]
    elif kind not in fits:
        raise SystemExit("%d files (%d blocks) do not fit on a %s (%d blocks); try --disk d81"
                         % (len(files), need, kind, DISKS[kind][0]))
    disk = os.path.join(BUILD, "vic2orious." + kind)
    for k in DISKS:
        if os.path.exists(os.path.join(BUILD, "vic2orious." + k)):
            os.remove(os.path.join(BUILD, "vic2orious." + k))
    cmd = ["c1541", "-format", "vic2orious,v2", kind, disk]
    for path, name in files:
        cmd += ["-write", path, name.lower()]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    print("%s: %d files, %d of %d blocks" % (disk, len(files), need, DISKS[kind][0]))
    return disk


class Overflow(SystemExit):
    pass


def assemble(out_prg, source="slideshow.s", frame=False, defines=()):
    with open(os.path.join(BUILD, "font.inc"), "w") as f:
        f.write(Font().asm())
    defs = []
    for d in ["FRAME=%d" % frame] + list(defines):
        defs += ["--asm-define", d]
    res = subprocess.run(["cl65", "-t", "none", "-C", os.path.join(ASM, "c64.cfg"), "-I", BUILD,
                          "--asm-include-dir", BUILD, "--asm-include-dir", ASM] + defs +
                         ["-o", out_prg, os.path.join(ASM, source)],
                         cwd=BUILD, capture_output=True, text=True)
    for f in glob.glob(os.path.join(ASM, "*.o")):
        os.remove(f)
    if res.returncode:
        msg = res.stderr.strip()
        if "overflows memory area" in msg:
            raise Overflow("assembly failed:\n" + msg + "\n(the images do not all fit in one PRG)")
        raise SystemExit("assembly failed:\n" + msg)


SLIDESHOW_SPACE = 0xC000 - 0x0801 - 3000    # a little more than is left for images


def assemble_slideshow(prg, infos, auto, frame):
    """Assemble the slideshow with as many of the images (from the first on) as fit.
    Returns how many."""
    n, total = 0, 0
    for inf in infos:
        total += inf["size"] + (os.path.getsize(inf["txt"]) - 2 if inf["txt"] else 0)
        if total > SLIDESHOW_SPACE:
            break
        n += 1
    while n:
        write_inc(infos[:n], auto)
        try:
            assemble(prg, frame=frame)
            return n
        except Overflow:
            n -= 1
    raise SystemExit("not even the first image fits in the slideshow")


def diskshow_screenshot(prg, disk, png, cycles):
    """Like vice_screenshot, with disk in drive 8 (true drive emulation)."""
    if os.path.exists(png):
        os.remove(png)
    cmd = ["x64sc", "-default", "-pal", "-warp", "-sounddev", "dummy", "+sound",
           "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", "pepto-pal.vpl"]
    if disk.endswith(".d81"):
        cmd += ["-drive8type", "1581"]
    cmd += ["-8", disk, "-autostartprgmode", "1", "-autostart", prg,
            "-limitcycles", str(cycles), "-exitscreenshot", png]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
    return os.path.exists(png)


def vice_screenshot(prg, png, cycles=10_000_000):
    if os.path.exists(png):
        os.remove(png)
    cmd = ["x64sc", "-default", "-pal", "-warp", "-sounddev", "dummy", "+sound",
           "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", "pepto-pal.vpl",
           "-autostartprgmode", "1", "-limitcycles", str(cycles), "-exitscreenshot", png, prg]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    return os.path.exists(png)


def framed(img):
    """img (palette indices) with the frame v2i_frame draws around it."""
    h, w = len(img) + 8, len(img[0]) + 8
    out = [[FRAME[min(x, y, w - 1 - x, h - 1 - y)] if min(x, y, w - 1 - x, h - 1 - y) < 4 else 0
            for x in range(w)] for y in range(h)]
    for y, row in enumerate(img):
        out[y + 4][4:-4] = row
    return out


def expected_screen(inf, frame_img=True, text=True):
    """320x200 palette indices: the image (and frame) as the converter modelled it, plus its
    .v2t text drawn as v2t_draw would."""
    scr = Screen()
    if text and inf["txt"]:
        with open(inf["txt"], "rb") as f:
            scr.v2t(Font(), f.read()[2:])
    g = inf["geom"]
    if g.frame and frame_img:
        scr.paste(framed(inf["expected"]), g.col0 * 8 - 4, g.row0 * 8 - 4)
    else:
        scr.paste(inf["expected"], g.col0 * 8, g.row0 * 8)
    return scr


def compare_screenshot(png, exp):
    """Locate the screen exp (palette indices; only its non-black bounding box counts) in
    the screenshot and list pixels differing from it. VICE renders its own idea of the
    palette, so screenshot colours are mapped to palette indices by majority vote."""
    im = Image.open(png).convert("RGB")
    W, H = im.size
    px = im.load()
    ys = [y for y in range(len(exp)) if any(exp[y])]
    xs = [x for x in range(len(exp[0])) if any(row[x] for row in exp)]
    nz = [(x, y) for y in range(H) for x in range(W) if px[x, y] != (0, 0, 0)]
    if not nz or not xs:
        return None
    exp = [row[xs[0]:xs[-1] + 1] for row in exp[ys[0]:ys[-1] + 1]]
    w, h = len(exp[0]), len(exp)
    ox = min(x for x, _ in nz)
    oy = min(y for _, y in nz)
    best = None
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            votes = {}
            for y in range(h):
                for x in range(w):
                    X, Y = ox + dx + x, oy + dy + y
                    if 0 <= X < W and 0 <= Y < H:
                        v = votes.setdefault(px[X, Y], {})
                        v[exp[y][x]] = v.get(exp[y][x], 0) + 1
            score = sum(max(v.values()) for v in votes.values())
            if best is None or score > best[0]:
                best = (score, ox + dx, oy + dy, votes)
    _, ox, oy, votes = best
    cmap = {rgb: max(v, key=v.get) for rgb, v in votes.items()}
    wrong = []
    for y in range(h):
        for x in range(w):
            v = cmap[px[ox + x, oy + y]]
            if v != exp[y][x]:
                wrong.append((x + xs[0], y + ys[0], exp[y][x], v))
    return ox, oy, wrong


V2T_DEMO_TITLE = "v2t demo: text without an image"
V2T_DEMO_FOOT = "Press any key"
V2T_DEMO_POS = (16, 30)       # TXT_X, TXT_Y in asm/v2t-demo.s


def write_v2t_demo_inc(inf):
    from .font import screen_code
    def string(label, text):
        return "%s: .byte %s,0" % (label, ",".join("%d" % screen_code(c) for c in text))
    with open(os.path.join(BUILD, "v2tdemo.inc"), "w") as f:
        f.write("\n".join(["        .data", 'demo_txt: .incbin "%s", 2' % inf["txt"],
                           string("demo_title", V2T_DEMO_TITLE), string("demo_foot", V2T_DEMO_FOOT)])
                + "\n")


def v2t_demo_screen(inf):
    """What asm/v2t-demo.s draws."""
    from .font import screen_code
    font, scr = Font(), Screen()
    scr.clear(0, 0, 40, 25, 0xF0)
    codes = lambda text: [screen_code(c) for c in text]
    scr.text_line(font, (320 - font.width(V2T_DEMO_TITLE)) // 2, 8, 40, 0x10, codes(V2T_DEMO_TITLE))
    with open(inf["txt"], "rb") as f:
        scr.v2t(font, f.read()[2:], *V2T_DEMO_POS, lead=2)
    scr.text_line(font, 312 - font.width(V2T_DEMO_FOOT), 184, 40, 0xB0, codes(V2T_DEMO_FOOT))
    return scr


def check_in_vice(prg, png, exp, label):
    """Screenshot prg in VICE and compare with exp."""
    if not vice_screenshot(prg, png):
        print("  %s: no screenshot" % label)
        return False
    res = compare_screenshot(png, exp)
    if res is None:
        print("  %s: nothing found in the screenshot" % label)
        return False
    wrong = res[2]
    print("  %s: VICE output vs model: %d differing pixels" % (label, len(wrong)))
    for wv in wrong[:12]:
        print("     x=%d y=%d expected %d got %d" % wv)
    return not wrong


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="*")
    ap.add_argument("-b", "--frame", action="store_true",
                    help="frame the images: place them at row 1, column 1 (where they fit) and "
                         "build the slideshow and viewer to draw a frame around them")
    ap.add_argument("--verify", action="store_true", help="screenshot each image in VICE and compare")
    ap.add_argument("--run", action="store_true", help="launch the slideshow in VICE")
    ap.add_argument("--leading", type=int, default=TEXT_LEADING,
                    help="blank pixel lines between text lines (default %d)" % TEXT_LEADING)
    ap.add_argument("--at", metavar="COLUMN,ROW",
                    help="place the images at this character column and row (default 0,0; 1,1 "
                         "with -b)")
    ap.add_argument("--auto", type=int, default=250,
                    help="frames per image (max 255) in the slideshow (0: until space)")
    ap.add_argument("--hold", type=int, default=15,
                    help="seconds per image (max 1300) in diskshow, not counting the loading "
                         "(0: until space)")
    ap.add_argument("--disk", choices=sorted(DISKS),
                    help="disk image type (default: d64 if everything fits, else d81)")
    ap.add_argument("--convert-only", action="store_true",
                    help="convert the images and build nothing else")
    ap.add_argument("--force", action="store_true", help="convert images even if unchanged")
    a = ap.parse_args()
    if not 0 <= a.auto <= 255:
        ap.error("--auto must be 0..255")
    if not 0 <= a.hold <= 1300:
        ap.error("--hold must be 0..1300")
    if not 0 <= a.leading <= 64:
        ap.error("--leading must be 0..64")
    at = None
    if a.at:
        try:
            at = tuple(int(v) for v in a.at.split(","))
            assert len(at) == 2
        except (ValueError, AssertionError):
            ap.error("--at takes COLUMN,ROW")
    images = a.images or sorted(glob.glob(os.path.join(ROOT, "input", "*.png")))
    os.makedirs(BUILD, exist_ok=True)
    infos = [convert_image(p, frame=a.frame, leading=a.leading, at=at, force=a.force)
             for p in images]
    if a.convert_only:
        return 0
    prg = os.path.join(BUILD, "slideshow.prg")
    in_prg = assemble_slideshow(prg, infos, a.auto, a.frame)
    if in_prg < len(infos):
        print("slideshow.prg holds the first %d of the %d images; diskshow loads them all from disk"
              % (in_prg, len(infos)))
    diskshow = os.path.join(BUILD, "diskshow.prg")
    write_diskshow_inc(infos, a.hold * 50)
    assemble(diskshow, "diskshow.s", frame=a.frame)
    viewer = os.path.join(BUILD, "viewer.prg")
    assemble(viewer, "viewer.s", frame=a.frame)
    demos = []
    v2i_demo = os.path.join(BUILD, "v2i-demo.prg")
    with open(os.path.join(BUILD, "v2idemo.inc"), "w") as f:
        f.write('        .data\ndemo_img: .incbin "%s", 2\n' % infos[0]["v2i"])
    assemble(v2i_demo, "v2i-demo.s", frame=a.frame)
    demos.append((v2i_demo, "v2i demo"))
    story = next((inf for inf in infos if inf["txt"]), None)
    if story:
        v2t_demo = os.path.join(BUILD, "v2t-demo.prg")
        write_v2t_demo_inc(story)
        assemble(v2t_demo, "v2t-demo.s")
        demos.append((v2t_demo, "v2t demo"))
    asks = []
    for img_path, inf in zip(images, infos):
        path = os.path.splitext(img_path)[0] + ".ask"
        if os.path.exists(path):
            area = text_area(inf["geom"], min_width=12)
            if area is None:
                print("  ask %s: no room beside the image" % inf["name"])
                continue
            ask = Ask(path, inf, area, a.leading)
            ask.write_inc(os.path.join(BUILD, "ask.inc"))
            out = os.path.join(BUILD, "ask-%s.prg" % inf["name"])
            assemble(out, "ask.s", frame=a.frame)
            asks.append((ask, out))
    files = [(viewer, "viewer"), (diskshow, "diskshow"), (prg, "slideshow")]
    for inf in infos:
        files.append((inf["v2i"], disk_name(inf["name"])))
        if inf["txt"]:
            files.append((inf["txt"], text_disk_name(inf["name"])))
    for ask, out in asks:
        files.append((out, "ask " + disk_name(ask.info["name"])[:12]))
    files += demos
    disk = make_disk(files, a.disk)
    print("built %s (%d bytes), %s, %s and %s" % (prg, os.path.getsize(prg), diskshow, viewer, disk))
    print("disk files: " + ", ".join(name.lower() for _, name in files))
    ok = True
    if a.verify:
        font = Font()
        for inf in infos:
            write_inc([inf], 255)
            one = os.path.join(BUILD, "verify_%s.prg" % inf["name"])
            assemble(one, frame=a.frame)
            png = os.path.join(BUILD, "vice_%s.png" % inf["name"])
            ok &= check_in_vice(one, png, expected_screen(inf).pixels(), inf["name"])
        for ask, _ in asks:
            sel = len(ask.topics) - 1
            ask.write_inc(os.path.join(BUILD, "ask.inc"))
            one = os.path.join(BUILD, "verify_ask_%s.prg" % ask.info["name"])
            assemble(one, "ask.s", frame=a.frame, defines=["AUTO=%d" % (sel + 1)])
            scr = expected_screen(ask.info, text=False)
            ask.model(scr, font, sel)
            png = os.path.join(BUILD, "vice_ask_%s.png" % ask.info["name"])
            ok &= check_in_vice(one, png, scr.pixels(), "ask " + ask.info["name"])
        ok &= check_in_vice(v2i_demo, os.path.join(BUILD, "vice_v2i_demo.png"),
                            expected_screen(infos[0], text=False).pixels(), "v2i demo")
        if story:
            ok &= check_in_vice(v2t_demo, os.path.join(BUILD, "vice_v2t_demo.png"),
                                v2t_demo_screen(story).pixels(), "v2t demo")
        # diskshow: the first image (and its text) from a disk of its own, shown until space
        inf = infos[0]
        write_diskshow_inc([inf], 0)
        one = os.path.join(BUILD, "verify_diskshow.prg")
        assemble(one, "diskshow.s", frame=a.frame)
        vdisk = os.path.join(BUILD, "verify_diskshow.d64")
        cmd = ["c1541", "-format", "verify,v2", "d64", vdisk, "-write", inf["v2i"],
               disk_name(inf["name"]).lower()]
        if inf["txt"]:
            cmd += ["-write", inf["txt"], text_disk_name(inf["name"]).lower()]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        png = os.path.join(BUILD, "vice_diskshow.png")
        size = inf["size"] + (os.path.getsize(inf["txt"]) if inf["txt"] else 0)
        if diskshow_screenshot(one, vdisk, png, 40_000_000 + 8_000 * size):
            res = compare_screenshot(png, expected_screen(inf).pixels())
            n = len(res[2]) if res else -1
            print("  diskshow: VICE output vs model: %d differing pixels" % n)
            ok &= n == 0
        else:
            print("  diskshow: no screenshot")
            ok = False
        write_diskshow_inc(infos, a.hold * 50)
        assemble(diskshow, "diskshow.s", frame=a.frame)
        assemble_slideshow(prg, infos, a.auto, a.frame)
    if a.run:
        subprocess.Popen(["x64sc", "-pal", "-VICIIextpal", "-VICIIpalette", "pepto-pal.vpl",
                          "-autostartprgmode", "1", prg],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
