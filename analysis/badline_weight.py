"""Wrong pixels with row_cost weighing retasks into a badline line by WEIGHT (others 20).

The writes of a badline must land in the line before, so changing sprites there is
dearer. Converts every image as the converter would (PAL, upper left) with that weight.
See README.md.

    python analysis/badline_weight.py WEIGHT [IMAGE ...]   (default: build/analysis/src
                                                           and input/*.png)
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vic2 import convert, timing  # noqa: E402
from vic2.palette import load_indexed  # noqa: E402

WEIGHT = int(sys.argv[1])
paths = sys.argv[2:] or (sorted(glob.glob(os.path.join(ROOT, "build", "analysis", "src", "*.png")))
                         + sorted(glob.glob(os.path.join(ROOT, "input", "*.png"))))
timing.set_standard("pal")
BAD = set(convert.badlines())


def row_cost(self, cy, pairs, prev_spans, lost_px):
    cost = 0
    prev = prev_spans
    for i in range(8):
        y = cy * 8 + i
        sp, lost = self.spans_of(y, pairs)
        cost += lost_px * lost + 5 * len(sp)
        if prev is not None:
            w = WEIGHT if self.g.raster0 + y in BAD else 20
            cost += w * convert.spans_cost(prev, sp)
        prev = sp
    return cost


convert.Converter.row_cost = row_cost
total = 0
for path in paths:
    w, h, img = load_indexed(path)
    conv = convert.Converter(img, log=lambda *a: None)
    try:
        conv.run()
    except convert.SchedFail as e:
        print("%s FAIL %s" % (os.path.basename(path), e), flush=True)
        continue
    out = conv.render()
    wrong = sum(out[y][x] != img[y][x] for y in range(h) for x in range(w))
    total += wrong
    print("%s %d" % (os.path.basename(path), wrong), flush=True)
print("total %d" % total)
