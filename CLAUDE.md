# vic2orious

Converts C64-palette PNGs into C64 hires bitmap + per-line multiplexed hires sprites (or a
multicolour bitmap with X-expanded sprites), aiming for pixel-perfect output, and plays the results on a real (emulated) C64: a slideshow PRG
with the images embedded, a disk slideshow (`diskshow`) that loads every image in turn, a
viewer PRG that loads `.v2i` image files (plus optional `.txt` narrative files drawn
beside the picture) from disk by name, a thumbnail browser (`thumbs`: reads only the
start of each `.v2i`, where thumbnail and metadata are), an interactive `ask` demo, and two smooth
scrolling text demos (a prepared page; a stream the C64 wraps itself).
The C64 side is two independent libraries, `asm/v2i.inc` (images) and `asm/v2t.inc`
(text), that other programs can include. Apache-2.0 licensed (`LICENSE`).

## Layout

- `vic2/convert.py`: the converter. Picks two bitmap colours per 8x8 cell (local search
  per character row, single and neighbour-pair moves, run for each of `ROW_WEIGHTS`; the
  candidate that really schedules with the fewest wrong pixels wins), then for every raster
  line covers the remaining pixels with at most 8 single-colour 24-pixel "spans" (`cover`:
  exact max-pixels DP, memoised) and assigns them to the 8 sprites (DP over sprite subsets,
  minimising register writes). `Geometry` holds size and screen placement. Multicolour
  (`mc=True`, img2c64 `-m` PNGs): see How it works.
- `vic2/timing.py`: cycle model of the VIC-II bus stealing (badlines, sprite DMA, the 3
  write cycles allowed after BA goes low), the kernel code generator (prologue, sync phase)
  and the EDF write scheduler with per-line checkpoints. `set_standard("pal"|"ntsc")`
  switches module globals (`CYCLES`, `LINES`, `SPR_P`, `Y_AFTER`, `FPS`) for the whole
  process; `build --ntsc` calls it before converting.
- `vic2/build.py`: CLI. Converts images, writes `.v2i`/`.txt` files, generates
  `images.inc`, `diskshow.inc`, `ask.inc` and `font.inc`, assembles with cl65, makes the
  D64 (or D81), and optionally verifies in VICE, all in one build directory per video
  system: `build/pal/`, `build/ntsc/` (`build/dual/` for the dual disk). The file formats
  are documented in its docstring.
- `vic2/prg.py`: one picture -> `<name>.prg` (cwd, or `-o`) for PAL and NTSC: runs
  img2c64 (`-d`, `-w`, `-c`, `-P`, `-s`, `-l`, `-m` passed on, else its defaults: it picks the dither) into `build/prg/<name>-p/-n.png`, converts each (centred) into
  `build/prg/pal|ntsc/` (sets `build.BUILD` itself, cached as in the build) and assembles
  `v2i-demo.s` with `DUAL=1`. `--verify` checks both in VICE, `--run [pal|ntsc]`;
  `make prg PIC=path [DITHER=mode] [CHROMA=S] [PALETTE=F.vpl] [SIZE=WxH] [LINES=N|none] [MC=1]`
  (`-m`, multicolour: PAL and NTSC of a 160x200 photo fit one PRG, ~37K).
- `vic2/dither_pick.py`: the dither recommender's metrics (blurred RMS, SSIM of the
  luma, a*b* colour error), `rank`, `CANDIDATES`, `shown` (through the converter) and
  `estimate` (img2c64 `-t`: top-2 colours per cell, one exact cover per line as if every
  span fitted, no timing; ~0.1 s against 10-370 s); img2c64 without `-d` and
  `analysis/dither_rank.py` use it. Imported only for that (numpy).
- `vic2/disk.py`: `make pictures` (`python3 -m vic2.disk [--ntsc|--dual] [--viewer]
  [--disk K] [-o FILE] [FILE.v2i...]`): the build directory's `.v2i` files (not
  `*-centred`, not older versions or the other system's) with `thumbs.prg` (and
  `viewer.prg` and the `.txt.prg` stories) onto `build/<pal|ntsc|dual>/pictures.d64`/`.d81`,
  named as `build.py` names them (`v2i_disk_name`; dual: `dual_base` + `-P`/`-N`, texts
  shared when the same). Needs a build first for the programs.
- `vic2/info.py`: `python3 -m vic2.info [-t DIR] FILE.v2i...` prints a `.v2i`'s header,
  thumbnail and metadata (`build.read_v2i`; `-t` writes the thumbnails as PNGs).
- `vic2/thumb.py`: thumbnails (Nov 2026): the picture as the C64 shows it, box-shrunk into
  24x21 (24x15 for 320x200), saturation x1.5 (`SATURATE`; averaging greys colours),
  black plus at most 8 colours (`choose`: backward elimination from 16 by error), one
  sprite per colour, all at one position, so 8 overlaid sprites show it exactly. img2c64
  makes it from the source picture (`thumbnail`, PNG `tEXt` `vic2orious-thumb`, hex);
  `build.v2i_thumbnail` takes that, else makes one from the PNG, and writes `build/<system>/<name>_thumb.png`. Tried: F-S
  dither (noise at this size), Lanczos (no better than box).
- `vic2/layers.py`: `build/<system>/<name>_sprites.png`, written with `_compare.png` on
  every new conversion (not from the cache: `--force` for old ones): bitmap alone, sprite
  pixels alone, each sprite's windows by number, sprite pixels per cell as a heat map
  with sprites painting per line (and bad lines) beside it.
