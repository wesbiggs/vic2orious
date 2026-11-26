// Thumbnails (ported from vic2/thumb.py, which now only reads them): a picture shrunk into
// one sprite's 24x21 pixels, in at most 8 colours over a background colour
// (docs/v2i-format.md, "Thumbnail").

import { resize, enhanceColor } from "./imaging.js";
import { pyRound } from "./pyround.js";

export const W = 24, H = 21, SPRITES = 8, BG = 0;
// The shrunk picture's saturation is raised this much before its colours are chosen:
// averaging greys the colours, and the nearest palette colours were browns and greys
// (Nov 2026, Kodak photos: 1.3-1.6 keep a parrot's green, 2 turns skin green; dithering
// 24 pixels only added noise).
export const SATURATE = 1.5;

export function size(w, h) {
  const s = Math.min(W / w, H / h, 1.0);
  return [Math.max(1, Math.min(W, pyRound(w * s))), Math.max(1, Math.min(H, pyRound(h * s)))];
}

const d2 = (p, q) => (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2;

/** The colours (palette indices) for pixels px against pal: bg and at most `colours`
 * others, by backward elimination. */
export function choose(px, pal, bg = BG, colours = SPRITES) {
  const keep = new Set(pal.map((_, i) => i));
  const cost = new Map();
  const err = (cs) => {
    const key = [...cs].sort((a, b) => a - b).join(",");
    if (!cost.has(key)) {
      let s = 0;
      for (const p of px) {
        let m = Infinity;
        for (const c of cs) m = Math.min(m, d2(p, pal[c]));
        s += m;
      }
      cost.set(key, s);
    }
    return cost.get(key);
  };
  while (keep.size > colours + 1) {
    let drop = null, best = null;
    for (const c of keep) {
      if (c === bg) continue;
      const rest = new Set(keep);
      rest.delete(c);
      const e = err(rest);
      if (best === null || e < best || (e === best && c < drop)) { best = e; drop = c; }
    }
    keep.delete(drop);
  }
  return [...keep].sort((a, b) => a - b);
}

/** Thumbnail bytes of img (RGB image, any size) shown at screenSize [w, h] (screen
 * pixels), colours chosen against pal (16 [r, g, b]). */
export function make(img, screenSize, pal, bg = BG, colours = SPRITES) {
  const [tw, th] = size(...screenSize);
  const small = enhanceColor(resize(img, tw, th, "box"), SATURATE);
  const px = [];
  for (let i = 0; i < tw * th; i++) px.push([small.data[i * 3], small.data[i * 3 + 1], small.data[i * 3 + 2]]);
  const cs = choose(px, pal, bg, colours);
  const idx = px.map((p) => {
    let b = cs[0];
    for (const c of cs) if (d2(p, pal[c]) < d2(p, pal[b])) b = c;
    return b;
  });
  const x0 = Math.floor((W - tw) / 2), y0 = Math.floor((H - th) / 2);
  const count = new Map();
  for (const c of idx) if (c !== bg) count.set(c, (count.get(c) || 0) + 1);
  const used = [...count.keys()].sort((a, b) => count.get(b) - count.get(a) || a - b);
  const out = [tw, th, bg, used.length];
  for (const c of used) {
    const spr = new Array(63).fill(0);
    idx.forEach((v, i) => {
      if (v === c) {
        const x = x0 + (i % tw), y = y0 + Math.floor(i / tw);
        spr[y * 3 + (x >> 3)] |= 0x80 >> (x % 8);
      }
    });
    out.push(c, ...spr);
  }
  return Uint8Array.from(out);
}

/** The 24x21 area as the C64 shows it: rows of palette indices. */
export function pixels(data) {
  const bg = data[2], n = data[3];
  const out = [];
  for (let y = 0; y < H; y++) out.push(new Array(W).fill(bg));
  for (let i = n - 1; i >= 0; i--) {
    const c = data[4 + 64 * i], o = 5 + 64 * i;
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) if (data[o + y * 3 + (x >> 3)] & (0x80 >> (x % 8))) out[y][x] = c;
    }
  }
  return out;
}
