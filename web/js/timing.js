// Port of vic2/timing.py: the VIC-II bus model and the raster kernel generator. It must
// make the same kernel as the Python byte for byte (web/test/golden.mjs checks), so it
// follows the Python closely, ties and orders included; see that file for the details.

export const STANDARDS = {
  pal: { CYCLES: 63, LINES: 312, SPR_P: [58, 60, 62, 1, 3, 5, 7, 9], Y_AFTER: 57, FPS: 50 },
  ntsc: { CYCLES: 65, LINES: 263, SPR_P: [59, 61, 63, 65, 2, 4, 6, 8], Y_AFTER: 58, FPS: 60 },
};
export const SYSTEM_ID = { pal: 0, ntsc: 1 };
export let STANDARD = null;
export let CYCLES, LINES, SPR_P, Y_AFTER, FPS;

export function setStandard(name) {
  const v = STANDARDS[name];
  if (!v) throw new Error("unknown video system " + name);
  STANDARD = name;
  ({ CYCLES, LINES, SPR_P, Y_AFTER, FPS } = v);
}
setStandard("pal");

export const OPS = {
  "lda#": [0xa9, "RR"], "ldx#": [0xa2, "RR"], "ldy#": [0xa0, "RR"],
  sta: [0x8d, "RRRW"], stx: [0x8e, "RRRW"], sty: [0x8c, "RRRW"],
  nop: [0xea, "RR"], bitzp: [0x24, "RRR"], inczp: [0xe6, "RRRWW"],
  stazp: [0x85, "RRW"], rts: [0x60, "RRRRRR"],
};
const OPLEN = { 0xa9: 2, 0xa2: 2, 0xa0: 2, 0x8d: 3, 0x8e: 3, 0x8c: 3, 0xea: 1, 0x24: 2,
  0xe6: 2, 0x85: 2, 0x60: 1 };

/** Offsets of the high byte of every absolute store to an address in ptrs (a Set). */
export function pointerHiOffsets(code, ptrs) {
  const out = [];
  let i = 0;
  while (i < code.length) {
    const op = code[i];
    if (op === OPS.sta[0] || op === OPS.stx[0] || op === OPS.sty[0]) {
      if (ptrs.has(code[i + 1] | (code[i + 2] << 8))) out.push(i + 2);
    }
    if (!(op in OPLEN)) throw new Error("kernel does not decode at " + i);
    i += OPLEN[op];
  }
  if (i !== code.length) throw new Error(`kernel does not decode: ends at ${i} of ${code.length}`);
  return out;
}

const LOAD = { A: "lda#", X: "ldx#", Y: "ldy#" };
const STORE = { A: "sta", X: "stx", Y: "sty" };
const RN = ["A", "X", "Y"];
export const DUMMY_ZP = 0x02;
const FILLERS = [[], ["nop"], ["bitzp"], ["nop", "nop"], ["nop", "bitzp"], ["bitzp", "bitzp"],
  ["nop", "nop", "bitzp"], ["nop", "bitzp", "bitzp"], ["bitzp", "bitzp", "bitzp"],
  ["nop", "nop", "nop", "nop"], ["nop", "nop", "nop", "bitzp"]];

export const T = (raster, cyc) => raster * CYCLES + (cyc - 1);
// Python's // and % floor towards minus infinity
export const fdiv = (a, b) => Math.floor(a / b);
export const fmod = (a, b) => ((a % b) + b) % b;

export function pTime(s, d) {
  const p = SPR_P[s];
  return p > fdiv(CYCLES, 2) ? T(d - 1, p) : T(d, p);
}
export const rasterOf = (t) => fdiv(t, CYCLES);
export const cycOf = (t) => fmod(t, CYCLES) + 1;

function indexError(t) {
  return new Error("IndexError: VIC timeline index " + t);
}

/** BA (bus available) timeline for a frame. */
export class Vic {
  constructor(badlines, spriteLines) {
    this.n = (LINES + 1) * CYCLES + 200;
    const n = this.n;
    const ba = new Uint8Array(n);
    for (const r of badlines) for (let c = 12; c < 55; c++) ba[T(r, c)] = 1;
    const frame = LINES * CYCLES;
    spriteLines.forEach((lines, s) => {
      for (const d of lines) {
        const tp = pTime(s, d);
        for (let t = tp - 3; t < tp + 2; t++) if (t < frame) ba[t] = 1;
      }
    });
    this.ba = ba;
    const wb = new Uint8Array(n);
    for (let t = 3; t < n; t++) wb[t] = ba[t] & ba[t - 1] & ba[t - 2] & ba[t - 3];
    this.wb = wb;
  }

