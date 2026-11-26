# vic2orious in the browser

A static page that does what `python3 -m vic2.prg PICTURE` does, in the visitor's
browser: picks a dither per system, converts the picture for PAL and NTSC, packs both
`.v2i` and builds the dual PRG. Nothing is uploaded and there is no server code, so any
static host serves it. `.github/workflows/pages.yml` publishes it on GitHub Pages
(index.html, style.css and js/) whenever web/ changes on main; it needs Settings > Pages >
Source set to "GitHub Actions" once.

    python3 -m http.server -d web 8000      # then open http://localhost:8000

ES modules and module workers need the page served over HTTP, not opened as a file.

## Files

- `index.html`, `style.css`, `js/app.js`: the page.
- `js/pipeline.js`: vic2.prg's flow; `js/jobs.js`: its steps as plain functions;
  `js/pool.js`, `js/worker.js`: web workers that run them (one fewer than the CPU's
  cores, at most 8).
- The engine, which the Python tools run too (`vic2/engine.py` starts
  `node tools/engine.mjs`), so the page and `vic2.prg` make the same bytes. Ported from
  the Python, which it replaced, keeping its arithmetic, ties and orders:
  - `js/timing.js`, `js/convert.js`: the bus model, the kernel and the converter
  - `js/imaging.js`: the parts of Pillow 13.0 that img2c64 uses (LANCZOS and BOX resize,
    with Pillow 13's choice of which pass goes first; quantize with and without
    Floyd-Steinberg, ImageEnhance.Color, BoxBlur)
  - `js/img2c64.js`, `js/thumb.js`: img2c64's preparation, thumbnails
  - `js/pick.js`: img2c64's dither picker
  - `js/v2i.js`: the build's `convert_new` (.v2i version 6)
  - `js/prg.js` with `js/prg-template.js`: the dual v2i demo with two images after it
- `js/version.js` is the version (`vic2.VERSION` reads it).

`js/prg-template.js` is generated from `asm/v2i-demo.s`; after changing the demo or
`asm/v2i.inc`, run (needs cc65 and the C64 character ROM, VICE_DATA):

    python3 web/tools/prg_template.py

## Checks

The page and the Python tools run the same engine (these modules; the Python through
`vic2/engine.py` and `tools/engine.mjs`), so the build's `--verify` in VICE checks it. Two
checks remain for what only the page does:

    python3 web/test/prg_golden.py pal.v2i ntsc.v2i ref.prg && node web/test/prg_golden.mjs pal.v2i ntsc.v2i ref.prg
    python3 web/test/picture.py photo.jpg photo.json && python3 -m vic2.prg -o ref.prg photo.jpg &&
        node web/test/prg_e2e.mjs photo.json ref.prg photo.jpg
        [-m] [-d DITHER] [-c S] [-w R,S,C] [-s WxH]   # as given to vic2.prg (-d hybrid,l=6 for -d hybrid -l 6)

The first compares `prg.js`'s dual PRG with the one cc65 assembles from two `.v2i`; the
second runs the page's pipeline in worker threads on the picture as img2c64 loads it and
compares the whole PRG with `vic2.prg`'s (apart from the conversion dates in the metadata).

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
- Aspect None (Advanced settings) is `img2c64 -a none`: the picture's pixels as they
  are (in multicolour one pixel per wide pixel), for pictures made at C64 size. vic2.prg
  has no option for it; `web/test/prg_e2e.mjs --aspect none` checks it against
  `web/test/prg_aspect.py`, vic2.prg running img2c64 with `-a none`, given a `-d`: with
  a picked dither img2c64 makes one PNG for both systems, judged as PAL, where the page
  picks for each system.
- "Leave out the thumbnail and metadata" writes .v2i files with flags bits 0 and 2 clear
  (docs/v2i-format.md), which the players and v2i.inc read; the build always writes both.
- "Use this" under Compare the dithers converts that dither for both systems as `vic2.prg -d` does (from the candidates already made); `hybrid,l=6` and
  `hybrid,l=none` there are `-d hybrid -l 6` and `-d hybrid -l none`.
