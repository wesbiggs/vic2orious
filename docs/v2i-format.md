# .v2i image format (version 5)

A `.v2i` file holds one converted image: a hires or a multicolour bitmap, its cell
colours, the sprite data, and a *kernel*. The kernel is 6502 code generated for this image that rewrites the sprite
registers on every raster line, so the sprites paint the pixels the bitmap can't. A
thumbnail and the metadata come first, so a program can read them without the rest.
`vic2/build.py` writes it, and `asm/v2i.inc` displays it ([v2i-lib.md](v2i-lib.md)).

On disk it is a PRG file with load address `$2000`. The contents don't depend on where
they're loaded, so a program can load the file anywhere outside `$c000-$ffff` and pass
that address to `v2i_show`.

## Layout

All words are little endian. Offsets are from the start of the data, after the PRG's
2-byte load address.

| offset | size | field |
|---|---|---|
| 0 | 3 | magic `"V2I"` |
| 3 | 1 | format version: 5 |
| 4 | 1 | width in cells (width / 8 screen pixels) |
| 5 | 1 | height in cells (height / 8) |
| 6 | 1 | character column of the image's left edge |
| 7 | 1 | character row of the image's top edge |
| 8 | 2 | kernel length |
| 10 | 2 | bitmap stream length |
| 12 | 2 | screen stream length |
| 14 | 2 | sprite stream length |
| 16 | 2 | bitmap destination: `$e000 + 320 * row` |
| 18 | 2 | screen destination: `$c000 + 40 * row` |
| 20 | 2 | number of image lines that are not pixel perfect (information only) |
| 22 | 2 | number of image pixels that are not pixel perfect (information only) |
| 24 | 1 | video system the kernel is made for: 0 PAL (6569/8565, 63 cycles x 312 lines), 1 NTSC (6567R8/8562, 65 cycles x 263 lines) |
| 25 | 1 | flags: bit 0 metadata, bit 1 multicolour (see [Multicolour](#multicolour)), bit 2 thumbnail; other bits 0 |
| 26 | ... | the [thumbnail](#thumbnail) if bit 2 is set, then the [metadata](#metadata) if bit 0 is set, then the kernel, the bitmap, screen and sprite streams, back to back (multicolour: then the background and colour RAM stream) |

The build always writes a thumbnail and metadata. The kernel starts after them: skip the
thumbnail (4 + 64 * its sprite count bytes) and the metadata (2 + its length).

Older versions: 3 (hires) and 4 (multicolour, flags bit 1) had the same header, but the
kernel right after it and the metadata (flags bit 0) at the end, after the sprite stream
(and colour RAM stream); no thumbnails. Version 5 moved thumbnail and metadata to the
front so they can be read alone, and has one version number for both modes; players
(`v2i_show`) take version 5 only. Version 2 kernels were entered on raster line 2.
Version 1 had no video system byte (always PAL) and a 24-byte header.

## Thumbnail

The picture shrunk into one sprite's 24x21 pixels, in at most 8 colours over a background
colour, made so that up to 8 hires sprites on top of each other, at the same position,
one colour each, show it exactly: no raster tricks, any program can show it beside other
things (`v2i_thumb` in [v2i-lib.md](v2i-lib.md)).

| size | field |
|---|---|
| 1 | width in pixels (1-24) |
| 1 | height in pixels (1-21) |
| 1 | background colour: the colour of the pixels no sprite covers, and of the rest of the 24x21 area |
| 1 | n, the number of sprites (0-8) |
| 64 * n | for each sprite: its colour (1 byte), then its 63 bytes of sprite data (3 bytes a line, 21 lines, leftmost pixel in bit 7 of the first byte) |

- **Size and place:** the picture as the C64 shows it (a multicolour image counts screen
  pixels: 160 wide pixels are 320), fitted into 24x21 and never enlarged: 24x15 for the
  full screen, 21x21 for a square one. It is centred in the 24x21 area (left and top
  margin `(24 - width) / 2`, `(21 - height) / 2`, rounded down); the margins are
  background.
- **Pixels:** every pixel is the background colour or set in exactly one sprite, so the
  order and priority of the sprites don't matter. Show them unexpanded and hires (or
  expanded, both ways, for a 48x42 picture); the background is the host's to paint (or
  to choose the screen behind it): the build writes black, the screen colour around the
  images.
- **Making it:** `tools/img2c64.py` makes it from the original picture (shrunk with box
  averaging, saturation raised 1.5 times, then the 8 colours besides black chosen from
  the palette it writes, by dropping the colour that adds the least error until 8 are
  left; `vic2/thumb.py`) and stores it in the PNG (text chunk `vic2orious-thumb`, hex).
  For a PNG without one (not from img2c64, or from one older than 0.1.0) the build
  makes it the same way from the PNG itself.

## Multicolour

A multicolour image (`tools/img2c64.py -m`) is 160 wide pixels across at most, each two
screen pixels wide, in cells of 4x8 wide pixels; the header still counts 8-pixel cells.
Byte 25 has bit 1 set, and after the sprite stream come:

| size | field |
|---|---|
| 1 | background colour (`$d021`; the build writes 0, black) |
| 2 | colour RAM stream length |
| ... | colour RAM stream |

- **Bitmap:** bit pairs, leftmost pixel in bits 7-6: `00` background, `01` the screen
  byte's high nibble, `10` its low nibble, `11` colour RAM.
- **Screen:** `c1 << 4 | c2`, as for hires.
- **Colour RAM:** zero-run encoded like the other streams, whole 40-byte rows, decoded to
  `$d800 + 40 * row` (screen destination + `$1800`). `v2i_show` clears colour RAM first.
- **Kernel:** sets `$d016` = `$18` (multicolour) and `$d01d` = `$ff`: the sprites are
  X-expanded hires sprites, so each covers 24 wide pixels with one colour. Its sprite X
  registers are screen pixels as usual (the image's wide pixel x is at X = 24 + 8 *
  column + 2 * x).

## Metadata

Information only: the settings the image was made with that the rest of the file does
not record. A 2-byte length n (at most 1024), then n bytes of text: ASCII lines of the
form `key: value`, each ending in `$0a` (line feed, not PETSCII). Keys are lower case;
readers should ignore keys they don't know. The build writes, in this order:

- `quantized by`: the tool that made the PNG and its version, `img2c64@0.1.0` (from
  img2c64's settings in the PNG; just `img2c64` for PNGs from before versions were
  recorded, whose line was `quantiser`), or `unknown`.
- `generated by`: the build that converted it, `vic2orious@0.1.0` (`vic2.VERSION`).
- `date`: when it was converted, `YYYY-MM-DD HH:MM UTC` (a cached conversion keeps its
  date).
- The rest of what `tools/img2c64.py` recorded in the PNG (a `tEXt` chunk with keyword
  `vic2orious`, copied line by line), if the picture came from it: `mode` (`multicolor`, only for `-m` pictures), `source` (the input picture's file name), `aspect` (`pal`, `ntsc` or
  `none`, with the pixel width), `fit` (the box, `WxH`; for `-m` also in wide pixels), `dither` (mode and parameter;
  for hybrid also its line runs, spread, clamp and pair candidates), `chroma` and
  `palette`.
- `image`: the PNG file that was converted.
- `palette`, if img2c64 named none: the known palette that holds all the PNG's colours
  (Pepto, Colodore, or Colodore as VICE shows it, PAL or NTSC), or `unknown, mapped to
  nearest Pepto`.
- `frame`: `yes` if the build draws a frame around it (`build -b`), else `no`.

For example:

```
quantized by: img2c64@0.1.0
generated by: vic2orious@0.1.0
date: 2026-11-12 14:03 UTC
source: IMG_1639.png
aspect: pal (pixel width 0.936)
fit: 320x200
dither: hybrid:90, line runs none, spread 0.1, clamp 64, pair candidates 4
chroma: 1
palette: Colodore as VICE shows it (PAL)
image: IMG_1639-p.png
frame: no
```

`python3 -m vic2.info FILE.v2i` prints the header, the thumbnail's size and colours, and
the metadata (`-t DIR` also writes the thumbnail as a PNG).

## Streams

All three streams are **zero-run encoded**: `$00, n` stands for n zero bytes (n =
1..255), any other byte is itself, and `$00, $00` ends the stream. (`v2i.inc` clears
bank 3 first and skips the zero runs instead of writing them.)

- **Bitmap:** whole 320-byte screen rows, one per character row the image covers. They
  decode straight to the bitmap destination, so cells outside the image are 0.
- **Screen:** whole 40-byte rows of cell colours, `fg << 4 | bg`, decoded to the screen
  destination.
- **Sprites:** 64-byte sprite blocks, decoded to `$c400` (sprite pointer 16). Block 16 is
  all zero; the kernel points sprites at it outside the image. The stream holds as many
  blocks as the image uses. Each block holds one 21-line stretch of one sprite.

## Kernel

The kernel is an unrolled, cycle-exact routine, called with `JSR` once per frame. It
only works on the video system in byte 24: on the other one every write lands at the
wrong cycle (`v2i_show` refuses such a file). The sprite and bitmap data are converted
together with the kernel, so they differ between PAL and NTSC files too. It assumes:

- **Screen layout:** VIC bank 3 (`$c000-$ffff`), with the screen at `$c000`, sprite
  pointers at `$c3f8` and the bitmap at `$e000`. It sets `$d011` = `$3b`, `$d016` = `$08` and
  `$d018` = `$08`, but doesn't select the bank itself or touch the border and background
  colours (`v2i_start` sets them to black: a colour write leaves a grey dot on the 85xx,
  and the kernel's first lines are visible on NTSC).
- **Entry time:** it is entered on raster line 9, between cycles 20 and 47 of that line.
  Line 9 is below the sprite DMA that can still be running from the previous frame:
  `$d015` = 0 does not stop a sprite's 21-line block, and on NTSC (263 lines) the blocks
  of a 200-line image run on to line 8. `v2i.inc`'s IRQ handler (raster IRQ at line 9, then `STA`/`STX`/`STY` to zero page,
  `JSR`, `JMP (vector)`) gets there from any interrupted instruction. The kernel's first
  instructions sync to the exact cycle, so the entry time can vary within that window.
- **No DMA surprises:** nothing else may change VIC registers or steal cycles while it
  runs.
- **What it touches:** zero page `$02` (scratch for the sync code), VIC registers and the
  sprite pointers. Nothing else, and it doesn't depend on where it is in memory.

It turns all 8 sprites on, rewrites their position, colour and pointer registers line by
line down to the image's last line, sets `$d015` = 0, and returns with `RTS` at about
raster line `$33 + 8 * (row + height)`. Sprites crossing X = 256 also get their high bit
in `$d010`, which the kernel rewrites as a whole.

The image's position is part of the kernel: every write is timed for that column and row.
To show an image somewhere else, convert it again with `build --at COLUMN,ROW`.
