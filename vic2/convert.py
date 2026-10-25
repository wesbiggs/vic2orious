"""Convert a C64-palette image into hires bitmap + per-line multiplexed hires sprites.

Width and height must be multiples of 8 (width up to 256, height up to 200). Every 8x8
cell gets two bitmap colours; every pixel of any other colour must be painted by one of the
8 hardware sprites. On each raster line the 8 sprites may be re-coloured and re-positioned
(by the generated raster kernel), so each line needs a set of at most 8 "spans" (24 pixel
wide, single colour). Lines needing more spans keep the 8 covering the most pixels; lines
whose retasking writes do not fit drop the spans losing the fewest pixels. Uncovered pixels
fall back to the nearer of the two cell colours.
"""

import functools
import heapq
import itertools

from . import timing
from .timing import T, Task, SchedFail

SPR_START = [14 + 2 * s for s in range(8)]   # raster of each sprite's first block
IRQ_LINE = 9          # kernel entry line (V2I_IRQ_LINE): below sprite DMA left running
                      # past the frame end (200-line image on NTSC: up to line 8)
ZERO_SLOT = 16        # sprite pointer of the all-zero block ($c400)
D011 = 0x3B
PIX_C0 = 13           # cycle in which sprite X coordinate x is drawn = PIX_C0 + x//8
MARGIN = 1            # extra safety cycles around every pixel edge
FIT_TRIES = 24        # schedules tried per line before dropping spans greedily
ROW_WEIGHTS = (150, 40)  # cell colour searches per row: cost of a pixel no span covers
MAX_W, MAX_H = 256, 200
REG_X = [0xD000 + 2 * s for s in range(8)]
REG_Y = [0xD001 + 2 * s for s in range(8)]
REG_C = [0xD027 + s for s in range(8)]
PTR = [0xC3F8 + s for s in range(8)]


def pc(xreg):
    return PIX_C0 + (xreg >> 3)


def badlines():
    return [r for r in range(0x30, 0xF8) if r & 7 == 3]


def block_of(s, raster):
    return (raster - SPR_START[s]) // 21


def block_start(s, k):
    return SPR_START[s] + 21 * k