- `vic2/screen.py`: Python model of the screen as the library's text/clear routines leave
  it (used by `--verify`). `vic2/ask.py`: `.ask` parsing, layout and model for the demo.
- `vic2/font.py`: proportional fonts as GEOS point-size records: the default derived from
  the ROM lower/upper case set, or one size of a GEOS `.cvt` font (`build --font`); the
  ASCII text codes and the pixel-width word wrap. `font.use()` selects the font for the
  whole process (like `timing.set_standard`), `font.current()` returns it.
- `vic2/palette.py`: Pepto palette, and Colodore (`.vpl`, and as VICE renders it with
  its default colour controls, PAL and NTSC: `COLODORE_VICE_*`, measured from a colour
  bar PRG), and the user's TV (`TV_2026_11`, `tools/tv.vpl`, img2c64's default, plus the
  current `tools/tv.vpl` if it differs). `load_indexed` maps colours of all of them exactly
  (`KNOWN`), others to the nearest Pepto (which gets VICE's bright Colodore wrong, e.g.
  red -> light red); the build warns about such a PNG.
- `asm/v2i.inc`: image library (`v2i_*`: machine takeover and exit, raster IRQ,
  unpacking into VIC bank 3, frame). `v2i_show` takes 0.2-0.4 s (unrolled clear, 5
  cycles a byte; `v2i_unrle` 18 cycles a literal and skips zero runs, so it relies on the
  clear; was 0.5-0.85 s, measured with py65). `asm/v2t.inc`: text library (`v2t_*`: .v2t files,
  single lines, measure, clear; bitmap/screen addresses configurable, no VIC setup).
  Each stands alone (own zero page block, own row address helper, prefixed names).
  `asm/slideshow.s`, `asm/diskshow.s`, `asm/viewer.s` and `asm/ask.s` use both;
  `asm/thumbs.s` (KERNAL on, BASIC banked out, text screen) reads the directory (`scan`, again on D for another disk:
  `$` as BASIC lists it) into a name table at `$a000` (17 bytes a name, up to 240):
  every name ending `.V2I` except the other system's `-N.V2I`/`-P.V2I`, so one program
  serves single and dual disks (no DUAL build). For the image shown it
  reads header, thumbnail and metadata through a data channel (`preview`, OPEN/CHRIN,
  about 600 bytes), shows them with `v2i_info`/`v2i_thumb` (sprite blocks at `$3e00`)
  and its own screen writer (`putc`, ASCII to screen codes, no KERNAL editor: no
  scrolling or line linking), and loads the whole file to `$2800` for `v2i_show` on
  return. It saves BASIC's zero page that `v2i_info` uses (`V2I_ZP`). `asm/v2i-demo.s`,
  `asm/v2t-demo.s` (KERNAL on, bitmap in bank 1), `asm/scroll.s` and `asm/stream.s` use
  one.
- `docs/`: `v2i-format.md`, `v2t-format.md` (incl. the font), `v2i-lib.md`, `v2t-lib.md`.
  Keep them in sync with the code.