  /** Execute a cycle pattern starting at t. Returns [end_time, time_of_last_write]. */
  run(t, pattern) {
    const ba = this.ba, wb = this.wb, n = this.n;
    let w = null;
    for (let i = 0; i < pattern.length; i++) {
      if (t < 0 || t >= n) throw indexError(t);
      if (pattern.charCodeAt(i) === 82) {     // "R"
        while (ba[t]) t++;
      } else {
        while (wb[t]) t++;
        w = t;
      }
      if (t >= n) throw indexError(t);
      t++;
    }
    return [t, w];
  }

  /** run(t, pattern)[0] */
  end(t, pattern) {
    return this.run(t, pattern)[0];
  }
}

export class Task {
  constructor(id, reg, val, lo, hi, tag = "") {
    this.id = id; this.reg = reg; this.val = val; this.lo = lo; this.hi = hi; this.tag = tag;
  }
  toString() {
    const h = (v) => v.toString(16).padStart(2, "0");
    return `Task(${this.id} $${this.reg.toString(16).padStart(4, "0")}=${h(this.val)} ` +
      `[${rasterOf(this.lo)}:${cycOf(this.lo)}..${rasterOf(this.hi)}:${cycOf(this.hi)}] ${this.tag})`;
  }
}

export class SchedFail extends Error {
  constructor(task, t) {
    const at = t === null || t === undefined ? "" : ` at ${rasterOf(t)}:${cycOf(t)}`;
    super(task ? `missed ${task}${at}` : "no schedule" + at);
    this.task = task;
    this.t = t;
  }
}

const sortedUnique = (a) => [...new Set(a)].sort((x, y) => x - y);

/** Builds the unrolled kernel code (an array of byte values). */
export class Kernel {
  constructor(vic, entryTimes) {
    this.vic = vic;
    this.code = [];
    this.hyps = sortedUnique(entryTimes);
    this.patches = {};
  }

  _emitH(name, ...operands) {
    const [op, pat] = OPS[name];
    this.code.push(op);
    for (const o of operands) this.code.push(o & 0xff);
    this.hyps = sortedUnique(this.hyps.map((t) => this.vic.end(t, pat)));
  }

  /** writes: [reg, value or patch name] pairs */
  prologue(writes) {
    let a = null;
    for (const [reg, val] of writes) {
      if (typeof val === "string") {
        this.patches[val] = this.code.length + 1;
        this._emitH("lda#", 0);
        a = null;
      } else if (val !== a) {
        this._emitH("lda#", val);
        a = val;
      }
      this._emitH("sta", reg & 0xff, reg >> 8);
    }
  }

  /** Collapse all entry hypotheses into one timeline. */
  sync(maxSteps = 400) {
    const fillers = [[], ["nop"], ["bitzp"], ["nop", "nop"], ["nop", "bitzp"], ["bitzp", "bitzp"],
      ["nop", "nop", "bitzp"]];
    const bodies = ["inczp", "stazp", "sta"];
    let steps = 0;
    while (this.hyps.length > 1) {
      steps++;
      if (steps > maxSteps) throw new Error("sync did not converge: " + this.hyps);
      let best = null;
      for (const f of fillers) {
        for (const b of bodies) {
          const [seq, hy] = this._trySeq(f, b);
          const key = [new Set(hy).size, Math.max(...hy) - Math.min(...hy), seq.length];
          if (best === null || cmpArr(key, best[0]) < 0) best = [key, seq];
        }
      }
      for (const name of best[1]) {
        if (name === "sta") this._emitH(name, 0x02, 0x00);
        else if (name === "inczp" || name === "stazp" || name === "bitzp") this._emitH(name, DUMMY_ZP);
        else this._emitH(name);
      }
    }
    return this.hyps[0];
  }

  _trySeq(filler, body) {
    const vic = this.vic;
    let hy = [...this.hyps];
    const seq = [];
    for (const name of filler) {
      hy = hy.map((t) => vic.end(t, OPS[name][1]));
      seq.push(name);
    }
    const t0 = Math.min(...hy);
    let b = t0;
    while (!vic.ba[b]) {
      if (b >= vic.n) throw indexError(b);
      b++;
    }
    let e = b;
    while (vic.ba[e]) e++;
    let n = 0;
    while (Math.min(...hy) <= e + 2 && n < 60) {
      hy = hy.map((t) => vic.end(t, OPS[body][1]));
      seq.push(body);
      n++;
    }
    return [seq, hy];
  }

  emitRaw(name, ...operands) {
    this.code.push(OPS[name][0]);
    for (const o of operands) this.code.push(o & 0xff);
  }
}

/** Lexicographic comparison of arrays of numbers (Python tuple order). */
export function cmpArr(a, b) {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  return a.length - b.length;
}

