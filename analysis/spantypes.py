"""How many leftover pixels could X-expanded / multicolour sprite spans cover?

Runs the real converter on each source, keeps its cell colour pairs, and for every line
takes the problem pixels (not in their cell's pair). Then, with 8 sprites a line and no
timing at all, covers them greedily (one sprite at a time, the most new pixels):

  std   24 px, one colour, any pattern (today's span)
  xexp  48 px ($d01d), one colour, pixel pairs
  mc    24 px ($d01c), pixel pairs, own colour or $d025/$d026 (shared by the line)
  mcx   48 px, both bits, 4-pixel groups, three colours as mc

A pair/group is only painted where all its pixels really have that colour, so no
painting ever breaks a correct pixel. $d025/$d026 are tried for every pair of the line's
6 most common problem colours. See README.md.

    python analysis/spantypes.py [SRC_DIR]     (default build/analysis/src)
"""
import glob
import itertools
import os
import sys
from collections import Counter

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vic2 import convert, timing  # noqa: E402
from vic2.palette import load_indexed  # noqa: E402

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "analysis", "src")
PAD = 48
NSPR = 8
timing.set_standard("pal")


def unit_gain(col, todo, unit, phase):
    """For pixel groups of size unit starting at phase (padded line): per group its colour
    (-1 if mixed) and how many still uncovered problem pixels it holds."""
    n = (len(col) - phase) // unit
    g = col[phase:phase + n * unit].reshape(n, unit)
    t = todo[phase:phase + n * unit].reshape(n, unit)
    gc = np.where((g == g[:, :1]).all(1), g[:, 0], -1)
    return gc, t.sum(1)


def best_span(col, todo, kind, mcols):
    """(gain, start x, unit, colour set) of the best single sprite of this kind."""
    unit, width = {"std": (1, 24), "xexp": (2, 48), "mc": (2, 24), "mcx": (4, 48)}[kind]
    ngroups = width // unit
    best = (0, None, None, None, None)
    for phase in range(unit):
        gc, gv = unit_gain(col, todo, unit, phase)
        for c in range(16):
            ok = (gc == c) | np.isin(gc, mcols) if kind in ("mc", "mcx") else gc == c
            if kind in ("mc", "mcx") and c in mcols:
                continue
            v = np.where(ok, gv, 0)
            cs = np.concatenate(([0], np.cumsum(v)))
            win = cs[ngroups:] - cs[:-ngroups]
            i = int(win.argmax()) if len(win) else 0
            if len(win) and win[i] > best[0]:
                cols = (c,) + tuple(mcols) if kind in ("mc", "mcx") else (c,)
                best = (int(win[i]), phase + i * unit, unit, cols, width)
    return best


def greedy(col, prob, kinds, mcols=()):
    todo = prob.copy()
    use = Counter()
    for _ in range(NSPR):
        cands = [best_span(col, todo, k, mcols) + (k,) for k in kinds]
        g = max(cands, key=lambda e: e[0])
        if g[0] == 0:
            break
        _, x, unit, cols, width, k = g
        seg = slice(x, x + width)
        grp = col[seg].reshape(-1, unit)
        okg = (grp == grp[:, :1]).all(1) & np.isin(grp[:, 0], cols)
        todo[seg] &= ~np.repeat(okg, unit)
        use[k] += 1
    return int(todo.sum()), use


def line_lost(col, prob, kinds):
    """Best greedy result over $d025/$d026 choices (when a multicolour kind is allowed)."""
    if not prob.any():
        return 0, Counter()
    if not any(k in ("mc", "mcx") for k in kinds):
        return greedy(col, prob, kinds)
    common = [c for c, _ in Counter(col[prob].tolist()).most_common(6)]
    best = greedy(col, prob, [k for k in kinds if k not in ("mc", "mcx")])
    for m in itertools.combinations(range(16) if len(common) < 2 else common, 2):
        r = greedy(col, prob, kinds, m)
        if r[0] < best[0]:
            best = r
    return best


KINDSETS = {"std": ("std",), "+xexp": ("std", "xexp"), "+mc": ("std", "mc", "mcx"),
            "all": ("std", "xexp", "mc", "mcx")}

print("image          actual  exact8  " + "  ".join("%7s" % k for k in KINDSETS)
      + "   sprite kinds used (all)", flush=True)
for path in sorted(glob.glob(os.path.join(SRC, "*.png"))):
    name = os.path.splitext(os.path.basename(path))[0]
    w, h, img = load_indexed(path)
    conv = convert.Converter(img, log=lambda *a: None)
    conv.run()
    out = conv.render()
    actual = sum(out[y][x] != img[y][x] for y in range(h) for x in range(w))
    pairs_of = lambda y: [conv.pairs[y >> 3][x >> 3] for x in range(0, w, 8)]  # noqa: E731
    exact = sum(conv.spans_of(y, pairs_of(y))[1] for y in range(h))
    tot = Counter()
    used = Counter()
    for y in range(h):
        row = np.full(w + 2 * PAD, -2, dtype=np.int64)
        row[PAD:PAD + w] = img[y]
        prob = np.zeros(w + 2 * PAD, dtype=bool)
        prob[PAD:PAD + w] = [img[y][x] not in conv.pairs[y >> 3][x >> 3] for x in range(w)]
        for ks, kinds in KINDSETS.items():
            lost, use = line_lost(row, prob, kinds)
            tot[ks] += lost
            if ks == "all":
                used += use
    print("%-14s %6d  %6d  " % (name, actual, exact)
          + "  ".join("%7d" % tot[k] for k in KINDSETS) + "   " + dict(used).__repr__(), flush=True)
