// Compares the JavaScript .v2i packing with the Python's (web/test/v2i_golden.py), the
// metadata's date taken from the Python's file.
//   node web/test/v2i_golden.mjs ref.json...
import { readFileSync } from "node:fs";
import { convertImage } from "../js/v2i.js";

let bad = 0;
for (const file of process.argv.slice(2)) {
  const ref = JSON.parse(readFileSync(file, "utf8"));
  const want = Buffer.from(ref.v2i, "hex");
  const m = want.toString("latin1").match(/date: (\d+)-(\d+)-(\d+) (\d+):(\d+) UTC/);
  const date = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]));
  const t = Date.now();
  const r = convertImage(ref.img, ref.std, { mc: ref.mc, settings: ref.settings, thumb: [...Buffer.from(ref.thumb, "hex")], imageName: ref.image, date });
  const got = Buffer.from(r.v2i);
  const diffs = [];
  if (!got.equals(want)) {
    let i = 0;
    while (i < Math.min(got.length, want.length) && got[i] === want[i]) i++;
    diffs.push(`v2i: ${got.length} vs ${want.length} bytes, first difference at ${i}`);
  }
  if (r.wrong !== ref.wrong) diffs.push(`wrong ${r.wrong} vs ${ref.wrong}`);
  if (r.topSlot !== ref.top_slot) diffs.push(`top slot ${r.topSlot} vs ${ref.top_slot}`);
  if (r.badLines.join() !== ref.bad_lines.join()) diffs.push("bad lines");
  console.log(`${file}: ${diffs.length ? "DIFF " + diffs.join("; ") : "same"} (${got.length} bytes, ${((Date.now() - t) / 1000).toFixed(1)} s)`);
  bad += diffs.length ? 1 : 0;
}
process.exit(bad ? 1 : 0);
