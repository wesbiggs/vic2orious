// The JavaScript dual PRG against the assembled one (web/test/prg_golden.py).
//   node web/test/prg_golden.mjs pal.json ntsc.json ref.prg
import { readFileSync } from "node:fs";
import { dualPrg } from "../js/prg.js";

const v2i = (p) => new Uint8Array(Buffer.from(JSON.parse(readFileSync(p, "utf8")).v2i, "hex"));
const got = Buffer.from(dualPrg(v2i(process.argv[2]), v2i(process.argv[3])));
const want = readFileSync(process.argv[4]);
console.log(got.equals(want) ? `same (${got.length} bytes)` : `DIFF ${got.length} vs ${want.length}`);
process.exit(got.equals(want) ? 0 : 1);
