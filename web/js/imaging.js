// The parts of Pillow (13.0) that img2c64 and the thumbnails use, ported so the page and
// the Python tools make the pixels Pillow would: resize (Resample.c, 8 bits per channel),
// RGB -> L and blend (Convert.c, Blend.c: ImageEnhance.Color), quantize to a given palette
// without or with Floyd-Steinberg (Convert.c topalette, Palette.c's colour cache), BoxBlur.
//
// An image is {width, height, data}: data a Uint8ClampedArray or Uint8Array of RGB
// triples, row by row.

export function newImage(width, height) {
  return { width, height, data: new Uint8Array(width * height * 3) };
}

/** From canvas ImageData (RGBA), transparency flattened onto black. */
export function fromRGBA(width, height, rgba) {
  const im = newImage(width, height);
  const d = im.data;
  for (let i = 0, j = 0; i < width * height; i++, j += 4) {
    const a = rgba[j + 3];
    if (a === 255) {
      d[i * 3] = rgba[j]; d[i * 3 + 1] = rgba[j + 1]; d[i * 3 + 2] = rgba[j + 2];
    } else {
      // Image.paste with an alpha mask: (in * a + bg * (255 - a)) / 255, rounded (Paste.c
      // BLEND: tmp = in * a + 128, (tmp + (tmp >> 8)) >> 8), bg black
      for (let k = 0; k < 3; k++) {
        const t = rgba[j + k] * a + 128;
        d[i * 3 + k] = (t + (t >> 8)) >> 8;
      }
    }
  }
  return im;
}

// ---------------------------------------------------------------- resize

const PRECISION_BITS = 32 - 8 - 2;

const FILTERS = {
  box: [(x) => (x > -0.5 && x <= 0.5 ? 1.0 : 0.0), 0.5],
  lanczos: [(x) => (-3.0 <= x && x < 3.0 ? sinc(x) * sinc(x / 3) : 0.0), 3.0],
};

function sinc(x) {
  if (x === 0.0) return 1.0;
  x = x * Math.PI;
  return Math.sin(x) / x;
}

function precomputeCoeffs(inSize, in0, in1, outSize, [filter, fsupport]) {
  let scale = (in1 - in0) / outSize;
  let filterscale = scale < 1.0 ? 1.0 : scale;
  const support = fsupport * filterscale;
  const ksize = Math.ceil(support) * 2 + 1;
  const kk = new Int32Array(outSize * ksize);
  const bounds = new Int32Array(outSize * 2);
  const invFilterscale = 1.0 / filterscale;
  const k = new Float64Array(ksize);
  for (let xx = 0; xx < outSize; xx++) {
    const center = in0 + (xx + 0.5) * scale;
    let ww = 0.0;
    let xmin = Math.trunc(center - support + 0.5);
    if (xmin < 0) xmin = 0;
    let xmax = Math.trunc(center + support + 0.5);
    if (xmax > inSize) xmax = inSize;
    xmax -= xmin;
    k.fill(0);
    for (let x = 0; x < xmax; x++) {
      const w = filter((x + xmin - center + 0.5) * invFilterscale);
      k[x] = w;
      ww += w;
    }
    if (ww !== 0.0) for (let x = 0; x < xmax; x++) k[x] /= ww;
    // normalize_coeffs_8bpc
    for (let x = 0; x < ksize; x++) {
      const v = k[x];
      kk[xx * ksize + x] = v < 0 ? Math.trunc(-0.5 + v * (1 << PRECISION_BITS)) : Math.trunc(0.5 + v * (1 << PRECISION_BITS));
    }
    bounds[xx * 2] = xmin;
    bounds[xx * 2 + 1] = xmax;
  }
  return { ksize, kk, bounds };
}

const clip8 = (ss) => {
  const v = ss >> PRECISION_BITS;
  return v < 0 ? 0 : v > 255 ? 255 : v;
};

function horizontalPass(im, { ksize, kk, bounds }, width, y0, rows) {
  const out = newImage(width, rows);
  const sd = im.data, td = out.data;
  for (let yy = 0; yy < rows; yy++) {
    const row = (yy + y0) * im.width * 3;
    for (let xx = 0; xx < width; xx++) {
      const xmin = bounds[xx * 2], xmax = bounds[xx * 2 + 1];
      const ko = xx * ksize;
      let s0 = 1 << (PRECISION_BITS - 1), s1 = s0, s2 = s0;
      for (let x = 0; x < xmax; x++) {
        const w = kk[ko + x], p = row + (x + xmin) * 3;
        s0 += sd[p] * w; s1 += sd[p + 1] * w; s2 += sd[p + 2] * w;
      }
      const o = (yy * width + xx) * 3;
      td[o] = clip8(s0); td[o + 1] = clip8(s1); td[o + 2] = clip8(s2);
    }
  }
  return out;
}

