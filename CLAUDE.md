# vic2orious

Converts C64-palette PNGs into C64 hires bitmap + per-line multiplexed hires sprites, aiming
for pixel-perfect output, and plays the results on a real (emulated) C64: a slideshow PRG
with the images embedded, a disk slideshow (`diskshow`) that loads every image in turn, a
viewer PRG that loads `.v2i` image files (plus optional `.txt` narrative files drawn
beside the picture) from disk by name, and an interactive `ask` demo.
The C64 side is two independent libraries, `asm/v2i.inc` (images) and `asm/v2t.inc`
(text), that other programs can include. Apache-2.0 licensed (`LICENSE`).

## Layout

- `vic2/convert.py`: the converter. Picks two bitmap colours per 8x8 cell (local search
  per character row, single and neighbour-pair moves, run for each of `ROW_WEIGHTS`; the
  candidate that really schedules with the fewest wrong pixels wins), then for every raster
  line covers the remaining pixels with at most 8 single-colour 24-pixel "spans" (`cover`:
  exact max-pixels DP, memoised) and assigns them to the 8 sprites (DP over sprite subsets,
  minimising register writes). `Geometry` holds size and screen placement.
- `vic2/timing.py`: cycle model of the PAL VIC-II bus stealing (badlines, sprite DMA, the 3
  write cycles allowed after BA goes low), the kernel code generator (prologue, sync phase)
  and the EDF write scheduler with per-line checkpoints.
- `vic2/build.py`: CLI. Converts images, writes `.v2i`/`.txt` files, generates
  `build/images.inc`, `build/diskshow.inc`, `build/ask.inc` and `build/font.inc`,
  assembles with cl65, makes the D64 (or D81), and optionally verifies in VICE. The file
  formats are documented in its docstring.
- `vic2/screen.py`: Python model of the screen as the library's text/clear routines leave
  it (used by `--verify`). `vic2/ask.py`: `.ask` parsing, layout and model for the demo.
- `vic2/font.py`: proportional font derived from the ROM lower/upper case set, plus the
  pixel-width word wrap.
- `vic2/palette.py`: Pepto palette, nearest-colour loading.
- `asm/v2i.inc`: image library (`v2i_*`: machine takeover and exit, raster IRQ,
  unpacking into VIC bank 3, frame). `asm/v2t.inc`: text library (`v2t_*`: .v2t files,
  single lines, measure, clear; bitmap/screen addresses configurable, no VIC setup).
  Each stands alone (own zero page block, own row address helper, prefixed names).
  `asm/slideshow.s`, `asm/diskshow.s`, `asm/viewer.s` and `asm/ask.s` use both;
  `asm/v2i-demo.s` and
  `asm/v2t-demo.s` (KERNAL on, bitmap in bank 1) use one each.
- `docs/`: `v2i-format.md`, `v2t-format.md` (incl. the font), `v2i-lib.md`, `v2t-lib.md`.
  Keep them in sync with the code.
- `tools/png2c64.py`: the user's quick quantiser (picture -> Pepto palette). `-o FILE` or
  `-o DIR/` (keeps input names, takes several files / glob patterns), `-d
  floydsteinberg|none` (default floydsteinberg). Refuses to overwrite its input. Its old
  `-b` frame option was removed: framed pixels did not always convert exactly; frames come
  from `v2i_frame` (`build -b`).
- `input/`: images (`name.png`), optional stories (`name.txt`) and optional demo questions
  (`name.ask`, builds `build/ask-name.prg`). `images/` holds older test images (local only, gitignored). `build/` is
  generated and gitignored.

## How it works (the parts that are easy to break)

- Image sits at the upper left by default (char row 0, column 0, so image line 0 is raster
  $33 and sprite X = 24 + column); `build --at C,R` places it elsewhere (`Geometry`). The
  position is baked into the kernel: moving by whole chars changes the schedule (pixel
  windows shift by a cycle per char while DMA stalls stay put; sprite blocks are at
  absolute raster lines, 21 apart). Sizes are multiples of 8, width <= 256, height <= 200.
  The X high bit ($d010) is never used, so span starts are limited to X <= 255 and the
  image must start at column <= 28.
