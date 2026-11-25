// The dual PRG (vic2/prg.py): the v2i demo's code (prg-template.js) with the PAL and the
// NTSC .v2i after it; it shows the one that suits the machine.

import { CODE, NTSC_LO, NTSC_HI } from "./prg-template.js";

const BANK_BASE = 3 * 0x4000;     // the program must end below the VIC bank it shows in

function fromBase64(s) {
  const bin = atob(s), out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** The PRG for two .v2i files (each with its load address, as v2i.convertImage makes
 * them). Throws if they do not fit below the VIC bank. */
export function dualPrg(pal, ntsc) {
  const code = fromBase64(CODE);
  const a = pal.subarray(2), b = ntsc.subarray(2);
  const load = code[0] | (code[1] << 8);
  const end = load + code.length - 2 + a.length + b.length;
  if (end > BANK_BASE) {
    throw new Error(`the PAL and NTSC images (${a.length} + ${b.length} bytes) do not fit in one PRG ($0801-$bfff); try a smaller picture`);
  }
  const prg = new Uint8Array(code.length + a.length + b.length);
  prg.set(code, 0);
  prg.set(a, code.length);
  prg.set(b, code.length + a.length);
  const n = load + code.length - 2 + a.length;
  prg[NTSC_LO] = n & 0xff;
  prg[NTSC_HI] = n >> 8;
  return prg;
}
