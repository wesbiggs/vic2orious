// A worker thread of tools/engine.mjs: img2c64's per-dither work (web/js/pick.js), as
// pool.js hands it out. candidate: one dither of a picture, scored (by the converter's
// estimate if quick); refine: a candidate through the converter, scored.
import { parentPort } from "node:worker_threads";
import { handle } from "../web/js/pool.js";
import * as pick from "../web/js/pick.js";
import * as img2c64 from "../web/js/img2c64.js";

const jobs = {
  candidate({ system, fitted, ref, cand, mc, box, frame, chroma, view, quick }) {
    const [result, out] = pick.candidate(fitted, system, cand, { mc, box, frame, chroma, view, fitted: true }, quick, ref);
    delete result.rows;
    return { result, out: { width: out.width, height: out.height, idx: out.idx } };
  },
  refine({ system, out, ref, est, view }) {
    const result = pick.refine(ref, { width: out.width, height: out.height, rows: img2c64.toRows(out.idx, out.width, out.height) },
      est, system, view);
    delete result.rows;
    return { result };
  },
};

parentPort.on("message", (m) => handle(jobs, m, (r) => parentPort.postMessage(r)));
