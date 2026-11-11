# .v2i image format (versions 3 and 4)

A `.v2i` file holds one converted image: a hires bitmap (version 3) or a multicolour
bitmap (version 4), its cell colours, the sprite data, and a *kernel*. The kernel is 6502 code generated for this image that rewrites the sprite
registers on every raster line, so the sprites paint the pixels the bitmap can't.
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
| 3 | 1 | format version: 3 hires, 4 multicolour (see [Multicolour](#multicolour-version-4)) |
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
| 25 | 1 | flags: bit 0 set if metadata follows the image data; bit 1 multicolour (version 4 only); other bits 0 |
| 26 | ... | kernel, then the bitmap, screen and sprite streams, back to back (multicolour: then the background and colour RAM stream), then the metadata if bit 0 of byte 25 is set |

Version 2 kernels were entered on raster line 2 (same layout). Version 1 had no video
system byte (always PAL) and a 24-byte header. Byte 25 was always 0 before metadata was
added (Nov 2026); players don't read it or anything after the sprite stream, so files
with and without metadata work with every version 3 player.

## Multicolour (version 4)

A multicolour image (`tools/img2c64.py -m`, written as version 4 so version 3 players
refuse it) is 160 wide pixels across at most, each two screen pixels wide, in cells of 4x8
wide pixels; the header still counts 8-pixel cells. Byte 25 has bit 1 set, and after the
sprite stream come:

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

- What `tools/img2c64.py` recorded in the PNG (a `tEXt` chunk with keyword
  `vic2orious`, copied line by line), if the picture came from it: `quantiser`
  (`img2c64`), `mode` (`multicolor`, only for `-m` pictures), `source` (the input picture's file name), `aspect` (`pal`, `ntsc` or
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
quantiser: img2c64
source: IMG_1639.png
aspect: pal (pixel width 0.936)
fit: 320x200
dither: hybrid:90, line runs none, spread 0.1, clamp 64, pair candidates 4
chroma: 1
palette: Colodore as VICE shows it (PAL)
image: IMG_1639-p.png
frame: no
```

`python3 -m vic2.info FILE.v2i` prints the header and the metadata.

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
