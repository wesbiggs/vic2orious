// The page: a dropped picture through pipeline.js in a pool of web workers, the result
// shown as the C64 shows it (with the original on a curtain over it), the PRG to
// download, and every dither tried with its figures.

import { fromRGBA } from "./imaging.js";
import { Pool } from "./pool.js";
import { makePrg, withDither } from "./pipeline.js";
import { VIEW, PAR } from "./img2c64.js";
import { rank, WEIGHTS } from "./pick.js";

const $ = (id) => document.getElementById(id);
const MAX_PIXELS = 16_000_000;      // larger photos are scaled down first (canvas limits)

let pool = null, busy = false, last = null, file = null, result = null, shownSystem = "pal";
let original = null;                // the picture last decoded (a canvas)
let split = 0;                      // how much of the screen, from the left, the curtain covers
let everyView = "quantised";        // what the cards show: quantised, estimate or original
let using = null;                   // {setting, fraction}: a dither being converted by Use this
const urls = [];

function workers() {
  const n = Math.max(1, Math.min(8, (navigator.hardwareConcurrency || 4) - 1));
  return new Pool(n, () => new Worker(new URL("./worker.js", import.meta.url), { type: "module" }));
}

async function decode(f) {
  let src;
  try {
    src = await createImageBitmap(f, { imageOrientation: "from-image" });
  } catch {
    const url = URL.createObjectURL(f);
    try {
      src = new Image();
      src.src = url;
      await src.decode();
    } catch {
      throw new Error(`${f.name}: this browser cannot read that picture`);
    } finally {
      URL.revokeObjectURL(url);
    }
  }
  let w = src.width, h = src.height;
  if (w * h > MAX_PIXELS) {
    const s = Math.sqrt(MAX_PIXELS / (w * h));
    w = Math.max(1, Math.floor(w * s));
    h = Math.max(1, Math.floor(h * s));
  }
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(src, 0, 0, w, h);
  original = c;
  showPicked(f, c, src.width, src.height);
  return fromRGBA(w, h, ctx.getImageData(0, 0, w, h).data);
}

/** The chosen picture in the drop box: a thumbnail, its name and size. */
function showPicked(f, c, w, h) {
  const t = $("thumb"), s = Math.min(1, 160 / c.width, 120 / c.height);
  t.width = Math.max(1, Math.round(c.width * s));
  t.height = Math.max(1, Math.round(c.height * s));
  const ctx = t.getContext("2d");
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(c, 0, 0, t.width, t.height);
  $("picked-name").textContent = f.name;
  $("picked-size").textContent = `${w}×${h} pixels`;
  $("picked").hidden = false;
  $("drop-main").textContent = "Drop another picture, or choose one";
}

/** The weights the page picks with (img2c64 -w): three numbers >= 0, not all 0. */
function weights() {
  const w = ["w0", "w1", "w2"].map((n) => {
    const v = +document.querySelector(`#weights [name=${n}]`).value;
    return Number.isFinite(v) && v > 0 ? v : 0;
  });
  return w[0] + w[1] + w[2] > 0 ? w : WEIGHTS.slice();
}

function options() {
  const form = $("options");
  return { mc: form.mode.value === "mc", dither: form.dither.value || null, chroma: +form.chroma.value,
    weights: weights() };
}

function setStatus(text, fraction, error = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", error);
  if (fraction !== undefined) $("progress").value = fraction;
  $("progress").hidden = error;
}

async function convert() {
  if (!file) return;
  if (busy) {                     // a new picture or new options: stop the old run
    pool.terminate();
    pool = null;
  }
  busy = true;
  using = null;
  const run = Symbol("run");
  last = run;
  setEveryStatus("");
  if (result) every();
  $("work").hidden = false;
  $("again").hidden = true;
  setStatus(`Reading ${file.name}`, 0);
  const t0 = performance.now();
  try {
    const img = await decode(file);
    const shownOriginal = original;
    if (!pool) pool = workers();
    const opts = options();
    const r = await makePrg(img, file.name, {
      ...opts,
      run: (type, payload, onProgress) => pool.run(type, payload, onProgress),
      status: (text, f) => { if (last === run) setStatus(text + "…", f); },
    });
    if (last !== run) return;
    busy = false;                   // before show(), which draws the Use this buttons
    r.original = shownOriginal;
    result = r;
    const secs = Math.round((performance.now() - t0) / 1000);
    setStatus(`Done in ${secs} s.`, 1);
    show(r);
  } catch (e) {
    if (last !== run) return;
    console.error(e);
    setStatus(`Could not convert ${file.name}: ${e.message}`, undefined, true);
  } finally {
    if (last === run) busy = false;
  }
}

