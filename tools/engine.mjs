// The engine for the Python tools: the JavaScript the web page runs (web/js), driven from
// vic2/engine.py, which starts it as
//
//     node tools/engine.mjs < REQUEST.json
//
// The request is one JSON object; "cmd" says what to do:
//   convert  one picture of palette indices to a .v2i (the build's convert_new): converter,
//            sprite blocks, kernel stream, thumbnail and metadata
//   img2c64  tools/img2c64.py's work on pictures it has read: fit, dither (or pick one
//            per picture and system, in worker threads), thumbnail
// The answer is JSON lines on stdout: {"log": text} for what the Python prints, then one
// {"result": ...} (img2c64: one per output, in the order given), or {"error": text} and
// exit status 1. Pictures go both ways as base64: RGB bytes, or one palette index a pixel.
// Needs Node 18 or later and nothing else (no npm packages).

import { readFileSync, writeFileSync } from "node:fs";
import { Worker } from "node:worker_threads";
import os from "node:os";
import { convertPlaced, pack } from "../web/js/v2i.js";
import { SchedFail } from "../web/js/timing.js";
import * as img2c64 from "../web/js/img2c64.js";
import * as pick from "../web/js/pick.js";
import * as thumb from "../web/js/thumb.js";
import { resize } from "../web/js/imaging.js";
import { Pool } from "../web/js/pool.js";

const out = (o) => process.stdout.write(JSON.stringify(o) + "\n");
const log = (text) => out({ log: text });
const b64 = (a) => Buffer.from(a).toString("base64");
const unb64 = (s) => new Uint8Array(Buffer.from(s, "base64"));
const rowsOf = (s, w, h) => img2c64.toRows(unb64(s), w, h);
const image = (p) => ({ width: p.w, height: p.h, data: unb64(p.rgb) });
const hex = (a) => Buffer.from(a).toString("hex");

// ---------------------------------------------------------------- convert

function convert(q) {
  const rows = rowsOf(q.rows, q.w, q.h);
  const res = convertPlaced(rows, q.system, { mc: q.mc, at: q.at, frame: q.frame, conv: true,
    log: (m) => log("  " + m) });
  const c = res.conv;
  // the thumbnail: img2c64's from the PNG, else made of the picture as the C64 shows it
  const tdata = q.thumb ? unb64(Buffer.from(q.thumb, "hex").toString("base64"))
    : thumb.make(image(q.picture), [q.w * (q.mc ? 2 : 1), q.h], q.thumbPalette);
  const v2i = pack(res, { settings: q.settings || "", thumb: Array.from(tdata), imageName: q.imageName,
    paletteName: q.paletteName, date: q.date ? new Date(q.date) : new Date() });
  writeFileSync(q.v2i, v2i);
  const g = c.g;
  const result = {
    w: res.w, h: res.h, at: res.at, frame: res.frame, mc: res.mc, size: v2i.length - 2,
    top_slot: res.topSlot, wrong_px: res.wrong, bad_lines: res.badLines, thumb: hex(tdata),
    rendered: b64(res.rendered.flat()),
  };
  if (q.layers) {               // what vic2/layers.py draws
    const cov = c.spriteCover();
    result.layers = {
      raster0: g.raster0, pairs: c.pairs, bitmap: b64(c.bitmap().flat()),
      cover: b64(cov.flat().map((v) => (v === null ? 255 : v))),
      sdata: c.sdata.map((m) => [...m]), line_cfg: c.lineCfg.map((m) => [...m]),
      bad_lines: [...c.badLines.keys()],
    };
  }
  out({ result });
}

// ---------------------------------------------------------------- img2c64

const fmt = (v, d) => v.toFixed(d);
const pad = (s, n) => (s.length >= n ? s : s + " ".repeat(n - s.length));
const lpad = (s, n) => (s.length >= n ? s : " ".repeat(n - s.length) + s);

/** img2c64 describe: a candidate's metrics, wrong pixels and time, for the log. */
function describe(r) {
  const wrong = r.wrong !== null && r.wrong !== undefined
    ? `wrong ${lpad(fmt((100 * r.wrong) / r.pixels, 1), 5)}%` : "";
  return `${pad(r.setting, 14)} rms ${lpad(fmt(r.rms, 2), 6)}  ssim ${fmt(r.ssim, 4)}  color ${lpad(fmt(r.color, 2), 6)}  ` +
    `${pad(wrong, 12)} cpu ${lpad(fmt(r.secs, 1), 5)} s${r.estimate ? "  (estimate)" : ""}`;
}

/** Promises in the order they settle. */
async function* settled(promises) {
  const left = new Map(promises.map((p, i) => [i, p.then((v) => [i, v])]));
  while (left.size) {
    const [i, v] = await Promise.race(left.values());
    left.delete(i);
    yield v;
  }
}

/** img2c64 pick: a picture's candidates ranked, logged as they finish, then the ranking. */
async function rankLogged(promises, weights, label, extra = []) {
  const done = [];
  let n = 0;
  for await (const r of settled(promises)) {
    done.push(r);
    log(`  ${label} [${++n}/${promises.length}] ${describe(r.result)}`);
  }
  const outs = new Map(done.map((r) => [r.result.setting, r]));
  const ranked = pick.rank(done.map((r) => r.result).concat(extra.map((r) => Object.assign({}, r, { estimate: true }))), weights);
  const g = img2c64.g;
  log(`  ${label} ranked (weights rms ${g(weights[0])}, ssim ${g(weights[1])}, color ${g(weights[2])}):`);
  ranked.forEach((r, i) => log(`    ${i + 1}. score ${fmt(r.score, 3)}  ${describe(r)}`));
  return [ranked, outs];
}

