// The work a page hands to its web workers (worker.js), as plain functions of plain data,
// so tests can call them directly. Each takes its payload and a progress callback (0-1).

import * as img2c64 from "./img2c64.js";
import * as pick from "./pick.js";
import * as thumb from "./thumb.js";
import { resize } from "./imaging.js";
import { convertImage, place } from "./v2i.js";

export const SYSTEMS = ["pal", "ntsc"];

const sized = (img, w, h) => (img.width === w && img.height === h ? img : resize(img, w, h, "lanczos"));

/** Everything that needs the whole photo, per system: the picture fitted to the screen
 * (what every dither starts from), the photo at the size of what the C64 shows (what
 * each result is scored against) and the thumbnail. */
export function prepare({ img, mc = false, box = [img2c64.MAX_W, img2c64.MAX_H] }) {
  const out = {};
  for (const system of SYSTEMS) {
    const [w, h] = img2c64.targetSize(img.width, img.height, system, false, box, mc);
    out[system] = {
      w, h,
      fitted: sized(img, w, h),
      ref: sized(img, mc ? 2 * w : w, h),
      thumb: Array.from(thumb.make(img, [w * (mc ? 2 : 1), h], img2c64.palette(system, 1.0, img2c64.VIEW))),
    };
  }
  return out;
}

/** One dither: its indices and its scores (by the converter's estimate if quick). */
export function candidate({ system, fitted, ref, cand, mc = false, box, chroma = 1.0, quick }) {
  const [r, out] = pick.candidate(fitted, system, cand, { mc, box, chroma, fitted: true }, quick, ref);
  delete r.rows;
  return { result: r, idx: out.idx, w: out.width, h: out.height };
}

/** Whether the converter's upper left placement (the picker's) is where the .v2i puts the
 * picture (centred), so one conversion serves both. */
export function sameAsCentred(w, h, mc) {
  const [c, r] = place(w / (mc ? 4 : 8), h / 8);
  return c === 0 && r === 0;
}

const rowsOf = (idx, w, h) => img2c64.toRows(idx instanceof Uint8Array ? idx : Uint8Array.from(idx), w, h);

/** A candidate through the converter, scored. Where the placements agree it is converted
 * as the .v2i needs it, and the conversion comes back too (conv). */
export function refine({ system, idx, w, h, ref, est }, progress) {
  const rows = rowsOf(idx, w, h);
  if (!sameAsCentred(w, h, false)) {
    const r = pick.refine(ref, { rows, width: w, height: h }, est, system, img2c64.VIEW, progress);
    delete r.rows;
    return { result: r };
  }
  const t0 = performance.now();
  const conv = convertImage(rows, system, { progress });
  const c64 = pick.toImage(conv.rendered, img2c64.VIEW);
  const r = Object.assign(pick.scores(c64, pick.refImage(ref, c64.width, c64.height)),
    { wrong: conv.wrong, pixels: w * h, setting: est.setting, dither: est.dither, runs: est.runs,
      secs: (performance.now() - t0) / 1000 });
  return { result: r, conv };
}

/** The picked dither converted for the .v2i. */
export function convert({ system, idx, w, h, mc = false }, progress) {
  return convertImage(rowsOf(idx, w, h), system, { mc, progress });
}