- `tools/img2c64.py` (was `png2c64.py`): the user's quantiser (any picture -> PNG in
  the user's TV palette, `tools/tv.vpl`, by default; with `-P none` in Colodore as VICE
  shows it, its PAL or NTSC rendering per file; tagged sRGB;
  the profile's creation date is zeroed so the same input gives the same file, for the cache).
  Converts the input's ICC profile to sRGB, EXIF orientation,
  alpha onto black; `-a both|pal|ntsc|none` (default both) stretches the width by 1/PAR
  (PAL 0.936, NTSC 0.75) and writes `-p`/`-n` files; then fits 320x200 (or `-s WxH`,
  multiples of 8) and rounds to multiples of 8. `-o FILE` or `-o DIR/` (keeps input names, takes several files / glob
  patterns), `-d floydsteinberg|none` (Pillow's) or `fs:K|atkinson[:K]|hybrid[:E]`;
  without `-d` it picks one per picture and system (`candidate`/`pick`, all candidates of
  all pictures in one process pool): `vic2/dither_pick.py`'s `CANDIDATES` through the
  converter, ranked by blurred SSIM and a*b* colour error (`-w R,S,C`, default `0,1,1`;
  needs numpy), recorded as `dither choice` in the settings; `-t N` (default 3, `all`)
  ranks them all by `dither_pick.estimate` first and converts only the best N, then ranks
  those with the others' estimates (`rank` scales each metric over the set it gets, so
  ranking the N alone flipped a near tie; Nov 2026, kodim05/13 at 160x96: same picks as
  `-t all`, a third of the CPU); the log prints every candidate's metrics, wrong
  pixels and CPU time
  (`diffuse`: own serpentine error diffusion, pure Python; hybrid picks each cell's pair
  with `cell_pairs`, segment distance plus a spread penalty as in Yliluoma, and leaves the
  pair only beyond RGB distance E), `-c S` (colours are chosen against `palette(system,
  S)`, the palette moved towards its luma, then written with the real ones; helps hybrid,
  hurts the others), `-P FILE.vpl` (the user's screen's palette: colours are chosen
  against `palette(system, S, view)` and written in view's colours; default
  `tools/tv.vpl` (`VIEW`), measured from a photo of the user's TV running a colour bar
  (Nov 2026; far paler than VICE's Colodore, nearest stock VICE palette
  community-colors), `-P none` for VICE's Colodore; the library functions default to
  none, so `analysis/` scripts still use Colodore; the dither picker scores what that
  screen shows, `dither_pick.shown(.., view)`; the build reads the PNGs through
  `palette.KNOWN`, which has `TV_2026_11` (= tools/tv.vpl) and the current
  `tools/tv.vpl` if it was measured again: keep old palettes there, or their PNGs map to
  the nearest Pepto colours), `-l N|none` (hybrid: a line's colours outside the cell pairs fit in N
  runs of 24 px, `runs_needed`; else the nearest colour that fits; default 8,
  `HYBRID_RUNS`), `-m` (multicolour: one PNG pixel per wide pixel, 160 wide for the full
  screen, multiples of 4, aspect stretch doubled; `-s`/`-b` still in screen pixels; no
  hybrid; the picker scores the picture itself, pixels doubled, no converter; settings get
  `mode: multicolor`, `MODE_MC`, which `build.png_mode`/`is_mc` read). Hybrid's defaults (`-l 8`, `HYBRID_SPREAD` 0.1, `HYBRID_CLAMP` 64) changed
  in Nov 2026. Each output PNG records the settings (`settings`: source name, aspect,
  fit, dither with hybrid's constants, chroma, palette) in a `tEXt` chunk `vic2orious`
  (`TEXT_KEY`), which the build copies into the `.v2i` metadata. Refuses to overwrite its input. `-b` only leaves
  room for the frame `v2i_frame` draws (`build -b`): fits 304x184. (Its old `-b` drew the
  frame into the pixels, which did not always convert exactly.) Every output PNG also
  gets a thumbnail (`vic2/thumb.py`, text chunk `vic2orious-thumb`).
- `analysis/`: one-off measurements, not part of the build (`compare.py`: v2i vs AFLI and
  NUFLI; `spantypes.py`: X-expanded/multicolour spans; `timingloss.py`: wrong pixels by
  cause; `badline_weight.py`: the `RETASK` badline weight; `dither_score.py`: img2c64
  settings by wrong pixels and blurred RMS against the photo; `dither_rank.py`: one
  picture's settings ranked by weighted blurred RMS, SSIM and colour error; `mc_estimate.py`:
  multicolour bitmap + X-expanded sprites vs hires, timing-free). Inputs and outputs in `build/analysis/`; requirements, invocation and results in
  its README.
- `fonts/`: GEOS fonts in Convert format for `--font` (gitignored: third party fonts are
  not committed; the README tells users to bring their own). Tested with a 26 px Old
  English (one size) and NLQ (10-24, several sizes per file).
- `input/`: images (`name.png`; or `name-p.png` / `name-n.png`, which a PAL / NTSC build
  converts instead: `image_name` maps either to `name.png`, `image_source` picks the file
  per system, falling back to `name.png`; main errors if neither exists; the Makefile's
  `src` does the same for the json dependencies), optional stories (`name.txt`) and optional demo questions
  (`name.ask`, builds `build/pal/ask-name.prg`); texts too can be per system
  (`name-p.txt`/`name-n.txt`, `.ask` likewise: `text_source`, Makefile `txtsrc`; the dual
  disk then gets `NAME-P.TXT`/`NAME-N.TXT`, `dual_texts`). The castle, gaoler and princess
  examples are `-p` (the originals, Pepto) and `-n` (Nov 2026: widened by 0.936/0.75 with
  Lanczos, 4x oversampled, re-dithered by img2c64 `-a none -P pepto.vpl -s WxH`, castle
  144x200, the others 160x128) with shorter `-n.txt` stories (the text area is narrower). `images/` holds older test images (local
  only, gitignored). `build/` is generated and gitignored.

## How it works (the parts that are easy to break)

- Multicolour (Nov 2026): the PNG is in wide pixels (img2c64 `-m`, `mode: multicolor`
  in its settings, `build.png_mode`). `Geometry(mc=True)`: `w` in wide pixels, cells `cw`
  = 4 wide, `scale` 2, `w_px` on screen; `xr(x)`/`xr_last(x)` map image columns to sprite
  X (all X/window code goes through them, hires included). Cells get three colours plus
  the background (`pairs` = (c1, c2, c3, bg), `mc_cands`: triples of the cell's
  `MC_CANDS` commonest colours); the cover, assignment and scheduler are unchanged, in
  image pixels: X-expanded hires sprites (`$d01d` = `$ff`, `$d016` = `$18` in the
  prologue) paint 24 wide pixel single colour spans, and their pixel timing matched VICE
  first time (0 differing pixels). Background black (`bg=0`): `00` shows `$d021` on the
  whole screen, also around the image. `.v2i` flags bit 1 (`V2I_MC`; was version 4,
  now all files are version 5): background, colour RAM stream after the sprites. The
  build centres them and leaves out text, `.ask` and frame (they would be drawn in
  multicolour); `expected` and `_expected.png` are in screen pixels (doubled).
  `v2i_show` clears and fills colour RAM, `v2i_start` writes `v2i_bg` to `$d021`,
  `v2i_stop` resets `$d01d`/`$d016`, `v2i_frame` skips them; diskshow and the viewer
  check only "V2I" and leave the version to `v2i_show`.

- An image with text (`name.txt` or `name.ask`, `has_text`) sits at the upper left by
  default (char row 0, column 0, so image line 0 is raster $33 and sprite X = 24 +
  column); one without is centred (`place`: column (40 - cols) // 2, row (25 - rows) // 2).
  The v2i demo shows no text, so it gets a centred second conversion of its image
  (`demo_image`, `build/<system>/<name>-centred.*`) when the image has text.
  `build --at C,R` places all of them (`Geometry`), the demo's too. The
  position is baked into the kernel: moving by whole chars changes the schedule (pixel
  windows shift by a cycle per char while DMA stalls stay put; sprite blocks are at
  absolute raster lines, 21 apart). Sizes are multiples of 8, up to 320x200 anywhere on
  screen.
- 9-bit X: a sprite moving across X = 256 also needs its bit in `$d010`, which all 8 share.
  `line_tasks` turns a line's high bit changes into `$d010` tasks writing the whole mask
  (one per group of overlapping windows, stabbed by deadline, each later than the previous
  one, `last_use[8]`, so they land in order). Between the X and `$d010` writes the sprite
  sits at a mixed X: `safe_window` keeps both writes out of the times either mixed X would
  start it on lines r-1 and r. Unused sprites are at high bit 0 once any `$d010` write
  happened (the prologue's `$d010` is patched with the earlier ones' bits). `assign`
  counts a crossing as 0.8 writes; `pick_x` keeps the high bit when the range allows.
  The 320x200 `input/dragon.png` needs 55 `$d010` writes; most of its ~2100 wrong pixels
  are lines needing more than 8 spans, not timing.
- Frame (`build -b`, for all images of a build): images with text move to char row 1,
  column 1 (raster $3b, X = 32 + column; centred ones stay centred; or to `--at`) and the programs are assembled with
  `FRAME=1`, so they call `v2i_frame`, which draws a 4 px frame
  (white/white/black/white) into the ring of cells around the image if it fits on
  screen. The `.v2i` format does not know about it. Images without room for the ring are
  not framed. `--verify` compares the frame too.
- Each image gets its own unrolled, cycle-exact kernel, run from a raster IRQ at line 9
  (`IRQ_LINE`, `V2I_IRQ_LINE`; line 2 before `.v2i` version 3).
  It is position independent (only touches zp `$02`, VIC registers, pointers at `$c3f8`).
  Host programs run in the rest of the frame (below the image); the library's text
  routines are safe to call then.
- Sync: the kernel does not need a stable raster. `Kernel.sync()` tracks a set of possible
  entry times ("hypotheses") and emits RMW/store instructions that land on the start of BA
  low periods until all hypotheses merge. Keep the IRQ prologue in `v2i.inc`
  (`sta/stx/sty zp`, `jsr v2i_kjump`, `nop`, `jmp` whose operand is `v2i_kvec`: 5 cycles, as the `jmp (v2i_kvec)` it replaced, which broke when the vector landed at $xxff) as is; the entry window assumed in
  `convert.py` (`T(IRQ_LINE, 20..47)`) depends on it. It covers any interrupted instruction
  (the `ask` verify build draws text continuously and still matches).
- All 8 sprites run continuously in 21-line blocks with staggered phases (`SPR_START`), so
  every kernel line has the same sprite DMA. Pointer writes must land on the line before a
  block; on a badline that leaves one possible write cycle (cycle 12), which is why
  `Scheduler._tighten` shrinks windows to cycles a store can really hit and why
  `ok_after`/`_can_meet` guard every emitted instruction.
- Y restart tasks are added 21 lines early (`fixed[B - 21]`) so EDF fills idle time with
  them; adding them at their deadline caused failures on 200-line images.
- Look ahead: each line is scheduled one line further (`Scheduler.add(ahead=1)`, that
  part dropped again) with the next line's fixed tasks (`fit_line`'s `nxt`). In an image
  with no idle cycles EDF puts a Y restart off to its deadline, which on a badline is
  cycle 12, the only cycle its block's pointer write has too: without the look ahead the
  clash showed only when the lines that could drop spans for it were done, and the line
  failed outright (a Floyd-Steinberg dithered 320x168 image). Without the look ahead is
  still tried last.
- At the end of the image a timed `$d015 = 0` stops sprites before any new block starts
  without its pointer (otherwise old sprite data repeats below the image). It lands after
  the last line's Y compares, so blocks starting on the line below always start, and
  `sprite_lines` gives each sprite's exact DMA end: `$d015 = 0` does not stop a running
  block. It is scheduled with the image's last line (`fixed[r - 1]`, `until` r), so
  `fit_line` drops spans for it: a full width image ending above a badline leaves it one
  cycle (r:12), and adding it after the rows failed (`SchedFail` on a pointer write). On NTSC the blocks of an image ending on raster 251 (200 lines) run on to line 8
  of the next frame, which is why the kernel is entered on line 9 (`timing.Vic` leaves
  DMA past the last line out). The prologue writes the Y registers and `$d015` first, so
  sprite 0 is on before its first compare (line 13).
- No border/background writes in the kernel: an 85xx VIC-II (VICE emulates it) shows a
  grey dot for a colour register write, and lines 9-11 are visible on NTSC (a dot left of
  the image broke `compare_screenshot`'s alignment). `v2i_start` sets them.
- Pixel timing: sprite X coordinate x is drawn in cycle `PIX_C0 + x // 8` (13), with
  `MARGIN = 1` cycle on each side of every edge. Validated against VICE; changing either
  needs a `--verify` run. The same on NTSC (X = 0 falls in cycle 13 on both chips).
- PAL/NTSC: a kernel only works on the system it was made for (6569/8565: 63 x 312;
  6567R8/8562: 65 x 263), and the converted data differs too, since the scheduler decides
  which spans fit. NTSC sprite p-accesses are at cycles 59, 61, 63, 65, 2, 4, 6, 8 (sprite
  3 in the line before, so `p_time` decides the line by cycle, not by sprite number), Y
  compares at 56/57; badlines and pixel timing as on PAL. Source: VICE
  `src/viciisc/vicii-chip-model.c` (`cycle_tab_pal`/`cycle_tab_ntsc`; BA low from 3
  cycles before a p-access to 1 after). `.v2i` version 2 has the system in header byte
  24; `v2i_init` detects the machine from its last raster line (`$37` PAL, `$06` NTSC)
  and `v2i_show` refuses a file for the other system (hosts print `v2i_errmsg`). PAL
  builds go to `build/pal/`, NTSC builds to `build/ntsc/` (`NTSC=1` in make, VICE
  `-ntsc`); `--verify` checks either.
- Dual disk (`build --dual`, `make DUAL=1`): `build_system` runs for PAL and NTSC (cached
  conversions, own disks), then `build_dual` writes `build/dual/` with diskshow and viewer
  assembled `DUAL=1`: they call `v2i_detect` (KERNAL on) and add `-P.V2I`/`-N.V2I` to the
  image names (base cut to 10 by `dual_base`). A text is shared (`NAME.TXT`) when both
  systems pack it byte for byte the same (same position and size), else written as
  `NAME-P.TXT`/`NAME-N.TXT` (`dual_texts`; sizes differ with `-p`/`-n` inputs): diskshow
  gets a text name table per system (`tname`, `ntname`); the viewer, when the suffixed
  `.V2I` loaded, swaps its `V2I` for `TXT` and falls back to `NAME.TXT`. The v2i demo is assembled `DUAL=1` there too, with the first image's
  PAL and NTSC `.v2i` both embedded (`demo_img`, `demo_img_n`), picked by `v2i_system`
  after `v2i_init`; it replaces the `v2i demo-p`/`-n` pair on the dual disk. `--verify`
  with `--dual` also boots the dual diskshow, the dual viewer (typing the first image's
  `dual_base`), the dual v2i demo and the dual thumbnail browser on both systems.
  diskshow's hold time is `HOLD_SECS`, multiplied by 50 or 60 at startup.
- Buffers: diskshow and the viewer load images at `$2800` (`PLAYER_BUF`; build asserts a
  `.v2i` fits below `$9800`) and texts at `$9800`. The programs may use up to `$27ff`:
  diskshow's name tables grow with the image count, and a big font is several K (the
  viewer with the 26 px Old English font ends at `$2179`; images were at `$2000` and the
  viewer's texts at `$1800` before GEOS fonts). Not `$a000-$bfff`: the players
  check the header with the BASIC ROM still on, which hides that RAM (a text buffer at
  `$b800` silently lost every story).
- Lines that cannot be done exactly are not skipped: with more than 8 spans needed the
  cover keeps the most pixels; when the writes do not fit, `fit_line` searches best-first
  (up to `FIT_TRIES` schedules) for the set of dropped spans losing the fewest pixels.
  `recover` then lets sprites paint leftover pixels they already reach without writes.
  Remaining pixels fall back to the nearer of the cell's two colours.
- Text: the build word-wraps by pixel width and ships finished lines (ASCII codes); the
  C64 only draws glyphs and colours each row's cells. The C64 does not wrap. The font
  (a GEOS record, or the ROM's) is assembled into the program as byte columns
  (`font.inc`, `Font.asm`): `v2t_tglyphs` draws a glyph one 8-pixel column at a time,
  top to bottom, Y = pixel line in the char row for both font (src = column - tyo) and
  bitmap; each byte is shifted by x & 7 (self-modified jump into an unrolled shift: 1-4
  right, 5-7 as 3-1 left) and ORed into two bitmap bytes (pp, pp2 = pp + 8; +320 at a
  char row's bottom). The OR is needed: neighbouring glyphs share bitmap bytes. Lines
  are H + leading pixels apart (H = font height, stored in `.txt` byte 8 and checked by
  `v2t_draw`; `build --leading`, default 2), so a line touches every char row its H lines
  reach, and all of them get the line's colour (the later line wins a shared row). The
  text layout depends on the font; it is packed on every build, outside the conversion
  cache. The ask demo puts each menu line on a char row boundary (`ASK_MENU_LEAD`) and
  skips itself (`NoRoom`) when a big font leaves no room for answers.
- Scroll demo (`asm/scroll.s`, `build_scroll`/`scroll.inc`): a page of the intro and all
  stories (up to 255 lines, cut to fit below `$4000`), 24-row mode, YSCROLL 0-7, two
  bitmaps (A: `$6000`/`$4000` in bank 1, B: `$a000`/`$8000` in bank 2, BASIC banked out),
  swapped by the raster IRQ (line 250) only when the back's tag (`btag`) is the base it
  needs; otherwise the scroll waits. The main loop prepares the back: row colours from
  `scr_rc` (only rows that change), 7680 bytes copied (~74k cycles, the fixed cost), the
  new row cleared and its lines drawn with `v2t_over` into a bitmap `VOFF` = 4 rows early,
  clipped to that row (`v2t_rtop`/`v2t_rbot`), so lines may start above row 0 (fonts up
  to 32 px). At one pixel per frame it has 8 frames: worst step ~124k cycles (ROM font)
  against ~126k on NTSC, ~148k on PAL; anything that makes text drawing slower can make
  it hitch on NTSC, which `--verify`'s timing check (`AUTO=2`: N frames down must end
  at line N) catches.
- Stream demo (`asm/stream.s`, `build_stream`/`stream.inc`): the same display, downwards
  only, but the C64 lays out the text: a byte stream (`stm_data`, `STM_RATE` bytes a
  frame) is word-wrapped by pixel width (`stream_layout` is the Python model: line feed
  = space, two = paragraph, first word "#" = title, WMAX/LMAX limits; for normal text it
  matches `text_layout`) into a ring of `LN` line slots and a text ring (`$4400-$5aff`,
  each line contiguous, LMAX + 1 bytes reserved). Each finished word is drawn into the
  front and, if it holds base + 8, the back; `render` finds the lines of row 24 by
  walking the ring from `tail`. Lines above the front are dropped; the stream waits for
  `room`. The back is prepared as soon as it isn't base + 8 (eagerly: preparing only once
  the target needed it stalled the scroll a few frames whenever a line arrived at rest),
  and the stream is only read while the back is ready, so the scroll never waits (0
  stalls on PAL and NTSC, rates 0-64); copying a word's cells into the back instead of
  drawing it twice made no difference and was dropped. `STALLS=1` counts waits into the
  border; `--verify` uses it, so a wait fails the check. It writes `$d020` only on a wait:
  writing it every frame left the 85xx colour-write dot on a visible NTSC line, which
  broke `compare_screenshot`'s alignment.

## Working in the repo

- Build everything from `input/`: `make` (or `python3 -m vic2.build`; add `--verify` to
  compare each screen with VICE, `--run` to launch the slideshow; specific files can be
  passed as arguments). The Makefile wraps it: `make verify`,
  `make run[-diskshow|-viewer|-thumbs|-ask|-d64|-pictures]`, `make pictures`, options `IMAGES FRAME AT LEADING AUTO HOLD
  DISK NTSC DUAL FAST IMAGE ASK FONT VIEWER FILES` (`make help`). macOS make is 3.81, so the Makefile uses a
  stamp file (`build/<system>/.built`, plus `.opts`/`.copts` there for the options) instead
  of grouped targets.
- Conversion cache: `build/pal/<name>.json` (`build/ntsc/` for NTSC) holds the converter result (stats, geometry, path
  of `_expected.png`) and a key hashing the png, frame/at, the video system,
  `CACHE_VERSION` and `CACHE_SOURCES` (convert, timing, palette, thumb, `__init__` for the version). Builds reuse it;
  `--force` reconverts. build.py itself is not hashed: bump `CACHE_VERSION` when changing
  how `.v2i` is packed. Texts are not cached: `convert_image` packs the `.txt` again on
  every run (milliseconds), so editing a story, `--font` or `--leading` never reconverts
  the image. The Makefile converts each image in its own
  `--convert-only` run (target `build/<system>/<name>.json`, so `make -j` parallelises), then runs
  the full build, which finds everything cached.
- After touching `timing.py`, `convert.py`, `v2i.inc` or `v2t.inc`, run `--verify`: every check
  must report `0 differing pixels` (VICE output vs the model). The converter itself reports
  bad lines / wrong pixels vs the source; those are expected to be non-zero.
- `.v2i` version 5 (Nov 2026): header, thumbnail (flags bit 2, `V2I_THUMB`), metadata
  (bit 0, `V2I_META`, `v2i_metadata`), then kernel and streams, so a program can read
  thumbnail and metadata alone. Versions 3/4 had the metadata at the end and no
  thumbnail; `v2i_show` (through `v2i_info`) takes only version 5, `read_v2i` all.
  Metadata: `quantized by` (img2c64's line, `img2c64@VERSION`; old PNGs' `quantiser`
  is renamed; else `unknown`), `generated by: vic2orious@VERSION` (`vic2/__init__.py`
  `VERSION`, img2c64 imports it too), `date` (UTC, at conversion), img2c64's other PNG
  `tEXt` lines, then the build's `image`, `palette` (if img2c64 named none;
  `palette_name`), `frame`. Both are written at conversion, so
  they are cached with the `.v2i` (the key hashes the PNG, which holds img2c64's text and
  thumbnail, and `thumb.py`). Settings not in the format go there.
- `--verify` builds one single-image slideshow per image, with its text, and compares the
  whole screen with a model (`expected_screen`: converter output + `Screen` text model).
  For each `.ask` it builds `ask.s` with `AUTO=n` (picks the last topic, then keeps
  drawing a black-on-black line) and compares with `Ask.model`; the v2i demo against the
  first image, the thumbnail browser (`VERIFY=1`: text in black, booted with the disk)
  against `thumbs_screen`, and the v2t demo against `v2t_demo_screen`; the scroll demo scrolls itself
  (`AUTO=1`: down, then back up; `AUTO=2`: the timing check) and is compared with
  `scroll_screen`, as is the stream demo's last screen (all at once, 4 times over, so both
  rings wrap; and at `STREAM_RATE`; built `STALLS=1`). If text rendering
  changes, change `vic2/screen.py` to match.
