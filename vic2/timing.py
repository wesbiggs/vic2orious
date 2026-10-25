"""Cycle-level model of the VIC-II bus stealing and a 6510 straight-line code generator.

Two video systems (set_standard): PAL (6569, 63 cycles x 312 lines) and NTSC (6567R8,
65 cycles x 263 lines). Time is measured in absolute cycles: t = raster * CYCLES +
(cycle - 1), cycle in 1..CYCLES, using the cycle numbering of Christian Bauer's
vic-ii.txt. The sprite DMA cycles follow VICE's cycle tables (viciisc/vicii-chip-model.c):
on the 6567R8 every sprite's p-access is one cycle later (sprites 0-2) or one earlier
(4-7) than on the 6569, and sprite 3's moves to the end of the line before; its Y
compares are one cycle later. Badlines (BA from cycle 12, c-accesses 15-54) and the X
coordinate of each cycle up to the display's right edge (sprite X = 0 in cycle 13) are
the same.

The generator emits an unrolled, cycle-exact raster kernel:
  * a fixed prologue (initial register values, patched at the end),
  * a synchronisation phase that collapses the unknown IRQ entry time onto a single
    timeline by exploiting the 3 "write cycles allowed" after BA goes low,
  * an earliest-deadline-first scheduler that places register writes (each with a
    time window in which the write cycle must land) into the free bus cycles.
"""

STANDARDS = {
    # cycles per line, lines per frame, cycle of each sprite's p-access (BA is low from 3
    # cycles before it to 1 after), first cycle after the sprite Y compares (6569: 55
    # and 56; 6567R8: 56 and 57)
    "pal": dict(CYCLES=63, LINES=312, SPR_P=[58, 60, 62, 1, 3, 5, 7, 9], Y_AFTER=57, FPS=50),
    "ntsc": dict(CYCLES=65, LINES=263, SPR_P=[59, 61, 63, 65, 2, 4, 6, 8], Y_AFTER=58, FPS=60),
}
SYSTEM_ID = {"pal": 0, "ntsc": 1}   # .v2i header byte, v2i_system in v2i.inc
STANDARD = None


def set_standard(name):
    """Select the video system for everything below (module globals)."""
    global STANDARD, CYCLES, LINES, SPR_P, Y_AFTER, FPS
    STANDARD = name
    v = STANDARDS[name]
    CYCLES, LINES, SPR_P, Y_AFTER, FPS = v["CYCLES"], v["LINES"], v["SPR_P"], v["Y_AFTER"], v["FPS"]


set_standard("pal")

# instruction cycle patterns (R = read, W = write)
OPS = {
    "lda#": (0xA9, "RR"), "ldx#": (0xA2, "RR"), "ldy#": (0xA0, "RR"),
    "sta": (0x8D, "RRRW"), "stx": (0x8E, "RRRW"), "sty": (0x8C, "RRRW"),
    "nop": (0xEA, "RR"), "bitzp": (0x24, "RRR"), "inczp": (0xE6, "RRRWW"),
    "stazp": (0x85, "RRW"), "rts": (0x60, "RRRRRR"),
}
LOAD = {"A": "lda#", "X": "ldx#", "Y": "ldy#"}
STORE = {"A": "sta", "X": "stx", "Y": "sty"}
DUMMY_ZP = 0x02  # scratch zero page byte used by sync / filler instructions
FILLERS = [[], ["nop"], ["bitzp"], ["nop", "nop"], ["nop", "bitzp"], ["bitzp", "bitzp"],
           ["nop", "nop", "bitzp"], ["nop", "bitzp", "bitzp"], ["bitzp", "bitzp", "bitzp"],
           ["nop", "nop", "nop", "nop"], ["nop", "nop", "nop", "bitzp"]]


def T(raster, cyc):
    return raster * CYCLES + (cyc - 1)


def p_time(s, d):
    """Time of the p-access of sprite s for its display line d: in the line before for
    the sprites fetched at the end of a line."""
    p = SPR_P[s]
    return T(d - 1, p) if p > CYCLES // 2 else T(d, p)


def raster_of(t):
    return t // CYCLES


def cyc_of(t):
    return t % CYCLES + 1


