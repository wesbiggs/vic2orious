// A picture to a dual PRG, as `python3 -m vic2.prg PICTURE` makes it: img2c64 picks a
// dither per system (or takes the one given), the pick is converted centred (or at a
// position, as `vic2.build --at` places it) and packed as a .v2i, and both .v2i go into
// the v2i demo. The work runs through run(type, payload, onProgress), which hands it to
// web workers on a page (jobs.js) or calls jobs.js in tests.

import * as img2c64 from "./img2c64.js";
import * as pick from "./pick.js";
import { SYSTEMS, samePlace } from "./jobs.js";
import { pack } from "./v2i.js";
import { dualPrg } from "./prg.js";

const SUFFIX = { pal: "-p", ntsc: "-n" };

// img2c64 -a none makes one PNG for both systems, without the -p/-n suffix, and its
// settings say "aspect: none"
const aspected = (system, aspect) => (aspect === "none" ? null : system);
const imageName = (name, system, aspect) => name + (aspect === "none" ? "" : SUFFIX[system]) + ".png";

/** The candidate for a dither given by name: one of the picker's (as the page offers them
 * from its ranking), or img2c64 -d's (hybrid with its line budget). */
export function fixedCandidate(dither) {
  const known = pick.CANDIDATES.find((c) => c[0] === dither);
  if (known) return known;
  const [mode] = img2c64.parseDither(dither);
  return [dither, dither, mode === "hybrid" ? img2c64.HYBRID_RUNS : null];
}

/**
 * img: the photo ({width, height, data} RGB). source: its file name. Options: mc
 * (multicolour), dither (null: pick), chroma (img2c64 -c), weights (img2c64 -w, for the
 * pick), box (img2c64 -s: the largest [width, height]), at ([column, row] on the screen,
 * vic2.build --at; null: centred), bare (.v2i without thumbnail and metadata), aspect
 * ("system": each system's pixel aspect, as vic2.prg; "none": img2c64 -a none, the
 * picture's pixels as they are, for pictures made at C64 size), run (see
 * above), status(text, fraction) for progress, date for the metadata, by for its
 * "quantized by".
 * Returns {prg, name, source, opts, systems: {pal, ntsc}}; each system has v2i, rendered
 * (rows of palette indices as the C64 shows them), w, h, at (where the picture went, in
 * cells), mc, wrong, setting (the dither),
 * pick (the picker's choice), ranked (the picker's results, best first; null with a given
 * dither), candidates (every dither tried) and convs (conversions by setting).
 */