/** Incremental EDF scheduler with per-raster-line checkpoints. */
export class Scheduler {
  constructor(kernel, tStart) {
    this.k = kernel;
    this.vic = kernel.vic;
    this.tasks = new Map();
    this.wtime = new Map();
    this.nextId = 0;
    const base = { t: tStart, clen: kernel.code.length, regs: [null, null, null], done: new Set() };
    this.ck = new Map([[rasterOf(tStart), base]]);
    this.baseLine = rasterOf(tStart);
    this.endState = base;
  }

  newTask(reg, val, lo, hi, tag = "") {
    return new Task(this.nextId++, reg, val, lo, hi, tag);
  }

  snapshot() {
    return { code: this.k.code.slice(), ck: new Map(this.ck), tasks: new Map(this.tasks),
      end: this.endState };
  }

  restore(snap) {
    this.k.code = snap.code.slice();
    this.ck = new Map(snap.ck);
    this.tasks = new Map(snap.tasks);
    this.endState = snap.end;
  }

  add(newTasks, untilRaster, rewind = true, ahead = 0) {
    for (const t of newTasks) {
      this._tighten(t);
      if (t.hi < t.lo) throw new SchedFail(t, t.lo);
      this.tasks.set(t.id, t);
    }
    const lines = newTasks.map((t) => rasterOf(t.lo));
    const curLine = rasterOf(this.endState.t);
    let start = curLine - Scheduler.REWIND;
    if (lines.length) start = Math.min(start, Math.max(Math.min(...lines), curLine - 3 * Scheduler.REWIND));
    start = Math.max(start, this.baseLine);
    if (!rewind) start = curLine;
    while (!this.ck.has(start)) start--;
    this._run(this.ck.get(start), T(untilRaster + 1 + ahead, 1));
    if (ahead) {
      const end = this.ck.get(untilRaster + 1);
      if (end === undefined) throw new Error("KeyError: checkpoint " + (untilRaster + 1));
      this.endState = end;
      this.k.code.length = end.clen;
      for (const line of [...this.ck.keys()]) if (line > untilRaster + 1) this.ck.delete(line);
    }
  }

