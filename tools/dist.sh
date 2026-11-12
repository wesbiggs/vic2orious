#!/usr/bin/env bash
# Copyright 2026 Wes Biggs. Licensed under the Apache License, Version 2.0 (LICENSE).
#
# Package a finished dual build (make DUAL=1) for release: tools/dist.sh VERSION [OUTDIR]
#   vic2orious-VERSION-dual.d64|d81   one disk for PAL and NTSC C64s (diskshow, viewer)
#   vic2orious-VERSION-pal.zip        PAL programs and disk (slideshow, demos, ask)
#   vic2orious-VERSION-ntsc.zip       the same for NTSC
#   vic2orious-VERSION-lib.zip        asm/v2i.inc, asm/v2t.inc, their docs and LICENSE
set -euo pipefail
ver=${1:?usage: tools/dist.sh VERSION [OUTDIR]}
out=$(mkdir -p "${2:-dist}" && cd "${2:-dist}" && pwd)
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
name=vic2orious-$ver

disk() {    # the disk the build made in $1 (.d81 if it needed one)
    local f
    for f in "$1"/vic2orious.d81 "$1"/vic2orious.d64; do
        if [ -e "$f" ]; then echo "$f"; return; fi
    done
}

d=$(disk build/dual)
[ -n "$d" ] || { echo "no build/dual disk: run make DUAL=1 first" >&2; exit 1; }
cp "$d" "$out/$name-dual.${d##*.}"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
for sys in pal ntsc; do
    dir=$tmp/$name-$sys
    mkdir -p "$dir"
    d=$(disk "build/$sys")
    [ -n "$d" ] || { echo "no build/$sys disk" >&2; exit 1; }
    cp "$d" "$dir/"
    for p in build/$sys/*.prg; do      # the programs, not the verify builds or text PRGs
        case $(basename "$p") in verify_*|*.txt.prg) continue ;; esac
        cp "$p" "$dir/"
    done
    cp LICENSE "$dir/"
    (cd "$tmp" && zip -qr "$out/$name-$sys.zip" "$name-$sys")
done

lib=$tmp/$name-lib
mkdir -p "$lib/asm" "$lib/docs"
cp asm/v2i.inc asm/v2t.inc "$lib/asm/"
cp docs/*.md "$lib/docs/"
cp LICENSE "$lib/"
(cd "$tmp" && zip -qr "$out/$name-lib.zip" "$name-lib")

ls -l "$out"
