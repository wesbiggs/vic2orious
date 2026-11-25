// Compares the JavaScript dither picker with the Python's (web/test/pick_golden.py):
// every metric (to a relative 1e-9) and the picks.
//   node web/test/pick_golden.mjs ref.json...
import { readFileSync } from "node:fs";
import * as pick from "../js/pick.js";
import * as img2c64 from "../js/img2c64.js";

let bad = 0;
const close = (a, b) => (a === null || b === null ? a === b : Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(b)));
function compare(label, got, want) {
  const diffs = [];
  if (got.length !== want.length) diffs.push(`${got.length} results vs ${want.length}`);
  got.forEach((r, i) => {
    const w = want[i];
    if (!w) return;
    for (const k of ["setting", "wrong"]) if (r[k] !== w[k]) diffs.push(`${i} ${k} ${r[k]} vs ${w[k]}`);
    for (const k of ["rms", "ssim", "color", "score"]) {
      if (!close(r[k], w[k])) diffs.push(`${i} ${w.setting} ${k} ${r[k]} vs ${w[k]} (${(r[k] - w[k]).toExponential(2)})`);
    }
  });
  let maxRel = 0;
  got.forEach((r, i) => { for (const k of ["rms", "ssim", "color"]) if (want[i] && want[i].setting === r.setting) maxRel = Math.max(maxRel, Math.abs(r[k] - want[i][k]) / Math.max(1, Math.abs(want[i][k]))); });
  console.log(`${label}: ${diffs.length ? "DIFF\n  " + diffs.join("\n  ") : "same"} (largest metric difference ${maxRel.toExponential(1)})`);
  return diffs.length;
}

for (const file of process.argv.slice(2)) {
  const ref = JSON.parse(readFileSync(file, "utf8"));
  const img = { width: ref.width, height: ref.height, data: new Uint8Array(Buffer.from(ref.rgb, "base64")) };
  const cands = pick.CANDIDATES.filter((c) => !(ref.mc && c[1].startsWith("hybrid")));
  const opts = { box: ref.box, mc: ref.mc };
  for (const [system, want] of Object.entries(ref.systems)) {
    const t = Date.now();
    const quick = !ref.mc;
    const done = cands.map((c) => pick.candidate(img, system, c, opts, quick));
    const outs = new Map(done.map(([r, o]) => [r.setting, o]));
    let ranked = pick.rank(done.map(([r]) => r));
    bad += compare(`${file} ${system} estimate`, ranked, want.stage1);
    if (quick) {
      const conv = ranked.slice(0, img2c64.TOP).map((r) => pick.refine(img, outs.get(r.setting), r, system, img2c64.VIEW));
      const extra = ranked.slice(img2c64.TOP).map((r) => Object.assign({}, r, { estimate: true }));
      ranked = pick.rank(conv.concat(extra));
      bad += compare(`${file} ${system} converted`, ranked, want.final);
    }
    const p = ranked.filter((r) => !r.estimate)[0].setting;
    console.log(`${file} ${system}: pick ${p} (Python ${want.pick}) ${p === want.pick ? "same" : "DIFF"} ${((Date.now() - t) / 1000).toFixed(1)} s`);
    if (p !== want.pick) bad++;
  }
}
process.exit(bad ? 1 : 0);