- Keys in the demo and space in the viewer are read from the CIA matrix, so VICE
  `-keybuf` cannot press them (it only feeds the KERNAL buffer).
- Requires Python 3 with Pillow, cc65 (`cl65`), VICE (`x64sc`, `c1541`). The character
  ROM is read from `$VICE_DATA`, else the first of Homebrew's and the usual Linux VICE data
  directories that has it (`font.vice_file`, `VICE_DIRS`).
- CI (`.github/workflows/ci.yml`, on pushes to any branch and manually): Ubuntu with apt's
  cc65 and a headless VICE built from upstream source (Debian's lacks the ROMs), cached
  (`.github/actions/setup-toolchain`); `make convert DUAL=1` in parallel, then
  `make verify DUAL=1` (fails on any differing pixel), `vic2.prg --verify` hires and
  `-m`, and `tools/dist.sh` packages the build as artifact `dist`. Release
  (`release.yml`): pushing a tag `v*` runs CI, then publishes `dist` (dual disk, PAL and
  NTSC zips, the libraries with their docs) as a GitHub release with `CHANGELOG.md` as the
  notes (a tag with `-` is a prerelease).
- VICE notes: screenshots are not exactly Pepto even with `-VICIIpalette pepto-pal.vpl`, so
  `compare_screenshot` maps colours by majority vote. Disk loading works with true drive
  emulation (the default; a 12-16K image takes ~25M cycles, the viewer test with autostart
  ~90M) or, near instantly, with `+drive8truedrive -trapdevice8` (VICE traps the KERNAL's
  serial calls; `+drive8truedrive` alone loads nothing, and `-virtualdev8` does not exist
  in this VICE). The Makefile's `FAST=1` adds both; checked with diskshow on the D81, 0
  differing pixels. `--verify` still uses true drive emulation. A PRG that is not on the
  attached disk needs `-autostartprgmode 1` (otherwise VICE looks for it on the disk).
  The viewer test pattern: `-8 build/pal/vic2orious.d64 -autostart build/pal/viewer.prg
  -keybuf 'princess\n'`.
- Memory (see also Buffers above): the slideshow PRG must fit `$0801-$bfff` (about 46K); each image is 9-15K, so
  3-4 images. With more, `assemble_slideshow` keeps the longest prefix that assembles;
  `diskshow` gets all of them (names baked in from `diskshow.inc`, loaded like the
  viewer, a yellow floppy sprite on black while loading (sprite 0, data at `$0340`, the text printed in black), the text screen only after a load error; `HOLD` seconds per image, 16-bit frame count,
  0 holds an image until space, used by its `--verify` check, which boots it with a one-image D64). The disk is a D64 if
  everything fits (664 blocks, 144 entries; about 13 images), else a D81 (3160 blocks;
  VICE needs `-drive8type 1581`, which the Makefile adds). VIC bank 3 (`$c000-$ffff`) holds the image on screen and is not available.
  The viewer and diskshow must end below `$2800` (asserted): images load there.
  (The viewer once loaded text at `$1000` and overwrote the end of its own font.)
- Disk names: images are the first 12 chars of their name (`-c64` dropped) + `.v2i`
  (`v2i_disk_name`; Nov 2026, so the thumbnail browser can find them in the directory;
  the dual disk's are `dual_base` + `-p.v2i`/`-n.v2i`); the viewer tries the typed name +
  `.v2i` first (a typed `.v2i` is dropped first), then the name as typed. Text files are
  the first 12 chars + `.txt`.

## What has been tried

- First version stopped at the first line that could not be reproduced and blacked out the
  rest (ECM+BMM invalid mode). Replaced by doing every line and dropping spans; the ECM
  write was later removed so text can sit below shorter images.
- Images were first centred on screen, then always upper left; now upper left only when
  text needs the rest of the screen.
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
  line; letters average 6.8 px because of the 2 px strokes), first as 8 bytes per glyph
  indexed by screen code, then as a GEOS record (same pixels: `--verify` and the models
  matched before and after the switch).
- Text speed (Oct 2026): drawing from the GEOS bitstream (align 8 bits from the glyph's bit
  offset, mask, shift loop) cost ~235 cycles per glyph row byte; byte columns with an
  unrolled shift made a story 2.7x (ROM font) to 3.2x (NLQ 24) faster, same pixels, font
  data 15-30% bigger. Measured with py65 (cycle counts of `v2t_draw`). Most of what is
  left is the per-byte loop; `v2t_rowaddr`'s multiply loop is next (~8%).
- NTSC sprite DMA from Bauer's vic-ii.txt alone: its 6567R8 diagram is abbreviated and
  reads as sprites 0-2 at 60/62/64 with 3-7 unchanged; that gave ~2300 wrong pixels in
  VICE, and guessed shifts did not converge. VICE's cycle tables (above) gave 0.
- 200-line NTSC images with entry on line 2: modelling the leftover DMA in lines 0-8
  failed (the first frame has none; the sync then lands wrong, no block starts, so the
  next frame has none either: a stable state without sprites). Tracking hypotheses for
  both cases spread them ~60 cycles and the sync ran to line 86. Entry on line 9 fixed it.

- Dithering (Nov 2026, IMG_1639 320x168 PAL, wrong pixels / 3x3-blurred RMS error vs
  the source): F-S 15% / 12.1, none 0.2% / 24.0, fs:0.5 4.1% / 15.2, atkinson:0.75 4.8% /
  14.7, F-S with error clamped to 24 5.1% / 14.5, hybrid 3.3% / 15.1 (with `-c 0.6` 2.0%,
  and visibly warmer). Dropped: Yliluoma-style pattern dither over the whole palette (9.5%,
  no better looking); ordered (Bayer) dither between each cell's pair (0% wrong, but the
  cell edges look jagged); saturating the picture instead of desaturating the palette
  (more wrong pixels for the same colour); greens stay rare (Colodore's are far brighter
  than foliage). F-S at 0.75 (10% wrong) made `fit_line` fail outright, fixed by
  the look ahead (see How it works).