function verticalPass(im, { ksize, kk, bounds }, height) {
  const out = newImage(im.width, height);
  const sd = im.data, od = out.data, w3 = im.width * 3;
  for (let yy = 0; yy < height; yy++) {
    const ymin = bounds[yy * 2], ymax = bounds[yy * 2 + 1];
    const ko = yy * ksize;
    for (let xx = 0; xx < w3; xx++) {
      let s = 1 << (PRECISION_BITS - 1);
      for (let y = 0; y < ymax; y++) s += sd[(y + ymin) * w3 + xx] * kk[ko + y];
      od[yy * w3 + xx] = clip8(s);
    }
  }
  return out;
}

/** Image.resize(size, filter) for an RGB image; filter "lanczos" or "box". Like Pillow 13,
 * the vertical pass goes first when the height shrinks by more than twice what the width
 * does (the passes round, so the order shows in the result). */
export function resize(im, width, height, filterName = "lanczos") {
  if (width === im.width && height === im.height) {
    return { width, height, data: im.data.slice() };
  }
  const filter = FILTERS[filterName];
  const needH = width !== im.width;
  const needV = height !== im.height;
  const dy = im.height - height, dx = im.width - width;
  const horizontalFirst = !(dy > 0 && dy > dx * 2);
  const vert = needV || horizontalFirst ? precomputeCoeffs(im.height, 0, im.height, height, filter) : null;
  const hor = needH ? precomputeCoeffs(im.width, 0, im.width, width, filter) : null;
  let src = im;
  if (horizontalFirst) {
    if (needH) {
      const yFirst = vert.bounds[0];
      const yLast = vert.bounds[height * 2 - 2] + vert.bounds[height * 2 - 1];
      for (let i = 0; i < height; i++) vert.bounds[i * 2] -= yFirst;
      src = horizontalPass(src, hor, width, yFirst, yLast - yFirst);
    }
    if (needV) src = verticalPass(src, vert, height);
  } else {
    if (needV) src = verticalPass(src, vert, height);
    if (needH) src = horizontalPass(src, hor, width, 0, height);
  }
  return src;
}

/** Nearest neighbour enlargement by whole factors (Image.NEAREST at integer scales). */
export function scaleUp(im, fx, fy) {
  const out = newImage(im.width * fx, im.height * fy);
  for (let y = 0; y < out.height; y++) {
    for (let x = 0; x < out.width; x++) {
      const s = (Math.floor(y / fy) * im.width + Math.floor(x / fx)) * 3, d = (y * out.width + x) * 3;
      out.data[d] = im.data[s]; out.data[d + 1] = im.data[s + 1]; out.data[d + 2] = im.data[s + 2];
    }
  }
  return out;
}

// ---------------------------------------------------------------- colour

/** ImageEnhance.Color(im).enhance(factor): blend with its grey (L) version. */
export function enhanceColor(im, factor) {
  const out = newImage(im.width, im.height);
  const d = im.data, o = out.data;
  for (let i = 0; i < d.length; i += 3) {
    const l = (d[i] * 19595 + d[i + 1] * 38470 + d[i + 2] * 7471 + 0x8000) >> 16;
    for (let k = 0; k < 3; k++) {
      const t = Math.fround(l + Math.fround(factor) * (d[i + k] - l));
      if (factor >= 0 && factor <= 1.0) o[i + k] = Math.trunc(t);
      else o[i + k] = t <= 0.0 ? 0 : t >= 255.0 ? 255 : Math.trunc(t);
    }
  }
  return out;
}

/** Image.quantize(palette=...) with dither NONE (false) or FLOYDSTEINBERG (true): indices
 * (Uint8Array) into pal, a list of [r, g, b], padded to 256 entries of black as
 * img2c64's palette_image does. */
export function quantize(im, pal, dither) {
  const P = new Uint8Array(256 * 3);
  pal.forEach((c, i) => { P[i * 3] = c[0]; P[i * 3 + 1] = c[1]; P[i * 3 + 2] = c[2]; });
  const cache = new Int16Array(64 * 64 * 64).fill(0x100);
  const lookup = (r, g, b) => {
    const at = (r >> 2) + (g >> 2) * 64 + (b >> 2) * 4096;
    if (cache[at] === 0x100) cacheUpdate(P, cache, r, g, b);
    return cache[at];
  };
  const { width: w, height: h, data } = im;
  const out = new Uint8Array(w * h);
  if (!dither) {
    for (let i = 0; i < w * h; i++) out[i] = lookup(data[i * 3], data[i * 3 + 1], data[i * 3 + 2]);
    return out;
  }
  const clip = (v) => (v < 0 ? 0 : v > 255 ? 255 : v);
  const errors = new Int32Array((w + 1) * 3);
  for (let y = 0; y < h; y++) {
    let r = 0, r0 = 0, r1 = 0, r2;
    let g = 0, g0 = 0, g1 = 0, g2;
    let b = 0, b0 = 0, b1 = 0, b2 = 0;
    let e = 0;
    for (let x = 0; x < w; x++) {
      const p = (y * w + x) * 3;
      r = clip(data[p] + Math.trunc((r + errors[e + 3]) / 16));
      g = clip(data[p + 1] + Math.trunc((g + errors[e + 4]) / 16));
      b = clip(data[p + 2] + Math.trunc((b + errors[e + 5]) / 16));
      const c = lookup(r, g, b);
      out[y * w + x] = c;
      r -= P[c * 3]; g -= P[c * 3 + 1]; b -= P[c * 3 + 2];
      let d2;
      r2 = r; d2 = r + r; r += d2; errors[e] = r + r0; r += d2; r0 = r + r1; r1 = r2; r += d2;
      g2 = g; d2 = g + g; g += d2; errors[e + 1] = g + g0; g += d2; g0 = g + g1; g1 = g2; g += d2;
      b2 = b; d2 = b + b; b += d2; errors[e + 2] = b + b0; b += d2; b0 = b + b1; b1 = b2; b += d2;
      e += 3;
    }
    errors[e] = b0; errors[e + 1] = b1; errors[e + 2] = b2;
  }
  return out;
}

