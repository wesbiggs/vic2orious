# vic2orious

Converts C64-palette PNGs into C64 hires bitmap + per-line multiplexed hires sprites, aiming
for pixel-perfect output, and plays the results on a real (emulated) C64: a slideshow PRG
with the images embedded, a disk slideshow (`diskshow`) that loads every image in turn, a
viewer PRG that loads `.v2i` image files (plus optional `.txt` narrative files drawn
beside the picture) from disk by name, an interactive `ask` demo, and two smooth
scrolling text demos (a prepared page; a stream the C64 wraps itself).
The C64 side is two independent libraries, `asm/v2i.inc` (images) and `asm/v2t.inc`
(text), that other programs can include. Apache-2.0 licensed (`LICENSE`).

## Layout

- `vic2/convert.py`: the converter. Picks two bitmap colours per 8x8 cell (local search
  per character row, single and neighbour-pair moves, run for each of `ROW_WEIGHTS`; the
  candidate that really schedules with the fewest wrong pixels wins), then for every raster
  line covers the remaining pixels with at most 8 single-colour 24-pixel "spans" (`cover`:
  exact max-pixels DP, memoised) and assigns them to the 8 sprites (DP over sprite subsets,
  minimising register writes). `Geometry` holds size and screen placement.
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
- `vic2/screen.py`: Python model of the screen as the library's text/clear routines leave
  it (used by `--verify`). `vic2/ask.py`: `.ask` parsing, layout and model for the demo.
- `vic2/font.py`: proportional fonts as GEOS point-size records: the default derived from
  the ROM lower/upper case set, or one size of a GEOS `.cvt` font (`build --font`); the
  ASCII text codes and the pixel-width word wrap. `font.use()` selects the font for the
  whole process (like `timing.set_standard`), `font.current()` returns it.
- `vic2/palette.py`: Pepto palette, nearest-colour loading.
- `asm/v2i.inc`: image library (`v2i_*`: machine takeover and exit, raster IRQ,
  unpacking into VIC bank 3, frame). `asm/v2t.inc`: text library (`v2t_*`: .v2t files,
  single lines, measure, clear; bitmap/screen addresses configurable, no VIC setup).
  Each stands alone (own zero page block, own row address helper, prefixed names).
  `asm/slideshow.s`, `asm/diskshow.s`, `asm/viewer.s` and `asm/ask.s` use both;
  `asm/v2i-demo.s`,
  `asm/v2t-demo.s` (KERNAL on, bitmap in bank 1), `asm/scroll.s` and `asm/stream.s` use
  one.
- `docs/`: `v2i-format.md`, `v2t-format.md` (incl. the font), `v2i-lib.md`, `v2t-lib.md`.
  Keep them in sync with the code.
- `tools/png2c64.py`: the user's quick quantiser (picture -> Pepto palette). `-o FILE` or
  `-o DIR/` (keeps input names, takes several files / glob patterns), `-d
  floydsteinberg|none` (default floydsteinberg). Refuses to overwrite its input. Its old
  `-b` frame option was removed: framed pixels did not always convert exactly; frames come
  from `v2i_frame` (`build -b`).
- `fonts/`: GEOS fonts in Convert format for `--font` (gitignored: third party fonts are
  not committed; the README tells users to bring their own). Tested with a 26 px Old
  English (one size) and NLQ (10-24, several sizes per file).
- `input/`: images (`name.png`), optional stories (`name.txt`) and optional demo questions
  (`name.ask`, builds `build/pal/ask-name.prg`). `images/` holds older test images (local
  only, gitignored). `build/` is generated and gitignored.

## How it works (the parts that are easy to break)

- Image sits at the upper left by default (char row 0, column 0, so image line 0 is raster
  $33 and sprite X = 24 + column); `build --at C,R` places it elsewhere (`Geometry`). The
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
- Frame (`build -b`, for all images of a build): images move to char row 1, column 1
  (raster $3b, X = 32 + column; or to `--at`) and the programs are assembled with
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
  (`sta/stx/sty zp`, `jsr v2i_kjump`, `jmp (v2i_kvec)`) as is; the entry window assumed in
  `convert.py` (`T(IRQ_LINE, 20..47)`) depends on it. It covers any interrupted instruction
  (the `ask` verify build draws text continuously and still matches).
