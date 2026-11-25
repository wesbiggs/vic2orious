// Port of tools/img2c64.py's picture preparation: fit to the C64 screen with the system's
// pixel aspect, map to the palette with one of the dithers, settings text and thumbnail.
// A picture is an imaging.js image (RGB); the result is palette indices (rows of numbers),
// as the converter takes them, so no colour lookup (vic2/palette.py KNOWN) is needed.

import { resize, quantize } from "./imaging.js";
import { pyRound } from "./pyround.js";
import { COLODORE_VICE_PAL, COLODORE_VICE_NTSC, TV_2026_11 } from "./palette.js";
import * as thumb from "./thumb.js";
import { VERSION } from "./version.js";

export const PALETTES = { pal: COLODORE_VICE_PAL, ntsc: COLODORE_VICE_NTSC };
export const VIEW = TV_2026_11, VIEW_NAME = "tv.vpl";

export const DITHERS = {
  none: null, floydsteinberg: [1.0, [0.0, 1.0]], fs: [1.0, [0.0, 1.0]],
  atkinson: [1.0, [0.0, 1.0]], hybrid: [90.0, [0.0, 442.0]],
};
const KERNELS = {
  fs: [[1, 0, 7 / 16], [-1, 1, 3 / 16], [0, 1, 5 / 16], [1, 1, 1 / 16]],
  atkinson: [[1, 0, 1 / 8], [2, 0, 1 / 8], [-1, 1, 1 / 8], [0, 1, 1 / 8], [1, 1, 1 / 8],
    [0, 2, 1 / 8]],
};
export const HYBRID_CLAMP = 64, HYBRID_SPREAD = 0.1, HYBRID_RUNS = 8, TOP = 3;
export const HYBRID_NEAR = 4, SPAN_W = 24;
export const PAR = { pal: 0.936, ntsc: 0.75 };
export const MAX_W = 320, MAX_H = 200, FRAME = 16;
export const MODE_MC = "multicolor";

/** The system's colours (or view's) moved away from their own grey by chroma. */
export function palette(system, chroma = 1.0, view = null) {
  return (view || PALETTES[system || "pal"]).map((rgb) => {
    const y = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2];
    return rgb.map((v) => Math.max(0, Math.min(255, pyRound(y + chroma * (v - y)))));
  });
}

function round8(v, limit, step = 8) {
  return Math.max(step, Math.min(limit, Math.trunc(v / step + 0.5) * step));
}

export function targetSize(w, h, system, frame = false, box = [MAX_W, MAX_H], mc = false) {
  let [mw, mh] = box;
  if (frame) { mw = Math.min(mw, MAX_W - FRAME); mh = Math.min(mh, MAX_H - FRAME); }
  if (system) w = w / PAR[system] / (mc ? 2 : 1);
  if (mc) mw = Math.floor(mw / 2);
  const s = Math.min(1.0, mw / w, mh / h);
  return [round8(w * s, mw, mc ? 4 : 8), round8(h * s, mh)];
}

