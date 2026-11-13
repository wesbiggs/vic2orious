"""A disk of .v2i images for the thumbnail browser (and, with --viewer, the viewer and the
images' stories): every .v2i in the build directory by default, or the files given.

usage: python3 -m vic2.disk [--ntsc | --dual] [--viewer] [--disk d64|d81] [-o FILE]
                            [FILE.v2i ...]

PAL: build/pal/*.v2i onto build/pal/pictures.d64 (or .d81); --ntsc: build/ntsc/;
--dual: both, named as on the dual disk (NAME-P.V2I / NAME-N.V2I, base cut to 10
characters), onto build/dual/pictures.d64. The programs come from the same directory
(thumbnails always; viewer with --viewer), so build first (make, make NTSC=1, make
DUAL=1). The demo's centred copies (*-centred.v2i) are left out, and so are files that
are not .v2i version 5 or not for the disk's video system. Names are those the build gives:
the first 12 characters + .v2i (texts: + .txt, the packed build/<system>/<name>.txt.prg,
with --viewer). D64 if everything fits (664 blocks, 144 files), else D81, unless --disk.
"""

import argparse
import glob
import os
import subprocess
import sys

from .build import (DISKS, ROOT, SUFFIX, V2I_VERSION, blocks, dual_base, text_disk_name,
                    v2i_disk_name)

STANDARDS = {0: "pal", 1: "ntsc"}      # .v2i header byte 24 (timing.SYSTEM_ID)


def system_of(path):
    """('pal' or 'ntsc', None) for a .v2i version 5 file, else (None, why not)."""
    with open(path, "rb") as f:
        head = f.read(2 + 26)
    if len(head) < 28 or head[2:5] != b"V2I":
        return None, "not .v2i files"
    if head[5] != V2I_VERSION:
        return None, "older .v2i versions (convert them again)"
    return STANDARDS.get(head[2 + 24]), None


def name_of(path):
    return os.path.basename(path)[:-len(".v2i")]


def text_of(path):
    """The packed story next to a .v2i (build/<system>/<name>.txt.prg), or None."""
    t = os.path.join(os.path.dirname(path), name_of(path) + ".txt.prg")
    return t if os.path.exists(t) else None


def default_files(systems):
    """The .v2i files in build/<system>/, by name (PAL before NTSC)."""
    found = [(os.path.basename(p), i, p) for i, s in enumerate(systems)
             for p in glob.glob(os.path.join(ROOT, "build", s, "*.v2i"))
             if not p.endswith("-centred.v2i")]
    return [p for _, _, p in sorted(found)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help=".v2i files (default: all in the build directory)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--ntsc", action="store_true", help="NTSC images and programs")
    g.add_argument("--dual", action="store_true", help="PAL and NTSC images on one disk")
    ap.add_argument("--viewer", action="store_true", help="add the viewer and the stories")
    ap.add_argument("--disk", choices=sorted(DISKS), help="disk type (default: d64 if it fits)")
    ap.add_argument("-o", "--output", help="the disk image (default: build/<dir>/pictures.d64)")
    a = ap.parse_args()

    systems = ["pal", "ntsc"] if a.dual else ["ntsc" if a.ntsc else "pal"]
    bdir = os.path.join(ROOT, "build", "dual" if a.dual else systems[0])
    progs = [("thumbs.prg", "thumbnails")] + ([("viewer.prg", "viewer")] if a.viewer else [])
    files = []
    for prg, name in progs:
        path = os.path.join(bdir, prg)
        if not os.path.exists(path):
            raise SystemExit("%s is missing: build first (make%s)" % (
                path, " DUAL=1" if a.dual else " NTSC=1" if a.ntsc else ""))
        files.append((path, name))

    images = []                          # (path, system)
    skipped = {}                         # why -> [path]
    for p in a.files or default_files(systems):
        s, why = system_of(p)
        if s and s not in systems:
            why = "made for " + s.upper()
        if why:
            skipped.setdefault(why, []).append(p)
        else:
            images.append((p, s))
    for why, ps in skipped.items():
        print("left out, %s: %s" % (why, " ".join(os.path.relpath(p) for p in ps)),
              file=sys.stderr)
    if not images:
        raise SystemExit("no .v2i files to put on the disk")

    texts = {}                           # disk name -> data (shared texts written once)
    for p, s in images:
        n = name_of(p)
        if a.dual:
            files.append((p, dual_base(n) + SUFFIX[s] + ".V2I"))
        else:
            files.append((p, v2i_disk_name(n)))
        t = text_of(p) if a.viewer else None
        if not t:
            continue
        if a.dual:
            # one NAME.TXT if both systems' texts are the same (the viewer falls back to
            # it), else NAME-P.TXT / NAME-N.TXT, as build.dual_texts names them
            other = os.path.join(ROOT, "build", "ntsc" if s == "pal" else "pal",
                                 n + ".txt.prg")
            same = (os.path.exists(other) and
                    open(other, "rb").read() == open(t, "rb").read())
            tname = text_disk_name(n) if same else dual_base(n) + SUFFIX[s] + ".TXT"
        else:
            tname = text_disk_name(n)
        if tname not in texts:
            texts[tname] = t
            files.append((t, tname))

    names = {}
    for p, name in files:
        if name in names:
            raise SystemExit("%s and %s would both be %s on the disk (names are cut to fit)"
                             % (names[name], p, name.lower()))
        names[name] = p

    need = sum(blocks(p) for p, _ in files)
    fits = [k for k, (free, entries) in DISKS.items() if need <= free and len(files) <= entries]
    kind = a.disk or (fits[0] if fits else None)
    if kind is None or kind not in fits:
        raise SystemExit("%d files (%d blocks) do not fit on a %s" % (
            len(files), need, kind or "d81"))
    out = a.output or os.path.join(bdir, "pictures." + kind)
    if not a.output:
        for k in DISKS:
            old = os.path.join(bdir, "pictures." + k)
            if os.path.exists(old):
                os.remove(old)
    cmd = ["c1541", "-format", "pictures,v2", kind, out]
    for p, name in files:
        cmd += ["-write", p, name.lower()]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    print("%s: %d images, %d files, %d of %d blocks" % (
        out, len(images), len(files), need, DISKS[kind][0]))
    print("disk files: " + ", ".join(name.lower() for _, name in files))


if __name__ == "__main__":
    main()
