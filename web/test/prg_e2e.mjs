// A photo to a PRG through the page's pipeline and worker pool (in worker threads),
// compared with the PRG `python3 -m vic2.prg` made of the same photo. The photo comes as
// web/test/prep_golden.py's JSON (the picture as img2c64 loads it); the metadata's date
// is left out of the comparison, the tool name is the Python's.
//   node web/test/prg_e2e.mjs photo.json python.prg SOURCE-NAME [-m] [-d DITHER] [-c S] [-w R,S,C]
//     [-s WxH] [--at COLUMN,ROW] [--then DITHER]
// --then: the page's Use: the picked result, then that dither of it (vic2.prg -d DITHER).
// --at: the page's screen position; vic2.prg has none, so python.prg comes from a vic2.prg
// whose conversions are placed as `vic2.build --at` places them.
import { readFileSync, writeFileSync } from "node:fs";
import { Worker } from "node:worker_threads";
import os from "node:os";
import { Pool } from "../js/pool.js";
import { makePrg, withDither } from "../js/pipeline.js";

const [json, prgPath, source, ...opts] = process.argv.slice(2);
const ref = JSON.parse(readFileSync(json, "utf8"));
const want = readFileSync(prgPath);
const m = want.toString("latin1").match(/date: (\d+)-(\d+)-(\d+) (\d+):(\d+) UTC/);
const date = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]));
const arg = (o) => (opts.includes(o) ? opts[opts.indexOf(o) + 1] : null);
const img = { width: ref.width, height: ref.height, data: new Uint8Array(Buffer.from(ref.rgb, "base64")) };
const spawn = () => {
  const w = new Worker(new URL("./node-worker.mjs", import.meta.url));
  const o = { postMessage: (msg) => w.postMessage(msg), terminate: () => w.terminate() };
  w.on("message", (d) => o.onmessage({ data: d }));
  w.on("error", (e) => o.onerror(e));
  return o;
};
const pool = new Pool(Math.max(1, Math.min(8, os.cpus().length - 1)), spawn);
const t = Date.now();
let lastText = "";
let r = await makePrg(img, source, {
  weights: opts.includes("-w") ? opts[opts.indexOf("-w") + 1].split(",").map(Number) : undefined,
  box: arg("-s") ? arg("-s").split("x").map(Number) : undefined,
  at: arg("--at") ? arg("--at").split(",").map(Number) : null,
  mc: opts.includes("-m"), chroma: opts.includes("-c") ? +opts[opts.indexOf("-c") + 1] : 1.0, dither: opts.includes("-d") ? opts[opts.indexOf("-d") + 1] : null,
  run: (type, payload, onProgress) => pool.run(type, payload, onProgress),
  status: (text, f) => { if (text !== lastText) { console.log(`  ${((Date.now() - t) / 1000).toFixed(1)} s ${text} (${Math.round(f * 100)}%)`); lastText = text; } },
  date, by: "img2c64",
});
if (opts.includes("--then")) {
  r = await withDither(r, opts[opts.indexOf("--then") + 1], {
    run: (type, payload, onProgress) => pool.run(type, payload, onProgress), date,
  });
}
pool.terminate();
writeFileSync(prgPath.replace(/\.prg$/, "-js.prg"), r.prg);
// each .v2i has the minute it was converted in: compare without them
const undated = (b) => Buffer.from(b.toString("latin1").replace(/date: [0-9-]+ [0-9:]+ UTC/g, "date: -"), "latin1");
const got = undated(Buffer.from(r.prg)), wantU = undated(want);
for (const s of ["pal", "ntsc"]) {
  const y = r.systems[s];
  console.log(`  ${s}: ${y.setting}, ${y.w}x${y.h}, wrong ${y.wrong}`);
  if (opts.includes("-v") && y.ranked) for (const q of y.ranked) console.log(`    ${q.score.toFixed(3)} ${q.setting} rms ${q.rms.toFixed(2)} ssim ${q.ssim.toFixed(4)} color ${q.color.toFixed(2)} wrong ${q.wrong}`);
}
let i = 0;
while (i < Math.min(got.length, wantU.length) && got[i] === wantU[i]) i++;
const same = got.equals(wantU);
console.log(`${source}: ${same ? "same apart from the dates" : `DIFF ${got.length} vs ${wantU.length} bytes, first at ${i}`} (${((Date.now() - t) / 1000).toFixed(1)} s, ${pool.size} workers)`);
process.exit(same ? 0 : 1);
