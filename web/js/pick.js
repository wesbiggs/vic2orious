// img2c64's dither picker (judge, candidate, refine, pick): which dither gives the C64
// picture closest to the source. Ported from vic2/dither_pick.py and tools/img2c64.py,
// whose numpy arithmetic it follows; numpy's matrix products (BLAS) and its exp, pow and
// cbrt could differ in the last bits, so a near tie between two dithers can go the other
// way than the Python's did.

import * as timing from "./timing.js";
import { Converter, resetCaches } from "./convert.js";
import { resize, boxBlur1, scaleUp, newImage } from "./imaging.js";
import { COLODORE_VICE_PAL, COLODORE_VICE_NTSC, PEPTO } from "./palette.js";
import * as img2c64 from "./img2c64.js";

export const METRICS = ["rms", "ssim", "color"];
const HIGHER = { rms: false, ssim: true, color: false };
export const WEIGHTS = [0.0, 1.0, 1.0];
export const CANDIDATES = [["none", "none", null], ["fs", "fs", null], ["fs:0.75", "fs:0.75", null],
  ["fs:0.5", "fs:0.5", null], ["atkinson", "atkinson", null],
  ["atkinson:0.75", "atkinson:0.75", null], ["hybrid", "hybrid", 8],
  ["hybrid,l=6", "hybrid", 6], ["hybrid,l=none", "hybrid", null]];

function useStandard(system) {
  system = system || "pal";
  if (system !== timing.STANDARD) { timing.setStandard(system); resetCaches(); }
}

/** Rows of palette indices as an RGB image in pal. */
export function toImage(rows, pal) {
  const h = rows.length, w = rows[0].length;
  const im = newImage(w, h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const c = pal[rows[y][x]], o = (y * w + x) * 3;
      im.data[o] = c[0]; im.data[o + 1] = c[1]; im.data[o + 2] = c[2];
    }
  }
  return im;
}

const screenPal = (system, view) => view || (system === "ntsc" ? COLODORE_VICE_NTSC : COLODORE_VICE_PAL);

/** What the C64 shows of out's rows (upper left), and its wrong pixels; rows as well. */
export function shown(rows, system, view = null, progress = null) {
  useStandard(system);
  const conv = new Converter(rows, { progress });
  conv.run();
  const out = conv.render();
  let wrong = 0;
  for (let y = 0; y < rows.length; y++) for (let x = 0; x < rows[0].length; x++) if (out[y][x] !== rows[y][x]) wrong++;
  return [toImage(out, screenPal(system || "pal", view)), wrong, out];
}

/** The converter's quick estimate (dither_pick.estimate). */
export function estimate(rows, system, view = null) {
  useStandard(system);
  const h = rows.length;
  const conv = new Converter(rows);
  const pairs = conv.cellColors.map((cnts) => cnts.map((cnt) => {
    const cols = [...cnt.keys()].map((c, i) => [c, i]).sort((a, b) => cnt.get(b[0]) - cnt.get(a[0]) || a[1] - b[1]).map((e) => e[0]);
    return [cols[0], cols.length > 1 ? cols[1] : cols[0]];
  }));
  const dist = (a, b) => (PEPTO[a][0] - PEPTO[b][0]) ** 2 + (PEPTO[a][1] - PEPTO[b][1]) ** 2 + (PEPTO[a][2] - PEPTO[b][2]) ** 2;
  const out = [];
  let wrong = 0;
  for (let y = 0; y < h; y++) {
    const rp = pairs[y >> 3];
    const [spans] = conv.spansOf(y, rp);
    const painted = new Set();
    for (const sp of spans) for (const x of sp.xs) painted.add(x);
    const line = rows[y].slice();
    line.forEach((c, x) => {
      const [fg, bg] = rp[x >> 3];
      if (c !== fg && c !== bg && !painted.has(x)) {
        line[x] = dist(c, fg) < dist(c, bg) ? fg : bg;
        wrong++;
      }
    });
    out.push(line);
  }
  return [toImage(out, screenPal(system || "pal", view)), wrong, out];
}

// ---------------------------------------------------------------- metrics

