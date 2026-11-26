# vic2orious in the browser

A static page that does what `python3 -m vic2.prg PICTURE` does, in the visitor's
browser: picks a dither per system, converts the picture for PAL and NTSC, packs both
`.v2i` and builds the dual PRG. Nothing is uploaded and there is no server code, so any
static host serves it (Cloudflare Pages or Workers static assets, GitHub Pages).

    python3 -m http.server -d web 8000      # then open http://localhost:8000

ES modules and module workers need the page served over HTTP, not opened as a file.

## Files

- `index.html`, `style.css`, `js/app.js`: the page.
- `js/pipeline.js`: vic2.prg's flow; `js/jobs.js`: its steps as plain functions;
  `js/pool.js`, `js/worker.js`: web workers that run them (one fewer than the CPU's
  cores, at most 8).
- Ports of the Python, kept to the same arithmetic, ties and orders so the results are
  the same bytes:
  - `js/timing.js`, `js/convert.js`: `vic2/timing.py`, `vic2/convert.py`
  - `js/imaging.js`: the parts of Pillow 12.3 that img2c64 uses (LANCZOS and BOX resize,
    quantize with and without Floyd-Steinberg, ImageEnhance.Color, BoxBlur)
  - `js/img2c64.js`, `js/thumb.js`: `tools/img2c64.py`'s preparation, `vic2/thumb.py`
  - `js/pick.js`: `vic2/dither_pick.py` and img2c64's picker
  - `js/v2i.js`: `vic2/build.py`'s `convert_new` (.v2i version 6)
  - `js/prg.js` with `js/prg-template.js`: the dual v2i demo with two images after it
- `js/version.js` is `vic2.VERSION`; bump it with the Python's.

`js/prg-template.js` is generated from `asm/v2i-demo.s`; after changing the demo or
`asm/v2i.inc`, run (needs cc65 and the C64 character ROM, VICE_DATA):

    python3 web/tools/prg_template.py

## Checks against the Python

Each writes the Python's results as JSON (or a PRG) and the `.mjs` compares the
JavaScript's with them:

    python3 web/test/golden.py pal input/dragon.png ref.json && node web/test/golden.mjs ref.json
    python3 web/test/prep_golden.py photo.jpg prep.json [-m] && node web/test/prep_golden.mjs prep.json
    python3 web/test/pick_golden.py photo.jpg pick.json [-m] && node web/test/pick_golden.mjs pick.json
    python3 web/test/v2i_golden.py pal pic-p.png v.json && node web/test/v2i_golden.mjs v.json
    python3 -m vic2.prg -o ref.prg photo.jpg && node web/test/prg_e2e.mjs prep.json ref.prg photo.jpg
        [-m] [-d DITHER] [-c S] [-w R,S,C] [-s WxH]   # as given to vic2.prg (-d hybrid,l=6 for -d hybrid -l 6)

The last runs the page's pipeline in worker threads and compares the whole PRG (apart
from the conversion dates in the metadata). The picker's scores match to about the last
digit: numpy's sums are followed, but its matrix products and exp, pow and cbrt can differ
in the last bits, so a near tie between two dithers could in principle go the other way.

## Differences from vic2.prg

- The metadata says "quantized by: vic2orious web@VERSION" instead of img2c64.
- A chosen hybrid dither has the line budget of 8 that img2c64's help gives as the
  default (`img2c64 -d hybrid` without `-l` currently runs with none).
- The browser decodes the picture: EXIF orientation and colour profiles are applied as
  the browser does; photos over 16 megapixels are scaled down by the browser first.
- Options not offered: palette (`-P`, always tools/tv.vpl). Under Advanced settings,
  Colour matching is chroma (`-c`, 0.5 to 1.5) and Largest size is `-s WxH`; weights
  (`-w`) are under Compare the dithers, which shows every dither tried (dithered or the
  estimate) with its scores, ranked again as the weights change.
- Screen position (Advanced settings) places the picture as `vic2.build --at COLUMN,ROW`
  does, which vic2.prg has no option for; a position that would run off the screen moves
  in until the picture fits (the build would stop instead). `web/test/prg_e2e.mjs --at`
  checks it against `web/test/prg_at.py COLUMN,ROW`, vic2.prg with its conversions
  placed that way.
- "Leave out the thumbnail and metadata" writes .v2i files with flags bits 0 and 2 clear
  (docs/v2i-format.md), which the players and v2i.inc read; the build always writes both.
- "Use this" under Compare the dithers converts that dither for both systems as `vic2.prg -d` does (from the candidates already made); `hybrid,l=6` and
  `hybrid,l=none` there are `-d hybrid -l 6` and `-d hybrid -l none`.
