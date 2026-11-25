// Port of vic2/convert.py: cell colours, sprite spans and the raster kernel for one image.
// It must give the same result as the Python byte for byte (web/test/golden.mjs). Where
// the Python's result depends on an order, this follows it: dicts keep insertion order
// (Map here), sorts are stable, min/max return the first extreme, and tuples compare
// lexicographically (cmpSpan, cmpArr).

import * as timing from "./timing.js";
import { T, SchedFail, cmpArr, fdiv } from "./timing.js";
import { PEPTO } from "./palette.js";

export const SPR_START = [0, 1, 2, 3, 4, 5, 6, 7].map((s) => 14 + 2 * s);
export const IRQ_LINE = 9;
export const ZERO_SLOT = 16;
const D011 = 0x3b;
const PIX_C0 = 13;
const MARGIN = 1;
const FIT_TRIES = 24;
const ROW_WEIGHTS = [150, 40];
const RETASK = [100, 20];
export const MAX_W = 320, MAX_H = 200;
const MC_CANDS = 7;
const D010 = 0xd010;
const REG_X = [0, 1, 2, 3, 4, 5, 6, 7].map((s) => 0xd000 + 2 * s);
const REG_Y = [0, 1, 2, 3, 4, 5, 6, 7].map((s) => 0xd001 + 2 * s);
const REG_C = [0, 1, 2, 3, 4, 5, 6, 7].map((s) => 0xd027 + s);
export const PTR = [0, 1, 2, 3, 4, 5, 6, 7].map((s) => 0xc3f8 + s);

const pc = (xreg) => PIX_C0 + (xreg >> 3);

function matchCycle(xreg) {
  if (xreg < 404) return pc(xreg);
  if (timing.STANDARD === "pal" && xreg >= 504) return null;
  return 1 + fdiv(xreg - 404, 8);
}

function badlines() {
  const out = [];
  for (let r = 0x30; r < 0xf8; r++) if ((r & 7) === 3) out.push(r);
  return out;
}

export const blockOf = (s, raster) => fdiv(raster - SPR_START[s], 21);
export const blockStart = (s, k) => SPR_START[s] + 21 * k;

const range = (a, b) => {
  const out = [];
  for (let i = a; i < b; i++) out.push(i);
  return out;
};

export class Geometry {
  constructor(w, h, frame = false, at = null, mc = false) {
    this.mc = mc;
    this.scale = mc ? 2 : 1;
    this.cw = 8 / this.scale;
    const mw = MAX_W / this.scale;
    if (w % this.cw || h % 8 || !(this.cw <= w && w <= mw) || !(8 <= h && h <= MAX_H)) {
      throw new Error(`image must be WxH with W a multiple of ${this.cw}, H of 8, W <= ${mw}, ` +
        `H <= ${MAX_H} (got ${w}x${h})`);
    }
    this.w = w; this.h = h;
    this.w_px = w * this.scale;
    this.cols = w / this.cw; this.rows = h / 8;
    [this.col0, this.row0] = at ?? (frame ? [1, 1] : [0, 0]);
    if (this.col0 < 0 || this.row0 < 0 || this.col0 + this.cols > 40 || this.row0 + this.rows > 25) {
      throw new Error(`a ${w}x${h} image does not fit on the screen at column ${this.col0}, row ${this.row0}`);
    }
    if (frame && !Geometry.frameFits(this.col0, this.row0, this.cols, this.rows)) {
      throw new Error(`no room for a frame around a ${w}x${h} image`);
    }
    this.frame = frame;
    this.raster0 = 0x33 + 8 * this.row0;
    this.xreg0 = 24 + 8 * this.col0;
    this.xs_max = w - 1;
  }

  xr(x) { return this.xreg0 + this.scale * x; }
  xrLast(x) { return this.xreg0 + this.scale * x + this.scale - 1; }

  static frameFits(col0, row0, cols, rows) {
    return col0 >= 1 && row0 >= 1 && col0 + cols <= 39 && row0 + rows <= 24;
  }

  firstImageBlock(s) {
    let k = 0;
    while (blockStart(s, k) + 20 < this.raster0) k++;
    return k;
  }

  slotOf(s, k) {
    const k0 = this.firstImageBlock(s);
    if (k < k0) return ZERO_SLOT;
    return ZERO_SLOT + 1 + (k - k0) * 8 + s;
  }

  spriteLines() {
    const r = this.raster0 + this.h;
    return [0, 1, 2, 3, 4, 5, 6, 7].map((s) => range(SPR_START[s], blockStart(s, blockOf(s, r)) + 21));
  }
}

// ---------------------------------------------------------------- spans
// A span is {c, a, b, xs, id}: colour, first and last pixel, the pixels it covers. Spans
// are interned (one object per value), so === is value equality.