const dist2 = (p, q) => (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2;

function nearest(p, pal, cand) {
  let best = cand[0], bd = dist2(p, pal[best]);
  for (let i = 1; i < cand.length; i++) {
    const d = dist2(p, pal[cand[i]]);
    if (d < bd) { bd = d; best = cand[i]; }
  }
  return best;
}

const sortedBy = (cs, key) => cs.map((c, i) => [key(c), i, c]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((e) => e[2]);
const FULL = Array.from({ length: 16 }, (_, i) => i);

/** hybrid: two colours per 8x8 cell (px: rows of [r, g, b]). */
export function cellPairs(px, w, h, pal) {
  const pairs = [];
  for (let cy = 0; cy < h / 8; cy++) {
    const row = [];
    for (let cx = 0; cx < w / 8; cx++) {
      const cell = [];
      for (let y = cy * 8; y < cy * 8 + 8; y++) for (let x = cx * 8; x < cx * 8 + 8; x++) cell.push(px[y][x]);
      const nearSet = new Set();
      for (const p of cell) for (const c of sortedBy(FULL, (c) => dist2(p, pal[c])).slice(0, HYBRID_NEAR)) nearSet.add(c);
      const near = [...nearSet].sort((a, b) => a - b);
      let best = null;
      for (let i = 0; i < near.length; i++) {
        for (let j = i; j < near.length; j++) {
          const A = pal[near[i]], B = pal[near[j]];
          const d = [B[0] - A[0], B[1] - A[1], B[2] - A[2]];
          const dd = d[0] ** 2 + d[1] ** 2 + d[2] ** 2;
          let cost = 0.0;
          for (const p of cell) {
            const t = dd === 0 ? 0.0 : Math.max(0.0, Math.min(1.0,
              ((p[0] - A[0]) * d[0] + (p[1] - A[1]) * d[1] + (p[2] - A[2]) * d[2]) / dd));
            cost += dist2(p, [A[0] + t * d[0], A[1] + t * d[1], A[2] + t * d[2]]);
            cost += HYBRID_SPREAD * dd * t * (1 - t);
          }
          if (best === null || cost < best[0]) best = [cost, near[i], near[j]];
        }
      }
      row.push([best[1], best[2]]);
    }
    pairs.push(row);
  }
  return pairs;
}

export function runsNeeded(xs) {
  let n = 0, end = null;
  for (const x of xs) if (end === null || x > end) { n++; end = x + SPAN_W - 1; }
  return n;
}

function insort(a, x) {
  let lo = 0, hi = a.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (x < a[mid]) hi = mid; else lo = mid + 1; }
  a.splice(lo, 0, x);
}

/** Serpentine error diffusion (img2c64 diffuse); indices, row by row (Uint8Array). */
export function diffuse(img, pal, kernel, { strength = 1.0, clamp = null, pairs = null, escape = null, budget = null } = {}) {
  const { width: w, height: h, data } = img;
  const buf = new Float64Array(data.length);
  for (let i = 0; i < data.length; i++) buf[i] = data[i];
  const out = new Uint8Array(w * h);
  const esc2 = escape === null ? null : escape * escape;
  const K = KERNELS[kernel];
  for (let y = 0; y < h; y++) {
    const sgn = y % 2 === 0 ? 1 : -1;
    const extra = new Map(), used = new Map();
    let usedSum = 0;
    for (let i = 0; i < w; i++) {
      const x = sgn > 0 ? i : w - 1 - i;
      const o = (y * w + x) * 3;
      const p = [0, 1, 2].map((k) => Math.max(0.0, Math.min(255.0, buf[o + k])));
      const pair = pairs ? pairs[y >> 3][x >> 3] : FULL;
      let c = nearest(p, pal, pair);
      if (pairs && dist2(p, pal[c]) > esc2) {
        if (budget === null) c = nearest(p, pal, FULL);
        else {
          for (const c2 of sortedBy(FULL, (c2) => dist2(p, pal[c2]))) {
            if (pair.includes(c2)) { c = c2; break; }
            const had = extra.has(c2);
            const xs = had ? extra.get(c2) : [];
            insort(xs, x);
            const n = runsNeeded(xs);
            const u = used.get(c2) || 0;
            if (usedSum - u + n <= budget) {
              extra.set(c2, xs); used.set(c2, n); usedSum += n - u; c = c2;
              break;
            }
            xs.splice(xs.indexOf(x), 1);
          }
        }
      }
      const q = pal[c];
      out[y * w + x] = c;
      let e = [(p[0] - q[0]) * strength, (p[1] - q[1]) * strength, (p[2] - q[2]) * strength];
      if (clamp !== null) e = e.map((v) => Math.max(-clamp, Math.min(clamp, v)));
      for (const [dx, dy, f] of K) {
        const xx = x + dx * sgn, yy = y + dy;
        if (xx >= 0 && xx < w && yy < h) {
          const r = (yy * w + xx) * 3;
          buf[r] += e[0] * f; buf[r + 1] += e[1] * f; buf[r + 2] += e[2] * f;
        }
      }
    }
  }
  return out;
}

/** -d MODE[:PARAM] -> [mode, param] (floydsteinberg as fs); throws on a bad one. */
export function parseDither(v) {
  const [mode, ...rest] = v.toLowerCase().split(":");
  const arg = rest.join(":");
  if (!(mode in DITHERS)) throw new Error(`${v}: unknown mode`);
  if (DITHERS[mode] === null) {
    if (arg) throw new Error(`${v}: none takes no parameter`);
    return ["none", null];
  }
  const [def, [lo, hi]] = DITHERS[mode];
  const k = arg ? Number(arg) : def;
  if (!(lo < k && k <= hi)) throw new Error(`${v}: the parameter must be above ${lo}, at most ${hi}`);
  return [mode === "floydsteinberg" ? "fs" : mode, k];
}

/** img2c64 convert: {width, height, idx (Uint8Array of palette indices), rows}. mc: wide
 * pixels, one index each. */
export function convert(img, system, dither, { frame = false, box = [MAX_W, MAX_H], chroma = 1.0,
  runs = HYBRID_RUNS, view = VIEW, mc = false, fitted = false } = {}) {
  if (mc && dither[0] === "hybrid") throw new Error("hybrid dithers hires cells; not with multicolour");
  // fitted: img is targetSize already (the photo resized once for every dither)
  const [tw, th] = fitted ? [img.width, img.height] : targetSize(img.width, img.height, system, frame, box, mc);
  if (tw !== img.width || th !== img.height) img = resize(img, tw, th, "lanczos");
  const [mode, k] = dither;
  const pal = palette(system, chroma, view);
  let idx;
  if (mode === "none" || (mode === "fs" && k === 1.0)) idx = quantize(img, pal, mode !== "none");
  else if (mode === "hybrid") {
    const px = [];
    for (let y = 0; y < th; y++) {
      const row = [];
      for (let x = 0; x < tw; x++) { const o = (y * tw + x) * 3; row.push([img.data[o], img.data[o + 1], img.data[o + 2]]); }
      px.push(row);
    }
    idx = diffuse(img, pal, "fs", { clamp: HYBRID_CLAMP, pairs: cellPairs(px, tw, th, pal), escape: k, budget: runs });
  } else idx = diffuse(img, pal, mode, { strength: k });
  return { width: tw, height: th, idx, rows: toRows(idx, tw, th) };
}

export function toRows(idx, w, h) {
  const rows = [];
  for (let y = 0; y < h; y++) rows.push(Array.from(idx.subarray(y * w, y * w + w)));
  return rows;
}

/** %g of Python for the numbers used here. */
export function g(v) {
  if (Number.isInteger(v)) return String(v);
  return String(Number(v.toPrecision(6)));
}

/** img2c64 settings: "key: value" lines. by names the tool ("quantized by"). */
export function settings(src, system, dither, { frame = false, box = [MAX_W, MAX_H], chroma = 1.0,
  runs = HYBRID_RUNS, picked = null, viewName = VIEW_NAME, mc = false, by = "vic2orious web" } = {}) {
  const [mode, k] = dither;
  let d;
  if (mode === "none") d = "none";
  else if (mode === "fs" && k === 1.0) d = "floydsteinberg (Pillow's)";
  else d = `${mode}:${g(k)}`;
  if (mode === "hybrid") {
    d += `, line runs ${runs === null ? "none" : runs}, spread ${g(HYBRID_SPREAD)}, clamp ${g(HYBRID_CLAMP)}, pair candidates ${HYBRID_NEAR}`;
  }
  let [mw, mh] = box;
  if (frame) { mw = Math.min(mw, MAX_W - FRAME); mh = Math.min(mh, MAX_H - FRAME); }
  const lines = [["quantized by", `${by}@${VERSION}`],
    ["source", src],
    ["aspect", system ? `${system} (pixel width ${g(PAR[system])})` : "none"],
    ["fit", `${mw}x${mh}${frame ? ", room for a frame" : ""}`],
    ["dither", d],
    ["chroma", g(chroma)],
    ["palette", viewName || `Colodore as VICE shows it (${(system || "pal").toUpperCase()})`]];
  if (picked) lines.splice(5, 0, ["dither choice", picked]);
  if (mc) {
    lines[3] = ["fit", lines[3][1] + ` (${Math.floor(mw / 2)}x${mh} wide pixels)`];
    lines.splice(1, 0, ["mode", MODE_MC]);
  }
  return lines.map(([key, v]) => `${key}: ${v}\n`).join("");
}

/** img2c64 thumbnail: of picture img for out (a convert result). */
export function thumbnail(img, out, system, view = VIEW, mc = false) {
  return thumb.make(img, [out.width * (mc ? 2 : 1), out.height], palette(system, 1.0, view));
}