class Vic:
    """BA (bus available) timeline for a frame."""

    def __init__(self, badlines, sprite_lines):
        """badlines: iterable of raster lines; sprite_lines[s]: rasters on which sprite s is
        displayed. Lines past the frame's last one are left out."""
        self.n = (LINES + 1) * CYCLES + 200
        ba = bytearray(self.n)
        for r in badlines:
            for c in range(12, 55):
                ba[T(r, c)] = 1
        # $d015 = 0 does not stop a running sprite DMA: it ends with its 21-line block, which
        # can run past the last line (200-line image on NTSC) into the top of the next frame.
        # It ends by line 8, before the kernel's entry line (convert.IRQ_LINE), so it is
        # left out here.
        frame = LINES * CYCLES
        for s, lines in enumerate(sprite_lines):
            for d in lines:
                tp = p_time(s, d)
                for t in range(tp - 3, tp + 2):
                    if t < frame:
                        ba[t] = 1
        self.ba = ba
        # wb[t]: a write cycle is not possible at t (BA low for 4+ cycles -> AEC low)
        wb = bytearray(self.n)
        for t in range(3, self.n):
            wb[t] = ba[t] & ba[t - 1] & ba[t - 2] & ba[t - 3]
        self.wb = wb

    def run(self, t, pattern):
        """Execute a cycle pattern starting at t. Returns (end_time, time_of_last_write)."""
        ba, wb = self.ba, self.wb
        w = None
        for ch in pattern:
            if ch == "R":
                while ba[t]:
                    t += 1
            else:
                while wb[t]:
                    t += 1
                w = t
            t += 1
        return t, w


class Task:
    __slots__ = ("id", "reg", "val", "lo", "hi", "tag")

    def __init__(self, id, reg, val, lo, hi, tag=""):
        self.id, self.reg, self.val, self.lo, self.hi, self.tag = id, reg, val, lo, hi, tag

    def __repr__(self):
        return "Task(%s $%04x=%02x [%d:%d..%d:%d] %s)" % (
            self.id, self.reg, self.val, raster_of(self.lo), cyc_of(self.lo),
            raster_of(self.hi), cyc_of(self.hi), self.tag)


class SchedFail(Exception):
    def __init__(self, task, t):
        super().__init__("missed %r at %d:%d" % (task, raster_of(t), cyc_of(t)))
        self.task, self.t = task, t


class Kernel:
    """Builds the unrolled kernel code."""

    def __init__(self, vic, entry_times):
        self.vic = vic
        self.code = bytearray()
        self.hyps = sorted(set(entry_times))
        self.patches = {}  # name -> offset of immediate byte

    # ---- multi-hypothesis emission (prologue + sync) ----
    def _emit_h(self, name, *operands):
        op, pat = OPS[name]
        self.code.append(op)
        for o in operands:
            self.code.append(o & 0xFF)
        self.hyps = sorted(set(self.vic.run(t, pat)[0] for t in self.hyps))

    def prologue(self, writes):
        """writes: list of (reg, value or patch-name)."""
        a = None
        for reg, val in writes:
            if isinstance(val, str):
                self.patches[val] = len(self.code) + 1
                self._emit_h("lda#", 0)
                a = None
            elif val != a:
                self._emit_h("lda#", val)
                a = val
            self._emit_h("sta", reg & 0xFF, reg >> 8)

    def sync(self, max_steps=400):
        """Collapse all entry hypotheses into one timeline."""
        fillers = [[], ["nop"], ["bitzp"], ["nop", "nop"], ["nop", "bitzp"], ["bitzp", "bitzp"],
                   ["nop", "nop", "bitzp"]]
        bodies = ["inczp", "stazp", "sta"]
        steps = 0
        while len(self.hyps) > 1:
            steps += 1
            if steps > max_steps:
                raise RuntimeError("sync did not converge: %r" % self.hyps)
            best = None
            for f in fillers:
                for b in bodies:
                    seq, hy = self._try_seq(f, b)
                    key = (len(set(hy)), max(hy) - min(hy), len(seq))
                    if best is None or key < best[0]:
                        best = (key, seq)
            for name in best[1]:
                if name in ("sta",):
                    self._emit_h(name, 0x02, 0x00)
                elif name in ("inczp", "stazp", "bitzp"):
                    self._emit_h(name, DUMMY_ZP)
                else:
                    self._emit_h(name)
        return self.hyps[0]

    def _try_seq(self, filler, body):
        vic = self.vic
        hy = list(self.hyps)
        seq = []
        for name in filler:
            hy = [vic.run(t, OPS[name][1])[0] for t in hy]
            seq.append(name)
        # find next BA-low period after the latest hypothesis start
        t0 = min(hy)
        b = t0
        while not vic.ba[b]:
            b += 1
        e = b
        while vic.ba[e]:
            e += 1
        # repeat body until every hypothesis has passed the stall
        n = 0
        while min(hy) <= e + 2 and n < 60:
            hy = [vic.run(t, OPS[body][1])[0] for t in hy]
            seq.append(body)
            n += 1
        return seq, hy

    def emit_raw(self, name, *operands):
        op, _ = OPS[name]
        self.code.append(op)
        for o in operands:
            self.code.append(o & 0xFF)


