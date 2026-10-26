"""Convert images to .v2i files, assemble the slideshow, viewer and demos, build a D64
and optionally verify in VICE.

usage: python3 -m vic2.build [-b] [--at COLUMN,ROW] [--font FILE.cvt[:SIZE]] [--ntsc | --dual]
                             [--disk d64|d81] [--convert-only] [--force] [--verify] [--run]
                             [images...]

Kernels are cycle exact for one video system: PAL by default, NTSC (6567R8) with --ntsc.
A PAL build goes to build/pal/, an NTSC build to build/ntsc/, so both can be kept;
--dual builds both and a disk with both in build/dual/.

Each image is converted once: build/<system>/<name>.json records what the conversion depended on,
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

from . import convert, timing
from . import font as fonts
from .ask import Ask, NoRoom
from .palette import load_indexed, save_indexed, PEPTO, nearest, load_vpl
from .screen import Screen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build", "pal")  # build/ntsc with --ntsc (see use_system)
ASM = os.path.join(ROOT, "asm")
V2I_VERSION = 3
V2I_LOAD = 0x2000
PLAYER_BUF = 0x2800           # diskshow and viewer load images here, texts at $9800
V2T_LOAD = 0x1800
V2T_VERSION = 4
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


CACHE_VERSION = 5             # bump when the .v2i packing below changes
CACHE_SOURCES = ("convert.py", "timing.py", "palette.py")


def cache_key(path, frame, at):
    """Everything an image conversion depends on: the image, the options and the converter
    sources. Not the text: make_text packs that again on every build (it is quick)."""
    h = hashlib.sha1(repr((CACHE_VERSION, timing.STANDARD, frame, at)).encode())
    for f in [path] + [os.path.join(ROOT, "vic2", s) for s in CACHE_SOURCES]:
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
    files = [inf.get("v2i"), inf.get("expected_png")]
    if inf.get("key") != key or not all(f and os.path.exists(f) for f in files):
        return None
    os.utime(meta)                      # up to date (for make)
    g = inf.pop("geom")
    inf["geom"] = convert.Geometry(inf["w"], inf["h"], frame=g["frame"], at=(g["col0"], g["row0"]))
    inf["expected"] = load_indexed(inf["expected_png"])[2]
    return inf


def convert_image(path, log=print, frame=False, leading=TEXT_LEADING, at=None, force=False):
    """Convert one image to build/<name>.v2i, reusing the previous result (build/<name>.json)
    when nothing it depends on changed, unless force; then pack its text (input/<name>.txt)
    to build/<name>.txt.prg with the current font."""
    name = os.path.splitext(os.path.basename(path))[0]
    key = cache_key(path, frame, at)
    inf = None if force else cached_image(path, key)
    if inf:
        log_stats(inf, log, cached=True)
    else:
        inf = convert_new(path, name, key, log, frame, at)
    txt = os.path.splitext(path)[0] + ".txt"
    inf["txt"] = make_text(txt, inf["geom"], name, log, leading) if os.path.exists(txt) else None
    return inf


def convert_new(path, name, key, log, frame, at):
    """convert_image without the cache and the text."""
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
    hdr += bytes((timing.SYSTEM_ID[timing.STANDARD], 0))
    assert len(hdr) == 26
    assert len(hdr) + sum(len(d) for d in packed) <= 0x9800 - PLAYER_BUF, \
        "%s: .v2i too big for the players' buffer ($%04x-$97ff)" % (name, PLAYER_BUF)
    v2i = os.path.join(BUILD, name + ".v2i")
    with open(v2i, "wb") as f:
        f.write(V2I_LOAD.to_bytes(2, "little") + hdr + b"".join(packed))
    size = os.path.getsize(v2i) - 2
    info = dict(name=name, w=w, h=h, geom=g, expected=out, size=size,
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


def write_diskshow_inc(infos, hold_secs, dual=False):
    """File names for asm/diskshow.s, as c1541 writes them (see make_disk). dual: the image
    names without their -p.v2i / -n.v2i (diskshow adds the one that suits the machine)."""
    def entry(label, name):
        return "%s: .byte %d,%s" % (label, len(name), ",".join("$%02x" % petscii(c) for c in name))
    lines = ["SHOW_COUNT = %d" % len(infos), "HOLD_SECS = %d" % hold_secs, "", "        .data"]
    lines.append("name_lo: .byte %s" % ",".join("<dsn%d" % i for i in range(len(infos))))
    lines.append("name_hi: .byte %s" % ",".join(">dsn%d" % i for i in range(len(infos))))
    lines.append("tname_lo: .byte %s" % ",".join("<dst%d" % i if f["txt"] else "0" for i, f in enumerate(infos)))
    lines.append("tname_hi: .byte %s" % ",".join(">dst%d" % i if f["txt"] else "0" for i, f in enumerate(infos)))
    for i, inf in enumerate(infos):
        lines.append(entry("dsn%d" % i, dual_base(inf["name"]) if dual else disk_name(inf["name"])))
        if inf["txt"]:
            lines.append(entry("dst%d" % i, text_disk_name(inf["name"])))
    with open(os.path.join(BUILD, "diskshow.inc"), "w") as f:
        f.write("\n".join(lines) + "\n")


def text_layout(text, font, px, height, leading=0):
    """Word-wrap paragraphs (blank-line separated) to px pixels. A paragraph starting with
    "# " is a title. Lines are font height + leading pixels apart in a height pixel area. Returns
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
    fit = (height + leading) // (font.height + leading)
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
    font = fonts.current()
    with open(path) as f:
        text = f.read()
    area = text_area(g)
    if area is None:
        log("  %s: no room for text" % name)
        return None
    col0, row0, width, height = area
    out = os.path.join(BUILD, name + ".txt.prg")
    n = pack_text(text, out, col0, row0, width, height * 8, leading, name, log)
    log("  %s: text area %dx%d at column %d, row %d: %d lines, leading %d, font %s" %
        (name, width, height, col0, row0, n, leading, font.name))
    return out