/** numpy's pairwise summation (pairwise_sum in loops_utils), for its sums and means. */
export function npSum(a, lo = 0, n = a.length) {
  if (n < 8) {
    let res = 0.0;
    for (let i = 0; i < n; i++) res += a[lo + i];
    return res;
  }
  if (n <= 128) {
    const r = [];
    for (let j = 0; j < 8; j++) r.push(a[lo + j]);
    let i = 8;
    for (; i < n - (n % 8); i += 8) for (let j = 0; j < 8; j++) r[j] += a[lo + i + j];
    let res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
    for (; i < n; i++) res += a[lo + i];
    return res;
  }
  let n2 = Math.floor(n / 2);
  n2 -= n2 % 8;
  return npSum(a, lo, n2) + npSum(a, lo + n2, n - n2);
}

export function rms(a, b) {
  const d = new Float64Array(a.data.length);
  for (let i = 0; i < d.length; i++) { const v = a.data[i] - b.data[i]; d[i] = v * v; }
  return Math.sqrt(npSum(d) / d.length);
}

const M = [[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]];
const WHITE = [0.95047, 1.0, 1.08883];

/** a* and b* of each pixel (CIELAB, D65). */
function ab(im) {
  const n = im.width * im.height, out = new Float64Array(n * 2);
  const e = 6 / 29, e3 = e ** 3;
  const f = (t) => (t > e3 ? Math.cbrt(t) : t / (3 * e * e) + 4 / 29);
  const lin = (v) => { const a = v / 255; return a <= 0.04045 ? a / 12.92 : ((a + 0.055) / 1.055) ** 2.4; };
  for (let i = 0; i < n; i++) {
    const r = lin(im.data[i * 3]), g = lin(im.data[i * 3 + 1]), b = lin(im.data[i * 3 + 2]);
    const xyz = M.map((m, k) => (r * m[0] + g * m[1] + b * m[2]) / WHITE[k]);
    const fx = f(xyz[0]), fy = f(xyz[1]), fz = f(xyz[2]);
    out[i * 2] = 500 * (fx - fy);
    out[i * 2 + 1] = 200 * (fy - fz);
  }
  return out;
}

export function color(a, b) {
  const la = ab(a), lb = ab(b), n = a.width * a.height, d = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const u = la[i * 2] - lb[i * 2], v = la[i * 2 + 1] - lb[i * 2 + 1];
    d[i] = Math.sqrt(u * u + v * v);
  }
  return npSum(d) / n;
}

const RADIUS = 5;
const KERNEL = (() => {
  const k = [];
  for (let i = -RADIUS; i <= RADIUS; i++) k.push(Math.exp(-0.5 * (i / 1.5) ** 2));
  const s = npSum(k);
  return k.map((v) => v / s);
})();

/** dither_pick.gauss: separable, edges reflected (numpy "reflect"); a is h x w. */
function gauss(a, w, h) {
  const refl = (i, n) => (i < 0 ? -i : i >= n ? 2 * (n - 1) - i : i);
  const tmp = new Float64Array(w * h), out = new Float64Array(w * h);
  for (let y = 0; y < h; y++) {           // axis 0 first
    for (let x = 0; x < w; x++) {
      let s = 0;
      for (let i = 0; i < KERNEL.length; i++) s += KERNEL[i] * a[refl(y + i - RADIUS, h) * w + x];
      tmp[y * w + x] = s;
    }
  }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let s = 0;
      for (let i = 0; i < KERNEL.length; i++) s += KERNEL[i] * tmp[y * w + refl(x + i - RADIUS, w)];
      out[y * w + x] = s;
    }
  }
  return out;
}

export function ssim(a, b) {
  const w = a.width, h = a.height, n = w * h;
  const x = new Float64Array(n), y = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    x[i] = a.data[i * 3] * 0.299 + a.data[i * 3 + 1] * 0.587 + a.data[i * 3 + 2] * 0.114;
    y[i] = b.data[i * 3] * 0.299 + b.data[i * 3 + 1] * 0.587 + b.data[i * 3 + 2] * 0.114;
  }
  const c1 = (0.01 * 255) ** 2, c2 = (0.03 * 255) ** 2;
  const prod = (p, q) => p.map((v, i) => v * q[i]);
  const mx = gauss(x, w, h), my = gauss(y, w, h);
  const gxx = gauss(prod(x, x), w, h), gyy = gauss(prod(y, y), w, h), gxy = gauss(prod(x, y), w, h);
  const s = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const vx = gxx[i] - mx[i] * mx[i], vy = gyy[i] - my[i] * my[i], cxy = gxy[i] - mx[i] * my[i];
    s[i] = ((2 * mx[i] * my[i] + c1) * (2 * cxy + c2)) / ((mx[i] * mx[i] + my[i] * my[i] + c1) * (vx + vy + c2));
  }
  return npSum(s) / n;
}