- Frame (`build -b`, for all images of a build): images move to char row 1, column 1
  (raster $3b, X = 32 + column; or to `--at`) and the programs are assembled with
  `FRAME=1`, so they call `v2i_frame`, which draws a 4 px frame
  (white/white/black/white) into the ring of cells around the image if it fits on
  screen. The `.v2i` format does not know about it. Images without room for the ring are
  not framed. `--verify` compares the frame too.
- Each image gets its own unrolled, cycle-exact kernel, run from a raster IRQ at line 2.
  It is position independent (only touches zp `$02`, VIC registers, pointers at `$c3f8`).
  Host programs run in the rest of the frame (below the image); the library's text
  routines are safe to call then.
- Sync: the kernel does not need a stable raster. `Kernel.sync()` tracks a set of possible
  entry times ("hypotheses") and emits RMW/store instructions that land on the start of BA
  low periods until all hypotheses merge. Keep the IRQ prologue in `v2i.inc`
  (`sta/stx/sty zp`, `jsr v2i_kjump`, `jmp (v2i_kvec)`) as is; the entry window assumed in
  `convert.py` (`T(2, 20..47)`) depends on it. It covers any interrupted instruction
  (the `ask` verify build draws text continuously and still matches).
- All 8 sprites run continuously in 21-line blocks with staggered phases (`SPR_START`), so
  every kernel line has the same sprite DMA. Pointer writes must land on the line before a
  block; on a badline that leaves one possible write cycle (cycle 12), which is why
  `Scheduler._tighten` shrinks windows to cycles a store can really hit and why
  `ok_after`/`_can_meet` guard every emitted instruction.
- Y restart tasks are added 21 lines early (`fixed[B - 21]`) so EDF fills idle time with
  them; adding them at their deadline caused failures on 200-line images.
- At the end of the image a timed `$d015 = 0` stops sprites before any new block starts
  without its pointer (otherwise old sprite data repeats below the image).
- Pixel timing: sprite X coordinate x is drawn in cycle `PIX_C0 + x // 8` (13), with
  `MARGIN = 1` cycle on each side of every edge. Validated against VICE; changing either
  needs a `--verify` run.
- Lines that cannot be done exactly are not skipped: with more than 8 spans needed the
  cover keeps the most pixels; when the writes do not fit, `fit_line` searches best-first
  (up to `FIT_TRIES` schedules) for the set of dropped spans losing the fewest pixels.
  `recover` then lets sprites paint leftover pixels they already reach without writes.
  Remaining pixels fall back to the nearer of the cell's two colours.
- Text: the build word-wraps by pixel width and ships finished lines; the C64 only draws
  glyphs (shift + OR into the bitmap) and colours each row's cells. The C64 does not wrap.
  Lines are 8 + leading pixels apart (`build --leading`, default 2, stored in the `.txt`
  header), so a line can straddle two char rows: glyph rows past the cell go through `pp2`
  (= `pp` + 312), and both rows get the line's colour (the later line wins a shared row).

## Working in the repo

- Build everything from `input/`: `make` (or `python3 -m vic2.build`; add `--verify` to
  compare each screen with VICE, `--run` to launch the slideshow; specific files can be
  passed as arguments). The Makefile wraps it: `make verify`,
  `make run[-diskshow|-viewer|-ask|-d64]`, options `IMAGES FRAME AT LEADING AUTO HOLD
  DISK IMAGE ASK` (`make help`). macOS make is 3.81, so the Makefile uses a stamp file
  (`build/.built`, plus `build/.opts`/`.copts` for the options) instead of grouped targets.
- Conversion cache: `build/<name>.json` holds the converter result (stats, geometry, path
  of `_expected.png`) and a key hashing the png, its `.txt`, frame/at/leading,
  `CACHE_VERSION` and `CACHE_SOURCES` (convert, timing, palette, font). Builds reuse it;
  `--force` reconverts. build.py itself is not hashed: bump `CACHE_VERSION` when changing
  how `.v2i`/`.txt` are packed. The Makefile converts each image in its own
  `--convert-only` run (target `build/<name>.json`, so `make -j` parallelises), then runs
  the full build, which finds everything cached.
- After touching `timing.py`, `convert.py`, `v2i.inc` or `v2t.inc`, run `--verify`: every check
  must report `0 differing pixels` (VICE output vs the model). The converter itself reports
  bad lines / wrong pixels vs the source; those are expected to be non-zero.
