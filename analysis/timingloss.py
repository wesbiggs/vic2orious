"""Where do pixels go to timing? Splits each image's wrong pixels by cause.

Runs the real converter (PAL, upper left, as spantypes.py) with fit_line, do_row and
recover wrapped, and records for every line of the chosen schedule:

  cover    problem pixels the exact 8-span cover leaves (no timing)
  dropped  pixels of the spans fit_line dropped so the writes fit
  recov    pixels recover() still painted without writes
  writes   X / colour / $d010 writes the full span set asked for
  fail     the first write that missed when all spans were scheduled (probe, undone)

The probe schedules the line once with no span dropped, notes the task that missed and
restores the scheduler (including its task ids), so the conversion is unchanged.
See README.md.

    python analysis/timingloss.py [SRC_DIR]     (default build/analysis/src)
"""
import glob
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vic2 import convert, timing  # noqa: E402
from vic2.palette import load_indexed  # noqa: E402

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "analysis", "src")
timing.set_standard("pal")
BAD = set(convert.badlines())
C = convert.Converter

orig_fit, orig_do_row, orig_recover = C.fit_line, C.do_row, C.recover


def kind(tag, y):
    """Kind of a missed task: x / c / $d010 of this line or an earlier one, pointer, Y, off."""
    m = re.match(r"([xch])\d*@(\d+)", tag)
    if m:
        k = {"x": "X", "c": "colour", "h": "$d010"}[m.group(1)]
        return k if int(m.group(2)) == y else k + " (earlier line)"
    return {"p": "pointer", "y": "Y restart", "o": "sprites off"}.get(tag[:1], tag or "none")


def fit_line(self, sch, spans, state, snap, fixed, nxt, r, until, y, fut):
    snap0, next_id = sch.snapshot(), sch.next_id
    cfg, first_cfg, last_use = (list(v) for v in state)
    assign = self.assign(spans, cfg, last_use, r, fut)
    tasks, _, _ = self.line_tasks(sch, assign, cfg, first_cfg, last_use, r, y)
    writes = Counter(t.tag[0] for t in tasks)
    try:
        sch.add(tasks + fixed + nxt, until, True, 1)
        fail = None
    except convert.SchedFail as e:
        fail = kind(e.task.tag, y) if e.task else "no schedule"
    sch.restore(snap0)
    sch.next_id = next_id
    res = orig_fit(self, sch, spans, state, snap, fixed, nxt, r, until, y, fut)
    self._cur[y] = dict(r=r, spans=len(spans), writes=writes, fail=fail,
                        dropped=sum(len(sp[3]) for sp in res[0]), ndropped=len(res[0]))
    return res


def do_row(self, sch, fixed, cy, pairs, start):
    self._cur = {}
    res = orig_do_row(self, sch, fixed, cy, pairs, start)
    self._rows[(cy, tuple(pairs))] = self._cur
    return res


def recover(self, y, r, rowpairs, rows, cfg, last_use):
    left = orig_recover(self, y, r, rowpairs, rows, cfg, last_use)
    self._cur[y]["left"] = left
    return left


C.fit_line, C.do_row, C.recover = fit_line, do_row, recover


def where(r):
    if r in BAD:
        return "badline"
    if r + 1 in BAD:
        return "line before badline"
    return "other"


summary = []
for path in sorted(glob.glob(os.path.join(SRC, "*.png"))):
    name = os.path.splitext(os.path.basename(path))[0]
    w, h, img = load_indexed(path)
    conv = C(img, log=lambda *a: None)
    conv._rows = {}
    conv.run()
    out = conv.render()
    lines = {}
    for cy in range(conv.g.rows):
        lines.update(conv._rows[(cy, tuple(conv.pairs[cy]))])
    tot = Counter()
    by_fail, by_where, by_writes = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    for y in range(h):
        L = lines[y]
        pairs = [conv.pairs[y >> 3][x >> 3] for x in range(0, w, 8)]
        cover = conv.spans_of(y, pairs)[1]
        wrong = sum(out[y][x] != img[y][x] for x in range(w))
        assert wrong == L["left"], (name, y, wrong, L["left"])
        nw = sum(L["writes"].values())
        rec = cover + L["dropped"] - L["left"]
        for k, d in ((L["fail"] or "fits", by_fail), (where(L["r"]), by_where),
                     ("%d-%d" % (nw // 3 * 3, nw // 3 * 3 + 2), by_writes)):
            d[k].update(lines=1, dropped=L["dropped"])
        tot.update(lines=1, wrong=wrong, cover=cover, dropped=L["dropped"], recov=rec,
                   lines_dropping=bool(L["ndropped"]), writes=nw,
                   **{"w_" + k: v for k, v in L["writes"].items()})
    summary.append((name, tot))
    print("\n## %s: %d wrong = %d cover + %d dropped - %d recovered; %d of %d lines drop spans;"
          " writes asked: %d X, %d colour, %d $d010 (%.1f a line)"
          % (name, tot["wrong"], tot["cover"], tot["dropped"], tot["recov"],
             tot["lines_dropping"], h, tot["w_x"], tot["w_c"], tot["w_h"], tot["writes"] / h))
    for title, d in (("first missed write, all spans scheduled", by_fail),
                     ("line", by_where), ("writes the line asked for", by_writes)):
        print("\n| %s | lines | dropped px |" % title)
        print("|---|---|---|")
        for k, v in sorted(d.items(), key=lambda kv: -kv[1]["dropped"]):
            print("| %s | %d | %d |" % (k, v["lines"], v["dropped"]))
    sys.stdout.flush()

print("\n| image | wrong | cover | dropped | recovered | lines dropping | writes/line |")
print("|---|---|---|---|---|---|---|")
for name, t in summary:
    print("| %s | %d | %d | %d | %d | %d | %.1f |" % (
        name, t["wrong"], t["cover"], t["dropped"], t["recov"], t["lines_dropping"],
        t["writes"] / t["lines"]))
