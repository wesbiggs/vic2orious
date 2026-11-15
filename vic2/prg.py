"""One picture -> one standalone PRG that shows it on PAL and NTSC C64s.

usage: python3 -m vic2.prg [-o OUT.prg] [-d MODE | -w R,S,C] [-c S] [-P FILE.vpl] [-s WxH]
                          [-l N|none] [-m] [--force]
                          [--verify] [--run [pal|ntsc]] PICTURE

The picture (any format tools/img2c64.py reads) is quantised by img2c64 (the palette of
tools/tv.vpl unless -P says otherwise, each system's pixel aspect, no room for a frame; -d, -w, -c, -P, -s, -l and
-m (multicolour) go to img2c64: the dither it picks per system unless -d names one, fitted into 320x200 unless -s WxH) into
build/prg/<name>-p.png and <name>-n.png, converted for each system (build/prg/pal/,
build/prg/ntsc/, cached like the build's conversions) and centred, and assembled into the
dual v2i demo (asm/v2i-demo.s, DUAL=1): both kernels in one PRG, which picks the one for
the machine and returns to BASIC on space. The PRG is <name>.prg in the current directory
unless -o names another.

    python3 -m vic2.prg [-o OUT.prg] [--font FILE.cvt[:SIZE]] [--verify] [--run [pal|ntsc]]
                        FILE.v2i [FILE.v2t] [FILE.v2i [FILE.v2t]]

Given .v2i files instead (made by the build, e.g. build/pal/<name>.v2i), nothing is
converted: the image, and the .v2t after it if any (the build's <name>.v2t, or one
copied off a disk), go into the v2i demo assembled with TEXT=1. Two .v2i files, one for
PAL and one for NTSC, make a dual PRG (each with its own text). The image is shown where
it was converted, framed if its metadata says so. The text must be drawn with the font it
was laid out with: --font as given to the build (default the ROM's), checked against the
height in the .v2t. --verify needs the build's <name>.json beside each .v2i (the model).
"""

import argparse
import json
import os
import re
import subprocess
import sys

from . import build, timing

TOOL = os.path.join(build.ROOT, "tools", "img2c64.py")
PRG_BUILD = os.path.join(build.ROOT, "build", "prg")


def use_system(standard):
    """Like build.use_system, into build/prg/<standard>/ (apart from the input/ builds)."""
    timing.set_standard(standard)
    build.BUILD = os.path.join(PRG_BUILD, standard)
    os.makedirs(build.BUILD, exist_ok=True)