- `--verify` builds one single-image slideshow per image, with its text, and compares the
  whole screen with a model (`expected_screen`: converter output + `Screen` text model).
  For each `.ask` it builds `ask.s` with `AUTO=n` (picks the last topic, then keeps
  drawing a black-on-black line) and compares with `Ask.model`; the v2i demo against the
  first image and the v2t demo against `v2t_demo_screen`. If text rendering
  changes, change `vic2/screen.py` to match.
- Keys in the demo and space in the viewer are read from the CIA matrix, so VICE
  `-keybuf` cannot press them (it only feeds the KERNAL buffer).
- Requires Python 3 with Pillow, cc65 (`cl65`), VICE (`x64sc`, `c1541`). The VICE palette
  and character ROM paths are hardcoded for Homebrew (`/opt/homebrew/share/vice/C64/`).
- VICE notes: screenshots are not exactly Pepto even with `-VICIIpalette pepto-pal.vpl`, so
  `compare_screenshot` maps colours by majority vote. Disk loading works with true drive
  emulation (the default; a 12-16K image takes ~25M cycles, the viewer test with autostart
  ~90M) or, near instantly, with `+drive8truedrive -trapdevice8` (VICE traps the KERNAL's
  serial calls; `+drive8truedrive` alone loads nothing, and `-virtualdev8` does not exist
  in this VICE). The Makefile's `FAST=1` adds both; checked with diskshow on the D81, 0
  differing pixels. `--verify` still uses true drive emulation. A PRG that is not on the
  attached disk needs `-autostartprgmode 1` (otherwise VICE looks for it on the disk).
  The viewer test pattern: `-8 build/vic2orious.d64 -autostart build/viewer.prg -keybuf
  'princess\n'`.
- Memory: the slideshow PRG must fit `$0801-$bfff` (about 46K); each image is 9-15K, so
  3-4 images. With more, `assemble_slideshow` keeps the longest prefix that assembles;
  `diskshow` gets all of them (names baked in from `build/diskshow.inc`, loaded like the
  viewer, text screen shown while loading; `HOLD` seconds per image, 16-bit frame count,
  0 holds an image until space, used by its `--verify` check, which boots it with a one-image D64). The disk is a D64 if
  everything fits (664 blocks, 144 entries; about 13 images), else a D81 (3160 blocks;
  VICE needs `-drive8type 1581`, which the Makefile adds). VIC bank 3 (`$c000-$ffff`) holds the image on screen and is not available.
  The viewer must end below `$1800` (asserted): text files load there, images at `$2000`.
  (It used to load text at `$1000` and overwrote the end of its own font.)
- Disk names: images keep their name (cut to 16 chars, `-c64` dropped); text files are the
  first 12 chars + `.txt`.

## What has been tried

- First version stopped at the first line that could not be reproduced and blacked out the
  rest (ECM+BMM invalid mode). Replaced by doing every line and dropping spans; the ECM
  write was later removed so text can sit below shorter images.
- Images were first centred on screen, now always upper left.
- Searching sprite phases so no pointer write falls on a badline: only phases 10, 31, 52
  (all the same mod 21) qualify, so 8 distinct phases are impossible; handled by the
  scheduler instead.
- `MARGIN = 0` has not been tried. The cover still ignores where sprites already are.
- Per-line search (Oct 2026, princess 404 -> 261 wrong pixels, castle 649 -> 485, gaoler
  413 -> 299): exact cover, pair moves, best-first drops, recover, per-row candidates.
  Results are chaotic: tie-break order alone moved castle by 200 pixels, so judge changes
  on all images. Did not help: banning span -> sprite assignments in `fit_line` (fits the
  line but leaves worse sprite state; worse overall), larger `FIT_TRIES` (100 no better than
  24), random restarts in the cell search (too slow for little gain).
- Text: fixed 8x8 ROM glyphs first, then the proportional ROM font (about 20% more text per
  line; letters average 6.8 px because of the 2 px strokes).

## Ideas not done yet

- Store the kernel as a compact write list and generate code on load (kernel is about half
  of each image; would fit roughly 6 images per PRG).
- Fastloader / IRQ-safe loader for the viewer and diskshow (the KERNAL load is slow and
  cannot run while a kernel is displaying; with one, diskshow could load the next image
  while showing the current one).
- C64-side word wrap for plain text files; custom fonts from a PNG.