const fileName = (name) => name.toLowerCase().replace(/[^a-z0-9._-]+/g, "-") || "picture";

function link(a, bytes, name) {
  const url = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
  urls.push(url);
  a.href = url;
  a.download = name;
}

function show(r, keepSplit = false) {
  while (urls.length) URL.revokeObjectURL(urls.pop());
  const name = fileName(r.name);
  link($("prg"), r.prg, `${name}.prg`);
  $("prg").textContent = `Download ${name}.prg (${Math.ceil(r.prg.length / 1024)} KB)`;
  link($("v2i-pal"), r.systems.pal.v2i, `${name}-p.v2i`);
  link($("v2i-ntsc"), r.systems.ntsc.v2i, `${name}-n.v2i`);
  $("result").hidden = false;
  if (!keepSplit) split = 0;
  draw(shownSystem);
}

/** Where the picture sits on the 320x200 screen (centred, as the .v2i puts it). */
function placement(s) {
  const scale = s.mc ? 2 : 1, wpx = s.w * scale;
  return { scale, wpx, x: Math.floor((40 - wpx / 8) / 2) * 8, y: Math.floor((25 - s.h / 8) / 2) * 8 };
}

/** Palette indices (rows of them, or flat, w wide) as a canvas in the screen colours the
 * dithers were chosen for, each index scale pixels wide. */
function pixels(rows, w, h, scale) {
  const nested = typeof rows[0] === "object";
  const img = new ImageData(w * scale, h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w * scale; x++) {
      const xi = Math.floor(x / scale);
      const c = VIEW[nested ? rows[y][xi] : rows[y * w + xi]];
      const o = (y * w * scale + x) * 4;
      img.data[o] = c[0]; img.data[o + 1] = c[1]; img.data[o + 2] = c[2]; img.data[o + 3] = 255;
    }
  }
  const c = document.createElement("canvas");
  c.width = w * scale; c.height = h;
  c.getContext("2d").putImageData(img, 0, 0);
  return c;
}

/** The 320x200 screen as the C64 shows it: the picture centred on black. */
function screenCanvas(s) {
  const { scale, x, y } = placement(s);
  const c = document.createElement("canvas");
  c.width = 320; c.height = 200;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, 320, 200);
  ctx.drawImage(pixels(s.rendered, s.w, s.h, scale), x, y);
  return c;
}

/** One system's result, at the system's pixel aspect. */
function draw(system) {
  shownSystem = system;
  for (const b of document.querySelectorAll(".tabs button")) {
    b.setAttribute("aria-selected", String(b.dataset.system === system));
  }
  if (!result) return;
  const s = result.systems[system];
  s.screen ||= screenCanvas(s);
  $("frame").style.setProperty("--ar", String((320 * PAR[system]) / 200));
  setSplit(split);
  const { wpx } = placement(s);
  const pct = ((100 * s.wrong) / (s.w * s.h)).toFixed(1);
  $("stats").textContent = `${system.toUpperCase()}: ${s.setting} dither, ${wpx}×${s.h} pixels` +
    `${s.mc ? " (multicolour)" : ""}; ${pct}% of them drawn in a nearby colour.`;
  every();
}

/** The screen, with the original picture over it from the left edge to the curtain. */
function paint(s) {
  if (!s.screen) return;
  const canvas = $("screen"), ctx = canvas.getContext("2d");
  const k = canvas.width / 320;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(s.screen, 0, 0, canvas.width, canvas.height);
  if (split <= 0 || !result.original) return;
  const { wpx, x, y } = placement(s);
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 0, split * canvas.width, canvas.height);
  ctx.clip();
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(result.original, x * k, y * k, wpx * k, s.h * k);
  ctx.restore();
}

function setSplit(v) {
  split = Math.max(0, Math.min(1, v));
  $("frame").style.setProperty("--split", String(split));
  $("curtain").setAttribute("aria-valuenow", String(Math.round(split * 100)));
  if (result) paint(result.systems[shownSystem]);
}