  _run(state, tEnd) {
    const vic = this.vic;
    const code = this.k.code;
    let t = state.t;
    code.length = state.clen;
    const regs = [...state.regs];
    const done = new Set(state.done);
    for (const line of [...this.ck.keys()]) if (line > rasterOf(t)) this.ck.delete(line);
    const pending = [];
    for (const [tid, tk] of this.tasks) if (!done.has(tid)) pending.push(tk);
    pending.sort((a, b) => a.hi - b.hi);
    const has = (v) => regs[0] === v || regs[1] === v || regs[2] === v;

    const emit = (name, ...ops) => {
      const [op, pat] = OPS[name];
      code.push(op);
      for (const o of ops) code.push(o & 0xff);
      const r = vic.run(t, pat);
      t = r[0];
      return r[1];
    };

    const nextUse = (val, exclude = null) => {
      let best = null;
      for (const tk of pending) {
        if (tk !== exclude && tk.val === val && (best === null || tk.lo < best)) best = tk.lo;
      }
      return best;
    };

    const pickReg = (protect = []) => {
      // Belady: evict the register whose value is needed farthest in the future
      let bestNu = null, bestI = null;
      for (let i = 0; i < 3; i++) {
        if (protect.includes(regs[i])) continue;
        const nu0 = regs[i] !== null ? nextUse(regs[i]) : null;
        const nu = nu0 === null ? Infinity : nu0;
        if (bestI === null || nu > bestNu || (nu === bestNu && i > bestI)) {
          bestNu = nu; bestI = i;
        }
      }
      if (bestI === null) throw new Error("IndexError: no register to evict");
      return bestI;
    };

    const landing = (t0, needLoad) => vic.run(t0, (needLoad ? "RR" : "") + "RRRW")[1];

    let lastLine = rasterOf(t);
    for (;;) {
      const line = rasterOf(t);
      if (line > lastLine) {
        for (let l = lastLine + 1; l <= line; l++) {
          this.ck.set(l, { t, clen: code.length, regs: [...regs], done: new Set(done) });
        }
        lastLine = line;
      }
      if (t >= tEnd && !pending.some((tk) => tk.hi < tEnd)) break;
      if (!pending.length) {
        if (t >= tEnd) break;
        const gap = tEnd - t;
        if (gap % 2 === 1 && gap >= 3) emit("bitzp", DUMMY_ZP);
        else emit("nop");
        continue;
      }
      const wDirect = landing(t, false);
      for (const tk of pending) if (tk.hi < wDirect) throw new SchedFail(tk, t);

      const okAfter = (pat, regsAfter, exclude = null) => {
        const t1 = vic.end(t, pat);
        for (const v of pending) {
          if (v.hi > t + 190) break;
          if (v === exclude) continue;
          if (!this._canMeet(v, t1, regsAfter.includes(v.val)) && this._canMeet(v, t, has(v.val))) {
            return false;
          }
        }
        return true;
      };

      let acted = false;
      for (const u of pending) {
        if (!(u.lo <= wDirect)) continue;     // ready (pending is sorted by hi, so ready is too)
        if (has(u.val)) {
          if (!okAfter("RRRW", regs, u)) continue;
          const r = regs.indexOf(u.val);
          const w = emit(STORE[RN[r]], u.reg & 0xff, u.reg >> 8);
          if (!(u.lo <= w && w <= u.hi)) throw new SchedFail(u, w);
          pending.splice(pending.indexOf(u), 1);
          done.add(u.id);
          this.wtime.set(u.id, w);
        } else {
          if (landing(t, true) > u.hi) throw new SchedFail(u, t);
          const r = pickReg();
          const regs2 = [...regs];
          regs2[r] = u.val;
          if (!okAfter("RR", regs2)) continue;
          emit(LOAD[RN[r]], u.val);
          regs[r] = u.val;
        }
        acted = true;
        break;
      }
      if (acted) continue;
      // nothing (safely) ready: prefetch upcoming values, else wait
      const want = [];
      for (const tk of pending.slice(0, 3)) if (!want.includes(tk.val)) want.push(tk.val);
      let did = false;
      for (const v of want) {
        if (!has(v)) {
          const r = pickReg(want.filter((x) => x !== v));
          if (want.includes(regs[r])) break;
          const regs2 = [...regs];
          regs2[r] = v;
          if (!okAfter("RR", regs2)) break;
          emit(LOAD[RN[r]], v);
          regs[r] = v;
          did = true;
          break;
        }
      }
      if (did) continue;
      let nxt = pending[0], soon = pending[0];
      for (const x of pending) {
        if (x.hi < nxt.hi || (x.hi === nxt.hi && x.lo < nxt.lo)) nxt = x;
        if (x.lo < soon.lo) soon = x;
      }
      // the shortest filler after which a store of the most urgent task lands in its window
      let plan = null;
      for (const tgt of [nxt, soon]) {
        const need = !has(tgt.val);
        for (const fill of FILLERS) {
          let tt = t;
          for (const name of fill) tt = vic.end(tt, OPS[name][1]);
          const w = landing(tt, need);
          if (tgt.lo <= w && w <= tgt.hi) {
            plan = fill;
            break;
          }
        }
        if (plan !== null) break;
      }
      let first;
      if (plan && plan.length) {      // (an empty plan counts as none, as in the Python)
        first = plan[0];
      } else {
        const gap = soon.lo - wDirect;
        first = gap >= 3 && gap % 2 === 1 ? "bitzp" : "nop";
      }
      if (!okAfter(OPS[first][1], regs)) {
        const other = first === "bitzp" ? "nop" : "bitzp";
        if (okAfter(OPS[other][1], regs)) first = other;
      }
      if (first === "bitzp") emit(first, DUMMY_ZP);
      else emit(first);
    }
    this.endState = { t, clen: code.length, regs: [...regs], done: new Set(done) };
  }

  /** Shrink a task's window to write cycles a store can actually hit (matters on badlines). */
  _tighten(tk) {
    const vic = this.vic;
    const lo = tk.lo, hi = tk.hi;
    let best = null;
    for (let ts = lo - 70; ts <= hi; ts++) {
      const w = vic.run(ts, "RRRW")[1];
      if (lo <= w && w <= hi) {
        best = w;
        break;
      }
    }
    if (best === null) {
      tk.hi = lo - 1;
      return;
    }
    tk.lo = best;
    for (let ts = hi; ts > lo - 70; ts--) {
      const w = vic.run(ts, "RRRW")[1];
      if (lo <= w && w <= hi) {
        tk.hi = w;
        break;
      }
    }
  }

  /** Can a store of v (after an optional load) starting no earlier than t0 land in its window? */
  _canMeet(v, t0, have) {
    const vic = this.vic;
    const ts = have ? t0 : vic.end(t0, "RR");
    for (let d = 0; d < 70; d++) {
      if (d === 1) continue;
      const w = vic.run(vic.end(ts, "R".repeat(d)), "RRRW")[1];
      if (v.lo <= w && w <= v.hi) return true;
      if (w > v.hi) break;
    }
    return false;
  }

  finish() {
    const { t, clen } = this.endState;
    this.k.code.length = clen;
    // sprites off, so that blocks restarted by early Y writes do not repeat old data
    this.k.emitRaw("lda#", 0);
    this.k.emitRaw("sta", 0x15, 0xd0);
    this.k.emitRaw("rts");
    return t;
  }
}
Scheduler.REWIND = 2;