export function scores(c64, ref) {
  const bc = boxBlur1(c64), br = boxBlur1(ref);
  return { rms: rms(bc, br), ssim: ssim(bc, br), color: color(bc, br) };
}

/** Adds the scaled metrics and the weighted `score`; returns the results best first. */
export function rank(results, weights = WEIGHTS) {
  for (const m of METRICS) {
    const vals = results.map((r) => r[m]);
    const lo = Math.min(...vals), hi = Math.max(...vals);
    for (const r of results) {
      const t = hi === lo ? 1.0 : (r[m] - lo) / (hi - lo);
      r["n" + m] = HIGHER[m] ? t : 1 - t;
    }
  }
  const total = weights[0] + weights[1] + weights[2];
  for (const r of results) {
    r.score = (weights[0] * r.nrms + weights[1] * r.nssim + weights[2] * r.ncolor) / total;
  }
  return results.map((r, i) => [r, i]).sort((p, q) => q[0].score - p[0].score || p[1] - q[1]).map((e) => e[0]);
}

// ---------------------------------------------------------------- img2c64's picker

/** The picture at the C64 picture's size, to score against; img may already be that (a
 * worker gets the picture resized once, not the photo). */
export function refImage(img, w, h) {
  return img.width === w && img.height === h ? img : resize(img, w, h, "lanczos");
}

/** img2c64 judge: the scores of out (a convert result) against picture img, as the screen
 * shows it; quick: by the estimate. Also returns what the C64 shows (rows). */
export function judge(img, out, system, view, mc, quick, progress = null) {
  let c64, wrong = null, rows = null;
  if (mc) c64 = scaleUp(toImage(out.rows, screenPal(system, view)), 2, 1);
  else [c64, wrong, rows] = (quick ? estimate : shown)(out.rows, system, view, progress);
  const r = scores(c64, refImage(img, c64.width, c64.height));
  return Object.assign(r, { wrong, pixels: out.width * out.height, rows });
}

/** img2c64 candidate: one dither tried; [result, out]. opts as img2c64.convert's; ref:
 * the picture to score against (img2c64 judge's img). */
export function candidate(img, system, [name, dither, runs], opts, quick, ref = img) {
  const t0 = performance.now();
  opts = Object.assign({ view: img2c64.VIEW, mc: false }, opts);
  const out = img2c64.convert(img, system, img2c64.parseDither(dither), Object.assign({}, opts, { runs }));
  const r = judge(ref, out, system, opts.view, opts.mc, quick);
  return [Object.assign(r, { setting: name, dither, runs, secs: (performance.now() - t0) / 1000 }), out];
}

/** img2c64 refine: a candidate the estimate ranked high, through the converter. */
export function refine(img, out, est, system, view, progress = null) {
  const t0 = performance.now();
  const r = judge(img, out, system, view, false, false, progress);
  return Object.assign(r, { setting: est.setting, dither: est.dither, runs: est.runs, secs: (performance.now() - t0) / 1000 });
}

const pct = (v) => v.toFixed(2);

/** img2c64's "dither choice" line for the ranked results (estimates filtered out). */
export function pickedText(ranked, ncands, top, weights = WEIGHTS, by = "vic2orious web") {
  const g = img2c64.g;
  return `picked by ${by} from ${ncands} dithers${top ? ` (the best ${top} by estimate converted)` : ""} (weights rms ${g(weights[0])}, ssim ${g(weights[1])}, color ${g(weights[2])}): ` +
    ranked.slice(0, 3).map((r) => `${r.setting} ${pct(r.score)}`).join(", ");
}