/** The shown system's screen as a PNG, twice the C64's size at its pixel aspect. */
function savePng() {
  if (!result) return;
  const s = result.systems[shownSystem];
  const c = document.createElement("canvas");
  c.width = Math.round(640 * PAR[shownSystem]); c.height = 400;
  const ctx = c.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(s.screen, 0, 0, c.width, c.height);
  c.toBlob((blob) => {
    const a = document.createElement("a");
    const url = URL.createObjectURL(blob);
    a.href = url;
    a.download = `${fileName(result.name)}-${shownSystem}.png`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, "image/png");
}

/** Another of the dithers tried, converted for PAL and NTSC, to show and download. */
async function useDither(setting) {
  if (!result || busy) return;
  busy = true;
  const run = Symbol("run");
  last = run;
  using = { setting, fraction: 0 };
  const t0 = performance.now();
  setEveryStatus(`Converting with ${setting} for PAL and NTSC…`);
  every();
  try {
    if (!pool) pool = workers();
    const r = await withDither(result, setting, {
      run: (type, payload, onProgress) => pool.run(type, payload, onProgress),
      status: (text, f) => { if (last === run && using) { using.fraction = f; cardProgress(); } },
    });
    if (last !== run) return;
    busy = false;
    using = null;
    result = r;
    show(r, true);
    const secs = Math.round((performance.now() - t0) / 1000);
    setStatus(`Converted with ${setting} in ${secs} s.`, 1);
    setEveryStatus(`Now showing ${setting} above; the downloads are this one.`, true);
  } catch (e) {
    if (last !== run) return;
    console.error(e);
    busy = false;
    using = null;
    every();
    setEveryStatus(`Could not convert with ${setting}: ${e.message}`);
  }
}

function setEveryStatus(text, seeIt = false) {
  const p = $("every-status");
  p.replaceChildren(text);
  if (seeIt) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = "See it";
    b.addEventListener("click", () => $("result").scrollIntoView({ behavior: "smooth", block: "start" }));
    p.append(b);
  }
}

/** The progress of Use this on its card, without drawing the cards again. */
function cardProgress() {
  const bar = document.querySelector(`#grid .card[data-setting="${CSS.escape(using.setting)}"] progress`);
  if (bar) bar.value = using.fraction;
}

// ------------------------------------------------------------- every dither, with figures

const copy = (rs) => rs.map((r) => Object.assign({}, r));
const fix = (v, n) => (v === null || v === undefined ? "–" : v.toFixed(n));
const share = (r) => (r.wrong === null || r.wrong === undefined ? "–" : `${((100 * r.wrong) / r.pixels).toFixed(1)}%`);

/** The figures ranked with the page's weights: every dither by the estimate, and the
 * converted ones as the picker ranks them (scaled over all, as img2c64 does). */
function ranked(s) {
  const w = weights();
  const all = rank(copy(s.candidates), w);
  let converted = null;
  if (s.ranked && !s.mc) {
    const done = new Set(s.ranked.map((r) => r.setting));
    const extra = copy(all.filter((r) => !done.has(r.setting))).map((r) => Object.assign(r, { estimate: true }));
    converted = rank(copy(s.ranked).concat(extra), w).filter((r) => !r.estimate);
  }
  return { all, converted, done: new Set((s.ranked || []).map((r) => r.setting)) };
}

function useButton(setting, s) {
  if (setting === s.setting) return null;
  const ready = SYSTEM_NAMES.every((y) => result.systems[y].convs.has(setting));
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = ready ? "Show this" : "Use this";
  b.disabled = busy;
  b.title = ready ? `Show ${setting} again (converted before)` : `Convert with ${setting} for PAL and NTSC and show it`;
  b.addEventListener("click", () => useDither(setting));
  return b;
}
const SYSTEM_NAMES = ["pal", "ntsc"];

function every() {
  const s = result.systems[shownSystem];
  if (s.candidates.length < 2 && !using) {
    setEveryStatus("Only one dither was tried: choose Best of several above to compare them.");
  }
  const { all, converted, done } = ranked(s);
  const table = $("ranking");
  $("converted-head").hidden = table.hidden = !converted;
  table.replaceChildren();
  if (converted) {
    const head = table.createTHead().insertRow();
    for (const [t, num] of [["Dither", false], ["Score", true], ["SSIM", true], ["RMS", true],
      ["Colour", true], ["Nearby colour", true], ["", false]]) {
      const th = document.createElement("th");
      th.textContent = t;
      if (num) th.className = "num";
      head.append(th);
    }
    const body = table.createTBody();
    for (const r of converted) {
      const row = body.insertRow();
      if (r.setting === s.setting) row.className = "picked";
      [r.setting, fix(r.score, 2), fix(r.ssim, 3), fix(r.rms, 2), fix(r.color, 2), share(r)].forEach((v, i) => {
        const td = row.insertCell();
        td.textContent = v;
        if (i) td.className = "num";
      });
      const b = useButton(r.setting, s);
      row.insertCell().append(...(b ? [b] : []));
    }
  }
  $("grid").replaceChildren(...all.map((r) => card(r, s, done.has(r.setting))));
}

function el(tag, cls, ...kids) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  e.append(...kids.filter((k) => k !== null && k !== undefined));
  return e;
}