class Geometry:
    """Image size and its place on the screen, in whole characters: the upper left corner
    by default, char row 1, column 1 with a frame (which the player draws in the ring of
    cells around the image), or any (column, row) passed as at.

    The X high bit ($d010) is never used, so sprites can start at most at X=255: the
    image must start at screen x <= 231, and pixel columns right of x = 255 + 24 can only
    be painted by the bitmap (a 256 wide image at column 0 loses its last column).
    """

    def __init__(self, w, h, frame=False, at=None):
        if w % 8 or h % 8 or not (8 <= w <= MAX_W) or not (8 <= h <= MAX_H):
            raise ValueError("image must be WxH with W, H multiples of 8, W <= %d, H <= %d (got %dx%d)"
                             % (MAX_W, MAX_H, w, h))
        self.w, self.h = w, h
        self.cols, self.rows = w // 8, h // 8
        self.col0, self.row0 = at if at is not None else ((1, 1) if frame else (0, 0))
        if self.col0 < 0 or self.row0 < 0 or self.col0 + self.cols > 40 or self.row0 + self.rows > 25:
            raise ValueError("a %dx%d image does not fit on the screen at column %d, row %d"
                             % (w, h, self.col0, self.row0))
        if 24 + 8 * self.col0 > 255:
            raise ValueError("images must start at column %d or less" % ((255 - 24) // 8))
        if frame and not self.frame_fits(self.col0, self.row0, self.cols, self.rows):
            raise ValueError("no room for a frame around a %dx%d image at column %d, row %d"
                             % (w, h, self.col0, self.row0))
        self.frame = frame
        self.raster0 = 0x33 + 8 * self.row0     # first raster line of the image (a badline)
        self.xreg0 = 24 + 8 * self.col0         # sprite X register value for image column 0
        self.xs_max = 255 - self.xreg0          # rightmost span start (image column)

    @staticmethod
    def frame_fits(col0, row0, cols, rows):
        """The frame needs the ring of cells around the image."""
        return col0 >= 1 and row0 >= 1 and col0 + cols <= 39 and row0 + rows <= 24

    def first_image_block(self, s):
        k = 0
        while block_start(s, k) + 20 < self.raster0:
            k += 1
        return k

    def slot_of(self, s, k):
        k0 = self.first_image_block(s)
        if k < k0:
            return ZERO_SLOT
        return ZERO_SLOT + 1 + (k - k0) * 8 + s

    def sprite_lines(self):
        """DMA lines of each sprite: $d015 = 0 lands in the image's last line after the Y
        compares (see "off" in Converter.run), so blocks starting on the line below still
        start, none later, and a started block runs its 21 lines (possibly into the next
        frame, which timing.Vic wraps to the top)."""
        r = self.raster0 + self.h
        return [range(SPR_START[s], block_start(s, block_of(s, r)) + 21) for s in range(8)]


# ---------------------------------------------------------------- spans

@functools.lru_cache(maxsize=1 << 16)
def colour_cover(xs, xs_max, kmax):
    """Exact cover DP for the problem pixels xs (sorted) of one colour. nxt[i] is the first
    pixel after a span whose leftmost pixel is xs[i]; f[i][k] the best value (16 * pixels
    covered - spans used) for pixels i.. with at most k spans."""
    n = len(xs)
    nxt = [0] * n
    j = 0
    for i in range(n):
        j = max(j, i)
        while j < n and xs[j] <= min(xs[i], xs_max) + 23:
            j += 1
        nxt[i] = j
    f = [[0] * (kmax + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        fi, f1 = f[i], f[i + 1]
        fn = f[nxt[i]]
        run = 16 * (nxt[i] - i) - 1
        for k in range(1, kmax + 1):
            take = run + fn[k - 1] if nxt[i] > i else -1
            fi[k] = take if take > f1[k] else f1[k]
    return nxt, f


@functools.lru_cache(maxsize=1 << 16)
def cover(by_c, xs_max, kmax):
    """Cover of a line's problem pixels by_c = ((colour, xs), ...) by at most kmax 24-wide
    single colour spans starting no further right than xs_max: as many pixels as possible,
    then as few spans as possible (exact DP per colour, knapsack over colours). Returns
    (spans, lost) with spans a tuple of (color, first_x, last_x, (xs)) and lost the number
    of problem pixels left uncovered (including pixels beyond the reach of the rightmost
    possible span)."""
    total = sum(len(xs) for _, xs in by_c)
    tables = {}
    best = {0: (0, ())}             # spans used -> (value, ((colour, spans), ...))
    for c, xs in by_c:
        nxt, f = colour_cover(xs, xs_max, kmax)
        tables[c] = (xs, nxt, f)
        nb = {}
        for used, (v, picks) in best.items():
            for k in range(kmax - used + 1):
                if k and f[0][k] <= f[0][k - 1]:
                    break
                v2 = v + f[0][k]
                if used + k not in nb or v2 > nb[used + k][0]:
                    nb[used + k] = (v2, picks + ((c, k),))
        best = nb
    _, picks = max(best.values(), key=lambda e: e[0])
    spans, covered = [], 0
    for c, k in picks:
        xs, nxt, f = tables[c]
        i = 0
        while k and i < len(xs):
            if f[i][k] == f[i + 1][k]:
                i += 1
                continue
            spans.append((c, xs[i], xs[nxt[i] - 1], tuple(xs[i:nxt[i]])))
            covered += nxt[i] - i
            i, k = nxt[i], k - 1
    return tuple(spans), total - covered


@functools.lru_cache(maxsize=1 << 16)
def spans_cost(prev_spans, spans):
    """Rough number of sprite retasks between two lines."""
    used = [False] * len(prev_spans)
    miss = 0
    for c, a, b, _ in spans:
        ok = False
        for i, (pc_, pa, pb, _) in enumerate(prev_spans):
            if not used[i] and pc_ == c and max(b - 23, pb - 23) <= min(a, pa):
                used[i] = True
                ok = True
                break
        if not ok:
            miss += 1
    return miss


# ---------------------------------------------------------------- converter

class Converter:
    def __init__(self, img, log=print, frame=False, at=None):
        self.img = img
        self.log = log
        self.g = g = Geometry(len(img[0]), len(img), frame, at)
        self.cell_colors = [[None] * g.cols for _ in range(g.rows)]
        for cy in range(g.rows):
            for cx in range(g.cols):
                cnt = {}
                for y in range(cy * 8, cy * 8 + 8):
                    for x in range(cx * 8, cx * 8 + 8):
                        cnt[img[y][x]] = cnt.get(img[y][x], 0) + 1
                self.cell_colors[cy][cx] = cnt
        self.pairs = [[None] * g.cols for _ in range(g.rows)]
        # per line and cell: ((colour, xs), ...) in order of first appearance
        self.line_cells = []
        for y in range(g.h):
            cells = []
            for cx in range(g.cols):
                by_c = {}
                for x in range(cx * 8, cx * 8 + 8):
                    by_c.setdefault(img[y][x], []).append(x)
                cells.append(tuple((c, tuple(xs)) for c, xs in by_c.items()))
            self.line_cells.append(cells)

    def spans_of(self, y, pairs):
        """cover() of image line y's problem pixels: those not in their cell's colour pair."""
        by_c = {}
        for p, cell in zip(pairs, self.line_cells[y]):
            for c, xs in cell:
                if c not in p:
                    by_c[c] = by_c[c] + xs if c in by_c else xs
        return cover(tuple(by_c.items()), self.g.xs_max, 8)

    # ---- cell colour choice for one character row
    def row_cost(self, cy, pairs, prev_spans, lost_px):
        cost = 0
        prev = prev_spans
        for i in range(8):
            y = cy * 8 + i
            sp, lost = self.spans_of(y, pairs)
            cost += lost_px * lost + 5 * len(sp)
            if prev is not None:
                cost += 20 * spans_cost(prev, sp)
            prev = sp
        return cost

    def choose_row(self, cy, prev_spans, lost_px):
        cands = []
        for cx in range(self.g.cols):
            cnt = self.cell_colors[cy][cx]
            cols = sorted(cnt, key=lambda c: -cnt[c])
            if len(cols) == 1:
                cands.append([(cols[0], cols[0])])
            elif len(cols) == 2:
                cands.append([(cols[0], cols[1])])
            else:
                cands.append(list(itertools.combinations(cols, 2)))
        pairs = [c[0] for c in cands]
        best = self.row_cost(cy, pairs, prev_spans, lost_px)
        # local search: change one cell at a time; when that is stuck, two neighbours at once
        # (a span often needs both cells under it to give up the same colour)
        moves = [[(cx, p)] for cx in range(self.g.cols) for p in cands[cx] if len(cands[cx]) > 1]
        moves2 = [[(cx, p), (cx + 1, q)] for cx in range(self.g.cols - 1)
                  for p in cands[cx] for q in cands[cx + 1]
                  if len(cands[cx]) > 1 and len(cands[cx + 1]) > 1]
        stuck = False
        for _ in range(16):
            improved = False
            for mv in moves2 if stuck else moves:
                if all(pairs[cx] == p for cx, p in mv):
                    continue
                old = [(cx, pairs[cx]) for cx, _ in mv]
                for cx, p in mv:
                    pairs[cx] = p
                c = self.row_cost(cy, pairs, prev_spans, lost_px)
                if c < best:
                    best = c
                    improved = True
                else:
                    for cx, p in old:
                        pairs[cx] = p
            if not improved and stuck:
                break
            stuck = not improved
        return pairs, best

    # ---- main
    def run(self):
        g = self.g
        RASTER0, XREG0, IMG_W, IMG_H = g.raster0, g.xreg0, g.w, g.h
        slot_of = g.slot_of
        vic = timing.Vic(badlines(), g.sprite_lines())
        entry = [T(IRQ_LINE, c) for c in range(20, 48)]
        k = timing.Kernel(vic, entry)
        # sprites on before sprite 0's first Y compare (line SPR_START[0] - 1, cycle 55 on
        # PAL), so the Y registers and $d015 first ($d015 is 0 from the last frame or
        # v2i_stop); pointers, colours and the rest are needed only from the image on
        pro = [(REG_Y[s], SPR_START[s] - 1) for s in range(8)]
        pro += [(0xD017, 0), (0xD015, 0xFF)]
        pro += [(PTR[s], ZERO_SLOT) for s in range(8)]
        pro += [(r, 0) for r in (0xD010, 0xD01B, 0xD01C, 0xD01D)]   # not $d020/$d021 (v2i_start)
        pro += [(0xD016, 0x08), (0xD018, 0x08), (0xD011, D011)]
        for s in range(8):
            pro += [(REG_X[s], "X%d" % s), (REG_C[s], "C%d" % s)]
        k.prologue(pro)
        t0 = k.sync()
        self.log("  sync done at raster %d cycle %d" % (timing.raster_of(t0), timing.cyc_of(t0)))
        self.kernel = k
        sch = timing.Scheduler(k, t0)
        self.sched = sch

        # fixed tasks: Y restarts and pointer changes, created lazily per raster line
        fixed = {}  # raster -> list of tasks whose hi falls on that raster
        ptr_tasks = []  # (first raster of new block, task)
        for s in range(8):
            for kk in range(1, 16):
                B = block_start(s, kk)
                if B > RASTER0 + IMG_H + 2:
                    break
                ty = sch.new_task(REG_Y[s], B - 1, T(B - 22, timing.Y_AFTER), T(B - 1, 54),
                                  "y%d.%d" % (s, kk))
                fixed.setdefault(B - 21, []).append(ty)  # add early: EDF fills idle time with it
                if slot_of(s, kk) != slot_of(s, kk - 1):
                    tp_old = timing.p_time(s, B - 1)
                    tp_new = timing.p_time(s, B)
                    tk = sch.new_task(PTR[s], slot_of(s, kk), tp_old + 1, tp_new - 1, "p%d.%d" % (s, kk))
                    sch._tighten(tk)
                    fixed.setdefault(timing.raster_of(tk.hi), []).append(tk)
                    ptr_tasks.append((B, tk))

        # schedule everything before the image
        pre = []
        for r in sorted(fixed):
            if r < RASTER0:
                pre += fixed[r]
        sch.add(pre, RASTER0 - 1)

        # sprite state
        cfg = [None] * 8          # (xstart, color)
        first_cfg = [None] * 8
        last_use = [None] * 8     # (raster, last pixel xreg)
        self.sdata = [dict() for _ in range(8)]   # raster -> 24-bit row
        self.line_cfg = [dict() for _ in range(8)]  # raster -> (xstart, color)
        prev_spans = None
        img = self.img
        self.bad_lines = {}   # y -> reason
        for cy in range(g.rows):
            # try the cell colours the search finds for each weight, keep the one that
            # really schedules with the fewest wrong pixels
            snap = sch.snapshot()
            start = (cfg, first_cfg, last_use, prev_spans)
            tried, best = [], None
            for w in ROW_WEIGHTS:
                pairs, _ = self.choose_row(cy, prev_spans, w)
                if pairs in tried:
                    continue
                tried.append(pairs)
                sch.restore(snap)
                try:
                    res = self.do_row(sch, fixed, cy, pairs, start)
                except SchedFail:
                    continue
                if best is None or res[0] < best[0]:
                    best = res + (pairs, sch.snapshot())
            if best is None:
                raise SchedFail(None, None)
            _, cfg, first_cfg, last_use, prev_spans, lines, pairs, done = best
            sch.restore(done)
            self.pairs[cy] = pairs
            for y, rows, why in lines:
                for s, (bits, c) in rows.items():
                    self.sdata[s][RASTER0 + y] = bits
                    self.line_cfg[s][RASTER0 + y] = c
                if why:
                    self.bad_lines[y] = why
        # end of image: sprites off before any further Y compare, so no block starts without
        # its pointer (the rest of the screen may hold text); after the Y compares in the last
        # line, so the blocks starting below it always start (sprite_lines models them)
        r = RASTER0 + IMG_H
        lo = max(T(r - 1, pc(XREG0 + IMG_W - 1) + 1 + MARGIN), T(r - 1, timing.Y_AFTER))
        off = sch.new_task(0xD015, 0, lo, T(r, 54), "off")
        extra = [p for (B, p) in ptr_tasks if B <= r and p.id not in sch.tasks]
        sch.add([off] + extra, r)
        self.cut = IMG_H
        sch.finish()
        for s in range(8):
            fc = first_cfg[s] or (0, 0)
            k.code[k.patches["X%d" % s]] = (XREG0 + fc[0]) & 0xFF
            k.code[k.patches["C%d" % s]] = fc[1]
        return len(self.bad_lines)

    def do_row(self, sch, fixed, cy, pairs, start):
        """Schedule the 8 lines of character row cy with the given cell colours. Returns
        (wrong pixels, cfg, first_cfg, last_use, prev_spans, [(y, {sprite: (bits, cfg)}, why)])."""
        g, img = self.g, self.img
        cfg, first_cfg, last_use, prev_spans = (list(v) if isinstance(v, list) else v for v in start)
        rowpairs = [set(p) for p in pairs]
        wrong = 0
        lines = []
        for i in range(8):
            y = cy * 8 + i
            r = g.raster0 + y
            spans, lost = self.spans_of(y, pairs)
            why = "%d pixels not covered by 8 spans" % lost if lost else ""
            state = (list(cfg), list(first_cfg), list(last_use))
            snap = sch.snapshot()
            fut = [self.spans_of(yy, pairs)[0] for yy in range(y + 1, min(cy * 8 + 8, y + 4))]
            dropped, cfg, first_cfg, last_use, rows = self.fit_line(
                sch, spans, state, snap, fixed.get(r, []), r, y, fut)
            wrong += self.recover(y, r, rowpairs, rows, cfg, last_use)
            if dropped:
                why = (why + "; " if why else "") + "dropped %d span(s) for timing" % len(dropped)
            lines.append((y, {s: (bits, cfg[s]) for s, bits in rows.items()}, why))
            prev_spans = spans
        return wrong, cfg, first_cfg, last_use, prev_spans, lines

    def fit_line(self, sch, spans, state, snap, fixed, r, y, fut):
        """Schedule one line, dropping spans until its writes fit. Best-first search over the
        sets of dropped spans (fewest lost pixels first, at most FIT_TRIES schedules), then
        greedy: keep dropping the span whose write missed, else the smallest retasked one."""
        def attempt(dropped, rewind):
            cfg, first_cfg, last_use = (list(v) for v in state)
            live = [sp for sp in spans if sp not in dropped]
            assign = self.assign(live, cfg, last_use, r, fut)
            tasks, rows, owner = self.line_tasks(sch, assign, cfg, first_cfg, last_use, r, y)
            try:
                sch.add(tasks + fixed, r, rewind)
                return (cfg, first_cfg, last_use, rows), None, None
            except SchedFail as e:
                sch.restore(snap)
                return None, owner.get(e.task.id), set(owner.values())

        for rewind in (True, False):
            # an already committed write may no longer fit when the previous lines are
            # rescheduled: then keep them as they are
            heap = [(0, False, ())]
            seen = {()}
            tries = 0
            while heap and tries < FIT_TRIES:
                _, _, dropped = heapq.heappop(heap)
                tries += 1
                res, victim, cands = attempt(dropped, rewind)
                if res:
                    return (list(dropped),) + res
                for sp in cands:
                    d = tuple(sorted(dropped + (sp,)))
                    if d not in seen:
                        seen.add(d)
                        # among equal losses try the span whose write missed first
                        heapq.heappush(heap, (sum(len(q[3]) for q in d), sp != victim, d))
            dropped = []
            while True:
                res, victim, cands = attempt(dropped, rewind)
                if res:
                    return (dropped,) + res
                if not cands:
                    break
                dropped.append(victim or min(cands, key=lambda sp: len(sp[3])))
        raise SchedFail(None, None)

    def recover(self, y, r, rowpairs, rows, cfg, last_use):
        """Let sprites paint problem pixels left uncovered (by the 8 span limit or dropped
        spans) when their colour and position already reach them: no register writes.
        A sprite painting a span already may only add pixels right of its first one, which
        its writes for this line are due before. Returns the number still uncovered."""
        XREG0, W = self.g.xreg0, self.g.w
        need = {}
        for x, c in enumerate(self.img[y]):
            if c not in rowpairs[x >> 3]:
                need[x] = c
        for s, bits in rows.items():
            xs = cfg[s][0]
            for i in range(24):
                if bits >> (23 - i) & 1:
                    need.pop(xs + i, None)
        for s in range(8):
            if cfg[s] is None:
                continue
            xs, c = cfg[s]
            bits = rows.get(s, 0)
            first = xs
            while bits and not bits >> (23 - (first - xs)) & 1:
                first += 1
            new = bits
            for x in range(first, min(xs + 24, W)):
                if need.get(x) == c:
                    new |= 1 << (23 - (x - xs))
                    del need[x]
            if new != bits:
                rows[s] = new
                last = xs + 23
                while not new >> (23 - (last - xs)) & 1:
                    last -= 1
                last_use[s] = (r, XREG0 + last)
        return len(need)

    def line_tasks(self, sch, assign, cfg, first_cfg, last_use, r, y):
        """Register write tasks and sprite rows for one line; updates cfg/first_cfg/last_use."""
        XREG0 = self.g.xreg0
        tasks, rows, owner = [], {}, {}
        for s, (sp, xs) in assign.items():
            c, a, b, pxs = sp
            newcfg = (xs, c)
            first_px = XREG0 + a
            if cfg[s] is None:
                first_cfg[s] = newcfg
            elif cfg[s] != newcfg:
                lr, lx = last_use[s]
                lo = T(lr, pc(lx) + 1 + MARGIN)
                if cfg[s][1] != c:
                    tk = sch.new_task(REG_C[s], c, lo, T(r, pc(first_px) - 1 - MARGIN), "c%d@%d" % (s, y))
                    tasks.append(tk)
                    owner[tk.id] = sp
                if cfg[s][0] != xs:
                    xm = XREG0 + min(cfg[s][0], xs)
                    tk = sch.new_task(REG_X[s], (XREG0 + xs) & 0xFF, lo, T(r, pc(xm) - 1 - MARGIN),
                                      "x%d@%d" % (s, y))
                    tasks.append(tk)
                    owner[tk.id] = sp
            cfg[s] = newcfg
            last_use[s] = (r, XREG0 + b)
            bits = 0
            for x in pxs:
                bits |= 1 << (23 - (x - xs))
            rows[s] = bits
        return tasks, rows, owner

    # ---- span -> sprite assignment (min writes), DP over sprite subsets
    def assign(self, spans, cfg, last_use, r, fut):
        m = len(spans)
        if m == 0:
            return {}
        opts = []  # per span, per sprite: (cost, xstart)
        for j, (c, a, b, pxs) in enumerate(spans):
            lo_x, hi_x = b - 23, min(a, self.g.xs_max)
            row = []
            for s in range(8):
                cur = cfg[s]
                writes = 0
                if cur is None:
                    xs = self.pick_x(c, lo_x, hi_x, fut)
                    cost = 0
                else:
                    if cur[1] != c:
                        writes += 1
                    if lo_x <= cur[0] <= hi_x:
                        xs = cur[0]
                    else:
                        writes += 1
                        xs = self.pick_x(c, lo_x, hi_x, fut)
                    cost = writes * 100
                    if writes:
                        lr, lx = last_use[s]
                        idle = r - lr
                        # prefer sprites idle for longer (bigger write window), and sprites
                        # whose last pixels were far left on the previous line
                        cost -= min(idle, 6) * 8
                        if idle == 1:
                            cost += max(0, (lx - self.g.xreg0) - a) // 8
                row.append((cost, xs))
            opts.append(row)
        INF = float("inf")
        dp = {0: (0, [])}
        for j in range(m):
            nd = {}
            for mask, (cst, lst) in dp.items():
                for s in range(8):
                    if mask & (1 << s):
                        continue
                    c2 = cst + opts[j][s][0]
                    nm = mask | (1 << s)
                    if nm not in nd or c2 < nd[nm][0]:
                        nd[nm] = (c2, lst + [s])
            dp = nd
        best = min(dp.values(), key=lambda v: v[0])
        return {s: (spans[j], opts[j][s][1]) for j, s in enumerate(best[1])}

    def pick_x(self, c, lo_x, hi_x, fut):
        best = None
        for xs in range(lo_x, hi_x + 1):
            score = 0
            for w, sp in zip((4, 2, 1), fut):
                for (c2, a2, b2, _) in sp:
                    if c2 == c and xs <= a2 and b2 <= xs + 23:
                        score += w
            key = (score, -abs(xs - (lo_x + hi_x) / 2))
            if best is None or key > best[0]:
                best = (key, xs)
        return best[1]

    # ---- outputs
    def sprite_cover(self):
        """Per pixel: colour painted by the sprites (topmost = lowest sprite number), or None."""
        W, H = self.g.w, self.g.h
        cov = [[None] * W for _ in range(H)]
        for y in range(H):
            r = self.g.raster0 + y
            for s in range(7, -1, -1):
                bits = self.sdata[s].get(r)
                if not bits:
                    continue
                xs, c = self.line_cfg[s][r]
                for i in range(24):
                    if bits & (1 << (23 - i)) and 0 <= xs + i < W:
                        cov[y][xs + i] = c
        return cov

    def bitmap(self):
        """Bitmap bits (1 = cell foreground). Pixels the sprites failed to paint get the
        nearer of the two cell colours."""
        from .palette import PEPTO

        def dist(a, b):
            return sum((p - q) ** 2 for p, q in zip(PEPTO[a], PEPTO[b]))
        cov = self.sprite_cover()
        W, H = self.g.w, self.g.h
        bits = [[0] * W for _ in range(H)]
        for y in range(H):
            for x in range(W):
                fg, bg = self.pairs[y >> 3][x >> 3]
                c = self.img[y][x]
                if c == fg and fg != bg:
                    bits[y][x] = 1
                elif c != bg and cov[y][x] is None and dist(c, fg) < dist(c, bg):
                    bits[y][x] = 1
        return bits

    def render(self):
        """What the VIC should display, as palette indices."""
        cov = self.sprite_cover()
        bits = self.bitmap()
        W, H = self.g.w, self.g.h
        out = [[0] * W for _ in range(H)]
        for y in range(H):
            for x in range(W):
                fg, bg = self.pairs[y >> 3][x >> 3]
                out[y][x] = cov[y][x] if cov[y][x] is not None else (fg if bits[y][x] else bg)
        return out