export async function makePrg(img, source, { mc = false, dither = null, chroma = 1.0, weights = pick.WEIGHTS,
  box = [img2c64.MAX_W, img2c64.MAX_H], at = null, bare = false, aspect = "system", run, status = () => {}, date = new Date(),
  by = "vic2orious web" } = {}) {
  const name = source.replace(/^.*[\\/]/, "").replace(/\.[^.]*$/, "") || "picture";
  // progress: each light job counts 1, each conversion HEAVY, as they finish (or move)
  const HEAVY = 30;
  let total = 1, done = 0;
  const moving = new Map();
  const report = (text) => {
    let f = done;
    for (const v of moving.values()) f += v;
    status(text, Math.min(1, f / total));
  };
  let stage = "Preparing the picture";
  const job = (type, payload, weight = 1) => {
    const key = {};
    return run(type, payload, (p) => { moving.set(key, p * weight); report(stage); })
      .then((r) => { moving.delete(key); done += weight; report(stage); return r; });
  };

  report(stage);
  const prep = await job("prepare", { img, mc, box, aspect });

  const auto = dither === null;
  const cands = auto ? pick.CANDIDATES.filter((c) => !(mc && c[1].startsWith("hybrid"))) : [fixedCandidate(dither)];
  const quick = !mc;                    // the estimate (multicolour is scored as it is)
  const top = auto && quick ? img2c64.TOP : 0;
  // the estimate: every dither, for both systems; then the converter for the best few,
  // and for the pick where the picker's conversion cannot serve
  total += 2 * cands.length + 2 * top * HEAVY + 2 * HEAVY;
  stage = auto ? `Trying ${cands.length} dithers` : "Dithering";
  const first = await Promise.all(SYSTEMS.map((system) => Promise.all(cands.map((cand) => job("candidate", {
    system, fitted: prep[system].fitted, ref: prep[system].ref, cand, mc, box, chroma, quick,
  })))));

  stage = top ? `Converting the best ${top} of each system` : "Converting";
  const systems = {};
  await Promise.all(SYSTEMS.map(async (system, si) => {
    const res = first[si];
    const outs = new Map(res.map((r) => [r.result.setting, r]));
    let ranked = auto ? pick.rank(res.map((r) => r.result), weights) : null;
    const convs = new Map();
    if (top) {
      const conv = await Promise.all(ranked.slice(0, top).map((est) => {
        const o = outs.get(est.setting);
        return job("refine", { system, idx: o.idx, w: o.w, h: o.h, ref: prep[system].ref, est, at }, HEAVY);
      }));
      for (const c of conv) if (c.conv) convs.set(c.result.setting, c.conv);
      const extra = ranked.slice(top).map((r) => Object.assign({}, r, { estimate: true }));
      ranked = pick.rank(conv.map((c) => c.result).concat(extra), weights);
      ranked = ranked.filter((r) => !r.estimate);
    }
    const best = auto ? ranked[0] : res[0].result;
    const o = outs.get(best.setting);
    const reuse = convs.get(best.setting);
    if (reuse) total -= HEAVY;           // the picker's conversion serves
    report(stage);
    const conv = reuse || await job("convert", { system, idx: o.idx, w: o.w, h: o.h, mc, at }, HEAVY);
    const picked = auto ? pick.pickedText(ranked, cands.length, top, weights, by) : null;
    const settings = img2c64.settings(source.replace(/^.*[\\/]/, ""), aspected(system, aspect), img2c64.parseDither(best.dither),
      { box, chroma, runs: best.runs, picked, mc, by });
    const v2i = pack(conv, { settings, thumb: prep[system].thumb, imageName: imageName(name, system, aspect), date, bare });
    systems[system] = {
      v2i, rendered: conv.rendered, w: conv.w, h: conv.h, at: conv.at, mc, wrong: conv.wrong,
      setting: best.setting, pick: auto ? best.setting : null, ranked, settings,
      samePlace: samePlace(conv.w, conv.h, mc, at), thumb: prep[system].thumb,
      // every dither tried, by the estimate: its indices (w x h) and figures
      candidates: res.map((r) => Object.assign({}, r.result, { idx: r.idx, w: r.w, h: r.h })),
      convs: new Map([[best.setting, conv]]),
    };
  }));
  status("Packing the PRG", 1);
  const prg = dualPrg(systems.pal.v2i, systems.ntsc.v2i);
  return { prg, name, source, opts: { mc, chroma, box, at, bare, aspect, by }, systems };
}

/**
 * An earlier result with another of its dithers, as `vic2.prg -d` makes it: the dither's
 * indices come from the candidates the earlier run made of the same picture with the same
 * options, so only the converter runs (and not at all for a dither converted before). The
 * figures stay. Options: run, status, date as makePrg's.
 */
export async function withDither(prev, setting, { run, status = () => {}, date = new Date() } = {}) {
  const { mc, chroma, box, at, bare, aspect, by } = prev.opts;
  const progress = { pal: 0, ntsc: 0 };
  const report = () => status(`Converting with ${setting}`, (progress.pal + progress.ntsc) / 2);
  const systems = {};
  report();
  await Promise.all(SYSTEMS.map(async (system) => {
    const p = prev.systems[system];
    const o = p.candidates.find((c) => c.setting === setting);
    if (!o) throw new Error(`${setting}: not one of the dithers tried`);
    let conv = p.convs.get(setting);
    if (!conv) {
      conv = await run("convert", { system, idx: o.idx, w: o.w, h: o.h, mc, at }, (f) => { progress[system] = f; report(); });
      p.convs.set(setting, conv);
    }
    progress[system] = 1;
    report();
    const settings = img2c64.settings(prev.source.replace(/^.*[\\/]/, ""), aspected(system, aspect), img2c64.parseDither(o.dither),
      { box, chroma, runs: o.runs, picked: null, mc, by });
    const v2i = pack(conv, { settings, thumb: p.thumb, imageName: imageName(prev.name, system, aspect), date, bare });
    systems[system] = Object.assign({}, p, {
      v2i, rendered: conv.rendered, w: conv.w, h: conv.h, at: conv.at, wrong: conv.wrong, setting, settings,
      samePlace: samePlace(conv.w, conv.h, mc, at), screen: undefined,
    });
  }));
  status("Packing the PRG", 1);
  return Object.assign({}, prev, { prg: dualPrg(systems.pal.v2i, systems.ntsc.v2i), systems });
}