function card(r, s, wasConverted) {
  const scale = s.mc ? 2 : 1;
  const c = document.createElement("canvas");
  c.width = r.w * scale * 2; c.height = r.h * 2;
  c.style.aspectRatio = String((r.w * scale * PAR[shownSystem]) / r.h);
  const ctx = c.getContext("2d");
  if (everyView === "original" && result.original) {
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(result.original, 0, 0, c.width, c.height);
  } else {
    const rows = everyView === "estimate" && r.shownRows ? r.shownRows : r.idx;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(pixels(rows, r.w, r.h, scale), 0, 0, c.width, c.height);
  }
  const shown = r.setting === s.setting, working = using && using.setting === r.setting;
  const badge = shown ? "showing" : wasConverted && !s.mc ? "converted in full" : null;
  let acts;
  if (working) {
    const bar = document.createElement("progress");
    bar.max = 1;
    bar.value = using.fraction;
    acts = el("div", "acts", el("span", "hint", "Converting…"), bar);
  } else {
    acts = el("div", "acts", useButton(r.setting, s));
  }
  const metric = (name, v, title) => {
    const m = el("span", null, name, el("b", null, v));
    if (title) m.title = title;
    return m;
  };
  const fill = el("div");
  fill.style.width = `${Math.round(100 * r.score)}%`;
  const div = el("div", "card" + (shown ? " shown-card" : "") + (working ? " working" : ""),
    el("div", "pic", c, badge ? el("span", "badge", badge) : null,
      r.setting === s.pick ? el("span", "badge pick", "page's pick") : null),
    el("div", "body",
      el("div", "name", el("span", null, r.setting), el("span", null, `score ${fix(r.score, 2)}`)),
      el("div", "scorebar", fill),
      el("div", "metrics",
        metric("SSIM", fix(r.ssim, 3)),
        metric("colour", fix(r.color, 2)),
        metric("RMS", fix(r.rms, 2)),
        metric("nearby", share(r), "pixels the estimate draws in a nearby colour")),
      acts));
  div.dataset.setting = r.setting;
  return div;
}

// ---------------------------------------------------------------------------- the page

function pickFile(f) {
  if (!f) return;
  file = f;
  convert();
}

function remember(key, value) {
  try { localStorage.setItem(key, value); } catch { /* no storage: it is a convenience */ }
}
function recall(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function init() {
  const drop = $("drop");
  $("file").addEventListener("change", (e) => pickFile(e.target.files[0]));
  for (const ev of ["dragenter", "dragover"]) {
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); });
  }
  for (const ev of ["dragleave", "drop"]) {
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); });
  }
  drop.addEventListener("drop", (e) => pickFile(e.dataTransfer.files[0]));

  const form = $("options");
  form.addEventListener("change", () => {
    for (const o of form.dither.querySelectorAll("[data-hires]")) o.disabled = form.mode.value === "mc";
    if (form.dither.selectedOptions[0]?.disabled) form.dither.value = "";
    $("again").hidden = !file || busy;
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); convert(); });
  form.chroma.addEventListener("input", () => {
    $("chroma-value").textContent = (+form.chroma.value).toFixed(2);
  });

  // the curtain: drag anywhere on the picture, or the handle with the keyboard
  const frame = $("frame");
  const fromPointer = (e) => {
    const b = frame.getBoundingClientRect();
    setSplit((e.clientX - b.left) / b.width);
  };
  frame.addEventListener("pointerdown", (e) => {
    if (!result) return;
    frame.setPointerCapture(e.pointerId);
    fromPointer(e);
    e.preventDefault();
  });
  frame.addEventListener("pointermove", (e) => { if (frame.hasPointerCapture(e.pointerId)) fromPointer(e); });
  $("curtain").addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 0.1 : 0.02;
    const to = { ArrowLeft: split - step, ArrowRight: split + step, Home: 0, End: 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    setSplit(to);
  });
  const stage = $("stage");
  $("full").hidden = !stage.requestFullscreen;
  $("full").addEventListener("click", () => stage.requestFullscreen());
  $("png").addEventListener("click", savePng);
  for (const b of document.querySelectorAll(".tabs button")) {
    b.addEventListener("click", () => draw(b.dataset.system));
  }

  // every dither: what the cards show, the weights; open or shut as last time
  const box = $("every-box");
  box.open = recall("vic2orious.every") === "open";
  box.addEventListener("toggle", () => remember("vic2orious.every", box.open ? "open" : "shut"));
  for (const b of $("every-view").querySelectorAll("button")) {
    b.addEventListener("click", () => {
      everyView = b.dataset.view;
      for (const o of $("every-view").querySelectorAll("button")) o.setAttribute("aria-pressed", String(o === b));
      if (result) every();
    });
  }
  $("weights").addEventListener("input", () => {
    if (result) every();
    $("again").hidden = !file || busy || form.dither.value !== "";
  });
}

init();