- Line budget for hybrid (`-l`, Nov 2026, 5 Kodak photos 320 wide, `analysis/
  dither_score.py`; wrong / blurred RMS of what the C64 shows): hybrid 1.3% / 14.46,
  `-l 8` 0.6% / 14.72, `-l 6` 0.3% / 14.89, F-S 9.9% / 13.59. The budget makes the C64
  show img2c64's picture almost exactly but does not bring it closer to the photo
  (hybrid's wrong pixels fall back to near colours anyway); a lower `E` with it adds
  wrong pixels for no RMS. Rejected beforehand: capping the colours of
  each 8-line band (F-S photos have only 640-2275 pixels outside each band's top 8
  colours but ~5000 the 8 spans miss: where the colours are matters, not how many).
- Hybrid's defaults (Nov 2026, same photos): spread 0.25 -> 0.1 and clamp 32 -> 64 with
  `-l 8` (the parrots' green background had gone grey): 2.4% / 13.09, closer to the photo
  than F-S with a quarter of its wrong pixels; `-l 6` 1.3% / 13.28 (some cells show as
  green blocks). Spread 0 or no clamp are worse. On IMG_1639 (the hard one): new default
  3.1% / 14.53, `-l 6` 1.6% / 14.38, old hybrid 3.3% / 14.61, F-S 14.6% / 14.05.
  But visibly the `-l 8` default turns much of IMG_1639's stone and foliage into flat
  grey areas (the budget's nearest-colour fallback), which the blurred RMS hardly
  charges; `-l none` (11.3% wrong) looks like F-S. Judge budget changes by eye too.
- Other converters (Nov 2026; 296 px wide inputs, scored right of the FLI bug columns,
  wrong pixels vs the source): dragon crop and kodim01/05/23 (`img2c64 -a pal -s 296x200`,
  F-S and `-d none`). v2i 0.1-3.4% (none, dragon) and 10-12% (F-S); retropixels AFLI
  (hires FLI, `-r 0 -c rgb`) 1.7-6.1% / 16-17%, which is exactly the AFLI optimum (two
  most common colours per 8x1), so v2i beats any AFLI picture; pynuvie NUFLI 3-8% /
  22-28% (its own model, not run in VICE; it dithers on purpose). retropixels' png matched
  its PRG in VICE (0 differing pixels). Mufflon (Crest's NUFLI converter) and Pixcen are
  Windows only. NUFLI (fixed sprite columns under FLI every 2 lines) is the nearest
  relative; no tool found that moves sprites per line like this one.
- Scripts and tables for the next two items: `analysis/` (its README).
- X-expanded / multicolour sprite spans (Nov 2026, same images, measured without timing:
  greedy 8-sprite cover of the converter's leftover pixels, a pair/group painted only
  where all its pixels have that colour): multicolour (`$d025`/`$d026` per line) took the
  dragon 1480 -> 1325 and kodim05 none 758 -> 675 (about 10%), nothing on F-S photos
  (isolated pixels); X-expanded nothing anywhere. Upper bounds before the extra register
  writes: not worth building. Timing costs more: actual wrong pixels minus the exact
  timing-free cover were 688-1035 on the F-S photos (12-19% of their wrong pixels), 326 on
  the dragon.

- Multicolour bitmap (Nov 2026, `analysis/mc_estimate.py`, 5 Kodak photos, no timing
  for multicolour): 3+1 colours per 4x8 cell plus X-expanded sprites (24 wide pixel spans)
  shows its picture almost exactly (0-49 wrong pixels, even F-S); with F-S the blurred RMS
  vs the photo is 12.42 (hires F-S 13.59, hires hybrid 13.09), without or with light
  dither hires is 0.4-1.0 closer. Built (one code base, mode per image): with timing,
  F-S photos lost 0-98 pixels (PAL) with the background chosen per image (the
  commonest of 3 leaving the fewest pixels outside cell triples; grey on these photos),
  1-509 (0-1.6%) with black, which was kept (the screen around the image stays black).

## Ideas not done yet

- Timing losses (12-19% of the wrong pixels on F-S photos; `analysis/timingloss.py`,
  tables in `analysis/README.md`): the first write to miss is an X write for 50-93% of
  the dropped pixels, and badlines (the first line of every char row, 1 in 8) lose
  37-60% of them; F-S lines ask 7.5-8.6 writes on average, and lines asking 9+ lose
  most. Done: `row_cost` charges a retask into the badline line 100 instead of 20
  (`RETASK`; its writes must fit in the line before): 1.7% fewer wrong pixels over 11
  images, 10 better (`analysis/badline_weight.py`). To try: a cover that prefers spans
  the sprites reach without X writes, `MARGIN = 0`.

- Store the kernel as a compact write list and generate code on load (kernel is about half
  of each image; would fit roughly 6 images per PRG).
- Fastloader / IRQ-safe loader for the viewer and diskshow (the KERNAL load is slow and
  cannot run while a kernel is displaying; with one, diskshow could load the next image
  while showing the current one).
- C64-side word wrap for `.txt`/`.v2t` drawing (`asm/stream.s` has one for its stream);
  scrollback in the stream demo (it scrolls down only and drops lines above the screen);
  a real stream source (RS-232 or disk, buffered by an IRQ); custom fonts from a PNG; fonts loaded at run
  time (the `.txt` could name one; the drawer would read the record through a pointer
  instead of the assembled labels); mega fonts.
- Text scrolling below a still image (raster split): `v2i_hook` (cycle exact, right
  after the kernel) switches `$dd00` to the text bitmap's bank and YSCROLL to the text's
  s; bank 3 and YSCROLL 3 must be back before line `$30`, which needs a second raster
  IRQ for the host in v2i (the IRQ prologue can't change without moving the kernels'
  entry window). The blank margin row under the image hides the seam (idle lines are
  black in hires; a repeated row is blank), but which memory row shows first depends on
  s: check in VICE. CPU is the limit: the host only gets the lines below the image
  (~9k cycles a frame on PAL under a 120-line image) for the copy (~3k per text row) and
  the new row (30-50k at full width), so keep the area narrow or scroll every other
  frame. Text above the image would need the kernel to do the switches (converter);
  text beside it can't use YSCROLL at all (software shifting is ~38k cycles a frame for
  a 19-cell column).
