"""One picture -> one standalone PRG that shows it on PAL and NTSC C64s.

usage: python3 -m vic2.prg [-o OUT.prg] [-d MODE] [-c S] [-s WxH] [--force]
                          [--verify] [--run [pal|ntsc]] PICTURE

The picture (any format tools/img2c64.py reads) is quantised by img2c64 (Colodore as VICE
shows it, each system's pixel aspect, no room for a frame; -d, -c and -s go to img2c64:
Floyd-Steinberg unless -d names another mode, fitted into 320x200 unless -s WxH) into
build/prg/<name>-p.png and <name>-n.png, converted for each system (build/prg/pal/,
build/prg/ntsc/, cached like the build's conversions) and centred, and assembled into the
dual v2i demo (asm/v2i-demo.s, DUAL=1): both kernels in one PRG, which picks the one for
the machine and returns to BASIC on space. The PRG is <name>.prg in the current directory
unless -o names another.
"""

import argparse
import os
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
    ap.add_argument("picture")
    ap.add_argument("-o", "--output", help="the PRG to write (default: <name>.prg)")
    ap.add_argument("-d", "--dither", default="floydsteinberg", metavar="MODE",
                    help="dithering for img2c64: floydsteinberg (default), fs:K, atkinson[:K], "
                         "hybrid[:E] or none")
    ap.add_argument("-c", "--chroma", metavar="S",
                    help="img2c64 -c: match against the colours at S times their saturation")
    ap.add_argument("-s", "--size", metavar="WxH",
                    help="fit WxH instead of 320x200 (multiples of 8)")
    ap.add_argument("--force", action="store_true", help="convert even if unchanged")
    ap.add_argument("--verify", action="store_true",
                    help="run the PRG in PAL and NTSC VICE and compare with the model")
    ap.add_argument("--run", nargs="?", const="pal", choices=("pal", "ntsc"),
                    help="launch the PRG in VICE (default PAL)")
    a = ap.parse_args()
    name = os.path.splitext(os.path.basename(a.picture))[0]
    out = os.path.abspath(a.output or name + ".prg")
    os.makedirs(PRG_BUILD, exist_ok=True)
    base = os.path.join(PRG_BUILD, name + ".png")   # its -p/-n files are what gets converted
    cmd = [sys.executable, TOOL, "-o", base, "-d", a.dither]
    if a.chroma:
        cmd += ["-c", a.chroma]
    if a.size:
        cmd += ["-s", a.size]
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


if __name__ == "__main__":
    sys.exit(main())
