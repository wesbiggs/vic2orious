// Runs the JavaScript converter on the inputs of reference files from golden.py and
// compares every output with the Python's:
//
//     node web/test/golden.mjs ref1.json [ref2.json ...]

import { readFileSync } from "node:fs";
import * as timing from "../js/timing.js";
import { Converter, resetCaches } from "../js/convert.js";

const hex = (a) => Buffer.from(a).toString("hex");
let failed = 0;
for (const file of process.argv.slice(2)) {
  const ref = JSON.parse(readFileSync(file, "utf8"));
  timing.setStandard(ref.std);
  resetCaches();
  const t = performance.now();
  const c = new Converter(ref.img, { ...ref.kw });
  c.run();
  const secs = (performance.now() - t) / 1000;
  const got = {
    kernel: hex(c.kernel.code),
    pairs: c.pairs,
    sdata: c.sdata.map((m) => [...m].sort((a, b) => a[0] - b[0])),
    line_cfg: c.lineCfg.map((m) => [...m].sort((a, b) => a[0] - b[0])),
    bad_lines: [...c.badLines].sort((a, b) => a[0] - b[0]),
    render: c.render(),
  };
  const bad = Object.keys(got).filter((k) => JSON.stringify(got[k]) !== JSON.stringify(ref[k]));
  if (bad.length) failed++;
  console.log(`${file}: ${bad.length ? "DIFFERS in " + bad.join(", ") : "same"} ` +
    `(${secs.toFixed(1)} s, Python ${ref.secs} s)`);
  if (bad.includes("kernel")) {
    const a = got.kernel, b = ref.kernel;
    let i = 0;
    while (i < a.length && a[i] === b[i]) i++;
    console.log(`  kernel: ${a.length / 2} vs ${b.length / 2} bytes, first difference at byte ${i >> 1}`);
  }
}
process.exit(failed ? 1 : 0);