const MEMO_MAX = 1 << 16;
let spanIntern = new Map();
let nextSpanId = 0;
let ccMemo = new Map(), coverMemo = new Map(), costMemo = new Map();
let nextCoverId = 0;
// memo keys: numbers as characters (pixel x < 320, colours offset past them)
const chars = (a) => String.fromCharCode.apply(null, a);
const COVER_PREFIX = "c";

/** Forget the memos (they are only caches). */
export function resetCaches() {
  spanIntern = new Map();
  ccMemo = new Map(); coverMemo = new Map(); costMemo = new Map();
}

function memoSet(m, k, v) {
  if (m.size >= MEMO_MAX) m.clear();
  m.set(k, v);
}

function span(c, a, b, xs) {
  const key = String.fromCharCode(1000 + c) + chars(xs);
  let sp = spanIntern.get(key);
  if (!sp) {
    sp = { c, a, b, xs, id: nextSpanId++ };
    spanIntern.set(key, sp);
  }
  return sp;
}

/** Python's comparison of span tuples (c, a, b, xs). */
export function cmpSpan(p, q) {
  if (p === q) return 0;
  if (p.c !== q.c) return p.c - q.c;
  if (p.a !== q.a) return p.a - q.a;
  if (p.b !== q.b) return p.b - q.b;
  return cmpArr(p.xs, q.xs);
}