function workers() {
  const spawn = () => {
    const w = new Worker(new URL("./engine-worker.mjs", import.meta.url));
    const o = { postMessage: (m) => w.postMessage(m), terminate: () => w.terminate() };
    w.on("message", (d) => o.onmessage({ data: d }));
    w.on("error", (e) => o.onerror(e));
    return o;
  };
  return new Pool(Math.max(1, os.cpus().length), spawn);
}

const sized = (img, w, h) => (img.width === w && img.height === h ? img : resize(img, w, h, "lanczos"));
const sysLabel = (system) => (system ? ", " + system.toUpperCase() : "");

async function quantise(q) {
  const { mc, frame, box, chroma, view } = q;
  const imgs = q.images.map(image);
  // what each output starts from: the picture fitted (every dither), and at the size of
  // what the C64 shows (what each is scored against)
  const prep = q.jobs.map((j) => {
    const img = imgs[j.image];
    const [w, h] = img2c64.targetSize(img.width, img.height, j.system, frame, box, mc);
    return { fitted: sized(img, w, h), ref: sized(img, mc ? 2 * w : w, h) };
  });
  const save = (i, made, dither, runs, picked, note) => {
    const j = q.jobs[i];
    const res = made || img2c64.convert(prep[i].fitted, j.system, dither, { frame, box, chroma, runs, view, mc, fitted: true });
    const settings = img2c64.settings(j.base, j.system, dither, { frame, box, chroma, runs, picked,
      viewName: q.viewName, mc, by: "img2c64" });
    const tdata = img2c64.thumbnail(imgs[j.image], res, j.system, view, mc);
    out({ result: { job: i, w: res.width, h: res.height, idx: b64(res.idx), settings, thumb: hex(tdata),
      palette: img2c64.palette(j.system, 1.0, view), note } });
  };
  if (q.dither) {
    q.jobs.forEach((j, i) => save(i, null, img2c64.parseDither(q.dither), q.runs, null, ""));
    return;
  }
  const weights = q.weights;
  const cands = pick.CANDIDATES.filter((c) => !(mc && c[1].startsWith("hybrid")));
  const quick = !mc && q.top !== null && q.top < cands.length;
  const pool = workers();
  try {
    const run = (type, payload) => pool.run(type, payload);
    // every candidate of every picture at once, so the pool stays busy
    let tried = q.jobs.map((j, i) => cands.map((cand) => run("candidate", {
      system: j.system, fitted: prep[i].fitted, ref: prep[i].ref, cand, mc, box, frame, chroma, view, quick,
    })));
    const extras = q.jobs.map(() => []);
    if (quick) {
      for (const [i, j] of q.jobs.entries()) {
        log(`${j.src}${sysLabel(j.system)}: estimating ${cands.length} dithers, converting the best ${q.top}`);
        const [ranked, outs] = await rankLogged(tried[i], weights, j.label + " estimate");
        tried[i] = ranked.slice(0, q.top).map((est) => {
          const o = outs.get(est.setting);
          return run("refine", { system: j.system, out: o.out, ref: prep[i].ref, est, view })
            .then((r) => Object.assign(r, { out: o.out }));
        });
        extras[i] = ranked.slice(q.top);
      }
    }
    for (const [i, j] of q.jobs.entries()) {
      log(`${j.src}${sysLabel(j.system)}: ${quick ? "converting" : "trying"} ${quick ? q.top : cands.length} dithers`);
      let [ranked, outs] = await rankLogged(tried[i], weights, j.label, extras[i]);
      ranked = ranked.filter((r) => !r.estimate);
      const best = ranked[0];
      const g = img2c64.g;
      const picked = `picked by img2c64 from ${cands.length} dithers${quick ? ` (the best ${q.top} by estimate converted)` : ""}` +
        ` (weights rms ${g(weights[0])}, ssim ${g(weights[1])}, color ${g(weights[2])}): ` +
        ranked.slice(0, 3).map((r) => `${r.setting} ${fmt(r.score, 2)}`).join(", ");
      const note = `; dither ${best.setting}` + (ranked.length > 1
        ? ` (next: ${ranked.slice(1, 3).map((r) => `${r.setting} ${fmt(r.score, 2)}`).join(", ")})` : "");
      save(i, outs.get(best.setting).out, img2c64.parseDither(best.dither), best.runs, picked, note);
    }
  } finally {
    pool.terminate();
  }
}

// ---------------------------------------------------------------- main

const q = JSON.parse(readFileSync(0, "utf8"));
try {
  if (q.cmd === "convert") convert(q);
  else if (q.cmd === "img2c64") await quantise(q);
  else throw new Error(`unknown cmd ${q.cmd}`);
} catch (e) {
  out({ error: e instanceof SchedFail ? `the converter found no timing that fits (${e.message})` : (e && e.stack) || String(e) });
  process.exitCode = 1;
}