- All 8 sprites run continuously in 21-line blocks with staggered phases (`SPR_START`), so
  every kernel line has the same sprite DMA. Pointer writes must land on the line before a
  block; on a badline that leaves one possible write cycle (cycle 12), which is why
  `Scheduler._tighten` shrinks windows to cycles a store can really hit and why
  `ok_after`/`_can_meet` guard every emitted instruction.
- Y restart tasks are added 21 lines early (`fixed[B - 21]`) so EDF fills idle time with
  them; adding them at their deadline caused failures on 200-line images.
- At the end of the image a timed `$d015 = 0` stops sprites before any new block starts
  without its pointer (otherwise old sprite data repeats below the image). It lands after
  the last line's Y compares, so blocks starting on the line below always start, and
  `sprite_lines` gives each sprite's exact DMA end: `$d015 = 0` does not stop a running
  block. On NTSC the blocks of an image ending on raster 251 (200 lines) run on to line 8
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
  image names (base cut to 10 by `dual_base`); texts are shared (layout depends on the
  position only). `--verify` with `--dual` also boots the dual diskshow on both systems.
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
  `make run[-diskshow|-viewer|-ask|-d64]`, options `IMAGES FRAME AT LEADING AUTO HOLD
  DISK NTSC DUAL FAST IMAGE ASK FONT` (`make help`). macOS make is 3.81, so the Makefile uses a
  stamp file (`build/<system>/.built`, plus `.opts`/`.copts` there for the options) instead
  of grouped targets.
- Conversion cache: `build/pal/<name>.json` (`build/ntsc/` for NTSC) holds the converter result (stats, geometry, path
  of `_expected.png`) and a key hashing the png, frame/at, the video system,
  `CACHE_VERSION` and `CACHE_SOURCES` (convert, timing, palette). Builds reuse it;
  `--force` reconverts. build.py itself is not hashed: bump `CACHE_VERSION` when changing
  how `.v2i` is packed. Texts are not cached: `convert_image` packs the `.txt` again on
  every run (milliseconds), so editing a story, `--font` or `--leading` never reconverts
  the image. The Makefile converts each image in its own
  `--convert-only` run (target `build/<system>/<name>.json`, so `make -j` parallelises), then runs
  the full build, which finds everything cached.
- After touching `timing.py`, `convert.py`, `v2i.inc` or `v2t.inc`, run `--verify`: every check
  must report `0 differing pixels` (VICE output vs the model). The converter itself reports
  bad lines / wrong pixels vs the source; those are expected to be non-zero.
- `--verify` builds one single-image slideshow per image, with its text, and compares the
  whole screen with a model (`expected_screen`: converter output + `Screen` text model).
  For each `.ask` it builds `ask.s` with `AUTO=n` (picks the last topic, then keeps
  drawing a black-on-black line) and compares with `Ask.model`; the v2i demo against the
  first image and the v2t demo against `v2t_demo_screen`; the scroll demo scrolls itself
  (`AUTO=1`: down, then back up; `AUTO=2`: the timing check) and is compared with
  `scroll_screen`, as is the stream demo's last screen (all at once, 4 times over, so both
  rings wrap; and at `STREAM_RATE`; built `STALLS=1`). If text rendering
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
  The viewer test pattern: `-8 build/pal/vic2orious.d64 -autostart build/pal/viewer.prg
  -keybuf 'princess\n'`.
- Memory (see also Buffers above): the slideshow PRG must fit `$0801-$bfff` (about 46K); each image is 9-15K, so
  3-4 images. With more, `assemble_slideshow` keeps the longest prefix that assembles;
  `diskshow` gets all of them (names baked in from `diskshow.inc`, loaded like the
  viewer, text screen shown while loading; `HOLD` seconds per image, 16-bit frame count,
  0 holds an image until space, used by its `--verify` check, which boots it with a one-image D64). The disk is a D64 if
  everything fits (664 blocks, 144 entries; about 13 images), else a D81 (3160 blocks;
  VICE needs `-drive8type 1581`, which the Makefile adds). VIC bank 3 (`$c000-$ffff`) holds the image on screen and is not available.
  The viewer and diskshow must end below `$2800` (asserted): images load there.
  (The viewer once loaded text at `$1000` and overwrote the end of its own font.)
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

## Ideas not done yet

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