function colourCover(xs, xsMax, kmax) {
  const key = String.fromCharCode(xsMax, kmax) + chars(xs);
  const hit = ccMemo.get(key);
  if (hit) return hit;
  const n = xs.length;
  const nxt = new Array(n).fill(0);
  let j = 0;
  for (let i = 0; i < n; i++) {
    j = Math.max(j, i);
    while (j < n && xs[j] <= Math.min(xs[i], xsMax) + 23) j++;
    nxt[i] = j;
  }
  const f = [];
  for (let i = 0; i <= n; i++) f.push(new Array(kmax + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    const fi = f[i], f1 = f[i + 1], fn = f[nxt[i]];
    const run = 16 * (nxt[i] - i) - 1;
    for (let k = 1; k <= kmax; k++) {
      const take = nxt[i] > i ? run + fn[k - 1] : -1;
      fi[k] = take > f1[k] ? take : f1[k];
    }
  }
  const res = { nxt, f };
  memoSet(ccMemo, key, res);
  return res;
}

/** byC: [[colour, xs], ...]. Returns [spans, lost]; spans has an id for the costs memo.
 * Memoised by Converter.spansOf (for one image, so for one xsMax and kmax). */
function coverNew(byC, xsMax, kmax) {
  let total = 0;
  for (const [, xs] of byC) total += xs.length;
  const tables = new Map();
  let best = new Map([[0, [0, []]]]);     // spans used -> [value, [[colour, k], ...]]
  for (const [c, xs] of byC) {
    const { nxt, f } = colourCover(xs, xsMax, kmax);
    tables.set(c, [xs, nxt, f]);
    const nb = new Map();
    for (const [used, [v, picks]] of best) {
      for (let k = 0; k <= kmax - used; k++) {
        if (k && f[0][k] <= f[0][k - 1]) break;
        const v2 = v + f[0][k];
        const cur = nb.get(used + k);
        if (cur === undefined || v2 > cur[0]) nb.set(used + k, [v2, [...picks, [c, k]]]);
      }
    }
    best = nb;
  }
  let pick = null;
  for (const e of best.values()) if (pick === null || e[0] > pick[0]) pick = e;
  const spans = [];
  let covered = 0;
  for (let [c, k] of pick[1]) {
    const [xs, nxt, f] = tables.get(c);
    let i = 0;
    while (k && i < xs.length) {
      if (f[i][k] === f[i + 1][k]) {
        i++;
        continue;
      }
      spans.push(span(c, xs[i], xs[nxt[i] - 1], xs.slice(i, nxt[i])));
      covered += nxt[i] - i;
      i = nxt[i];
      k--;
    }
  }
  spans.id = nextCoverId++;
  return [spans, total - covered];
}

function spansCost(prev, spans) {
  const key = prev.id + "/" + spans.id;
  const hit = costMemo.get(key);
  if (hit !== undefined) return hit;
  const used = new Array(prev.length).fill(false);
  let miss = 0;
  for (const { c, a, b } of spans) {
    let ok = false;
    for (let i = 0; i < prev.length; i++) {
      const p = prev[i];
      if (!used[i] && p.c === c && Math.max(b - 23, p.b - 23) <= Math.min(a, p.a)) {
        used[i] = true;
        ok = true;
        break;
      }
    }
    if (!ok) miss++;
  }
  memoSet(costMemo, key, miss);
  return miss;
}

/** itertools.combinations(arr, k) */
function combinations(arr, k) {
  const out = [];
  const idx = [];
  const rec = (start) => {
    if (idx.length === k) {
      out.push(idx.map((i) => arr[i]));
      return;
    }
    for (let i = start; i < arr.length; i++) {
      idx.push(i);
      rec(i + 1);
      idx.pop();
    }
  };
  rec(0);
  return out;
}

const sameArr = (p, q) => p.length === q.length && p.every((v, i) => v === q[i]);
const pairsKey = (pairs) => pairs.map((p) => p.join(",")).join(";");

/** Sort Map keys by descending count, stable (Python sorted(cnt, key=lambda c: -cnt[c])). */
const byCount = (cnt) => [...cnt.keys()].sort((a, b) => cnt.get(b) - cnt.get(a));

// ---------------------------------------------------------------- converter

export class Converter {
  /** img: rows of palette indices. log: called with progress lines. */
  constructor(img, { log = () => {}, frame = false, at = null, mc = false, bg = 0, progress = null } = {}) {
    this.img = img;
    this.log = log;
    this.progress = progress;
    const g = (this.g = new Geometry(img[0].length, img.length, frame, at, mc));
    const cw = g.cw;
    this.cellColors = [];
    for (let cy = 0; cy < g.rows; cy++) {
      const row = [];
      for (let cx = 0; cx < g.cols; cx++) {
        const cnt = new Map();
        for (let y = cy * 8; y < cy * 8 + 8; y++) {
          for (let x = cx * cw; x < cx * cw + cw; x++) cnt.set(img[y][x], (cnt.get(img[y][x]) || 0) + 1);
        }
        row.push(cnt);
      }
      this.cellColors.push(row);
    }
    this.pairs = [];
    for (let cy = 0; cy < g.rows; cy++) this.pairs.push(new Array(g.cols).fill(null));
    this.bg = mc ? bg : null;
    this.cellKeys = [];
    this.lineCells = [];
    for (let y = 0; y < g.h; y++) {
      const cells = [];
      for (let cx = 0; cx < g.cols; cx++) {
        const byC = new Map();
        for (let x = cx * cw; x < cx * cw + cw; x++) {
          const c = img[y][x];
          if (!byC.has(c)) byC.set(c, []);
          byC.get(c).push(x);
        }
        cells.push([...byC.entries()]);
      }
      this.lineCells.push(cells);
      this.cellKeys.push(cells.map(() => new Map()));
    }
  }

  spansOf(y, pairs) {
    // the memo key of cover(): its problem pixels (x, colour), which determine its input,
    // put together from each cell's (kept per cell and colour choice)
    const cells = this.lineCells[y], ck = this.cellKeys[y];
    let key = COVER_PREFIX;
    for (let i = 0; i < pairs.length; i++) {
      const p = pairs[i];
      const code = p.length === 2 ? p[0] * 16 + p[1] : (p[0] << 12) | (p[1] << 8) | (p[2] << 4) | p[3];
      let k = ck[i].get(code);
      if (k === undefined) {
        const a = [];
        for (const [c, xs] of cells[i]) if (!p.includes(c)) for (const x of xs) a.push(x * 16 + c);
        k = chars(a.sort((u, v) => u - v));
        ck[i].set(code, k);
      }
      key += k;
    }
    const hit = coverMemo.get(key);
    if (hit) return hit;
    const byC = new Map();
    for (let i = 0; i < pairs.length; i++) {
      const p = pairs[i];
      for (const [c, xs] of cells[i]) {
        if (!p.includes(c)) byC.set(c, byC.has(c) ? byC.get(c).concat(xs) : xs);
      }
    }
    const res = coverNew([...byC.entries()], this.g.xs_max, 8);
    memoSet(coverMemo, key, res);
    return res;
  }

  rowCost(cy, pairs, prevSpans, lostPx) {
    let cost = 0;
    let prev = prevSpans;
    for (let i = 0; i < 8; i++) {
      const [sp, lost] = this.spansOf(cy * 8 + i, pairs);
      cost += lostPx * lost + 5 * sp.length;
      if (prev !== null) cost += RETASK[i > 0 ? 1 : 0] * spansCost(prev, sp);
      prev = sp;
    }
    return cost;
  }

  mcCands(cnt) {
    const bg = this.bg;
    const cols = byCount(cnt).filter((c) => c !== bg).slice(0, MC_CANDS);
    if (!cols.length) return [[bg, bg, bg, bg]];
    if (cols.length <= 3) {
      const t = [...cols];
      while (t.length < 3) t.push(cols[cols.length - 1]);
      return [[...t, bg]];
    }
    return combinations(cols, 3).map((t) => [...t, bg]);
  }

  chooseRow(cy, prevSpans, lostPx) {
    const g = this.g;
    const cands = [];
    for (let cx = 0; cx < g.cols; cx++) {
      const cnt = this.cellColors[cy][cx];
      const cols = byCount(cnt);
      if (g.mc) cands.push(this.mcCands(cnt));
      else if (cols.length === 1) cands.push([[cols[0], cols[0]]]);
      else if (cols.length === 2) cands.push([[cols[0], cols[1]]]);
      else cands.push(combinations(cols, 2));
    }
    const pairs = cands.map((c) => c[0]);
    let best = this.rowCost(cy, pairs, prevSpans, lostPx);
    const moves = [];
    for (let cx = 0; cx < g.cols; cx++) {
      for (const p of cands[cx]) if (cands[cx].length > 1) moves.push([[cx, p]]);
    }
    const moves2 = [];
    for (let cx = 0; cx < g.cols - 1; cx++) {
      for (const p of cands[cx]) {
        for (const q of cands[cx + 1]) {
          if (cands[cx].length > 1 && cands[cx + 1].length > 1) moves2.push([[cx, p], [cx + 1, q]]);
        }
      }
    }
    let stuck = false;
    for (let it = 0; it < 16; it++) {
      let improved = false;
      for (const mv of stuck ? moves2 : moves) {
        if (mv.every(([cx, p]) => sameArr(pairs[cx], p))) continue;
        const old = mv.map(([cx]) => [cx, pairs[cx]]);
        for (const [cx, p] of mv) pairs[cx] = p;
        const c = this.rowCost(cy, pairs, prevSpans, lostPx);
        if (c < best) {
          best = c;
          improved = true;
        } else {
          for (const [cx, p] of old) pairs[cx] = p;
        }
      }
      if (!improved && stuck) break;
      stuck = !improved;
    }
    return [pairs, best];
  }

  run() {
    const g = this.g;
    const RASTER0 = g.raster0, XREG0 = g.xreg0, IMG_H = g.h;
    const vic = new timing.Vic(badlines(), g.spriteLines());
    const entry = range(20, 48).map((c) => T(IRQ_LINE, c));
    const k = new timing.Kernel(vic, entry);
    let pro = [];
    for (let s = 0; s < 8; s++) pro.push([REG_Y[s], SPR_START[s] - 1]);
    pro.push([0xd017, 0], [0xd015, 0xff]);
    for (let s = 0; s < 8; s++) pro.push([PTR[s], ZERO_SLOT]);
    pro.push([0xd01b, 0], [0xd01c, 0], [0xd01d, g.mc ? 0xff : 0]);
    pro.push([D010, "H"]);
    pro.push([0xd016, g.mc ? 0x18 : 0x08], [0xd018, 0x08], [0xd011, D011]);
    for (let s = 0; s < 8; s++) pro.push([REG_X[s], "X" + s], [REG_C[s], "C" + s]);
    k.prologue(pro);
    const t0 = k.sync();
    this.log(`  sync done at raster ${timing.rasterOf(t0)} cycle ${timing.cycOf(t0)}`);
    this.kernel = k;
    const sch = new timing.Scheduler(k, t0);
    this.sched = sch;

    const fixed = new Map();
    const pushFixed = (r, ...tks) => {
      if (!fixed.has(r)) fixed.set(r, []);
      fixed.get(r).push(...tks);
    };
    const ptrTasks = [];
    for (let s = 0; s < 8; s++) {
      for (let kk = 1; kk < 16; kk++) {
        const B = blockStart(s, kk);
        if (B > RASTER0 + IMG_H + 2) break;
        const ty = sch.newTask(REG_Y[s], B - 1, T(B - 22, timing.Y_AFTER), T(B - 1, 54), `y${s}.${kk}`);
        pushFixed(B - 21, ty);
        if (g.slotOf(s, kk) !== g.slotOf(s, kk - 1)) {
          const tpOld = timing.pTime(s, B - 1);
          const tpNew = timing.pTime(s, B);
          const tk = sch.newTask(PTR[s], g.slotOf(s, kk), tpOld + 1, tpNew - 1, `p${s}.${kk}`);
          sch._tighten(tk);
          pushFixed(timing.rasterOf(tk.hi), tk);
          ptrTasks.push([B, tk]);
        }
      }
    }

    const pre = [];
    for (const r of [...fixed.keys()].sort((a, b) => a - b)) if (r < RASTER0) pre.push(...fixed.get(r));
    sch.add(pre, RASTER0 - 1);

    const r = RASTER0 + IMG_H;
    const lo = Math.max(T(r - 1, pc(XREG0 + g.w_px - 1) + 1 + MARGIN), T(r - 1, timing.Y_AFTER));
    const off = sch.newTask(0xd015, 0, lo, T(r, 54), "off");
    pushFixed(r - 1, off, ...ptrTasks.filter(([B, p]) => B <= r && timing.rasterOf(p.hi) >= r).map(([, p]) => p));

    let cfg = new Array(8).fill(null);
    let firstCfg = new Array(8).fill(null);
    let lastUse = new Array(9).fill(null);
    this.sdata = [0, 1, 2, 3, 4, 5, 6, 7].map(() => new Map());
    this.lineCfg = [0, 1, 2, 3, 4, 5, 6, 7].map(() => new Map());
    let prevSpans = null;
    this.badLines = new Map();
    for (let cy = 0; cy < g.rows; cy++) {
      const snap = sch.snapshot();
      const start = [cfg, firstCfg, lastUse, prevSpans];
      const tried = [];
      let best = null;
      for (const w of ROW_WEIGHTS) {
        const [pairs] = this.chooseRow(cy, prevSpans, w);
        const pk = pairsKey(pairs);
        if (tried.includes(pk)) continue;
        tried.push(pk);
        sch.restore(snap);
        let res;
        try {
          res = this.doRow(sch, fixed, cy, pairs, start);
        } catch (e) {
          if (e instanceof SchedFail) continue;
          throw e;
        }
        if (best === null || res[0] < best[0]) best = [...res, pairs, sch.snapshot()];
      }
      if (best === null) throw new SchedFail(null, null);
      let lines, pairs, done;
      [, cfg, firstCfg, lastUse, prevSpans, lines, pairs, done] = best;
      sch.restore(done);
      this.pairs[cy] = pairs;
      for (const [y, rows, why] of lines) {
        for (const [s, [bits, c]] of rows) {
          this.sdata[s].set(RASTER0 + y, bits);
          this.lineCfg[s].set(RASTER0 + y, c);
        }
        if (why) this.badLines.set(y, why);
      }
      for (let yy = cy * 8; yy < cy * 8 + 8; yy++) this.cellKeys[yy] = null;
      if (this.progress) this.progress((cy + 1) / g.rows);
    }
    this.cut = IMG_H;
    sch.finish();
    let hiBits = 0;
    for (let s = 0; s < 8; s++) {
      const fc = firstCfg[s] || [0, 0, 0];
      k.code[k.patches["X" + s]] = g.xr(fc[0]) & 0xff;
      k.code[k.patches["C" + s]] = fc[1];
      hiBits |= fc[2] << s;
    }
    k.code[k.patches.H] = hiBits;
    return this.badLines.size;
  }

  doRow(sch, fixed, cy, pairs, start) {
    const g = this.g;
    let [cfg, firstCfg, lastUse, prevSpans] = start;
    cfg = [...cfg]; firstCfg = [...firstCfg]; lastUse = [...lastUse];
    const rowpairs = pairs.map((p) => new Set(p));
    let wrong = 0;
    const lines = [];
    for (let i = 0; i < 8; i++) {
      const y = cy * 8 + i;
      const r = g.raster0 + y;
      const [spans, lost] = this.spansOf(y, pairs);
      let why = lost ? `${lost} pixels not covered by 8 spans` : "";
      const state = [[...cfg], [...firstCfg], [...lastUse]];
      const snap = sch.snapshot();
      const fut = [];
      for (let yy = y + 1; yy < Math.min(cy * 8 + 8, y + 4); yy++) fut.push(this.spansOf(yy, pairs)[0]);
      const until = y === g.h - 1 ? r + 1 : r;
      let dropped, rows;
      [dropped, cfg, firstCfg, lastUse, rows] = this.fitLine(
        sch, spans, state, snap, fixed.get(r) || [], fixed.get(until + 1) || [], r, until, y, fut);
      wrong += this.recover(y, r, rowpairs, rows, cfg, lastUse);
      if (dropped.length) why = (why ? why + "; " : "") + `dropped ${dropped.length} span(s) for timing`;
      const m = new Map();
      for (const [s, bits] of rows) m.set(s, [bits, cfg[s]]);
      lines.push([y, m, why]);
      prevSpans = spans;
    }
    return [wrong, cfg, firstCfg, lastUse, prevSpans, lines];
  }

  fitLine(sch, spans, state, snap, fixed, nxt, r, until, y, fut) {
    let ahead;
    const attempt = (dropped, rewind) => {
      const [cfg, firstCfg, lastUse] = state.map((v) => [...v]);
      const live = spans.filter((sp) => !dropped.includes(sp));
      const assign = this.assign(live, cfg, lastUse, r, fut);
      const [tasks, rows, owner] = this.lineTasks(sch, assign, cfg, firstCfg, lastUse, r, y);
      try {
        sch.add([...tasks, ...fixed, ...(ahead ? nxt : [])], until, rewind, ahead);
        return [[cfg, firstCfg, lastUse, rows], null, null];
      } catch (e) {
        if (!(e instanceof SchedFail)) throw e;
        sch.restore(snap);
        const victim = (e.task && owner.get(e.task.id)) || null;
        const cands = [...new Set(owner.values())].sort(cmpSpan);
        return [null, victim, cands];
      }
    };
    const loss = (d) => d.reduce((n, q) => n + q.xs.length, 0);
    // heap entries [loss, sp !== victim, dropped (sorted)], compared as the Python tuples
    const cmpEntry = (p, q) => {
      if (p[0] !== q[0]) return p[0] - q[0];
      if (p[1] !== q[1]) return p[1] ? 1 : -1;
      const n = Math.min(p[2].length, q[2].length);
      for (let i = 0; i < n; i++) {
        const c = cmpSpan(p[2][i], q[2][i]);
        if (c) return c;
      }
      return p[2].length - q[2].length;
    };
    for (const [rewind, ah] of [[true, 1], [false, 1], [true, 0], [false, 0]]) {
      ahead = ah;
      const heap = new Heap(cmpEntry);
      heap.push([0, false, []]);
      const seen = new Set([""]);
      let tries = 0;
      while (heap.size && tries < FIT_TRIES) {
        const dropped = heap.pop()[2];
        tries++;
        const [res, victim, cands] = attempt(dropped, rewind);
        if (res) return [[...dropped], ...res];
        for (const sp of cands) {
          const d = [...dropped, sp].sort(cmpSpan);
          const key = d.map((q) => q.id).join(",");
          if (!seen.has(key)) {
            seen.add(key);
            heap.push([loss(d), sp !== victim, d]);
          }
        }
      }
      const dropped = [];
      for (;;) {
        const [res, victim, cands] = attempt(dropped, rewind);
        if (res) return [dropped, ...res];
        if (!cands.length) break;
        let pick = victim;
        if (!pick) {
          pick = cands[0];
          for (const sp of cands) if (sp.xs.length < pick.xs.length) pick = sp;
        }
        dropped.push(pick);
      }
    }
    throw new SchedFail(null, null);
  }

  recover(y, r, rowpairs, rows, cfg, lastUse) {
    const g = this.g, W = g.w;
    const need = new Map();
    this.img[y].forEach((c, x) => {
      if (!rowpairs[fdiv(x, g.cw)].has(c)) need.set(x, c);
    });
    for (const [s, bits] of rows) {
      const xs = cfg[s][0];
      for (let i = 0; i < 24; i++) if ((bits >> (23 - i)) & 1) need.delete(xs + i);
    }
    for (let s = 0; s < 8; s++) {
      if (cfg[s] === null) continue;
      const [xs, c] = cfg[s];
      const bits = rows.get(s) || 0;
      let first = xs;
      while (bits && !((bits >> (23 - (first - xs))) & 1)) first++;
      let nw = bits;
      for (let x = first; x < Math.min(xs + 24, W); x++) {
        if (need.get(x) === c) {
          nw |= 1 << (23 - (x - xs));
          need.delete(x);
        }
      }
      if (nw !== bits) {
        rows.set(s, nw);
        let last = xs + 23;
        while (!((nw >> (23 - (last - xs))) & 1)) last--;
        lastUse[s] = [r, g.xrLast(last)];
      }
    }
    return need.size;
  }

  lineTasks(sch, assign, cfg, firstCfg, lastUse, r, y) {
    const g = this.g;
    const tasks = [], rows = new Map(), owner = new Map();
    let bitsBefore = this.hiMask(cfg);
    let changes = [];
    for (const [s, [sp, xs]] of assign) {
      const { c, a, b, xs: pxs } = sp;
      const newcfg = [xs, c];
      const firstPx = g.xr(a);
      const newX = g.xr(xs);
      if (cfg[s] === null) {
        let hiBit = newX >> 8;
        if (lastUse[8] !== null && hiBit) {
          hiBit = 0;
          const [lo, hi] = this.safeWindow(0, T(r, pc(firstPx) - 1 - MARGIN), r, [newX & 0xff]);
          changes.push([s, lo, hi, sp]);
        }
        firstCfg[s] = [...newcfg, hiBit];
        bitsBefore |= hiBit << s;
      } else if (cfg[s][0] !== newcfg[0] || cfg[s][1] !== newcfg[1]) {
        const [lr, lx] = lastUse[s];
        let lo = T(lr, pc(lx) + 1 + MARGIN);
        if (cfg[s][1] !== c) {
          const tk = sch.newTask(REG_C[s], c, lo, T(r, pc(firstPx) - 1 - MARGIN), `c${s}@${y}`);
          tasks.push(tk);
          owner.set(tk.id, sp);
        }
        const oldX = g.xr(cfg[s][0]);
        if (oldX !== newX) {
          let hi = T(r, pc(Math.min(oldX, newX)) - 1 - MARGIN);
          if ((oldX ^ newX) & 0x100) {
            [lo, hi] = this.safeWindow(lo, hi, r, [(newX & 0xff) | (oldX & 0x100), (oldX & 0xff) | (newX & 0x100)]);
            changes.push([s, lo, hi, sp]);
          }
          if ((oldX ^ newX) & 0xff) {
            const tk = sch.newTask(REG_X[s], newX & 0xff, lo, hi, `x${s}@${y}`);
            tasks.push(tk);
            owner.set(tk.id, sp);
          }
        }
      }
      cfg[s] = newcfg;
      lastUse[s] = [r, g.xrLast(b)];
      let bits = 0;
      for (const x of pxs) bits |= 1 << (23 - (x - xs));
      rows.set(s, bits);
    }
    changes.sort((p, q) => p[2] - q[2]);
    let mask = bitsBefore;
    while (changes.length) {
      const stab = changes[0][2];
      const group = changes.filter((ch) => ch[1] <= stab);
      changes = changes.filter((ch) => ch[1] > stab);
      for (const ch of group) mask ^= 1 << ch[0];
      let lo = Math.max(...group.map((ch) => ch[1]));
      if (lastUse[8] !== null) lo = Math.max(lo, lastUse[8] + 1);
      const tk = sch.newTask(D010, mask, lo, stab, `h@${y}`);
      tasks.push(tk);
      let top = group[0];
      for (const ch of group) if (ch[1] > top[1]) top = ch;
      owner.set(tk.id, top[3]);
      lastUse[8] = stab;
    }
    return [tasks, rows, owner];
  }

  hiMask(cfg) {
    let m = 0;
    for (let s = 0; s < 8; s++) if (cfg[s] !== null && this.g.xr(cfg[s][0]) >= 256) m += 1 << s;
    return m;
  }

  safeWindow(lo, hi, r, mixed) {
    const bad = [];
    for (const xreg of mixed) {
      const m = matchCycle(xreg);
      if (m === null) continue;
      for (const line of [r - 1, r]) {
        const t = T(line, m);
        bad.push([t - MARGIN - 2, t + MARGIN + 2]);
      }
    }
    bad.sort(cmpArr);
    let best = [lo, lo - 1], cur = lo;
    for (const [b0, b1] of [...bad, [hi + 1, hi + 1]]) {
      if (b0 > cur && Math.min(b0 - 1, hi) - cur > best[1] - best[0]) best = [cur, Math.min(b0 - 1, hi)];
      cur = Math.max(cur, b1 + 1);
    }
    return best;
  }

  /** span -> sprite assignment (min writes), DP over sprite subsets: Map s -> [span, xstart] */
  assign(spans, cfg, lastUse, r, fut) {
    const m = spans.length;
    if (m === 0) return new Map();
    const g = this.g;
    const xr = (x) => g.xr(x);
    const opts = [];
    for (const { c, a, b } of spans) {
      const loX = b - 23, hiX = Math.min(a, g.xs_max);
      const row = [];
      for (let s = 0; s < 8; s++) {
        const cur = cfg[s];
        let writes = 0, xs, cost;
        if (cur === null) {
          xs = this.pickX(c, loX, hiX, fut, lastUse[8] !== null ? 0 : null);
          cost = lastUse[8] !== null ? 100 * (xr(xs) >> 8) : 0;
        } else {
          if (cur[1] !== c) writes += 1;
          if (loX <= cur[0] && cur[0] <= hiX) {
            xs = cur[0];
          } else {
            const hb = xr(cur[0]) >> 8;
            xs = this.pickX(c, loX, hiX, fut, hb);
            writes += (xr(xs) & 0xff) !== (xr(cur[0]) & 0xff) ? 1 : 0;
            writes += 0.8 * ((xr(xs) >> 8) !== hb ? 1 : 0);
          }
          cost = writes * 100;
          if (writes) {
            const [lr, lx] = lastUse[s];
            const idle = r - lr;
            cost -= Math.min(idle, 6) * 8;
            if (idle === 1) cost += fdiv(Math.max(0, lx - xr(a)), 8);
          }
        }
        row.push([cost, xs]);
      }
      opts.push(row);
    }
    let dp = new Map([[0, [0, []]]]);
    for (let j = 0; j < m; j++) {
      const nd = new Map();
      for (const [mask, [cst, lst]] of dp) {
        for (let s = 0; s < 8; s++) {
          if (mask & (1 << s)) continue;
          const c2 = cst + opts[j][s][0];
          const nm = mask | (1 << s);
          const cur = nd.get(nm);
          if (cur === undefined || c2 < cur[0]) nd.set(nm, [c2, [...lst, s]]);
        }
      }
      dp = nd;
    }
    let best = null;
    for (const v of dp.values()) if (best === null || v[0] < best[0]) best = v;
    const out = new Map();
    best[1].forEach((s, j) => out.set(s, [spans[j], opts[j][s][1]]));
    return out;
  }

  pickX(c, loX, hiX, fut, hiBit = null) {
    if (hiBit !== null) {
      const edge = Math.ceil((256 - this.g.xreg0) / this.g.scale);
      const [lo2, hi2] = hiBit === 0 ? [loX, Math.min(hiX, edge - 1)] : [Math.max(loX, edge), hiX];
      if (lo2 <= hi2) { loX = lo2; hiX = hi2; }
    }
    let best = null, bestScore = 0, bestDist = 0;
    const mid = (loX + hiX) / 2;
    const ws = [4, 2, 1];
    for (let xs = loX; xs <= hiX; xs++) {
      let score = 0;
      for (let i = 0; i < Math.min(3, fut.length); i++) {
        for (const q of fut[i]) if (q.c === c && xs <= q.a && q.b <= xs + 23) score += ws[i];
      }
      const dist = -Math.abs(xs - mid);
      if (best === null || score > bestScore || (score === bestScore && dist > bestDist)) {
        best = xs; bestScore = score; bestDist = dist;
      }
    }
    if (best === null) throw new Error("TypeError: no span start in " + loX + ".." + hiX);
    return best;
  }

  // ---- outputs
  spriteCover() {
    const { w: W, h: H } = this.g;
    const cov = [];
    for (let y = 0; y < H; y++) {
      const row = new Array(W).fill(null);
      const r = this.g.raster0 + y;
      for (let s = 7; s >= 0; s--) {
        const bits = this.sdata[s].get(r);
        if (!bits) continue;
        const [xs, c] = this.lineCfg[s].get(r);
        for (let i = 0; i < 24; i++) if (bits & (1 << (23 - i)) && xs + i >= 0 && xs + i < W) row[xs + i] = c;
      }
      cov.push(row);
    }
    return cov;
  }

  bitmap() {
    const dist = (a, b) => {
      const p = PEPTO[a], q = PEPTO[b];
      return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2;
    };
    const cov = this.spriteCover();
    const { w: W, h: H } = this.g;
    const bits = [];
    for (let y = 0; y < H; y++) bits.push(new Array(W).fill(0));
    if (this.g.mc) {
      for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
          const [c1, c2, c3, bg] = this.pairs[y >> 3][fdiv(x, 4)];
          const order = [bg, c1, c2, c3];
          const c = this.img[y][x];
          const i = order.indexOf(c);
          if (i >= 0) bits[y][x] = i;
          else if (cov[y][x] === null) {
            let bi = 0;
            for (let j = 1; j < 4; j++) if (dist(c, order[j]) < dist(c, order[bi])) bi = j;
            bits[y][x] = bi;
          }
        }
      }
      return bits;
    }
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const [fg, bg] = this.pairs[y >> 3][x >> 3];
        const c = this.img[y][x];
        if (c === fg && fg !== bg) bits[y][x] = 1;
        else if (c !== bg && cov[y][x] === null && dist(c, fg) < dist(c, bg)) bits[y][x] = 1;
      }
    }
    return bits;
  }

  /** What the VIC should display, as palette indices. */
  render() {
    const cov = this.spriteCover();
    const bits = this.bitmap();
    const { w: W, h: H } = this.g;
    const out = [];
    for (let y = 0; y < H; y++) {
      const row = new Array(W).fill(0);
      for (let x = 0; x < W; x++) {
        if (cov[y][x] !== null) row[x] = cov[y][x];
        else if (this.g.mc) {
          const [c1, c2, c3, bg] = this.pairs[y >> 3][fdiv(x, 4)];
          row[x] = [bg, c1, c2, c3][bits[y][x]];
        } else {
          const [fg, bg] = this.pairs[y >> 3][x >> 3];
          row[x] = bits[y][x] ? fg : bg;
        }
      }
      out.push(row);
    }
    return out;
  }
}

/** A binary heap ordered by cmp (smallest first). */
class Heap {
  constructor(cmp) { this.cmp = cmp; this.a = []; }
  get size() { return this.a.length; }
  push(v) {
    const a = this.a;
    a.push(v);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (this.cmp(a[i], a[p]) >= 0) break;
      [a[i], a[p]] = [a[p], a[i]];
      i = p;
    }
  }
  pop() {
    const a = this.a;
    const top = a[0];
    const last = a.pop();
    if (a.length) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < a.length && this.cmp(a[l], a[m]) < 0) m = l;
        if (r < a.length && this.cmp(a[r], a[m]) < 0) m = r;
        if (m === i) break;
        [a[i], a[m]] = [a[m], a[i]];
        i = m;
      }
    }
    return top;
  }
}