class Scheduler:
    """Incremental EDF scheduler with per-raster-line checkpoints."""

    REWIND = 2  # lines to rewind when new tasks are added

    def __init__(self, kernel, t_start):
        self.k = kernel
        self.vic = kernel.vic
        self.tasks = {}
        self.wtime = {}
        self.trace = None
        self.next_id = 0
        base = (t_start, len(kernel.code), (None, None, None), frozenset())
        self.ck = {raster_of(t_start): base}
        self.base_line = raster_of(t_start)
        self.end_state = base

    def new_task(self, reg, val, lo, hi, tag=""):
        t = Task(self.next_id, reg, val, lo, hi, tag)
        self.next_id += 1
        return t

    def snapshot(self):
        return (bytes(self.k.code), dict(self.ck), dict(self.tasks), self.end_state)

    def restore(self, snap):
        code, ck, tasks, end = snap
        self.k.code[:] = code
        self.ck, self.tasks, self.end_state = dict(ck), dict(tasks), end

    def add(self, new_tasks, until_raster, rewind=True):
        """Add tasks and (re)schedule up to the start of until_raster+1. Raises SchedFail."""
        for t in new_tasks:
            self._tighten(t)
            if t.hi < t.lo:
                raise SchedFail(t, t.lo)
            self.tasks[t.id] = t
        lines = [raster_of(t.lo) for t in new_tasks]
        cur_line = raster_of(self.end_state[0])
        start = cur_line - self.REWIND
        if lines:
            start = min(start, max(min(lines), cur_line - 3 * self.REWIND))
        start = max(start, self.base_line)
        if not rewind:
            start = cur_line
        while start not in self.ck:
            start -= 1
        self._run(self.ck[start], T(until_raster + 1, 1))

    def _run(self, state, t_end):
        vic = self.vic
        code = self.k.code
        t, clen, regs, done = state
        del code[clen:]
        regs = list(regs)
        done = set(done)
        for line in [l for l in self.ck if l > raster_of(t)]:
            del self.ck[line]
        pending = sorted((tk for tid, tk in self.tasks.items() if tid not in done), key=lambda x: x.hi)
        RN = ("A", "X", "Y")

        def emit(name, *ops):
            nonlocal t
            op, pat = OPS[name]
            code.append(op)
            for o in ops:
                code.append(o & 0xFF)
            t0 = t
            t, w = vic.run(t, pat)
            if self.trace is not None:
                self.trace.append((t0, name, ops))
            return w

        def next_use(val, exclude=None):
            best = None
            for tk in pending:
                if tk is not exclude and tk.val == val:
                    if best is None or tk.lo < best:
                        best = tk.lo
            return best

        def pick_reg(protect=()):
            # Belady: evict register whose value is needed farthest in the future
            cand = []
            for i in range(3):
                if regs[i] in protect:
                    continue
                nu = next_use(regs[i]) if regs[i] is not None else None
                cand.append((float("inf") if nu is None else nu, i))
            cand.sort(reverse=True)
            return cand[0][1]

        def landing(t0, need_load):
            pat = ("RR" if need_load else "") + "RRRW"
            return vic.run(t0, pat)[1]

        last_line = raster_of(t)
        while True:
            line = raster_of(t)
            if line > last_line:
                for l in range(last_line + 1, line + 1):
                    self.ck[l] = (t, len(code), tuple(regs), frozenset(done))
                last_line = line
            if t >= t_end and not any(tk.hi < t_end for tk in pending):
                break
            if not pending:
                if t >= t_end:
                    break
                gap = t_end - t
                emit("bitzp", DUMMY_ZP) if gap % 2 == 1 and gap >= 3 else emit("nop")
                continue
            w_direct = landing(t, False)
            for tk in pending:
                if tk.hi < w_direct and tk.val not in regs:
                    raise SchedFail(tk, t)
                if tk.hi < w_direct:
                    raise SchedFail(tk, t)
            ready = [tk for tk in pending if tk.lo <= w_direct]

            def ok_after(pat, regs_after, exclude=None):
                t1 = vic.run(t, pat)[0]
                for v in pending:
                    if v.hi > t + 190:
                        break
                    if v is exclude:
                        continue
                    if not self._can_meet(v, t1, v.val in regs_after) and self._can_meet(v, t, v.val in regs):
                        return False
                return True

            acted = False
            for u in ready:  # pending is sorted by hi, so ready is too
                if u.val in regs:
                    if not ok_after("RRRW", regs, u):
                        continue
                    r = regs.index(u.val)
                    w = emit(STORE[RN[r]], u.reg & 0xFF, u.reg >> 8)
                    if not (u.lo <= w <= u.hi):
                        raise SchedFail(u, w)
                    pending.remove(u)
                    done.add(u.id)
                    self.wtime[u.id] = w
                else:
                    if landing(t, True) > u.hi:
                        raise SchedFail(u, t)
                    r = pick_reg()
                    regs2 = list(regs)
                    regs2[r] = u.val
                    if not ok_after("RR", regs2):
                        continue
                    emit(LOAD[RN[r]], u.val)
                    regs[r] = u.val
                acted = True
                break
            if acted:
                continue
            # nothing (safely) ready: prefetch upcoming values, else wait
            upcoming = pending[:3]
            want = []
            for tk in upcoming:
                if tk.val not in want:
                    want.append(tk.val)
            did = False
            for v in want:
                if v not in regs:
                    r = pick_reg(protect=[x for x in want if x != v])
                    if regs[r] in want:
                        break
                    regs2 = list(regs)
                    regs2[r] = v
                    if not ok_after("RR", regs2):
                        break
                    emit(LOAD[RN[r]], v)
                    regs[r] = v
                    did = True
                    break
            if did:
                continue
            nxt = min(pending, key=lambda x: (x.hi, x.lo))
            soon = min(pending, key=lambda x: x.lo)
            # find the shortest filler after which a store of the most urgent task lands in its window
            plan = None
            for tgt in (nxt, soon):
                need = tgt.val not in regs
                for fill in FILLERS:
                    tt = t
                    for name in fill:
                        tt = vic.run(tt, OPS[name][1])[0]
                    w = landing(tt, need)
                    if tgt.lo <= w <= tgt.hi:
                        plan = fill
                        break
                if plan is not None:
                    break
            if plan:
                first = plan[0]
            else:
                gap = soon.lo - w_direct
                first = "bitzp" if gap >= 3 and gap % 2 == 1 else "nop"
            if not ok_after(OPS[first][1], regs):
                other = "nop" if first == "bitzp" else "bitzp"
                if ok_after(OPS[other][1], regs):
                    first = other
            emit(first, DUMMY_ZP) if first == "bitzp" else emit(first)
        self.end_state = (t, len(code), tuple(regs), frozenset(done))

    def _safe_to_do(self, u, t, regs, pending):
        """Doing u now must not make a more urgent pending task miss its window."""
        vic = self.vic
        need = u.val not in regs
        t1, w = vic.run(t, ("RR" if need else "") + "RRRW")
        if w > u.hi:
            return True  # will fail anyway; let caller raise
        regs2 = list(regs)
        if need:
            # approximate: assume we evict something not needed by others
            regs2[0] = u.val
        for v in pending:
            if v is u or v.hi >= u.hi + 200:
                continue
            if v.hi >= u.hi:
                break
            if not self._can_meet(v, t1, v.val in regs2):
                if self._can_meet(v, t, v.val in regs):
                    return False
        return True

    def _tighten(self, tk):
        """Shrink a task's window to write cycles a store can actually hit (matters on badlines)."""
        vic = self.vic
        lo, hi = tk.lo, tk.hi
        best = None
        for ts in range(lo - 70, hi + 1):
            w = vic.run(ts, "RRRW")[1]
            if lo <= w <= hi:
                best = w
                break
        if best is None:
            tk.hi = lo - 1
            return
        tk.lo = best
        for ts in range(hi, lo - 70, -1):
            w = vic.run(ts, "RRRW")[1]
            if lo <= w <= hi:
                tk.hi = w
                break

    def _can_meet(self, v, t0, have):
        """Can a store of v (after an optional load) starting no earlier than t0 land in its window?"""
        vic = self.vic
        starts = [t0]
        if not have:
            starts = [vic.run(t0, "RR")[0]]  # load first, then wait
        for ts in starts:
            for d in [0] + list(range(2, 70)):
                w = vic.run(vic.run(ts, "R" * d)[0], "RRRW")[1]
                if v.lo <= w <= v.hi:
                    return True
                if w > v.hi:
                    break
        return False

    def finish(self):
        t, clen, regs, done = self.end_state
        del self.k.code[clen:]
        # sprites off, so that blocks restarted by early Y writes do not repeat old data
        self.k.emit_raw("lda#", 0)
        self.k.emit_raw("sta", 0x15, 0xD0)
        self.k.emit_raw("rts")
        return t