def main():
    ap = argparse.ArgumentParser(description="Make one PRG that shows a picture on PAL and "
                                             "NTSC C64s.")
    ap.add_argument("picture", nargs="+",
                    metavar="PICTURE | FILE.v2i [FILE.v2t] [FILE.v2i [FILE.v2t]]")
    ap.add_argument("-o", "--output", help="the PRG to write (default: <name>.prg)")
    ap.add_argument("-d", "--dither", metavar="MODE",
                    help="dithering for img2c64: floydsteinberg, fs:K, atkinson[:K], "
                         "hybrid[:E] or none (default: img2c64 picks one)")
    ap.add_argument("-w", "--weights", metavar="R,S,C",
                    help="img2c64 -w, without -d: weights for picking the dither")
    ap.add_argument("-c", "--chroma", metavar="S",
                    help="img2c64 -c: match against the colours at S times their saturation")
    ap.add_argument("-P", "--palette", metavar="FILE.vpl",
                    help="img2c64 -P: choose colours as a screen with this palette shows them "
                         "(default tools/tv.vpl; none: VICE's Colodore)")
    ap.add_argument("-s", "--size", metavar="WxH",
                    help="fit WxH instead of 320x200 (multiples of 8)")
    ap.add_argument("-l", "--line-runs", metavar="N",
                    help="img2c64 -l, with -d hybrid: a line's colours outside their cell's "
                         "pair fit in N runs of 24 pixels (default 8, none for no budget)")
    ap.add_argument("-m", "--multicolor", action="store_true",
                    help="img2c64 -m: a multicolour picture (160 wide pixels across, three "
                         "colours per cell plus black; not with -d hybrid)")
    ap.add_argument("--force", action="store_true", help="convert even if unchanged")
    ap.add_argument("--font", metavar="FILE.cvt[:SIZE]",
                    help="with .v2i input: the font the .v2t was laid out with (default: the "
                         "character ROM's)")
    ap.add_argument("--verify", action="store_true",
                    help="run the PRG in PAL and NTSC VICE and compare with the model")
    ap.add_argument("--run", nargs="?", const="pal", choices=("pal", "ntsc"),
                    help="launch the PRG in VICE (default PAL)")
    a = ap.parse_args()
    if any(f.lower().endswith(".v2i") for f in a.picture):
        return from_files(a)
    if len(a.picture) > 1 or re.search(r"\.v2t$", a.picture[0], re.I):
        ap.error("one picture, or .v2i files each followed by its text")
    if a.font:
        ap.error("--font is for .v2i input (a picture's PRG has no text)")
    a.picture = a.picture[0]
    name = os.path.splitext(os.path.basename(a.picture))[0]
    out = os.path.abspath(a.output or name + ".prg")
    os.makedirs(PRG_BUILD, exist_ok=True)
    base = os.path.join(PRG_BUILD, name + ".png")   # its -p/-n files are what gets converted
    cmd = [sys.executable, TOOL, "-o", base]
    if a.dither:
        cmd += ["-d", a.dither]
    if a.weights:
        cmd += ["-w", a.weights]
    if a.chroma:
        cmd += ["-c", a.chroma]
    if a.palette:
        cmd += ["-P", a.palette]
    if a.size:
        cmd += ["-s", a.size]
    if a.line_runs:
        cmd += ["-l", a.line_runs]
    if a.multicolor:
        cmd += ["-m"]
    if subprocess.run(cmd + [a.picture]).returncode:
        return 1                        # img2c64 said why
    infos = {}
    for std in ("pal", "ntsc"):
        use_system(std)
        infos[std] = build.convert_image(base, force=a.force, centre=True)
    with open(os.path.join(PRG_BUILD, "v2idemo.inc"), "w") as f:
        f.write('        .data\ndemo_img: .incbin "%s", 2\ndemo_img_n: .incbin "%s", 2\n'
                % (infos["pal"]["v2i"], infos["ntsc"]["v2i"]))
    build.BUILD = PRG_BUILD
    try:
        build.assemble(out, "v2i-demo.s", defines=["DUAL=1"])
    except build.Overflow:
        raise SystemExit("%s: the PAL and NTSC images (%d + %d bytes) do not fit in one PRG "
                         "($0801-$bfff); try a smaller picture" % (
                             name, infos["pal"]["size"], infos["ntsc"]["size"]))
    print("built %s (%d bytes, PAL and NTSC)" % (out, os.path.getsize(out)))
    ok = True
    if a.verify:
        for std in ("pal", "ntsc"):
            timing.set_standard(std)
            ok &= build.check_in_vice(out, os.path.join(PRG_BUILD, "vice_%s_%s.png" % (name, std)),
                                      build.expected_screen(infos[std], text=False).pixels(),
                                      "%s on %s" % (name, std.upper()))
    if a.run:
        subprocess.Popen(["x64sc", "-" + a.run, "-VICIIextpal", "-VICIIpalette", "pepto-pal.vpl",
                          "-autostartprgmode", "1", out],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0 if ok else 1


def pairs(files):
    """[(v2i, txt or None)] from FILE.v2i [FILE.v2t] ...: a text belongs to the .v2i before
    it."""
    out = []
    for f in files:
        if f.lower().endswith(".v2i"):
            out.append([f, None])
        elif out and out[-1][1] is None:
            out[-1][1] = f
        else:
            raise SystemExit("%s: a text needs a .v2i before it (one text per image)" % f)
    return [tuple(p) for p in out]


def read_text(path, font):
    """Check a .v2t file (with its load address) against the font; returns its bytes."""
    with open(path, "rb") as f:
        d = f.read()
    if d[2:5] != b"V2T":
        raise SystemExit("%s: not a .v2t text" % path)
    if d[5] != build.V2T_VERSION:
        raise SystemExit("%s: .v2t version %d, this build draws version %d" % (
            path, d[5], build.V2T_VERSION))
    if d[10] != font.height:
        raise SystemExit("%s: laid out for a %d pixel font, but %s is %d high: pass the "
                         "build's --font" % (path, d[10], font.name, font.height))
    return d


def model(v2i, txt):
    """The build's record of v2i (its <name>.json beside it) as convert_image returns it,
    with txt as its text; None if there is none for this file."""
    meta = os.path.splitext(v2i)[0] + ".json"
    try:
        with open(meta) as f:
            inf = json.load(f)
    except (OSError, ValueError):
        return None
    if not (inf.get("v2i") and os.path.exists(inf["v2i"]) and os.path.samefile(inf["v2i"], v2i)
            and os.path.exists(inf.get("expected_png", ""))):
        return None
    g = inf.pop("geom")
    inf["geom"] = build.convert.Geometry(inf["w"], inf["h"], frame=g["frame"],
                                         at=(g["col0"], g["row0"]), mc=g.get("mc", False))
    inf["expected"] = build.load_indexed(inf["expected_png"])[2]
    inf["txt"] = txt
    return inf


def from_files(a):
    """vic2.prg with .v2i (and .v2t) input: see the module docstring."""
    if any(getattr(a, o) for o in ("dither", "weights", "chroma", "palette", "size",
                                   "line_runs", "multicolor", "force")):
        raise SystemExit("-d, -w, -c, -P, -s, -l, -m and --force are for a picture; .v2i "
                         "files are converted already")
    build.fonts.use(a.font)
    font = build.fonts.current()
    images = {}                         # system -> (v2i, txt, header, frame)
    for v2i, txt in pairs(a.picture):
        try:
            hdr, meta = build.read_v2i(v2i)
        except (OSError, AssertionError) as e:
            raise SystemExit(str(e))
        if hdr["version"] != 5:
            raise SystemExit("%s: .v2i version %d; v2i_show takes version 5 (build it "
                             "again)" % (v2i, hdr["version"]))
        std = "ntsc" if hdr["system"] == 1 else "pal"
        if std in images:
            raise SystemExit("%s and %s are both for %s: give one PAL and one NTSC image" % (
                images[std][0], v2i, std.upper()))
        if txt:
            read_text(txt, font)
            if hdr["mc"]:
                print("%s: multicolour, its text would be drawn wide and in the wrong "
                      "colours" % v2i)
        frame = bool(meta and re.search(r"^frame: yes$", meta, re.M))
        images[std] = (os.path.abspath(v2i), txt and os.path.abspath(txt), hdr, frame)
    if len({im[3] for im in images.values()}) > 1:
        raise SystemExit("one image is framed and the other not: they need one PRG each")
    dual = len(images) == 2
    first = images.get("pal") or images["ntsc"]
    name = os.path.splitext(os.path.basename(first[0]))[0]
    if dual:
        name = re.sub(r"-[pn]$", "", name, flags=re.I)
    out = os.path.abspath(a.output or name.lower() + ".prg")
    build.BUILD = os.path.join(PRG_BUILD, "v2i")
    os.makedirs(build.BUILD, exist_ok=True)
    order = [("pal", ""), ("ntsc", "_n")] if dual else [(next(iter(images)), "")]
    lines = ["        .data"]
    for std, sfx in order:
        v2i, txt = images[std][:2]
        lines.append('demo_img%s: .incbin "%s", 2' % (sfx, v2i))
        lines.append('demo_txt%s: .incbin "%s", 2' % (sfx, txt) if txt else
                     "demo_txt%s = 0" % sfx)
    with open(os.path.join(build.BUILD, "v2idemo.inc"), "w") as f:
        f.write("\n".join(lines) + "\n")
    try:
        build.assemble(out, "v2i-demo.s", frame=first[3],
                       defines=["TEXT=1"] + (["DUAL=1"] if dual else []))
    except build.Overflow:
        raise SystemExit("%s: the images and texts do not fit in one PRG ($0801-$bfff)" % name)
    print("built %s (%d bytes, %s%s%s)" % (
        out, os.path.getsize(out), " and ".join(s.upper() for s, _ in order),
        ", framed" if first[3] else "",
        ", %s" % font.name if any(im[1] for im in images.values()) else ""))
    ok = True
    if a.verify:
        for std, _ in order:
            v2i, txt = images[std][:2]
            inf = model(v2i, txt)
            if inf is None:
                print("  %s: no model (the build's .json beside it), not verified" % v2i)
                ok = False
                continue
            timing.set_standard(std)
            ok &= build.check_in_vice(out, os.path.join(build.BUILD, "vice_%s_%s.png" % (name, std)),
                                      build.expected_screen(inf).pixels(),
                                      "%s on %s" % (name, std.upper()))
    if a.run:
        subprocess.Popen(["x64sc", "-" + a.run, "-VICIIextpal", "-VICIIpalette", "pepto-pal.vpl",
                          "-autostartprgmode", "1", out],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
