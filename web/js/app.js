// The page: a dropped picture through pipeline.js in a pool of web workers, the result
// shown as the C64 shows it, the PRG to download.

import { fromRGBA } from "./imaging.js";
import { Pool } from "./pool.js";
import { makePrg } from "./pipeline.js";
import { VIEW, PAR } from "./img2c64.js";

const $ = (id) => document.getElementById(id);
const MAX_PIXELS = 16_000_000;      // larger photos are scaled down first (canvas limits)

let pool = null, busy = false, last = null, file = null, result = null, shownSystem = "pal";
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
  return fromRGBA(w, h, ctx.getImageData(0, 0, w, h).data);
}

function options() {
  const form = $("options");
  return { mc: form.mode.value === "mc", dither: form.dither.value || null };
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
  const run = Symbol("run");
  last = run;
  $("work").hidden = false;
  $("again").hidden = true;
  setStatus(`Reading ${file.name}`, 0);
  const t0 = performance.now();
  try {
    const img = await decode(file);
    if (!pool) pool = workers();
    const opts = options();
    const r = await makePrg(img, file.name, {
      ...opts,
      run: (type, payload, onProgress) => pool.run(type, payload, onProgress),
      status: (text, f) => { if (last === run) setStatus(text + "…", f); },
    });
    if (last !== run) return;
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

function link(a, bytes, name) {
  const url = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
  urls.push(url);
  a.href = url;
  a.download = name;
}

function show(r) {
  while (urls.length) URL.revokeObjectURL(urls.pop());
  const name = r.name.toLowerCase().replace(/[^a-z0-9._-]+/g, "-") || "picture";
  link($("prg"), r.prg, `${name}.prg`);
  $("prg").textContent = `Download ${name}.prg (${Math.ceil(r.prg.length / 1024)} KB)`;
  link($("v2i-pal"), r.systems.pal.v2i, `${name}-p.v2i`);
  link($("v2i-ntsc"), r.systems.ntsc.v2i, `${name}-n.v2i`);
  $("result").hidden = false;
  draw(shownSystem);
}

/** The screen as the C64 shows it (the picture centred on black), in the screen colours
 * the dithers were chosen for, at the system's pixel aspect. */
function draw(system) {
  shownSystem = system;
  for (const b of document.querySelectorAll(".tabs button")) {
    b.setAttribute("aria-selected", String(b.dataset.system === system));
  }
  if (!result) return;
  const s = result.systems[system];
  const scale = s.mc ? 2 : 1, wpx = s.w * scale;
  const col0 = Math.floor((40 - wpx / 8) / 2), row0 = Math.floor((25 - s.h / 8) / 2);
  const screen = new ImageData(320, 200);
  for (let i = 3; i < screen.data.length; i += 4) screen.data[i] = 255;
  for (let y = 0; y < s.h; y++) {
    for (let x = 0; x < wpx; x++) {
      const c = VIEW[s.rendered[y][Math.floor(x / scale)]];
      const o = ((row0 * 8 + y) * 320 + col0 * 8 + x) * 4;
      screen.data[o] = c[0]; screen.data[o + 1] = c[1]; screen.data[o + 2] = c[2];
    }
  }
  const small = document.createElement("canvas");
  small.width = 320; small.height = 200;
  small.getContext("2d").putImageData(screen, 0, 0);
  const canvas = $("screen"), ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(small, 0, 0, canvas.width, canvas.height);
  canvas.style.aspectRatio = String((320 * PAR[system]) / 200);
  const pct = ((100 * s.wrong) / (s.w * s.h)).toFixed(1);
  $("stats").textContent = `${system.toUpperCase()}: ${s.setting} dither, ${s.w * scale}×${s.h} pixels` +
    `${s.mc ? " (multicolour)" : ""}; ${pct}% of them drawn in a nearby colour.`;
  ranking(s);
}

function ranking(s) {
  const box = $("ranking-box"), table = $("ranking");
  box.hidden = !s.ranked;
  if (!s.ranked) return;
  table.replaceChildren();
  const head = table.createTHead().insertRow();
  for (const [t, num] of [["Dither", false], ["Score", true], ["SSIM", true], ["Colour error", true], ["Nearby colour", true]]) {
    const th = document.createElement("th");
    th.textContent = t;
    if (num) th.className = "num";
    head.append(th);
  }
  const body = table.createTBody();
  for (const r of s.ranked) {
    const row = body.insertRow();
    if (r.setting === s.setting) row.className = "picked";
    const cells = [r.setting, r.score.toFixed(2), r.ssim.toFixed(3), r.color.toFixed(1),
      r.wrong === null ? "" : `${((100 * r.wrong) / r.pixels).toFixed(1)}%`];
    cells.forEach((v, i) => {
      const td = row.insertCell();
      td.textContent = v;
      if (i) td.className = "num";
    });
  }
}

function pickFile(f) {
  if (!f) return;
  file = f;
  convert();
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
  const hybrid = form.dither.querySelector("[data-hires]");
  form.addEventListener("change", () => {
    hybrid.disabled = form.mode.value === "mc";
    if (hybrid.disabled && form.dither.value === "hybrid") form.dither.value = "";
    $("again").hidden = !file || busy;
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); convert(); });
  for (const b of document.querySelectorAll(".tabs button")) {
    b.addEventListener("click", () => draw(b.dataset.system));
  }
}

init();