function cacheUpdate(P, cache, r, g, b) {
  const r0 = r & 0xe0, r1 = r0 + 0x1f, rc = (r0 + r1) >> 1;
  const g0 = g & 0xe0, g1 = g0 + 0x1f, gc = (g0 + g1) >> 1;
  const b0 = b & 0xe0, b1 = b0 + 0x1f, bc = (b0 + b1) >> 1;
  const D = (a, q) => (a - q) * (a - q);
  const dmin = new Array(256);
  let dmax = Infinity;
  for (let i = 0; i < 256; i++) {
    const pr = P[i * 3], pg = P[i * 3 + 1], pb = P[i * 3 + 2];
    let tmin = pr < r0 ? D(pr, r0) : pr > r1 ? D(pr, r1) : 0;
    let tmax = pr <= rc ? D(pr, r1) : D(pr, r0);
    tmin += pg < g0 ? D(pg, g0) : pg > g1 ? D(pg, g1) : 0;
    tmax += pg <= gc ? D(pg, g1) : D(pg, g0);
    tmin += pb < b0 ? D(pb, b0) : pb > b1 ? D(pb, b1) : 0;
    tmax += pb <= bc ? D(pb, b1) : D(pb, b0);
    dmin[i] = tmin;
    if (tmax < dmax) dmax = tmax;
  }
  const d = new Float64Array(512).fill(Infinity);
  const c = new Uint8Array(512);
  for (let i = 0; i < 256; i++) {
    if (dmin[i] > dmax) continue;
    let ri = r0 - P[i * 3], gi = g0 - P[i * 3 + 1], bi = b0 - P[i * 3 + 2];
    let rd = ri * ri + gi * gi + bi * bi;
    ri = ri * 8 + 16; gi = gi * 8 + 16; bi = bi * 8 + 16;
    let rx = ri, j = 0;
    for (let rr = 0; rr < 8; rr++) {
      let gd = rd, gx = gi;
      for (let gg = 0; gg < 8; gg++) {
        let bd = gd, bx = bi;
        for (let bb = 0; bb < 8; bb++) {
          if (bd < d[j]) { d[j] = bd; c[j] = i; }
          bd += bx; bx += 32; j++;
        }
        gd += gx; gx += 32;
      }
      rd += rx; rx += 32;
    }
  }
  let j = 0;
  for (let rr = r0; rr < r1; rr += 4) {
    for (let gg = g0; gg < g1; gg += 4) {
      for (let bb = b0; bb < b1; bb += 4) cache[(rr >> 2) + (gg >> 2) * 64 + (bb >> 2) * 4096] = c[j++];
    }
  }
}

/** ImageFilter.BoxBlur(1) (BoxBlur.c: one pass each way, edges extended). */
export function boxBlur1(im) {
  // Pillow's box blur with radius 1: each output = sum of 3 inputs (edge pixels repeated)
  // scaled: ww = 1 / (2 * radius + 1) in fixed point; see blur() below for the exact form
  return boxBlur(im, 1);
}

function boxBlur(im, radius) {
  const { width: w, height: h } = im;
  const tmp = new Uint8Array(w * h * 3);
  const out = newImage(w, h);
  // horizontal: lines; then vertical (Pillow transposes and runs the same line blur)
  for (let y = 0; y < h; y++) blurLine(im.data, tmp, y * w * 3, 3, w, radius);
  for (let x = 0; x < w; x++) blurLine(tmp, out.data, x * 3, w * 3, h, radius);
  return out;
}

// BoxBlur.c ImagingLineBoxBlur32 for 8-bit channels with an integer radius: sum of the
// window (edge pixels extended), times ww = 2^24 / (2r + 1), rounded: (acc * ww + 2^23) >> 24
function blurLine(src, dst, off, step, n, radius) {
  const ww = Math.trunc((1 << 24) / (radius * 2 + 1));
  const at = (i) => off + Math.min(Math.max(i, 0), n - 1) * step;
  for (let k = 0; k < 3; k++) {
    for (let i = 0; i < n; i++) {
      let acc = 0;
      for (let j = i - radius; j <= i + radius; j++) acc += src[at(j) + k];
      dst[off + i * step + k] = Math.trunc((acc * ww + (1 << 23)) / (1 << 24));
    }
  }
}
