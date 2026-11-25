// Compares the JavaScript picture preparation with the Python's (web/test/prep_golden.py).
//   node web/test/prep_golden.mjs ref.json...
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import * as img2c64 from "../js/img2c64.js";

let bad = 0;
for (const file of process.argv.slice(2)) {
  const ref = JSON.parse(readFileSync(file, "utf8"));
  const img = { width: ref.width, height: ref.height, data: new Uint8Array(Buffer.from(ref.rgb, "base64")) };
  for (const r of ref.results) {
    const t = Date.now();
    const dither = img2c64.parseDither(r.dither);
    const o = img2c64.convert(img, r.system, dither, { box: ref.box, chroma: ref.chroma, runs: r.runs, mc: ref.mc });
    const h = createHash("sha1").update(o.idx).digest("hex");
    const diffs = [];
    if (o.width !== r.w || o.height !== r.h) diffs.push(`size ${o.width}x${o.height} vs ${r.w}x${r.h}`);
    else if (h !== r.idx) {
      const want = Buffer.from(r.idx_b64, "base64");
      let n = 0, first = -1;
      for (let i = 0; i < want.length; i++) if (want[i] !== o.idx[i]) { n++; if (first < 0) first = i; }
      diffs.push(`idx: ${n} pixels differ, first at ${first % o.width},${Math.floor(first / o.width)}`);
    }
    // the source name is the Python's argument; the tool name differs on purpose
    const s = img2c64.settings(r.settings.match(/^source: (.*)$/m)[1], r.system, dither,
      { box: ref.box, chroma: ref.chroma, runs: r.runs, mc: ref.mc, by: "img2c64" });
    if (s !== r.settings) diffs.push(`settings:\n${s}---\n${r.settings}`);
    const th = Buffer.from(img2c64.thumbnail(img, o, r.system, img2c64.VIEW, ref.mc)).toString("hex");
    if (th !== r.thumb) diffs.push(`thumb ${th.slice(0, 40)} vs ${r.thumb.slice(0, 40)}`);
    console.log(`${file} ${r.system} ${r.name}: ${diffs.length ? "DIFF " + diffs.join("; ") : "same"} (${Date.now() - t} ms)`);
    bad += diffs.length ? 1 : 0;
  }
}
process.exit(bad ? 1 : 0);