def pack_text(text, out, col0, row0, width, px_height, leading, name, log):
    """Lay text out width cells wide in px_height pixel lines and write it to out as a .v2t
    PRG. Returns the number of lines."""
    font = fonts.current()
    rows, lost = text_layout(text, font, width * 8, px_height, leading)
    if lost:
        log("  %s: text does not fit, %d line(s) dropped" % (name, lost))
    data = bytearray(b"V2T") + bytes((V2T_VERSION, col0, row0, width, len(rows), font.height,
                                      leading))
    for colour, line in rows:
        data += bytes((colour, len(line))) + bytes(fonts.codes(line))
    with open(out, "wb") as f:
        f.write(V2T_LOAD.to_bytes(2, "little") + data)
    return len(rows)


def disk_name(name):
    return name.upper().replace("-C64", "")[:16]


def text_disk_name(name):
    return disk_name(name)[:12] + ".TXT"


def dual_base(name):
    """Image name on a dual disk, before -P.V2I / -N.V2I (16 characters in all)."""
    return disk_name(name)[:10]


SUFFIX = {"pal": "-P", "ntsc": "-N"}


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
        f.write(fonts.current().asm())
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
    cmd = ["x64sc", "-default", "-" + timing.STANDARD, "-warp", "-sounddev", "dummy", "+sound",
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
    cmd = ["x64sc", "-default", "-" + timing.STANDARD, "-warp", "-sounddev", "dummy", "+sound",
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
            scr.v2t(fonts.current(), f.read()[2:])
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
V2T_DEMO_X = 16               # TXT_X in asm/v2t-demo.s (TXT_Y, FOOT_Y: see v2t_demo_screen)
V2T_DEMO_TEXT = """# A sample text

No image in this build has a story (input/<name>.txt), so the v2t demo shows this one.

The build wraps it by pixel width; the C64 draws the glyphs and colours the cells."""


def v2t_demo_text(infos):
    """The .v2t the v2t demo draws: the first image's story, else V2T_DEMO_TEXT."""
    story = next((inf["txt"] for inf in infos if inf["txt"]), None)
    if story:
        return story
    font = fonts.current()
    out = os.path.join(BUILD, "v2tdemo.txt.prg")
    pack_text(V2T_DEMO_TEXT, out, 2, 0, 36, 170 - 2 * font.height, 2, "v2t demo", print)
    return out


def write_v2t_demo_inc(txt):
    def string(label, text):
        return "%s: .byte %s,0" % (label, ",".join("%d" % c for c in fonts.codes(text)))
    with open(os.path.join(BUILD, "v2tdemo.inc"), "w") as f:
        f.write("\n".join(["        .data", 'demo_txt: .incbin "%s", 2' % txt,
                           string("demo_title", V2T_DEMO_TITLE), string("demo_foot", V2T_DEMO_FOOT)])
                + "\n")


def v2t_demo_screen(txt):
    """What asm/v2t-demo.s draws."""
    font, scr = fonts.current(), Screen()
    scr.clear(0, 0, 40, 25, 0xF0)
    codes = fonts.codes
    scr.text_line(font, max(0, 320 - font.width(V2T_DEMO_TITLE)) // 2, 8, 40, 0x10, codes(V2T_DEMO_TITLE))
    with open(txt, "rb") as f:
        scr.v2t(font, f.read()[2:], V2T_DEMO_X, 22 + font.height, lead=2)
    scr.text_line(font, 312 - font.width(V2T_DEMO_FOOT), 192 - font.height, 40, 0xB0,
                  codes(V2T_DEMO_FOOT))
    return scr


SCROLL_X, SCROLL_COLS = 8, 38  # SCR_X, SCR_COLS in scroll.inc
SCROLL_TOP = 8                # page line of the first text line
SCROLL_VOFF = 4               # VOFF in asm/scroll.s: lines may start 32 pixels above a row
SCROLL_END = 0x4000           # asm/scroll.s must end below bitmap A's screen
SCROLL_INTRO = """# v2t scroll demo

Cursor down scrolls down, cursor up (shift + cursor down) scrolls up, one pixel per frame;
a joystick in port 2 works too. Space returns to BASIC.

The VIC's fine scroll moves the bitmap up to 7 pixels. Two bitmaps in two VIC banks take
turns: while one is shown, the main loop prepares the other one char row further, copying
24 rows from the shown one and drawing the new row with v2t_line, clipped to that row. At
the row boundary the raster IRQ switches banks and resets the fine scroll."""


def stories(images):
    """The text of every image's story (input/<name>.txt), in image order."""
    texts = []
    for p in images:
        t = os.path.splitext(p)[0] + ".txt"
        if os.path.exists(t):
            with open(t) as f:
                texts.append(f.read())
    return texts


def scroll_page(images, leading):
    """The scroll demo's page: the intro, then every image's story. [(colour, text, page y)]
    of the non-empty lines, and the page height."""
    font = fonts.current()
    texts = [SCROLL_INTRO] + stories(images)
    rows = []
    for t in texts:
        if rows:
            rows.append((TEXT_BODY, ""))
        rows += text_layout(t, font, SCROLL_COLS * 8, 1 << 30, leading)[0]
    pitch = font.height + leading
    lines = [(c, l, SCROLL_TOP + i * pitch) for i, (c, l) in enumerate(rows) if l]
    return lines, SCROLL_TOP + len(rows) * pitch - leading + 8


def write_scroll_inc(lines, height):
    font = fonts.current()
    vmax = max(0, height - 192)
    nrows = vmax // 8 + 27                # rows a buffer can show: base <= vmax + 8, 25 rows
    first, cnt, colour = [], [], []
    for j in range(nrows):
        hit = [i for i, (_, _, y) in enumerate(lines) if y < 8 * j + 8 and y + font.height > 8 * j]
        first.append(hit[0] if hit else 0)
        cnt.append(len(hit))
        colour.append(lines[hit[-1]][0] if hit else TEXT_BODY)    # the last line wins

    def table(label, values):
        out.append(label + ":")
        for i in range(0, len(values), 16):
            out.append("        .byte " + ",".join(values[i:i + 16]))

    out = ["SCR_N = %d" % len(lines), "SCR_VMAX = %d" % vmax, "SCR_X = %d" % SCROLL_X, "SCR_COLS = %d" % SCROLL_COLS, "        .data"]
    n = range(len(lines))
    table("scr_tlo", ["<scr_t%d" % i for i in n])
    table("scr_thi", [">scr_t%d" % i for i in n])
    table("scr_clr", ["$%02x" % lines[i][0] for i in n])
    table("scr_ylo", ["%d" % (lines[i][2] & 0xFF) for i in n])
    table("scr_first", ["%d" % v for v in first])
    table("scr_cnt", ["%d" % v for v in cnt])
    table("scr_rc", ["$%02x" % v for v in colour])
    for i, (_, text, _) in enumerate(lines):
        out.append("scr_t%d: .byte %s,0" % (i, ",".join("%d" % c for c in fonts.codes(text))))
    with open(os.path.join(BUILD, "scroll.inc"), "w") as f:
        f.write("\n".join(out) + "\n")
    return vmax


def build_scroll(images, leading, out, defines=(), log=print):
    """Assemble asm/scroll.s with as much of the page as fits below SCROLL_END (and at most
    255 lines). Returns (lines, page height, vmax)."""
    font = fonts.current()
    if font.height > 8 * SCROLL_VOFF:
        raise SystemExit("scroll demo: fonts up to %d pixels high" % (8 * SCROLL_VOFF))
    lines, height = scroll_page(images, leading)
    n = min(len(lines), 255)
    while True:
        part = lines[:n]
        h = height if n == len(lines) else part[-1][2] + font.height + 8
        vmax = write_scroll_inc(part, h)
        assemble(out, "scroll.s", defines=defines)
        if 0x0801 + os.path.getsize(out) - 2 <= SCROLL_END:
            break
        n = n * 9 // 10
    if n < len(lines):
        log("  scroll demo: the first %d of %d lines fit" % (n, len(lines)))
    return part, h, vmax


def scroll_screen(lines, height, v):
    """What asm/scroll.s shows at page line v: lines v..v+191 (24-row mode)."""
    font = fonts.current()
    rows = (max(height, v + 192) + 7) // 8
    scr = Screen(rows)
    scr.clear(0, 0, 40, rows, TEXT_BODY)
    for c, text, y in lines:
        scr.text_line(font, SCROLL_X, y, SCROLL_COLS, c, fonts.codes(text))
    return scr.pixels(v, 192)


STREAM_RATE = 3               # bytes the stream demo receives per frame (0: all at once)
STREAM_WMAX = 40              # WMAX, LMAX in asm/stream.s: a word is split after WMAX
STREAM_LMAX = 150             # characters, a line ends before it would pass LMAX
STREAM_INTRO = """# v2t stream demo

The text arrives as a stream of plain ASCII, %s, and the C64 wraps it itself: word by
word, by pixel width, into a ring of lines. A line feed is a space, two of them end a
paragraph, and a paragraph that starts with "# " is a title. Each word is drawn as soon as
it is complete, and the page scrolls smoothly, one pixel per frame, whenever the newest
line reaches the bottom. Lines that have scrolled off the top are dropped from the ring;
while the ring is full, the stream waits. Space returns to BASIC."""


def stream_bytes(texts):
    """The stream: texts separated by blank lines, as character codes (32-127) and line
    feeds (10)."""
    out = bytearray()
    for i, t in enumerate(texts):
        if i:
            out += b"\n\n"
        for ch in t.replace("\r", ""):
            out.append(10 if ch == "\n" else fonts.code(ch))
    return bytes(out)


def stream_layout(data, leading):
    """The lines asm/stream.s makes of the stream data: [(colour, text, page y)] and the page
    height (8 pixels below the last line). Line feed: a space; two in a row: a paragraph
    ends (one blank line before the next); other codes up to 32: a space; a first word "#":
    the paragraph is a title. Greedy wrap as Font.wrap, plus the WMAX/LMAX limits."""
    font = fonts.current()
    pitch, px = font.height + leading, SCROLL_COLS * 8
    width = lambda cs: sum(font.glyph(c)[1] for c in cs)
    lines, st = [], dict(cur=None, had=False, title=False, anyp=False, y=SCROLL_TOP)
    word, nl = [], 0

    def place(w):
        if not st["had"]:
            if not st["title"] and w == [35]:
                st["title"] = True
                return
            st["had"] = True
            if st["anyp"]:
                st["y"] += pitch
            st["cur"] = None
        cur = st["cur"]
        if (cur is not None and width(cur[1] + [32] + w) - font.hang <= px
                and len(cur[1]) + 1 + len(w) <= STREAM_LMAX):
            cur[1] += [32] + w
        else:
            st["cur"] = [TEXT_TITLE if st["title"] else TEXT_BODY, list(w), st["y"]]
            lines.append(st["cur"])
            st["y"] += pitch

    def endword():
        if word:
            place(word[:])
            del word[:]

    def endpara():
        endword()
        st["cur"] = None
        if st["had"]:
            st["anyp"] = True
        st["had"] = st["title"] = False

    for b in data:
        if b == 10:
            endword()
            nl += 1
            if nl == 2:
                endpara()
        elif b <= 32:
            endword()
            nl = 0
        else:
            nl = 0
            if len(word) == STREAM_WMAX:
                endword()
            word.append(b)
    endpara()
    out = [(c, "".join(chr(x) for x in t), y) for c, t, y in lines]
    return out, (out[-1][2] + font.height + 8 if out else 0)


def write_stream_inc(data, rate, leading):
    font = fonts.current()
    out = ["STM_RATE = %d" % rate, "STM_PITCH = %d" % (font.height + leading),
           "STM_X = %d" % SCROLL_X, "STM_PX = %d" % (SCROLL_COLS * 8), "STM_TOP = %d" % SCROLL_TOP,
           "STM_TITLE = $%02x" % TEXT_TITLE, "STM_BODY = $%02x" % TEXT_BODY,
           "WMAX = %d" % STREAM_WMAX, "LMAX = %d" % STREAM_LMAX,
           "        .data", "stm_data:"]
    for i in range(0, len(data), 32):
        out.append("        .byte " + ",".join("%d" % b for b in data[i:i + 32]))
    out.append("stm_end:")
    with open(os.path.join(BUILD, "stream.inc"), "w") as f:
        f.write("\n".join(out) + "\n")


def build_stream(images, leading, out, rate=STREAM_RATE, repeat=1, defines=(), log=print):
    """Assemble asm/stream.s with the intro and the stories (repeat times) as its stream,
    as much as fits below SCROLL_END. Returns (lines, page height, final v, stream size)."""
    font = fonts.current()
    if font.height > 8 * SCROLL_VOFF:
        raise SystemExit("stream demo: fonts up to %d pixels high" % (8 * SCROLL_VOFF))
    how = "%d bytes a frame" % rate if rate else "all at once"
    data = stream_bytes([STREAM_INTRO % how] + stories(images) * repeat)
    n = len(data)
    while True:
        write_stream_inc(data[:n], rate, leading)
        assemble(out, "stream.s", defines=defines)
        if 0x0801 + os.path.getsize(out) - 2 <= SCROLL_END:
            break
        n = n * 9 // 10
    if n < len(data):
        log("  stream demo: the first %d of %d bytes fit" % (n, len(data)))
    lines, height = stream_layout(data[:n], leading)
    return lines, height, max(0, height - 192), n


def check_in_vice(prg, png, exp, label, retry=True, cycles=10_000_000):
    """Screenshot prg in VICE (after cycles) and compare with exp. A failed check runs once
    more: VICE's autostart now and then leaves the machine at the READY prompt (the kernels
    are deterministic, so a real fault fails both times)."""
    if not vice_screenshot(prg, png, cycles):
        print("  %s: no screenshot" % label)
        return False
    res = compare_screenshot(png, exp)
    if (res is None or res[2]) and retry:
        print("  %s: %s, running it again" % (
            label, "nothing found" if res is None else "%d differing pixels" % len(res[2])))
        return check_in_vice(prg, png, exp, label, retry=False, cycles=cycles)
    if res is None:
        print("  %s: nothing found in the screenshot" % label)
        return False
    wrong = res[2]
    print("  %s: VICE output vs model: %d differing pixels" % (label, len(wrong)))
    for wv in wrong[:12]:
        print("     x=%d y=%d expected %d got %d" % wv)
    return not wrong


def use_system(standard, dual=False):
    """Kernels for standard from here on, and its build directory (build/pal/, build/ntsc/;
    build/dual/ for the dual disk's own files)."""
    global BUILD
    timing.set_standard(standard)
    BUILD = os.path.join(ROOT, "build", "dual" if dual else standard)
    os.makedirs(BUILD, exist_ok=True)


def build_system(a, images, at, standard):
    """Convert the images for one video system and build its programs and disk (and verify
    them). Returns (ok, the built files by role)."""
    use_system(standard)
    infos = [convert_image(p, frame=a.frame, leading=a.leading, at=at, force=a.force)
             for p in images]
    if a.convert_only:
        return True, None
    prg = os.path.join(BUILD, "slideshow.prg")
    in_prg = assemble_slideshow(prg, infos, a.auto, a.frame)
    if in_prg < len(infos):
        print("slideshow.prg holds the first %d of the %d images; diskshow loads them all from disk"
              % (in_prg, len(infos)))
    diskshow = os.path.join(BUILD, "diskshow.prg")
    write_diskshow_inc(infos, a.hold)
    assemble(diskshow, "diskshow.s", frame=a.frame)
    viewer = os.path.join(BUILD, "viewer.prg")
    assemble(viewer, "viewer.s", frame=a.frame)
    demos = []
    v2i_demo = os.path.join(BUILD, "v2i-demo.prg")
    with open(os.path.join(BUILD, "v2idemo.inc"), "w") as f:
        f.write('        .data\ndemo_img: .incbin "%s", 2\n' % infos[0]["v2i"])
    assemble(v2i_demo, "v2i-demo.s", frame=a.frame)
    demos.append((v2i_demo, "v2i demo"))
    story = v2t_demo_text(infos)
    v2t_demo = os.path.join(BUILD, "v2t-demo.prg")
    write_v2t_demo_inc(story)
    assemble(v2t_demo, "v2t-demo.s")
    demos.append((v2t_demo, "v2t demo"))
    scroll = os.path.join(BUILD, "scroll-demo.prg")
    build_scroll(images, a.leading, scroll)
    demos.append((scroll, "scroll demo"))
    stream = os.path.join(BUILD, "stream-demo.prg")
    build_stream(images, a.leading, stream)
    demos.append((stream, "stream demo"))
    asks = []
    for img_path, inf in zip(images, infos):
        path = os.path.splitext(img_path)[0] + ".ask"
        if os.path.exists(path):
            area = text_area(inf["geom"], min_width=12)
            if area is None:
                print("  ask %s: no room beside the image" % inf["name"])
                continue
            try:
                ask = Ask(path, inf, area, a.leading)
            except NoRoom as e:
                print("  %s, skipped" % e)
                continue
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
        font = fonts.current()
        for inf in infos:
            write_inc([inf], 0)             # held: no re-show during the screenshot
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
        ok &= check_in_vice(v2t_demo, os.path.join(BUILD, "vice_v2t_demo.png"),
                            v2t_demo_screen(story).pixels(), "v2t demo")
        # scroll demo: down to v1, back up to v2 by itself
        one = os.path.join(BUILD, "verify_scroll.prg")
        lines, height, vmax = build_scroll(images, a.leading, one, log=lambda *x: None)
        v1 = min(vmax, 150)
        v2 = max(0, v1 - 37)
        build_scroll(images, a.leading, one, ["AUTO=1", "AUTO_V1=%d" % v1, "AUTO_V2=%d" % v2],
                     log=lambda *x: None)
        ok &= check_in_vice(one, os.path.join(BUILD, "vice_scroll.png"),
                            scroll_screen(lines, height, v2), "scroll demo (v = %d)" % v2)
        # and one pixel per frame without waiting: N frames down end at line N
        n = min(vmax, 300)
        build_scroll(images, a.leading, one, ["AUTO=2", "AUTO_N=%d" % n], log=lambda *x: None)
        ok &= check_in_vice(one, os.path.join(BUILD, "vice_scroll_timing.png"),
                            scroll_screen(lines, height, n), "scroll demo (%d frames)" % n)
        # stream demo: the last screen, once the stream is in; STALLS colours the border if
        # the scroll ever had to wait. All at once and 4 times over (the rings wrap, the
        # stream waits for room), and at STREAM_RATE
        one = os.path.join(BUILD, "verify_stream.prg")
        for rate, rep in ((0, 4), (STREAM_RATE, 1)):
            lines, height, v, n = build_stream(images, a.leading, one, rate=rate, repeat=rep,
                                               defines=["STALLS=1"], log=lambda *x: None)
            frames = (n // rate if rate else 0) + v + 100
            ok &= check_in_vice(one, os.path.join(BUILD, "vice_stream_%d.png" % rate),
                                scroll_screen(lines, height, v),
                                "stream demo (%d lines, %s)" % (len(lines), "rate %d" % rate if rate
                                                                 else "all at once"),
                                cycles=3_000_000 + 25_000 * frames)
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
        write_diskshow_inc(infos, a.hold)
        assemble(diskshow, "diskshow.s", frame=a.frame)
        assemble_slideshow(prg, infos, a.auto, a.frame)
    return ok, dict(infos=infos, slideshow=prg, diskshow=diskshow, viewer=viewer, asks=asks,
                    demos=demos, disk=disk)


def build_dual(a, res):
    """build/dual/vic2orious.d81 (or .d64): the PAL and the NTSC images and programs, with
    one diskshow and one viewer that pick the files that suit the machine."""
    pal, ntsc = res["pal"], res["ntsc"]
    use_system("pal", dual=True)
    diskshow = os.path.join(BUILD, "diskshow.prg")
    write_diskshow_inc(pal["infos"], a.hold, dual=True)
    assemble(diskshow, "diskshow.s", frame=a.frame, defines=["DUAL=1"])
    viewer = os.path.join(BUILD, "viewer.prg")
    assemble(viewer, "viewer.s", frame=a.frame, defines=["DUAL=1"])
    files = [(viewer, "viewer"), (diskshow, "diskshow")]
    for std in ("pal", "ntsc"):
        files.append((res[std]["slideshow"], "slideshow" + SUFFIX[std]))
    for p, n in zip(pal["infos"], ntsc["infos"]):
        files.append((p["v2i"], dual_base(p["name"]) + "-P.V2I"))
        files.append((n["v2i"], dual_base(n["name"]) + "-N.V2I"))
        if p["txt"]:                    # text layout depends on the position only: shared
            files.append((p["txt"], text_disk_name(p["name"])))
    for std in ("pal", "ntsc"):
        for ask, out in res[std]["asks"]:
            files.append((out, "ask " + disk_name(ask.info["name"])[:10] + SUFFIX[std]))
    for std in ("pal", "ntsc"):
        for out, name in res[std]["demos"]:
            if name == "v2i demo":          # the v2t demo has no kernel: one copy
                files.append((out, name + SUFFIX[std]))
    files += [d for d in pal["demos"] if d[1] != "v2i demo"]
    disk = make_disk(files, a.disk)
    print("built %s and %s for both PAL and NTSC, and %s" % (diskshow, viewer, disk))
    print("disk files: " + ", ".join(name.lower() for _, name in files))
    ok = True
    if a.verify:
        # the full disk, diskshow holding its first image, on both systems
        one = os.path.join(BUILD, "verify_diskshow.prg")
        write_diskshow_inc(pal["infos"], 0, dual=True)
        assemble(one, "diskshow.s", frame=a.frame, defines=["DUAL=1"])
        for std in ("pal", "ntsc"):
            inf = res[std]["infos"][0]
            timing.set_standard(std)
            png = os.path.join(BUILD, "vice_diskshow_%s.png" % std)
            size = inf["size"] + (os.path.getsize(inf["txt"]) if inf["txt"] else 0)
            label = "dual diskshow on %s" % std.upper()
            if diskshow_screenshot(one, disk, png, 40_000_000 + 8_000 * size):
                r = compare_screenshot(png, expected_screen(inf).pixels())
                n = len(r[2]) if r else -1
                print("  %s: VICE output vs model: %d differing pixels" % (label, n))
                ok &= n == 0
            else:
                print("  %s: no screenshot" % label)
                ok = False
        timing.set_standard("pal")
    return ok, disk


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
    ap.add_argument("--font", metavar="FILE.cvt[:SIZE]",
                    help="GEOS font (Convert format) for the texts, its smallest point size "
                         "unless SIZE is given (default: the character ROM's)")
    ap.add_argument("--at", metavar="COLUMN,ROW",
                    help="place the images at this character column and row (default 0,0; 1,1 "
                         "with -b)")
    ap.add_argument("--auto", type=int, default=250,
                    help="frames per image (max 255) in the slideshow (0: until space)")
    ap.add_argument("--hold", type=int, default=15,
                    help="seconds per image (max 1000) in diskshow, not counting the loading "
                         "(0: until space)")
    ap.add_argument("--ntsc", action="store_true",
                    help="make the kernels for NTSC C64s (6567R8) instead of PAL; builds into "
                         "build/ntsc/ instead of build/pal/")
    ap.add_argument("--dual", action="store_true",
                    help="build for both PAL and NTSC (build/pal/, build/ntsc/) and a disk with "
                         "both, whose diskshow and viewer pick the files for the machine "
                         "(build/dual/)")
    ap.add_argument("--disk", choices=sorted(DISKS),
                    help="disk image type (default: d64 if everything fits, else d81)")
    ap.add_argument("--convert-only", action="store_true",
                    help="convert the images and build nothing else")
    ap.add_argument("--force", action="store_true", help="convert images even if unchanged")
    a = ap.parse_args()
    if a.dual and a.ntsc:
        ap.error("--dual builds both systems; leave out --ntsc")
    if not 0 <= a.auto <= 255:
        ap.error("--auto must be 0..255")
    if not 0 <= a.hold <= 1000:
        ap.error("--hold must be 0..1000")
    if not 0 <= a.leading <= 64:
        ap.error("--leading must be 0..64")
    at = None
    if a.at:
        try:
            at = tuple(int(v) for v in a.at.split(","))
            assert len(at) == 2
        except (ValueError, AssertionError):
            ap.error("--at takes COLUMN,ROW")
        if not (0 <= at[0] < 40 and 0 <= at[1] < 25):
            ap.error("--at takes COLUMN,ROW in character cells (0-39, 0-24), not pixels: "
                     "x = 8 * COLUMN, y = 8 * ROW")
    fonts.use(a.font)
    if a.font:
        print("font: %s, %d pixels high" % (fonts.current().name, fonts.current().height))
    images = a.images or sorted(glob.glob(os.path.join(ROOT, "input", "*.png")))
    if a.dual:
        res = {}
        ok = True
        for std in ("pal", "ntsc"):
            k, res[std] = build_system(a, images, at, std)
            ok &= k
        if a.convert_only:
            return 0 if ok else 1
        k, disk = build_dual(a, res)
        ok &= k
        if a.run:
            subprocess.Popen(["x64sc", "-pal", "-VICIIextpal", "-VICIIpalette", "pepto-pal.vpl",
                              "-drive8type", "1581", "-8", disk, "-autostart",
                              os.path.join(BUILD, "diskshow.prg")],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 0 if ok else 1
    ok, built = build_system(a, images, at, "ntsc" if a.ntsc else "pal")
    if a.run and built:
        subprocess.Popen(["x64sc", "-" + timing.STANDARD, "-VICIIextpal", "-VICIIpalette", "pepto-pal.vpl",
                          "-autostartprgmode", "1", built["slideshow"]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
